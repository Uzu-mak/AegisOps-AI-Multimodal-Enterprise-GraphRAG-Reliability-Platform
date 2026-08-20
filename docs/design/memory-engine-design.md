# AegisOps AI — Persistent Operational Memory Engine Design

## 1. Proposed repository/file structure

```text
AegisOps/
  app/
    main.py
    core/
      config.py
      enums.py
      exceptions.py
    db/
      base.py
      session.py
      migrations/
        versions/
      models/
        memory.py
    schemas/
      memory.py
    repositories/
      memory_repository.py
    services/
      memory_service.py
    api/
      deps.py
      routes/
        memories.py
    integrations/
      interfaces.py
  tests/
    test_memory_service.py
    test_memory_routes.py
    test_memory_repository.py
    conftest.py
  docs/
    memory-engine.md
    decisions/
      ADR-001-canonical-operational-memory.md
  alembic.ini
  requirements.txt
  pyproject.toml
```

This keeps responsibilities separated in a way that matches the architecture:

- database model: SQLAlchemy table and metadata
- API schema: Pydantic request/response models
- repository: database access only
- service: validation, lifecycle rules, and transaction orchestration
- API routes: thin HTTP layer invoking the service
- integrations: future-ready Neo4j/Qdrant interface layer with no Phase 1 implementation

---

## 2. Domain model

### MemoryType enum

- observation
- incident
- diagnosis
- maintenance_action
- resolution
- recommendation
- document_fact
- agent_interaction
- feedback

### MemoryStatus enum

- active
- superseded
- disputed
- archived

### MemoryRecord model

```python
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
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_type: Mapped[MemoryType] = mapped_column(String, nullable=False)
    status: Mapped[MemoryStatus] = mapped_column(String, nullable=False, default=MemoryStatus.ACTIVE)

    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    asset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    component_id: Mapped[str | None] = mapped_column(String, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True)

    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    importance: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    facility_id: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str | None] = mapped_column(String, nullable=True)

    access_roles: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    supersedes_memory_id: Mapped[UUID | None] = mapped_column(ForeignKey("memories.id"), nullable=True)
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
```

### Domain rules

- title must not be blank
- content must not be empty
- source_type must not be blank
- confidence and importance must be in the inclusive range [0, 1]
- timestamps must be timezone-aware
- memory lifecycle is soft-state and non-destructive
- supersede is a versioning relationship, not a replacement overwrite
- a record cannot supersede itself
- a replacement memory cannot point to a nonexistent record

---

## 3. PostgreSQL schema design

### Canonical table

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    memory_type TEXT NOT NULL CHECK (
        memory_type IN (
            'observation',
            'incident',
            'diagnosis',
            'maintenance_action',
            'resolution',
            'recommendation',
            'document_fact',
            'agent_interaction',
            'feedback'
        )
    ),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    asset_id TEXT,
    component_id TEXT,
    incident_id TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    importance NUMERIC(3,2) NOT NULL CHECK (importance >= 0 AND importance <= 1),
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    tenant_id TEXT,
    facility_id TEXT,
    team_id TEXT,
    access_roles TEXT[] NOT NULL DEFAULT '{}',
    supersedes_memory_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT fk_supersedes_memory
        FOREIGN KEY (supersedes_memory_id) REFERENCES memories(id)
);
```

### Why use PostgreSQL UUID and JSONB

- UUID is the correct canonical identifier for cross-system memory records and future lineage links
- JSONB supports rich metadata without forcing a rigid schema too early
- JSONB also supports indexing and partial query patterns later

### Recommended access_roles representation

Use PostgreSQL `TEXT[]` for `access_roles` in Phase 1.

Reasoning:

- Access roles are a simple, attached list of strings on each memory record
- There is no separate role object domain model yet
- A join-table design would add complexity without value for the initial implementation
- `TEXT[]` supports efficient membership checks such as `ANY(access_roles)` and simple retrieval
- It is easy to evolve into a normalized RBAC model later if the authorization model becomes richer

### Index strategy

Recommended indexes:

```sql
CREATE INDEX idx_memories_memory_type ON memories(memory_type);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_asset_id ON memories(asset_id);
CREATE INDEX idx_memories_facility_id ON memories(facility_id);
CREATE INDEX idx_memories_source_type ON memories(source_type);
CREATE INDEX idx_memories_incident_id ON memories(incident_id);
CREATE INDEX idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX idx_memories_updated_at ON memories(updated_at DESC);
CREATE INDEX idx_memories_supersedes_memory_id ON memories(supersedes_memory_id);
CREATE INDEX idx_memories_access_roles ON memories USING GIN (access_roles);
CREATE INDEX idx_memories_metadata ON memories USING GIN (metadata jsonb_path_ops);
```

Additional useful partial index:

```sql
CREATE INDEX idx_memories_active ON memories(status) WHERE status = 'active';
```

This supports the expected query/load patterns without over-indexing the system.

### Foreign key and deletion policy

- `supersedes_memory_id` is a self-referential FK to `memories.id`
- the API does not allow hard deletion of memory records
- database-level deletion of a memory row should be restricted or avoided because version history must remain intact

---

## 4. API schemas

### CreateMemoryRequest

```python
class MemoryCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    memory_type: MemoryType
    title: str
    content: str
    asset_id: str | None = None
    component_id: str | None = None
    incident_id: str | None = None
    source_type: str
    source_id: str | None = None
    observed_at: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    is_synthetic: bool = False
    tenant_id: str | None = None
    facility_id: str | None = None
    team_id: str | None = None
    access_roles: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

New memory records are always created with `status = active` by the service layer. The create schema intentionally does not expose a lifecycle status override because lifecycle transitions are controlled by explicit service operations.

### MemoryResponse

```python
class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    memory_type: MemoryType
    status: MemoryStatus
    title: str
    content: str
    asset_id: str | None
    component_id: str | None
    incident_id: str | None
    source_type: str
    source_id: str | None
    created_at: datetime
    observed_at: datetime | None
    updated_at: datetime
    confidence: float
    importance: float
    is_synthetic: bool
    tenant_id: str | None
    facility_id: str | None
    team_id: str | None
    access_roles: list[str]
    supersedes_memory_id: UUID | None
    metadata: dict[str, Any]
```

### MemoryUpdateRequest

```python
class MemoryUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    title: str | None = None
    content: str | None = None
    status: MemoryStatus | None = None
    asset_id: str | None = None
    component_id: str | None = None
    incident_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    is_synthetic: bool | None = None
    facility_id: str | None = None
    team_id: str | None = None
    access_roles: list[str] | None = None
    metadata: dict[str, Any] | None = None
```

`supersedes_memory_id` is intentionally omitted from the generic update contract. Lineage is created only through the dedicated `MemoryService.supersede_memory()` service operation so lifecycle versioning cannot be manipulated through a normal PATCH request.

### List filters

Query params for GET /api/v1/memories:

- memory_type
- status
- asset_id
- facility_id
- source_type
- pagination (page/page_size)
- default ordering by created_at desc

---

## 5. Repository/service boundaries

### Repository responsibilities

- execute SQLAlchemy queries
- read/write memory rows
- list filtered results
- update rows
- fetch records by ID
- persist changes for the current session
- not responsible for semantic business rules
- not responsible for committing multi-step business operations

Repositories are persistence primitives. They may run SQL and flush/commit a transaction if the caller explicitly manages a session-level transaction, but they must not independently decide business semantics or commit cross-step business operations.

Example repository interface:

```python
class MemoryRepositoryProtocol(Protocol):
    def create(self, memory: MemoryRecord) -> MemoryRecord: ...
    def get_by_id(self, memory_id: UUID) -> MemoryRecord | None: ...
    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        asset_id: str | None = None,
        facility_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MemoryRecord]: ...
    def update(self, memory: MemoryRecord) -> MemoryRecord: ...
```

### Service responsibilities

- validate required business rules
- enforce lifecycle transitions
- own transaction boundaries for multi-step business operations
- orchestrate single-transaction supersede action
- convert API DTOs to model objects or DB records
- call repository methods
- keep routes thin and isolated from logic

The `MemoryService` is the transaction owner for business operations. A repository may participate in a transaction, but the service decides when the transaction begins, what steps are included, and when it is committed or rolled back.

Example service methods:

```python
class MemoryService:
    def create_memory(self, data: MemoryCreate) -> MemoryRecord: ...
    def get_memory(self, memory_id: UUID) -> MemoryRecord: ...
    def list_memories(self, *, filters: MemoryListFilters) -> list[MemoryRecord]: ...
    def update_memory(self, memory_id: UUID, patch: MemoryUpdate) -> MemoryRecord: ...
    def archive_memory(self, memory_id: UUID) -> MemoryRecord: ...
    def dispute_memory(self, memory_id: UUID) -> MemoryRecord: ...
    def supersede_memory(self, old_memory_id: UUID, replacement_memory: MemoryCreate) -> tuple[MemoryRecord, MemoryRecord]: ...
```

### Future integration interfaces

These are intentionally defined but not implemented in Phase 1:

```python
class Neo4jMemoryAdapterProtocol(Protocol):
    def sync_memory_graph(self, record: MemoryRecord) -> None: ...


class QdrantMemoryAdapterProtocol(Protocol):
    def sync_memory_vector(self, record: MemoryRecord) -> None: ...
```

The important distinction is that these adapters are future indexing helpers, not canonical records.

---

## 6. Transaction strategy

### Design principle

PostgreSQL is the canonical source of truth for the memory engine in Phase 1.

### Supersede transaction flow

`MemoryService.supersede_memory(old_memory_id, replacement_memory)` will:

1. begin a service-owned database transaction
2. validate inputs
3. lock the existing memory row using `SELECT ... FOR UPDATE`
4. ensure the old record exists
5. reject self-superseding attempts
6. enforce allowed lifecycle transitions (only `active` may be superseded in normal flow)
7. create the replacement memory record with `status = active`
8. set old record status to `superseded`
9. set replacement_record.supersedes_memory_id = old_memory_id
10. commit the transaction

If any validation or write step fails, rollback the entire transaction and leave the database unchanged.

Example pseudocode:

```python
with session.begin():
    existing = repo.get_for_update(old_memory_id)
    if existing is None:
        raise MemoryNotFoundError(old_memory_id)

    if old_memory_id == replacement_memory.id:
        raise ValueError("A memory cannot supersede itself.")

    if existing.status in {MemoryStatus.SUPERSEDED, MemoryStatus.ARCHIVED}:
        raise InvalidLifecycleTransition(existing.status, MemoryStatus.SUPERSEDED)

    replacement = repo.create(replacement_memory)
    existing.status = MemoryStatus.SUPERSEDED
    replacement.supersedes_memory_id = old_memory_id
    repo.update(existing)
    repo.update(replacement)
```

Why row-level locking matters:

- two concurrent requests can both read the same active memory and decide to supersede it
- with `SELECT ... FOR UPDATE`, the first request locks the row immediately
- the second request waits for the first transaction to complete
- once the first transaction commits, the second request sees the updated status and fails the lifecycle validation instead of creating a second superseding lineage
- this prevents independent concurrent supersession of the same active memory record

This guarantees atomicity and strongly preserves lineage while protecting against duplicate concurrent supersede operations.

---

## 7. Indexing strategy

### Why the indexes matter

The platform will query memory records by operational context, especially:

- memory type
- lifecycle state
- asset/facility
- source type
- lineage/version relationship
- access role membership

### Phase 1 index plan

1. `id` primary key
2. `memory_type` B-tree
3. `status` B-tree
4. `asset_id` B-tree
5. `facility_id` B-tree
6. `source_type` B-tree
7. `incident_id` B-tree
8. `created_at` descending B-tree
9. `updated_at` descending B-tree
10. `supersedes_memory_id` B-tree
11. `access_roles` GIN
12. `metadata` GIN (JSONB)

This is a balanced strategy: enough coverage for a working canonical store without over-engineering the DB for future phases.

Database constraints remain authoritative for confidence and importance values in addition to service validation, so invalid values fail even when application-layer checks are bypassed.

---

## 8. Planned tests

The implementation should include tests for:

1. memory creation
2. retrieval by ID
3. list retrieval
4. each supported filter:
   - memory_type
   - status
   - asset_id
   - facility_id
   - source_type
5. update
6. archive/dispute lifecycle changes
7. superseding
8. self-superseding rejection
9. nonexistent superseded memory
10. confidence/importance validation
11. empty content/title validation
12. timezone validation
13. transaction rollback
14. persistence across database sessions
15. concurrent/duplicate supersede protection
16. illegal lifecycle transitions
17. attempts to manipulate lineage through PATCH
18. rollback after replacement creation fails
19. rollback after old-record update fails
20. PostgreSQL-specific persistence/integration tests running against PostgreSQL

### Example test categories

- `tests/test_memory_service.py`: business rules, lifecycle transitions, validation, transactional supersede
- `tests/test_memory_repository.py`: DB querying and persistence semantics
- `tests/test_memory_routes.py`: FastAPI route contracts and HTTP validation
- `tests/test_memory_integration_postgres.py`: PostgreSQL-specific persistence and locking tests
- `tests/conftest.py`: PostgreSQL test database setup and fixture management

Unit tests may fake or mock repository behavior, but PostgreSQL integration tests must run against a real PostgreSQL database instance, not SQLite.

---

## 9. Risks and tradeoffs

### Tradeoff: canonical PostgreSQL versus specialized stores

- PostgreSQL gives the strongest source-of-truth semantics and strict relational integrity
- but it is less optimized for vector similarity search or graph traversals than Neo4j and Qdrant
- this is intentional: these specialized stores are future indexes, not the canonical record model

### Tradeoff: soft lifecycle instead of hard delete

- preserves lineage and auditability
- adds complexity in filtering active vs historical states
- requires explicit status management rather than simple delete semantics

### Tradeoff: TEXT[] access_roles

- simple and performant for Phase 1
- less normalized than a dedicated role table
- acceptable because the memory model is intentionally minimal and operationally focused

### Risk: business logic leakage into API routes

Mitigation:

- keep routes thin and delegate to services
- keep validation in the service layer
- keep DB access in the repository layer

### Risk: partial supersede writes

Mitigation:

- enforce one transaction per supersede operation
- rollback all writes on failure

---

## 10. Assumptions to approve

Before implementation, these assumptions should be confirmed:

1. PostgreSQL remains the only canonical memory store in Phase 1.
2. Neo4j and Qdrant are future index/relationship layers, not canonical truth.
3. Memory records are never physically deleted through the API.
4. Lifecycle transitions use `active`, `superseded`, `disputed`, and `archived` states.
5. access_roles will be stored as a PostgreSQL `TEXT[]` column for Phase 1.
6. all supersede operations will be atomic and database-transaction scoped.
7. FastAPI route functions remain thin wrappers and do not include business logic.
8. service-layer validation is authoritative, while Pydantic enforces type-level constraints.
9. list endpoints default to ordering by `created_at` descending.
10. the implementation will use Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, PostgreSQL, and Alembic.

---

## Summary

This design establishes a strict and traceable canonical memory layer for AegisOps AI without building the later graph/vector/agent stack. PostgreSQL owns the authoritative record state, while the future Neo4j and Qdrant adapters will provide relationship-aware and semantic representations as derived views. The lifecycle is intentionally versioned and non-destructive so operational memory remains auditable, explainable, and safe for future enterprise decision support.
