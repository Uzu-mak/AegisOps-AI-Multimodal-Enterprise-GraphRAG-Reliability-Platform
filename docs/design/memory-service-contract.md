# Phase 1 Memory Service Contract

## Scope

This document defines the approved service layer for AegisOps Phase 1. The service is responsible for business rules, lifecycle transitions, validation, and transaction ownership. The repository remains responsible only for persistence, retrieval, and row locking.

## Proposed service interface

```python
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.db.models.memory import MemoryRecord


class MemoryService(Protocol):
    def create_memory(
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
        memory_metadata: dict | None = None,
    ) -> MemoryRecord: ...

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
        replacement_memory: MemoryRecord,
    ) -> tuple[MemoryRecord, MemoryRecord]: ...
```

## Lifecycle state machine

```text
active
 ├─> disputed
 ├─> archived
 └─> superseded

disputed
 ├─> archived
 └─> active   (only if explicitly supported and tested)

superseded
 └─> no normal lifecycle transitions

archived
 └─> no normal lifecycle transitions
```

### Rules

- `active` can move to `disputed`, `archived`, or `superseded`
- `disputed` can move to `archived`
- `disputed` can move to `active` only if explicitly supported and tested
- `superseded` and `archived` are terminal states
- arbitrary status mutation is forbidden

## Transaction flow

### Single-step operations

1. open a service-owned transaction
2. validate input
3. call repository methods
4. flush if necessary
5. commit on success
6. rollback on any validation or DB error
7. return persisted entity

### Supersede flow

1. begin a single service-owned transaction
2. call `repository.get_for_update(old_memory_id)`
3. fail if old memory does not exist
4. fail if old memory is not in an allowed supersedable state
5. validate the replacement memory
6. set replacement status to `active`
7. set replacement `supersedes_memory_id = old_memory_id`
8. set old status to `superseded`
9. flush all changes
10. commit only if all steps succeed
11. rollback everything on any failure

## Exception design

```python
class AegisOpsError(Exception):
    pass


class MemoryNotFoundError(AegisOpsError):
    pass


class InvalidMemoryDataError(AegisOpsError):
    pass


class InvalidLifecycleTransitionError(AegisOpsError):
    pass


class MemoryConflictError(AegisOpsError):
    pass
```

### Responsibilities

- `MemoryNotFoundError`: missing memory records
- `InvalidMemoryDataError`: blank strings, invalid ranges, timezone issues
- `InvalidLifecycleTransitionError`: forbidden lifecycle mutation or invalid transition
- `MemoryConflictError`: concurrency or transactional conflict conditions

No FastAPI `HTTPException` should be raised from the service layer.

## Validation responsibility

Validation must be enforced in the service layer before any repository write.

Required validation:

- title cannot be blank
- content cannot be blank
- source_type cannot be blank
- confidence must be between 0 and 1 inclusive
- importance must be between 0 and 1 inclusive
- observed_at must be timezone-aware if provided
- generic update cannot modify `supersedes_memory_id`
- generic update cannot arbitrarily mutate lifecycle status

The repository is not responsible for business validation.

## Planned tests

### Unit tests

- create active memory
- get existing memory
- get nonexistent memory
- list/filter delegation
- update allowed fields
- reject blank title/content/source_type
- reject confidence/importance outside 0..1
- archive active memory
- dispute active memory
- reject illegal lifecycle transitions

### PostgreSQL-backed integration tests

- supersede active memory
- confirm old memory becomes superseded
- confirm new memory becomes active
- confirm new memory links to old memory
- reject superseding nonexistent memory
- reject superseding already superseded memory
- rollback if replacement creation fails
- rollback if old-record update fails
- verify transaction atomicity

## Files to create/modify

### Create

- app/services/**init**.py
- app/services/memory_service.py
- app/services/exceptions.py
- tests/services/test_memory_service.py

### Modify

- no repository change
- no database/schema change
- no API route change

## Out of scope

- FastAPI memory routes
- HTTP exception mapping
- Neo4j
- Qdrant
- Kafka
- agents
- LLMs
- ML
- vision
