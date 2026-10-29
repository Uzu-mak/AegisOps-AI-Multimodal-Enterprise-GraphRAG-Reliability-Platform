from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.outbox.models import ProjectionOutboxEvent, ProjectionStatus, ProjectionType
from app.outbox.publisher import ProjectionEventType
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.semantic.index import SemanticIndexError
from app.graph.index import GraphProjectionError
from app.services.exceptions import (
    InvalidLifecycleTransitionError,
    InvalidMemoryDataError,
    MemoryConflictError,
    MemoryNotFoundError,
)

logger = logging.getLogger(__name__)


class MemoryCreateData:
    def __init__(
        self,
        *,
        memory_type: str,
        title: str,
        content: str,
        source_type: str,
        asset_id: str | None = None,
        facility_id: str | None = None,
        component_id: str | None = None,
        incident_id: str | None = None,
        source_id: str | None = None,
        observed_at: datetime | None = None,
        confidence: float = 0.0,
        importance: float = 0.0,
        is_synthetic: bool = False,
        tenant_id: str | None = None,
        team_id: str | None = None,
        access_roles: list[str] | None = None,
        memory_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.memory_type = memory_type
        self.title = title
        self.content = content
        self.source_type = source_type
        self.asset_id = asset_id
        self.facility_id = facility_id
        self.component_id = component_id
        self.incident_id = incident_id
        self.source_id = source_id
        self.observed_at = observed_at
        self.confidence = confidence
        self.importance = importance
        self.is_synthetic = is_synthetic
        self.tenant_id = tenant_id
        self.team_id = team_id
        self.access_roles = access_roles or []
        self.memory_metadata = memory_metadata or {}


class MemoryService(Protocol):
    def create_memory(self, *, data: MemoryCreateData) -> MemoryRecord: ...

    def get_memory(self, memory_id: UUID) -> MemoryRecord: ...

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = None,
        asset_id: str | None = None,
        facility_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MemoryRecord]: ...

    def update_memory(
        self,
        memory_id: UUID,
        patch: dict[str, Any],
    ) -> MemoryRecord: ...

    def archive_memory(self, memory_id: UUID) -> MemoryRecord: ...

    def dispute_memory(self, memory_id: UUID) -> MemoryRecord: ...

    def supersede_memory(
        self,
        old_memory_id: UUID,
        replacement_data: MemoryCreateData,
    ) -> tuple[MemoryRecord, MemoryRecord]: ...


class RealMemoryService:
    def __init__(
        self,
        *,
        repository: SQLAlchemyMemoryRepository,
        session_factory,
        semantic_indexing_service: Optional[Any] = None,
        graph_projection_service: Optional[Any] = None,
    ) -> None:
        self.repository = repository
        self.session_factory = session_factory
        self.semantic_indexing_service = semantic_indexing_service
        self.graph_projection_service = graph_projection_service

    def _materialize_memory_for_return(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
        session.refresh(memory)
        session.expunge(memory)
        return memory

    def _materialize_memory_list_for_return(
        self,
        session: Session,
        memories: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        session.expunge_all()
        return memories

    def _enqueue_projection_events(
        self,
        *,
        session: Session,
        memory_id: UUID,
        operation: str,
        event_type: ProjectionEventType,
        memory: MemoryRecord | None = None,
    ) -> None:
        """Append one immutable logical envelope and two independent delivery jobs."""
        if memory is None:
            memory = session.scalar(select(MemoryRecord).where(MemoryRecord.id == memory_id).with_for_update())
        if memory is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found.")
        memory.revision = (memory.revision or 0) + 1
        event_id = uuid4()
        now = datetime.now(timezone.utc)
        payload = self._event_snapshot(memory)
        for projection_type in (ProjectionType.QDRANT.value, ProjectionType.NEO4J.value):
            session.add(ProjectionOutboxEvent(
                memory_id=memory_id, projection_type=projection_type, operation=operation,
                event_id=event_id, event_type=event_type.value, memory_version=memory.revision,
                schema_version=2, occurred_at=now, payload=payload,
                status=ProjectionStatus.PENDING.value,
            ))

    @staticmethod
    def _event_snapshot(memory: MemoryRecord) -> dict:
        # Historical content travels with its revision; credentials never belong here.
        return {
            column.name: (str(value) if isinstance(value, UUID) else
                          value.isoformat() if isinstance(value, datetime) else
                          float(value) if hasattr(value, "as_tuple") else value)
            for column in MemoryRecord.__table__.columns
            for value in [getattr(memory, column.key if column.name != "metadata" else "memory_metadata")]
        }

    def create_memory(self, *, data: MemoryCreateData) -> MemoryRecord:
        self._validate_create_data(data)

        with self.session_factory() as session:
            memory = self._build_memory_from_data(data)
            created = self.repository.create(session, memory)
            self._enqueue_projection_events(
                session=session,
                memory_id=created.id,
                operation="project",
                event_type=ProjectionEventType.MEMORY_CREATED,
            )
            session.commit()  # ← PostgreSQL commit FIRST
            materialized = self._materialize_memory_for_return(session, created)

        # ← Semantic indexing AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.semantic_indexing_service:
            try:
                self.semantic_indexing_service.index_memory(materialized)
            except SemanticIndexError as exc:
                logger.warning(f"Semantic indexing failed for memory {materialized.id}: {exc}")

        # ← Graph projection AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.graph_projection_service:
            try:
                self.graph_projection_service.project_memory(materialized)
            except GraphProjectionError as exc:
                logger.warning(f"Graph projection failed for memory {materialized.id}: {exc}")

        return materialized

    def get_memory(self, memory_id: UUID) -> MemoryRecord:
        with self.session_factory() as session:
            memory = self.repository.get_by_id(session, memory_id)
            if memory is None:
                raise MemoryNotFoundError(f"Memory {memory_id} not found.")
            return self._materialize_memory_for_return(session, memory)

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = None,
        asset_id: str | None = None,
        facility_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        with self.session_factory() as session:
            records = list(
                self.repository.list(
                    session,
                    memory_type=memory_type,
                    status=status,
                    asset_id=asset_id,
                    facility_id=facility_id,
                    source_type=source_type,
                    limit=limit,
                    offset=offset,
                )
            )
            return self._materialize_memory_list_for_return(session, records)

    def update_memory(
        self,
        memory_id: UUID,
        patch: dict[str, Any],
    ) -> MemoryRecord:
        if not isinstance(patch, dict):
            raise InvalidMemoryDataError("Patch payload must be a dictionary.")

        allowed_fields = {
            "title",
            "content",
            "asset_id",
            "component_id",
            "incident_id",
            "source_type",
            "source_id",
            "observed_at",
            "confidence",
            "importance",
            "is_synthetic",
            "tenant_id",
            "facility_id",
            "team_id",
            "access_roles",
            "memory_metadata",
        }

        # Track if semantic fields changed (for re-indexing decision)
        semantic_fields = {"title", "content", "confidence", "importance"}
        semantic_fields_changed = any(field in patch for field in semantic_fields)

        with self.session_factory() as session:
            memory = self.repository.get_for_update(session, memory_id)
            if memory is None:
                raise MemoryNotFoundError(f"Memory {memory_id} not found.")

            for field_name, value in patch.items():
                if field_name == "status":
                    raise InvalidLifecycleTransitionError("Lifecycle status may not be changed via generic update.")
                if field_name == "supersedes_memory_id":
                    raise InvalidLifecycleTransitionError("supersedes_memory_id is not mutable via generic update.")
                if field_name not in allowed_fields:
                    raise InvalidMemoryDataError(f"Field '{field_name}' cannot be updated through this method.")
                setattr(memory, field_name, value)

            self._validate_memory_record(memory)
            self.repository.update(session, memory)
            self._enqueue_projection_events(
                session=session,
                memory_id=memory.id,
                operation="project",
                event_type=ProjectionEventType.MEMORY_UPDATED,
            )
            session.commit()  # ← PostgreSQL commit FIRST
            materialized = self._materialize_memory_for_return(session, memory)

        # ← Semantic indexing AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.semantic_indexing_service:
            try:
                self.semantic_indexing_service.update_memory_index(
                    materialized,
                    semantic_fields_changed=semantic_fields_changed,
                )
            except SemanticIndexError as exc:
                logger.warning(f"Semantic index update failed for memory {materialized.id}: {exc}")

        # ← Graph projection AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.graph_projection_service:
            try:
                self.graph_projection_service.project_memory(materialized)
            except GraphProjectionError as exc:
                logger.warning(f"Graph projection update failed for memory {materialized.id}: {exc}")

        return materialized

    def archive_memory(self, memory_id: UUID) -> MemoryRecord:
        memory = self._transition_memory_status(
            memory_id,
            MemoryStatus.ARCHIVED.value,
            outbox_operation="status_update",
        )
        # Semantic indexing after PostgreSQL commit
        if self.semantic_indexing_service:
            try:
                self.semantic_indexing_service.archive_memory(memory_id)
            except SemanticIndexError as exc:
                logger.warning(f"Semantic archive failed for memory {memory_id}: {exc}")
        # Graph projection after PostgreSQL commit
        if self.graph_projection_service:
            try:
                self.graph_projection_service.update_memory_status(memory)
            except GraphProjectionError as exc:
                logger.warning(f"Graph archive projection failed for memory {memory_id}: {exc}")
        return memory

    def dispute_memory(self, memory_id: UUID) -> MemoryRecord:
        memory = self._transition_memory_status(
            memory_id,
            MemoryStatus.DISPUTED.value,
            outbox_operation="status_update",
        )
        # Semantic indexing after PostgreSQL commit
        if self.semantic_indexing_service:
            try:
                self.semantic_indexing_service.dispute_memory(memory_id)
            except SemanticIndexError as exc:
                logger.warning(f"Semantic dispute failed for memory {memory_id}: {exc}")
        # Graph projection after PostgreSQL commit
        if self.graph_projection_service:
            try:
                self.graph_projection_service.update_memory_status(memory)
            except GraphProjectionError as exc:
                logger.warning(f"Graph dispute projection failed for memory {memory_id}: {exc}")
        return memory

    def supersede_memory(
        self,
        old_memory_id: UUID,
        replacement_data: MemoryCreateData,
    ) -> tuple[MemoryRecord, MemoryRecord]:
        self._validate_create_data(replacement_data)

        with self.session_factory() as session:
            existing = self.repository.get_for_update(session, old_memory_id)
            if existing is None:
                raise MemoryNotFoundError(f"Memory {old_memory_id} not found.")
            if existing.status != MemoryStatus.ACTIVE.value:
                raise InvalidLifecycleTransitionError(
                    f"Only active memories may be superseded; found status '{existing.status}'."
                )

            replacement = self._build_memory_from_data(replacement_data)
            replacement.status = MemoryStatus.ACTIVE.value
            replacement.supersedes_memory_id = old_memory_id

            existing.status = MemoryStatus.SUPERSEDED.value
            session.flush([existing])
            self.repository.create(session, replacement)
            self.repository.update(session, existing)
            self._enqueue_projection_events(
                session=session,
                memory_id=existing.id,
                operation="status_update",
                event_type=ProjectionEventType.MEMORY_SUPERSEDED,
            )
            self._enqueue_projection_events(
                session=session,
                memory_id=replacement.id,
                operation="project",
                event_type=ProjectionEventType.MEMORY_CREATED,
            )
            session.flush()
            session.commit()  # ← PostgreSQL commit FIRST
            old_materialized = self._materialize_memory_for_return(session, existing)
            new_materialized = self._materialize_memory_for_return(session, replacement)

        # ← Semantic indexing AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.semantic_indexing_service:
            try:
                self.semantic_indexing_service.supersede_memory(old_memory_id, new_materialized)
            except SemanticIndexError as exc:
                logger.warning(f"Semantic supersede failed for memory {old_memory_id}: {exc}")

        # ← Graph projection AFTER PostgreSQL commit (best-effort, non-fatal)
        if self.graph_projection_service:
            try:
                self.graph_projection_service.project_supersession(old_materialized, new_materialized)
            except GraphProjectionError as exc:
                logger.warning(f"Graph supersede projection failed for memory {old_memory_id}: {exc}")

        return (old_materialized, new_materialized)

    # ------------------------------------------------------------ bulk import

    def active_source_fingerprints(self, *, source_type: str, source_ids: list[str], source_system: str = "default", tenant_id: str | None = None) -> dict[str, tuple[UUID, str | None]]:
        """
        Active records from one source system, keyed "facility|source_id".

        Returns (memory id, import fingerprint) so a re-import can tell new,
        changed and unchanged rows apart without loading full records.
        """
        out: dict[str, tuple[UUID, str | None]] = {}
        if not source_ids:
            return out
        with self.session_factory() as session:
            for start in range(0, len(source_ids), 1000):
                chunk = source_ids[start:start + 1000]
                rows = session.execute(
                    select(MemoryRecord.id, MemoryRecord.facility_id, MemoryRecord.source_id, MemoryRecord.memory_metadata)
                    .where(
                        MemoryRecord.source_type == source_type,
                        MemoryRecord.tenant_id.is_not_distinct_from(tenant_id),
                        func.coalesce(MemoryRecord.memory_metadata["import"]["source_system"].astext, "default") == source_system,
                        MemoryRecord.status == MemoryStatus.ACTIVE.value,
                        MemoryRecord.source_id.in_(chunk),
                    )
                ).all()
                for mid, facility, source_id, meta in rows:
                    fp = ((meta or {}).get("import") or {}).get("fingerprint")
                    out[f"{facility or ''}|{source_id}"] = (mid, fp)
        return out

    def bulk_import(
        self,
        *,
        creates: list[MemoryCreateData],
        supersedes: list[tuple[UUID, MemoryCreateData]],
    ) -> dict[str, int]:
        """
        Write a whole import in one PostgreSQL transaction (all or nothing).

        Projection is not done inline: every new or superseded record gets its
        outbox events in the same transaction and the projection worker
        indexes them into Qdrant and Neo4j. A record that is no longer active
        when the import runs (someone archived it meanwhile) aborts the import
        with MemoryConflictError so nothing is half-applied.
        """
        for data in creates:
            self._validate_create_data(data)
        for _, data in supersedes:
            self._validate_create_data(data)

        with self.session_factory() as session:
            from sqlalchemy import text as sql_text
            identities = sorted({self._import_identity(data) for data in creates + [d for _, d in supersedes]})
            for identity in identities:
                session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"), {"identity": identity})
            from collections import defaultdict
            groups = defaultdict(list)
            for data in creates:
                groups[self._import_identity(data)].append(data)
            for group in groups.values():
                data = group[0]
                for start in range(0, len(group), 1000):
                    source_ids = [item.source_id for item in group[start:start + 1000]]
                    existing = session.scalar(select(MemoryRecord.id).where(
                        MemoryRecord.source_type == data.source_type,
                        MemoryRecord.source_id.in_(source_ids),
                        MemoryRecord.facility_id.is_not_distinct_from(data.facility_id),
                        MemoryRecord.tenant_id.is_not_distinct_from(data.tenant_id),
                        MemoryRecord.status == "active",
                        func.coalesce(MemoryRecord.memory_metadata["import"]["source_system"].astext, "default") == data.memory_metadata.get("import", {}).get("source_system", "default"),
                    ).limit(1))
                    if existing is not None:
                        raise MemoryConflictError("Import changed concurrently; preview and retry. Nothing was imported.")
            records = [self._build_memory_from_data(data) for data in creates]
            session.add_all(records)
            session.flush()
            for record in records:
                self._enqueue_projection_events(session=session, memory_id=record.id, memory=record,
                    operation="project", event_type=ProjectionEventType.MEMORY_CREATED)
            for old_id, data in supersedes:
                existing = self.repository.get_for_update(session, old_id)
                if existing is None or existing.status != MemoryStatus.ACTIVE.value:
                    session.rollback()
                    raise MemoryConflictError(
                        f"Record {old_id} changed while the import was running; nothing was imported. Run the import again.")
                replacement = self._build_memory_from_data(data)
                replacement.supersedes_memory_id = old_id
                existing.status = MemoryStatus.SUPERSEDED.value
                session.flush([existing])
                self.repository.create(session, replacement)
                self.repository.update(session, existing)
                self._enqueue_projection_events(
                    session=session, memory_id=existing.id, operation="status_update",
                    event_type=ProjectionEventType.MEMORY_SUPERSEDED,
                )
                self._enqueue_projection_events(
                    session=session, memory_id=replacement.id, operation="project",
                    event_type=ProjectionEventType.MEMORY_CREATED,
                )
            session.commit()
        return {"created": len(creates), "superseded": len(supersedes)}

    @staticmethod
    def _import_identity(data: MemoryCreateData) -> str:
        import json
        return json.dumps([data.tenant_id, data.facility_id, data.source_type,
            data.memory_metadata.get("import", {}).get("source_system", "default")])

    def restore_memory(self, memory_id: UUID) -> MemoryRecord:
        return self._transition_memory_status(memory_id, MemoryStatus.ACTIVE.value, outbox_operation="status_update")

    def _transition_memory_status(
        self,
        memory_id: UUID,
        target_status: str,
        *,
        outbox_operation: str,
    ) -> MemoryRecord:
        with self.session_factory() as session:
            memory = self.repository.get_for_update(session, memory_id)
            if memory is None:
                raise MemoryNotFoundError(f"Memory {memory_id} not found.")

            current = memory.status
            allowed_transitions = {
                MemoryStatus.ACTIVE.value: {MemoryStatus.ARCHIVED.value, MemoryStatus.DISPUTED.value, MemoryStatus.SUPERSEDED.value},
                MemoryStatus.DISPUTED.value: {MemoryStatus.ARCHIVED.value, MemoryStatus.ACTIVE.value},
            }

            if current not in allowed_transitions or target_status not in allowed_transitions[current]:
                raise InvalidLifecycleTransitionError(
                    f"Invalid transition from status '{current}' to '{target_status}'."
                )

            memory.status = target_status
            self.repository.update(session, memory)
            self._enqueue_projection_events(
                session=session,
                memory_id=memory.id,
                operation=outbox_operation,
                event_type=self._event_type_for_status(target_status),
            )
            session.commit()
            return self._materialize_memory_for_return(session, memory)

    def _event_type_for_status(self, status: str) -> ProjectionEventType:
        mapping = {
            MemoryStatus.ARCHIVED.value: ProjectionEventType.MEMORY_ARCHIVED,
            MemoryStatus.DISPUTED.value: ProjectionEventType.MEMORY_DISPUTED,
            MemoryStatus.SUPERSEDED.value: ProjectionEventType.MEMORY_SUPERSEDED,
        }
        return mapping.get(status, ProjectionEventType.MEMORY_UPDATED)

    def _validate_create_data(self, data: MemoryCreateData) -> None:
        if not data.title or not data.title.strip():
            raise InvalidMemoryDataError("title cannot be blank.")
        if not data.content or not data.content.strip():
            raise InvalidMemoryDataError("content cannot be blank.")
        if not data.source_type or not data.source_type.strip():
            raise InvalidMemoryDataError("source_type cannot be blank.")
        if not 0.0 <= float(data.confidence) <= 1.0:
            raise InvalidMemoryDataError("confidence must be between 0 and 1 inclusive.")
        if not 0.0 <= float(data.importance) <= 1.0:
            raise InvalidMemoryDataError("importance must be between 0 and 1 inclusive.")
        if data.observed_at is not None and data.observed_at.tzinfo is None:
            raise InvalidMemoryDataError("observed_at must be timezone-aware when provided.")
        if data.memory_type not in {member.value for member in MemoryType}:
            raise InvalidMemoryDataError(f"Unsupported memory type: {data.memory_type}")

    def _validate_memory_record(self, memory: MemoryRecord) -> None:
        if not memory.title or not memory.title.strip():
            raise InvalidMemoryDataError("title cannot be blank.")
        if not memory.content or not memory.content.strip():
            raise InvalidMemoryDataError("content cannot be blank.")
        if not memory.source_type or not memory.source_type.strip():
            raise InvalidMemoryDataError("source_type cannot be blank.")
        if not 0.0 <= float(memory.confidence) <= 1.0:
            raise InvalidMemoryDataError("confidence must be between 0 and 1 inclusive.")
        if not 0.0 <= float(memory.importance) <= 1.0:
            raise InvalidMemoryDataError("importance must be between 0 and 1 inclusive.")
        if memory.observed_at is not None and memory.observed_at.tzinfo is None:
            raise InvalidMemoryDataError("observed_at must be timezone-aware when provided.")

    def _build_memory_from_data(self, data: MemoryCreateData) -> MemoryRecord:
        return MemoryRecord(
            memory_type=data.memory_type,
            status=MemoryStatus.ACTIVE.value,
            title=data.title.strip(),
            content=data.content.strip(),
            asset_id=data.asset_id,
            component_id=data.component_id,
            incident_id=data.incident_id,
            source_type=data.source_type.strip(),
            source_id=data.source_id,
            observed_at=data.observed_at,
            confidence=float(data.confidence),
            importance=float(data.importance),
            is_synthetic=bool(data.is_synthetic),
            tenant_id=data.tenant_id,
            facility_id=data.facility_id,
            team_id=data.team_id,
            access_roles=list(data.access_roles or []),
            supersedes_memory_id=None,
            memory_metadata=data.memory_metadata or {},
        )


MemoryService = RealMemoryService
