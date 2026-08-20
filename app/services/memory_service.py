from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
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
        return [self._materialize_memory_for_return(session, memory) for memory in memories]

    def create_memory(self, *, data: MemoryCreateData) -> MemoryRecord:
        self._validate_create_data(data)

        with self.session_factory() as session:
            memory = self._build_memory_from_data(data)
            created = self.repository.create(session, memory)
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
            memory = self.repository.get_by_id(session, memory_id)
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
        memory = self._transition_memory_status(memory_id, MemoryStatus.ARCHIVED.value)
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
        memory = self._transition_memory_status(memory_id, MemoryStatus.DISPUTED.value)
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
            self.repository.create(session, replacement)
            self.repository.update(session, existing)
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

    def _transition_memory_status(self, memory_id: UUID, target_status: str) -> MemoryRecord:
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
            session.commit()
            return self._materialize_memory_for_return(session, memory)

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
