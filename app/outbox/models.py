"""
ProjectionOutboxEvent — PostgreSQL-backed outbox for reliable projection.

PostgreSQL remains canonical. The outbox ensures Qdrant and Neo4j
projections are eventually completed even after transient failures.

Projection events are written in the SAME PostgreSQL transaction as the
MemoryRecord, guaranteeing that an outbox event exists for every memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class ProjectionType(str, Enum):
    QDRANT = "qdrant"
    NEO4J = "neo4j"


class ProjectionOutboxEvent(Base):
    """
    Outbox event tracking a required projection for a memory record.

    Written in the same PostgreSQL transaction as the MemoryRecord.
    Picked up by the OutboxWorker for async projection.
    """

    __tablename__ = "projection_outbox"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    projection_type: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False, default="project")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectionStatus.PENDING.value, index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
