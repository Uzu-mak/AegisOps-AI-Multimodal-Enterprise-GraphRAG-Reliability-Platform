# Phase 2 Design: Semantic Operational Memory

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

## 1. Updated Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Memory API (FastAPI)                       │
│  POST /memories, GET /memories/{id}, PATCH, /archive, etc.      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Memory Service                               │
│  (Business logic, lifecycle validation, transaction control)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                ┌──────────┴──────────┐
                ↓                     ↓
    ┌──────────────────────┐  ┌──────────────────────────┐
    │  Memory Repository   │  │ SemanticIndexingService  │
    │  (SQL operations)    │  │ (indexing orchestrator)  │
    └──────────────────────┘  └──────────────────────────┘
                │                     │
                ↓                     ├─→ EmbeddingProvider
        ┌───────────────┐             │  (embed_text interface)
        │  PostgreSQL   │             │
        │   (canonical) │             ↓
        └───────────────┘      ┌──────────────────┐
                               │ SemanticMemory   │
                               │    Index         │
                               │  (Qdrant ops)    │
                               └──────────────────┘
                                       │
                                       ↓
                                ┌──────────────┐
                                │   Qdrant     │
                                │  (vectors)   │
                                └──────────────┘
```

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
      - "6333:6333"      # REST API
      - "6334:6334"      # gRPC
    volumes:
      - qdrant_storage:/qdrant/storage
    environment:
      QDRANT_API_KEY: ""  # For now, no auth; add later
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
    """
    
    def __init__(self, dimension: int = 128):
        self.dimension = dimension
    
    def embed_text(self, text: str) -> list[float]:
        """
        Generate deterministic embedding from text hash.
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

## 6. Lifecycle Synchronization Strategy

**Design Principle: PostgreSQL → Qdrant; eventual consistency**

| Memory Status | Qdrant Action | Qdrant Searchable? | Notes |
|---|---|---|---|
| **ACTIVE** | Index/update vector | ✅ Yes | Full indexing |
| **DISPUTED** | Update status in payload | ✅ Yes | Marked as disputed in results |
| **ARCHIVED** | `mark_inactive("archived")` | ⚠️ Filtered | Can search but filters exclude by default |
| **SUPERSEDED** | `mark_inactive("superseded")` + `remove_memory()` | ❌ No | Remove vector; old state in PostgreSQL |

**Integration Points:**

1. **After `service.create_memory()` succeeds:**
   - FastAPI route calls `semantic_index.index_memory()`
   - If Qdrant fails: log error, continue (eventual retry)

2. **After `service.update_memory()` succeeds:**
   - If metadata/importance/confidence changed: re-embed and re-index
   - If only non-semantic fields changed: skip Qdrant

3. **After `service.archive_memory()` succeeds:**
   - Call `semantic_index.mark_inactive(memory_id, "archived")`

4. **After `service.dispute_memory()` succeeds:**
   - Call `semantic_index.mark_inactive(memory_id, "disputed")`

5. **After `service.supersede_memory()` succeeds:**
   - Call `semantic_index.remove_memory(old_memory_id)`
   - Index new replacement memory normally

---

## 7. Consistency & Failure Strategy

**Guaranteed:**
- PostgreSQL commit happens first and is never rolled back.
- If Qdrant indexing fails, PostgreSQL transaction is complete.
- PostgreSQL remains single source of truth.

**Eventual Consistency:**
- Qdrant may lag behind PostgreSQL (e.g., network timeout).
- A search result references memory_id; verification fetches from PostgreSQL.
- If Qdrant has stale metadata, PostgreSQL wins on re-fetch.

**Failure Handling Pattern:**

```python
# Pseudo-code for route
try:
    record = service.create_memory(data)  # PostgreSQL committed
    session.commit()
except (InvalidMemoryDataError, ...) as exc:
    raise HTTPException(...)

# Semantic indexing is best-effort, non-fatal
try:
    semantic_index.index_memory(
        memory_id=record.id,
        text=build_semantic_text(record),
        record=build_vector_record(record)
    )
except SemanticIndexError as exc:
    logger.warning(f"Failed to index memory {record.id} in Qdrant: {exc}")
    # Do NOT raise; memory is safe in PostgreSQL

return memory_to_response(record)
```

**Future Enhancement: Outbox Pattern**
- Create `semantic_index_queue` table in PostgreSQL.
- Each memory mutation writes an entry.
- Async job polls queue, indexes in Qdrant, marks done.
- Ensures Qdrant eventually catches up even after crashes.

---

## 8. Planned Tests

**File: `tests/integration/test_qdrant_health.py`**
- Qdrant container health check
- Collection creation
- Basic point insertion/retrieval

**File: `tests/semantic/test_fake_embedding.py`**
- Deterministic embedding generation
- Dimension validation
- Same input → same vector

**File: `tests/semantic/test_qdrant_index.py`**
- Index a memory
- Retrieve vector record
- Search similar (deterministic embeddings)
- Metadata filtering (status, asset_id, confidence)
- Update status (mark_inactive)
- Remove memory
- Handle missing memory gracefully

**File: `tests/api/test_semantic_api_integration.py`**
- POST memory → indexed in Qdrant
- GET memory → Qdrant record matches
- PATCH memory → Qdrant updated
- Archive memory → Qdrant marked inactive
- Supersede memory → Old removed, new indexed
- Qdrant failure does not affect PostgreSQL commit

**File: `tests/semantic/test_eventual_consistency.py`**
- Qdrant temporarily unavailable, PostgreSQL succeeds
- Memory queryable from PostgreSQL, missing from Qdrant
- Recovery: Qdrant re-indexed later
- Explicit re-sync endpoint (future)

---

## 9. Files to Create/Modify

| File | Action | Purpose |
|---|---|---|
| `docker-compose.yml` | **Modify** | Add Qdrant service + volume |
| `.env.example` | **Modify** | Add QDRANT_URL, QDRANT_COLLECTION_NAME |
| `app/embeddings/provider.py` | **Create** | EmbeddingProvider protocol |
| `app/embeddings/fake.py` | **Create** | DeterministicFakeEmbedding for tests |
| `app/embeddings/__init__.py` | **Create** | Package exports |
| `app/semantic/index.py` | **Create** | SemanticMemoryIndex protocol + models |
| `app/semantic/qdrant_config.py` | **Create** | Qdrant collection/payload config |
| `app/semantic/qdrant_impl.py` | **Create** | QdrantSemanticIndex implementation |
| `app/semantic/__init__.py` | **Create** | Package exports |
| `app/services/semantic_service.py` | **Create** | SemanticIndexingService (orchestrator) |
| `app/core/config.py` | **Modify** | Add QDRANT_URL, QDRANT_COLLECTION_NAME |
| `app/api/deps.py` | **Modify** | Dependency: get_semantic_index_service() |
| `app/api/routes/memories.py` | **Modify** | Call semantic indexing after service ops |
| `tests/integration/test_qdrant_health.py` | **Create** | Qdrant health + collection setup tests |
| `tests/semantic/test_fake_embedding.py` | **Create** | Deterministic embedding tests |
| `tests/semantic/test_qdrant_index.py` | **Create** | SemanticMemoryIndex integration tests |
| `tests/api/test_semantic_api_integration.py` | **Create** | End-to-end API + Qdrant tests |
| `tests/semantic/test_eventual_consistency.py` | **Create** | Qdrant failure scenarios |
| `requirements.txt` | **Modify** | Add qdrant-client |

---

## Summary: Ready for Implementation

This design ensures:
✅ **Separation of concerns**: Embedding, indexing, and API are decoupled  
✅ **Replaceability**: EmbeddingProvider interface allows future LLM swaps  
✅ **Canonical integrity**: PostgreSQL always wins; Qdrant is supplementary  
✅ **Fault tolerance**: Qdrant failures don't corrupt canonical data  
✅ **Eventual consistency**: Outbox pattern can be added later  
✅ **Deterministic testing**: Fake embeddings are fast, reproducible, no API calls  
