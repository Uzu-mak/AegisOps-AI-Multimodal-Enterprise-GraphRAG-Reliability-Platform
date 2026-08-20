from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MemoryType(str, Enum):
    OBSERVATION = "observation"
    INCIDENT = "incident"
    DIAGNOSIS = "diagnosis"
    MAINTENANCE_ACTION = "maintenance_action"
    RESOLUTION = "resolution"
    RECOMMENDATION = "recommendation"
    DOCUMENT_FACT = "document_fact"
    AGENT_INTERACTION = "agent_interaction"
    FEEDBACK = "feedback"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    ARCHIVED = "archived"


class MemoryRecord(Base):
    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=MemoryStatus.ACTIVE.value)

    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    component_id: Mapped[str | None] = mapped_column(String, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True)

    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    importance: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    facility_id: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str | None] = mapped_column(String, nullable=True)

    access_roles: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    supersedes_memory_id: Mapped[UUID | None] = mapped_column(ForeignKey("memories.id"), nullable=True)
    memory_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
