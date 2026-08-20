# Phase 1 Memory API Design

## Scope

This document defines the approved FastAPI layer for AegisOps Phase 1. The API is responsible only for HTTP parsing, request validation, dependency wiring, service invocation, response serialization, and domain-exception-to-HTTP mapping.

The API must not own transaction behavior, SQLAlchemy queries, or business validation. Those responsibilities remain in the service and repository layers.

## Router surface

Base prefix:

- `/api/v1`

Routes:

- `POST /api/v1/memories`
- `GET /api/v1/memories/{memory_id}`
- `GET /api/v1/memories`
- `PATCH /api/v1/memories/{memory_id}`
- `POST /api/v1/memories/{memory_id}/archive`
- `POST /api/v1/memories/{memory_id}/dispute`
- `POST /api/v1/memories/{memory_id}/supersede`

The existing health endpoint remains available:

- `GET /health`

## Schema design

Use Pydantic v2 models, separate from SQLAlchemy and from the internal `MemoryCreateData` contract.

### MemoryCreateRequest

```python
from datetime import datetime
from typing import Any

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
```

### MemoryUpdateRequest

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.memory import MemoryStatus, MemoryType


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
```

### SupersedeMemoryRequest

```python
from pydantic import BaseModel, ConfigDict


class SupersedeMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement: MemoryCreateRequest
```

### MemoryResponse

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models.memory import MemoryStatus, MemoryType


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
```

### MemoryListResponse

Optional but useful if list responses are wrapped for pagination metadata.

```python
class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    total: int | None = None
    limit: int | None = None
    offset: int = 0
```

## API field-name requirement

The HTTP response field name is `metadata`.

The internal ORM attribute remains `memory_metadata`.

This is intentionally mapped in the API layer as a clean alias/translator layer so we do not reintroduce SQLAlchemy’s reserved `metadata` attribute name in the model layer.

## Route responsibilities

Route logic must:

- parse body/query params
- validate request shape via Pydantic
- convert request to `MemoryCreateData` or patch dict
- call the service layer
- convert ORM data to `MemoryResponse`
- map domain exceptions to HTTP status codes

Routes must not:

- contain lifecycle validation logic
- execute SQLAlchemy queries directly
- commit, rollback, or manage sessions
- own repository semantics

## Dependency flow

Recommended pattern:

```python
from fastapi import Depends

from app.db.session import SessionLocal
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.memory_service import MemoryService, RealMemoryService


def get_memory_service() -> MemoryService:
    return RealMemoryService(
        repository=SQLAlchemyMemoryRepository(),
        session_factory=SessionLocal,
    )
```

Then each route receives the service via dependency injection:

```python
def read_memory(
    memory_id: UUID,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    ...
```

This keeps route code dependent on the service abstraction and not on database-engine construction details.

## Request -> service conversion

### Create

```python
service_data = MemoryCreateData(
    memory_type=request.memory_type,
    title=request.title,
    content=request.content,
    source_type=request.source_type,
    asset_id=request.asset_id,
    facility_id=request.facility_id,
    component_id=request.component_id,
    incident_id=request.incident_id,
    source_id=request.source_id,
    observed_at=request.observed_at,
    confidence=request.confidence,
    importance=request.importance,
    is_synthetic=request.is_synthetic,
    tenant_id=request.tenant_id,
    team_id=request.team_id,
    access_roles=request.access_roles,
    memory_metadata=request.metadata,
)
```

### Update

- convert `MemoryUpdateRequest` to a plain dict of approved fields
- route passes this dict to `service.update_memory(memory_id, patch=...)`
- route does not manually enforce lifecycle policy

### Supersede

```python
replacement_data = MemoryCreateData(
    memory_type=request.replacement.memory_type,
    title=request.replacement.title,
    content=request.replacement.content,
    source_type=request.replacement.source_type,
    asset_id=request.replacement.asset_id,
    facility_id=request.replacement.facility_id,
    component_id=request.replacement.component_id,
    incident_id=request.replacement.incident_id,
    source_id=request.replacement.source_id,
    observed_at=request.replacement.observed_at,
    confidence=request.replacement.confidence,
    importance=request.replacement.importance,
    is_synthetic=request.replacement.is_synthetic,
    tenant_id=request.replacement.tenant_id,
    team_id=request.replacement.team_id,
    access_roles=request.replacement.access_roles,
    memory_metadata=request.replacement.metadata,
)
```

Return both records from the service as a tuple and convert each to `MemoryResponse`.

## Response mapping

```python
def memory_to_response(record: MemoryRecord) -> MemoryResponse:
    return MemoryResponse(
        id=record.id,
        memory_type=record.memory_type,
        status=record.status,
        title=record.title,
        content=record.content,
        source_type=record.source_type,
        asset_id=record.asset_id,
        facility_id=record.facility_id,
        component_id=record.component_id,
        incident_id=record.incident_id,
        source_id=record.source_id,
        observed_at=record.observed_at,
        confidence=record.confidence,
        importance=record.importance,
        is_synthetic=record.is_synthetic,
        tenant_id=record.tenant_id,
        team_id=record.team_id,
        access_roles=record.access_roles or [],
        metadata=record.memory_metadata,
        supersedes_memory_id=record.supersedes_memory_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
```

## Exception mapping

- `MemoryNotFoundError` -> `404` with `detail: str(exc)`
- `InvalidMemoryDataError` -> `422` with `detail: str(exc)`
- `InvalidLifecycleTransitionError` -> `409` with `detail: str(exc)`
- `MemoryConflictError` -> `409` with `detail: str(exc)`

No stack traces or internal debug details are returned.

## Planned API tests

- create memory (`201`)
- get by id (`200`)
- get missing memory (`404`)
- list/filter (`200`)
- patch allowed fields (`200`)
- invalid create (`422`)
- archive memory (`200`)
- dispute memory (`200`)
- invalid lifecycle transition (`409`)
- supersede memory (`200`)
- supersede missing memory (`404`)
- response metadata mapping (`metadata` field is present and correct)
- status cannot be supplied on create
- `supersedes_memory_id` cannot be manipulated through generic patch

## Files to create/modify

Create:

- `app/api/__init__.py`
- `app/api/deps.py`
- `app/api/schemas/__init__.py`
- `app/api/schemas/memory.py`
- `app/api/routes/__init__.py`
- `app/api/routes/memories.py`
- `app/api/exception_handlers.py`
- `tests/api/test_memory_api.py`

Modify:

- `app/main.py`

## Out of scope

- Neo4j
- Qdrant
- Kafka
- agents
- LLMs
- ML
- vision
- authentication
