# Phase 2 Design: Semantic Operational Memory (CORRECTED)

## Overview

Add Qdrant as a semantic representation/index for canonical memories stored in PostgreSQL.

**Current State:**

- Dockerized FastAPI + PostgreSQL
- Alembic canonical memory schema
- repository/service/API architecture
- memory lifecycle and transactional supersession
- complete test suite passing
- manual POST and GET requests verified end to end

**Goals:**

- Add Qdrant as a separate Docker Compose service
- PostgreSQL remains canonical source of truth
- Qdrant records reference PostgreSQL memory UUIDs
- Separate semantic/vector adapter from repository and service logic
- No Qdrant calls directly in FastAPI routes
- No LLM generation, agents, GraphRAG, Neo4j, Kafka, ML, or vision yet

---

## 1. Updated Architecture (CORRECTED)

```
┌──────────────────────────────────────────────────────────┐
│              Memory API Routes (FastAPI)                 │
│  POST /memories, GET /memories/{id}, PATCH, etc.         │
│  ▪ Parse request                                         │
│  ▪ Call service                                          │
│  ▪ Return response                                       │
│  ✗ NO transaction control                               │
│  ✗ NO Qdrant calls                                       │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ↓
┌──────────────────────────────────────────────────────────┐
│             Memory Service (Orchestrator)                │
│  ▪ Business logic                                        │
│  ▪ Lifecycle validation                                  │
│  ▪ Transaction control (PostgreSQL COMMIT)              │
│  ▪ Orchestrate semantic indexing (best-effort)          │
│  ▪ Handle failures                                       │
└────────┬─────────────────────────────────────────────────┘
         │
    ┌────┴─────┐
    │           │
    ↓           ↓
 Repository  SemanticIndexingService
    │           │
    │           ├─→ EmbeddingProvider
    │           │   (embed_text interface)
    │           │
    │           ↓
    │       SemanticMemoryIndex
    │       (Qdrant adapter)
    │           │
    ↓           ↓
┌──────────────────────┐
│    PostgreSQL        │
│  (canonical source)  │
│  (after commit)      │
└──────────────────────┘

                   ┌──────────────────┐
                   │   Qdrant         │
                   │  (best-effort    │
                   │   vector index)  │
                   └──────────────────┘
```

**Key Principles:**

- **API routes** are thin; they do NOT control transactions or call Qdrant.
- **MemoryService** owns PostgreSQL transaction boundaries and orchestrates semantic indexing.
- **SemanticIndexingService** is called AFTER PostgreSQL commit succeeds.
- **Qdrant failure** never rolls back PostgreSQL; it is logged and will be retried later (outbox pattern).

---

## 2. Docker Compose Service Design

**Addition to `docker-compose.yml`:**

```yaml
services:
  app:
    # (existing FastAPI service)

  postgres:
    # (existing PostgreSQL service)

  qdrant:
    image: qdrant/qdrant:latest
    container_name: aegisops-qdrant
    ports:
      - "6333:6333" # REST API
      - "6334:6334" # gRPC
    volumes:
      - qdrant_storage:/qdrant/storage
    environment:
      QDRANT_API_KEY: "" # For now, no auth; add later
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 5s
      timeout: 2s
      retries: 5
    networks:
      - default

volumes:
  qdrant_storage:

networks:
  default:
    driver: bridge
```

**App environment variables (`.env.example`):**

```
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION_NAME=memories
```

---

## 3. EmbeddingProvider Interface

**File: `app/embeddings/provider.py`**

```python
from typing import Protocol


class EmbeddingProvider(Protocol):
    """
    Replaceability pattern: embedding generation strategy.
    Allows deterministic fakes for tests, real models in production.
    """

    def embed_text(self, text: str) -> list[float]:
        """
        Embed a text string into a vector.

        Args:
            text: The text to embed (title + content + context)

        Returns:
            A list of floats representing the embedding vector

        Raises:
            EmbeddingError: If embedding generation fails
        """
        ...

    def get_dimension(self) -> int:
        """Return the embedding dimension (e.g., 384, 768, 1536)."""
        ...


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass
```

**Deterministic fake for tests: `app/embeddings/fake.py`**

```python
import hashlib
from app.embeddings.provider import EmbeddingProvider


class DeterministicFakeEmbedding(EmbeddingProvider):
    """
    Deterministic fake embedding for testing.
    Same input always produces same vector.
    Dimension: 128 (small for test speed).

    ⚠️ WARNING: Hash-based vectors are NOT semantic embeddings.
    This class is for testing infrastructure (ranking, filtering, retrieval)
    NOT for testing semantic similarity or quality.
    """

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        """
        Generate deterministic embedding from text hash.
        Same input always produces the same vector.
        """
        hash_bytes = hashlib.sha256(text.encode()).digest()
        vector = []
        for i in range(self.dimension):
            byte_index = i % len(hash_bytes)
            # Normalize to [-1, 1]
            value = (hash_bytes[byte_index] / 128.0) - 1.0
            vector.append(value)
        return vector

    def get_dimension(self) -> int:
        return self.dimension
```

---

## 4. SemanticMemoryIndex Interface

**File: `app/semantic/index.py`**

```python
from typing import Any, Optional, Protocol
from uuid import UUID
from datetime import datetime


class VectorRecord:
    """Payload stored alongside vector in Qdrant."""

    def __init__(
        self,
        memory_id: UUID,
        memory_type: str,
        status: str,
        asset_id: Optional[str],
        facility_id: Optional[str],
        source_type: str,
        created_at: datetime,
        importance: float,
        confidence: float,
    ):
        self.memory_id = memory_id
        self.memory_type = memory_type
        self.status = status
        self.asset_id = asset_id
        self.facility_id = facility_id
        self.source_type = source_type
        self.created_at = created_at
        self.importance = importance
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        """Convert to Qdrant payload dict."""
        return {
            "memory_id": str(self.memory_id),
            "memory_type": self.memory_type,
            "status": self.status,
            "asset_id": self.asset_id,
            "facility_id": self.facility_id,
            "source_type": self.source_type,
            "created_at": self.created_at.isoformat(),
            "importance": self.importance,
            "confidence": self.confidence,
        }


class SemanticSearchResult:
    """Result from semantic search."""

    def __init__(
        self,
        memory_id: UUID,
        score: float,
        record: VectorRecord,
    ):
        self.memory_id = memory_id
        self.score = score
        self.record = record


class SemanticMemoryIndex(Protocol):
    """
    Vector index for memories.
    Qdrant stores vectors + metadata; PostgreSQL remains canonical.
    """

    def index_memory(self, memory_id: UUID, text: str, record: VectorRecord) -> None:
        """
        Index a memory by embedding its text and storing vector + metadata.

        Args:
            memory_id: UUID of the memory (used as Qdrant point ID)
            text: Text to embed (title + content + context)
            record: VectorRecord with metadata

        Raises:
            SemanticIndexError: If indexing fails (non-fatal)
        """
        ...

    def get_vector_record(self, memory_id: UUID) -> Optional[VectorRecord]:
        """
        Retrieve metadata stored alongside a vector.
        Returns None if not found in Qdrant.
        """
        ...

    def search_similar(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[SemanticSearchResult]:
        """
        Search for semantically similar memories.

        Args:
            query_vector: Embedding vector to search
            limit: Max results
            filters: Optional metadata filters (e.g., {"status": "active"})

        Returns:
            List of results with memory_id, score, and metadata
        """
        ...

    def remove_memory(self, memory_id: UUID) -> None:
        """
        Remove a memory's vector record from Qdrant.
        Called on supersession or explicit deletion.

        Raises:
            SemanticIndexError: If removal fails (non-fatal)
        """
        ...

    def mark_inactive(self, memory_id: UUID, new_status: str) -> None:
        """
        Mark a memory as archived/disputed without removing vector.
        Updates status in Qdrant payload.

        Args:
            memory_id: UUID of memory
            new_status: New status string (e.g., "archived")

        Raises:
            SemanticIndexError: If update fails (non-fatal)
        """
        ...


class SemanticIndexError(Exception):
    """Raised when semantic indexing fails (non-fatal)."""
    pass
```

---

## 5. Qdrant Collection & Payload Design

**File: `app/semantic/qdrant_config.py`**

```python
from qdrant_client.models import (
    CollectionStatus,
    PointStruct,
    RecreateCollection,
    VectorParams,
    Distance,
)

COLLECTION_NAME = "memories"
EMBEDDING_DIMENSION = 128  # Override for real embeddings (e.g., 768)

def get_collection_creation_config(embedding_dim: int):
    """
    Qdrant collection schema for semantic memories.
    """
    return {
        "name": COLLECTION_NAME,
        "vectors_config": VectorParams(
            size=embedding_dim,
            distance=Distance.COSINE,
        ),
        # Payload schema (for type hints; Qdrant is schemaless)
        "payload_schema": {
            "memory_id": {"type": "text"},
            "memory_type": {"type": "text"},
            "status": {"type": "text"},  # active, disputed, archived, superseded
            "asset_id": {"type": "text"},
            "facility_id": {"type": "text"},
            "source_type": {"type": "text"},
            "created_at": {"type": "text"},  # ISO 8601
            "importance": {"type": "float"},
            "confidence": {"type": "float"},
        }
    }

def point_from_vector_record(
    memory_id_int: int,  # Convert UUID to int for Qdrant point ID
    vector: list[float],
    record: dict,
) -> PointStruct:
    """Convert memory + embedding to Qdrant PointStruct."""
    return PointStruct(
        id=memory_id_int,
        vector=vector,
        payload=record,
    )
```

**Implementation Notes:**

- UUID to Point ID conversion: Convert memory UUID to a stable integer hash for Qdrant point ID.
  Example: `int(uuid.hex, 16) % (2**63 - 1)` to fit within Qdrant's int64 range.
- Do NOT store full MemoryRecord in Qdrant payload; only store metadata for filtering/ranking.
- Actual memory data is always fetched from PostgreSQL after search.

**Qdrant query examples:**

```python
# Search active/disputed memories only
filters = {
    "must": [
        {
            "key": "status",
            "match": {"any": ["active", "disputed"]}
        }
    ]
}

# Filter by asset and confidence threshold
filters = {
    "must": [
        {"key": "asset_id", "match": {"value": "asset-123"}},
        {"key": "confidence", "range": {"gte": 0.7}},
    ]
}
```

---

## 6. Lifecycle Synchronization Strategy (CORRECTED)

**Design Principle: PostgreSQL → Qdrant; eventual consistency; failures are non-fatal**

| Memory Status  | Qdrant Action               | Searchable? | PostgreSQL            | Notes                                                             |
| -------------- | --------------------------- | ----------- | --------------------- | ----------------------------------------------------------------- |
| **ACTIVE**     | `index_memory()`            | ✅ Yes      | Retained              | Full indexing                                                     |
| **DISPUTED**   | `mark_inactive("disputed")` | ✅ Yes      | Retained              | Marked as disputed; searchable with filters                       |
| **ARCHIVED**   | `mark_inactive("archived")` | ⚠️ Filtered | Retained              | Marked; excluded by default                                       |
| **SUPERSEDED** | `remove_memory()`           | ❌ No       | Retained (historical) | Old record removed from index; kept in PostgreSQL for audit trail |

**Transaction Flow (PostgreSQL FIRST):**

1. **MemoryService.create_memory()** calls service methods:
   - Creates memory in PostgreSQL via repository
   - Calls `session.commit()` ← **PostgreSQL transaction succeeds**

2. If PostgreSQL commit succeeds:
   - MemoryService calls `semantic_index_service.index_memory(memory_id, text, record)`
   - If Qdrant fails: log error, continue (memory is safe in PostgreSQL)

3. API route receives successful response and returns to client

**Integration Points (all in MemoryService):**

1. **After `service.create_memory()` commits:**
   - Call `semantic_indexing_service.index_memory()`
   - Non-fatal failure: log, continue

2. **After `service.update_memory()` commits:**
   - If semantic fields changed (title, content, confidence, importance): re-embed and re-index
   - If only non-semantic fields changed: skip Qdrant

3. **After `service.archive_memory()` commits:**
   - Call `semantic_indexing_service.mark_inactive(memory_id, "archived")`
   - Non-fatal failure: log, continue

4. **After `service.dispute_memory()` commits:**
   - Call `semantic_indexing_service.mark_inactive(memory_id, "disputed")`
   - Non-fatal failure: log, continue

5. **After `service.supersede_memory()` commits:**
   - Call `semantic_indexing_service.remove_memory(old_memory_id)` ← Remove from search, NOT mark inactive
   - PostgreSQL retains superseded record for audit trail
   - Index new replacement memory normally
   - Non-fatal failure: log, continue

**No double state changes:** Do NOT call both `mark_inactive()` and then `remove_memory()` on the same record.
Superseded memories are simply removed from the searchable index while the PostgreSQL record remains.

---

## 7. Consistency & Failure Strategy (CORRECTED)

**Guaranteed Properties:**

1. **PostgreSQL commits first, always**
   - MemoryService controls `session.commit()` before ANY Qdrant operation
   - API routes never call commit/rollback
   - Repositories never call commit/rollback
   - If PostgreSQL commit fails, an exception is raised and no Qdrant operation is attempted

2. **Qdrant failure is non-fatal**
   - If Qdrant indexing, removal, or status update fails, PostgreSQL transaction remains committed
   - PostgreSQL state is already persisted
   - Error is logged with memory_id for manual inspection or automated retry
   - API route returns success (memory is safely stored in PostgreSQL)

3. **PostgreSQL remains single source of truth**
   - Qdrant is purely a derived/supplementary index
   - Qdrant outages do not block memory operations
   - Qdrant may be out-of-sync with PostgreSQL temporarily; eventual consistency is acceptable

**Failure Handling Pattern (MemoryService):**

```python
# Example: create_memory()
def create_memory(self, *, data: MemoryCreateData) -> MemoryRecord:
    self._validate_create_data(data)

    with self.session_factory() as session:
        memory = self._build_memory_from_data(data)
        created = self.repository.create(session, memory)
        session.commit()  # ← PostgreSQL commit FIRST
        materialized = self._materialize_memory_for_return(session, created)

    # ← Qdrant indexing is AFTER PostgreSQL commit
    try:
        semantic_indexing_service.index_memory(
            memory_id=materialized.id,
            text=build_semantic_text(materialized),
            record=build_vector_record(materialized)
        )
    except SemanticIndexError as exc:
        logger.warning(f"Failed to index memory {materialized.id}: {exc}")
        # Do NOT raise; memory is safe in PostgreSQL

    return materialized
```

**Future Enhancement: Outbox/Event Pattern**

- Create `semantic_index_queue` table in PostgreSQL
- MemoryService writes indexing requests to queue (same transaction as memory creation)
- Async job polls queue, indexes in Qdrant, marks complete
- Ensures Qdrant eventually catches up even after service crashes
- Prevents repeated indexing requests

**Current Phase 2 Scope:**

- Qdrant failure → log only
- Outbox pattern → Phase 3 or later

---

## 8. Planned Tests (CORRECTED)

**File: `tests/semantic/test_fake_embedding.py`**

- Deterministic embedding generation
- Dimension validation
- **Same input always produces same vector** (key property for reproducible tests)
- ⚠️ **Does NOT test semantic similarity** — hash-based vectors are not semantic embeddings
- Test determinism property only, not vector quality

**File: `tests/semantic/test_qdrant_index.py`**

- Index a memory via `SemanticMemoryIndex.index_memory()`
- Retrieve vector record via `get_vector_record()`
- Search similar using deterministic embeddings via `search_similar()`
- Metadata filtering (status, asset_id, confidence) — test filter mechanics
- Status update via `mark_inactive()` — test payload update mechanics
- Memory removal via `remove_memory()` — test deletion mechanics
- Handle missing memory gracefully (None return)
- Re-index idempotency (index same memory twice, verify no duplicates)
- ⚠️ **Tests verify infrastructure behavior only**: ranking, filtering, retrieval mechanics
- ⚠️ **Tests do NOT verify semantic correctness** — hash vectors are not semantically meaningful

**File: `tests/api/test_semantic_api_integration.py`**

- POST memory → verify indexed in Qdrant
- GET memory → verify retrievable from PostgreSQL (Qdrant is supplementary)
- PATCH memory with semantic fields → verify Qdrant updated
- Archive memory → verify Qdrant marked inactive
- Dispute memory → verify Qdrant marked inactive
- Supersede memory → verify old removed from Qdrant, new indexed
- Qdrant unavailable → PostgreSQL operation succeeds, error logged
- Semantic indexing failure → memory safe in PostgreSQL, HTTP 201/200 returned

**File: `tests/semantic/test_eventual_consistency.py`**

- Qdrant temporarily unavailable (connection timeout)
- PostgreSQL operation succeeds, Qdrant call is retried/logged
- Memory queryable from PostgreSQL, missing from Qdrant
- Recovery: Qdrant indexing succeeds on retry or manual sync (future)
- Verify PostgreSQL is never rolled back due to Qdrant failure

---

## 9. Files to Create/Modify

| File                                          | Action     | Purpose                                  |
| --------------------------------------------- | ---------- | ---------------------------------------- |
| `docker-compose.yml`                          | **Modify** | Add Qdrant service + volume              |
| `.env.example`                                | **Modify** | Add QDRANT_URL, QDRANT_COLLECTION_NAME   |
| `app/embeddings/provider.py`                  | **Create** | EmbeddingProvider protocol               |
| `app/embeddings/fake.py`                      | **Create** | DeterministicFakeEmbedding for tests     |
| `app/embeddings/__init__.py`                  | **Create** | Package exports                          |
| `app/semantic/index.py`                       | **Create** | SemanticMemoryIndex protocol + models    |
| `app/semantic/qdrant_config.py`               | **Create** | Qdrant collection/payload config         |
| `app/semantic/qdrant_impl.py`                 | **Create** | QdrantSemanticIndex implementation       |
| `app/semantic/__init__.py`                    | **Create** | Package exports                          |
| `app/services/semantic_service.py`            | **Create** | SemanticIndexingService (orchestrator)   |
| `app/core/config.py`                          | **Modify** | Add QDRANT_URL, QDRANT_COLLECTION_NAME   |
| `app/api/deps.py`                             | **Modify** | Dependency: get_semantic_index_service() |
| `app/api/routes/memories.py`                  | **Modify** | Call semantic indexing after service ops |
| `tests/integration/test_qdrant_health.py`     | **Create** | Qdrant health + collection setup tests   |
| `tests/semantic/test_fake_embedding.py`       | **Create** | Deterministic embedding tests            |
| `tests/semantic/test_qdrant_index.py`         | **Create** | SemanticMemoryIndex integration tests    |
| `tests/api/test_semantic_api_integration.py`  | **Create** | End-to-end API + Qdrant tests            |
| `tests/semantic/test_eventual_consistency.py` | **Create** | Qdrant failure scenarios                 |
| `requirements.txt`                            | **Modify** | Add qdrant-client                        |

**Implementation Constraints:**

1. **Do NOT modify existing API routes** to add transaction control. Keep routes thin.
2. **Do NOT add Qdrant calls to routes.** All semantic operations belong in SemanticIndexingService.
3. **Do NOT modify `MemoryRepository` to commit/rollback.** It remains persistence-only.
4. **Do NOT rename existing Docker Compose services.** Use current service names (app, postgres, etc.).
5. **Do NOT claim hash-based deterministic embeddings test semantic similarity.**
   Tests verify mechanics and infrastructure, not vector quality.
6. **Do NOT add OpenAI, local ML models, Kafka, Neo4j, GraphRAG, or vision APIs yet.**
   EmbeddingProvider is replaceable; keep it an interface.

---

## Summary: Ready for Implementation

This design ensures:
✅ **Transaction integrity**: PostgreSQL commits first; Qdrant failures never roll back  
✅ **Thin routes**: No transaction/Qdrant logic in API layer  
✅ **Service ownership**: MemoryService controls orchestration and failures  
✅ **Eventual consistency**: Qdrant lags acceptable; outbox pattern for Phase 3  
✅ **Honest testing**: Deterministic fakes test mechanics, not semantics  
✅ **Extensibility**: EmbeddingProvider interface ready for future implementations
