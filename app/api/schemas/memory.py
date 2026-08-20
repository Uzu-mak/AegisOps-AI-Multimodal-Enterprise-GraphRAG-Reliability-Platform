from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.memory import MemoryStatus, MemoryType


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    title: str
    content: str
    source_type: str
    asset_id: str | None = None
    facility_id: str | None = None
    component_id: str | None = None
    incident_id: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    importance: float = Field(default=0.0, ge=0, le=1)
    is_synthetic: bool = False
    tenant_id: str | None = None
    team_id: str | None = None
    access_roles: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class MemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    content: str | None = None
    asset_id: str | None = None
    component_id: str | None = None
    incident_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    is_synthetic: bool | None = None
    tenant_id: str | None = None
    facility_id: str | None = None
    team_id: str | None = None
    access_roles: list[str] | None = None
    metadata: dict[str, Any] | None = None


class SupersedeMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement: MemoryCreateRequest


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    memory_type: MemoryType
    status: MemoryStatus
    title: str
    content: str
    source_type: str
    asset_id: str | None = None
    facility_id: str | None = None
    component_id: str | None = None
    incident_id: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    confidence: float
    importance: float
    is_synthetic: bool
    tenant_id: str | None = None
    team_id: str | None = None
    access_roles: list[str]
    metadata: dict[str, Any] | None = None
    supersedes_memory_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    total: int | None = None
    limit: int | None = None
    offset: int = 0
