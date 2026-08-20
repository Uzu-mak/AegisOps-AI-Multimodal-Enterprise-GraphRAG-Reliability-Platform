# Phase 1 Memory Repository Contract

## Scope

This document defines the approved repository/data-access layer for AegisOps Phase 1. The repository is responsible only for persistence and retrieval. It does not contain business or lifecycle rules.

## Repository interface

```python
from typing import Protocol, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

class MemoryRepository(Protocol):
    def create(self, session: Session, memory: MemoryRecord) -> MemoryRecord: ...
    def get_by_id(self, session: Session, memory_id: UUID) -> MemoryRecord | None: ...
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
    ) -> Sequence[MemoryRecord]: ...
    def update(self, session: Session, memory: MemoryRecord) -> MemoryRecord: ...
    def get_for_update(self, session: Session, memory_id: UUID) -> MemoryRecord | None: ...
```

## Method signatures

```python
class SQLAlchemyMemoryRepository:
    def create(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
        ...

    def get_by_id(self, session: Session, memory_id: UUID) -> MemoryRecord | None:
        ...

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
        ...

    def update(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
        ...

    def get_for_update(self, session: Session, memory_id: UUID) -> MemoryRecord | None:
        ...
```

## Transaction and flush behavior

- Repository methods must not commit.
- Repository methods must not rollback.
- Repository methods must use the caller-managed SQLAlchemy session.
- `flush()` may be called to ensure inserted/updated state is visible to the current transaction before the service layer commits.
- The service layer remains responsible for commit/rollback boundaries.

Example:

```python
def create(self, session: Session, memory: MemoryRecord) -> MemoryRecord:
    session.add(memory)
    session.flush()
    return memory
```

## SELECT ... FOR UPDATE support

For future supersede operations, the repository will provide row-level locking for a specific memory record:

```python
from sqlalchemy import select


def get_for_update(self, session: Session, memory_id: UUID) -> MemoryRecord | None:
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.id == memory_id)
        .with_for_update()
    )
    return session.execute(stmt).scalars().first()
```

This ensures the target row is locked within the same transaction and prevents concurrent races during lifecycle updates.

## Required constraints

- SQLAlchemy 2.x
- typed methods
- use the existing Session infrastructure
- no FastAPI dependencies inside the repository
- no HTTP exceptions
- no lifecycle decisions
- no independent commit inside repository methods
- preserve PostgreSQL as canonical storage
- keep the ORM attribute name as `memory_metadata` while the PostgreSQL column remains `metadata`

## Files to be created/modified

### Create
- app/repositories/__init__.py
- app/repositories/memory_repository.py
- tests/repositories/test_memory_repository.py

### Modify
- No schema changes expected
- No migration changes expected unless a verified blocking defect is found
- No business logic/service layer will be added in this phase

## Not in scope for Phase 1

- service layer
- API routes
- Pydantic schemas beyond what is strictly required
- supersede business logic
- Neo4j
- Qdrant
- Kafka
- agents
- LLMs
