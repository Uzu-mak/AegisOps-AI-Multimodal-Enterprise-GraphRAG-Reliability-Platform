from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models.memory import MemoryRecord


class SQLAlchemyMemoryRepository:
    def create(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
        session.add(memory)
        session.flush()
        return memory

    def get_by_id(self, session: Session, memory_id: UUID) -> MemoryRecord | None:
        stmt: Select[MemoryRecord] = select(MemoryRecord).where(MemoryRecord.id == memory_id)
        return session.execute(stmt).scalars().first()

    def list(
        self,
        session: Session,
        *,
        memory_type: str | None = None,
        status: str | None = None,
        asset_id: str | None = None,
        facility_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[MemoryRecord]:
        stmt: Select[MemoryRecord] = select(MemoryRecord)
        filters = []

        if memory_type is not None:
            filters.append(MemoryRecord.memory_type == memory_type)
        if status is not None:
            filters.append(MemoryRecord.status == status)
        if asset_id is not None:
            filters.append(MemoryRecord.asset_id == asset_id)
        if facility_id is not None:
            filters.append(MemoryRecord.facility_id == facility_id)
        if source_type is not None:
            filters.append(MemoryRecord.source_type == source_type)

        if filters:
            stmt = stmt.where(*filters)

        stmt = stmt.order_by(MemoryRecord.created_at.desc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return session.execute(stmt).scalars().all()

    def update(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
        session.add(memory)
        session.flush()
        return memory

    def get_for_update(self, session: Session, memory_id: UUID) -> MemoryRecord | None:
        stmt: Select[MemoryRecord] = (
            select(MemoryRecord)
            .where(MemoryRecord.id == memory_id)
            .with_for_update()
        )
        return session.execute(stmt).scalars().first()
