# AegisOps

Operational memory engine for infrastructure and asset monitoring.

AegisOps stores, retrieves, and semantically indexes operational memories — observations, incidents, diagnoses, recommendations, and more — with a durable PostgreSQL canonical store and a Qdrant vector index for semantic search.

---

## Architecture

```
API Routes (FastAPI)
       │
       ▼
Memory Service          ← owns PostgreSQL transaction boundaries
  │         │
  ▼         ▼
Repository  SemanticIndexingService   ← best-effort, called after PG commit
  │                │
  ▼                ▼
PostgreSQL       Qdrant
(canonical)    (vector index)
```

**Key principles:**
- PostgreSQL is the single source of truth. Qdrant is a derived index.
- PostgreSQL commits before any Qdrant operation is attempted.
- Qdrant failures are non-fatal — logged and skipped; the memory is safe in PostgreSQL.
- API routes are thin — no transaction control or direct Qdrant calls.

---

## Stack

| Component | Version |
|---|---|
| Python | 3.12 |
| FastAPI | 0.115 |
| SQLAlchemy | 2.0 |
| PostgreSQL | 16 |
| Alembic | 1.13 |
| Qdrant | latest (≥1.19) |
| qdrant-client | 1.11 |
| Pydantic | v2 |

---

## Memory Model

Every memory record has:

- **`memory_type`** — `observation`, `incident`, `diagnosis`, `maintenance_action`, `resolution`, `recommendation`, `document_fact`, `agent_interaction`, `feedback`
- **`status`** — `active` → `archived` / `disputed` / `superseded`
- **`title`**, **`content`** — searchable text (embedded into Qdrant)
- **`asset_id`**, **`facility_id`**, **`component_id`** — operational context
- **`confidence`**, **`importance`** — 0–1 scoring
- **`memory_metadata`** — arbitrary JSONB
- **`supersedes_memory_id`** — linked supersession chain

---

## Lifecycle Transitions

| From | To | Allowed |
|---|---|---|
| `active` | `archived` | ✅ |
| `active` | `disputed` | ✅ |
| `active` | `superseded` | ✅ (via supersede endpoint) |
| `disputed` | `active` | ✅ |
| `disputed` | `archived` | ✅ |
| any other | any | ❌ |

---

## Quickstart

### Prerequisites

- Docker Desktop (with Compose v2)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD at minimum
```

### 2. Start all services

```bash
docker compose up -d --build
```

Services started:
- `aegisops-api` → http://localhost:8000
- `aegisops-postgres` → localhost:5432
- `aegisops-qdrant` → http://localhost:6333

### 3. Check health

```bash
docker compose ps
# Expected: postgres (healthy), qdrant (healthy), api (running)

curl http://localhost:8000/docs        # FastAPI Swagger UI
curl http://localhost:6333/dashboard   # Qdrant Web UI
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/memories` | Create a memory |
| `GET` | `/api/v1/memories` | List memories (filterable) |
| `GET` | `/api/v1/memories/{id}` | Get a single memory |
| `PATCH` | `/api/v1/memories/{id}` | Update fields |
| `POST` | `/api/v1/memories/{id}/archive` | Archive |
| `POST` | `/api/v1/memories/{id}/dispute` | Mark disputed |
| `POST` | `/api/v1/memories/{id}/supersede` | Supersede with replacement |

Full schema available at http://localhost:8000/docs when running.

### Example: create a memory

```bash
curl -X POST http://localhost:8000/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "memory_type": "observation",
    "title": "Pump vibration elevated",
    "content": "Pump P-102 vibration at 12.4 mm/s, above threshold of 10 mm/s.",
    "source_type": "sensor",
    "asset_id": "pump-p102",
    "facility_id": "facility-west",
    "confidence": 0.95,
    "importance": 0.8
  }'
```

---

## Running Tests

All tests run inside the API container against the live PostgreSQL and Qdrant services.

```bash
# Full suite
docker compose exec -T api python -m pytest -q

# By suite
docker compose exec -T api python -m pytest tests/repositories/ -v
docker compose exec -T api python -m pytest tests/services/ -v
docker compose exec -T api python -m pytest tests/api/test_memory_api.py -v
docker compose exec -T api python -m pytest tests/api/test_semantic_api_integration.py -v
docker compose exec -T api python -m pytest tests/semantic/ -v
docker compose exec -T api python -m pytest tests/integration/ -v
```

### Test suites

| Suite | Tests | What it covers |
|---|---|---|
| `tests/repositories/` | 5 | SQLAlchemy repository CRUD |
| `tests/services/` | 8 | MemoryService lifecycle and transactions |
| `tests/api/test_memory_api.py` | 11 | HTTP endpoints (Phase 1) |
| `tests/api/test_semantic_api_integration.py` | 18 | Semantic indexing via API; Qdrant failure resilience |
| `tests/semantic/test_fake_embedding.py` | 8 | Deterministic embedding mechanics |
| `tests/semantic/test_qdrant_index.py` | 8 | Qdrant index operations (real Qdrant) |
| `tests/semantic/test_eventual_consistency.py` | 9 | Qdrant failure isolation |
| `tests/integration/test_qdrant_health.py` | 4 | Qdrant connectivity and collection setup |

> ⚠️ Embedding tests use `DeterministicFakeEmbedding` (SHA-256 hash-based). Vectors are reproducible but are **not** semantically meaningful. Tests verify infrastructure mechanics, not vector quality.

---

## Project Structure

```
app/
├── api/
│   ├── deps.py              # FastAPI dependency wiring
│   ├── routes/memories.py   # HTTP endpoints (thin layer)
│   └── schemas/             # Pydantic request/response models
├── core/config.py           # Settings (DATABASE_URL, QDRANT_URL, …)
├── db/
│   ├── base.py              # SQLAlchemy declarative base
│   ├── session.py           # Engine + SessionLocal
│   └── models/memory.py     # MemoryRecord ORM model
├── embeddings/
│   ├── provider.py          # EmbeddingProvider protocol
│   └── fake.py              # DeterministicFakeEmbedding
├── repositories/
│   └── memory_repository.py # Persistence-only data access (no commit/rollback)
├── semantic/
│   ├── index.py             # SemanticMemoryIndex protocol + VectorRecord
│   ├── qdrant_config.py     # Collection name constant
│   └── qdrant_impl.py       # QdrantSemanticIndex implementation
└── services/
    ├── memory_service.py    # Business logic + transaction ownership
    ├── semantic_service.py  # SemanticIndexingService orchestrator
    └── exceptions.py        # Domain exceptions

tests/
├── api/                     # API-level tests
├── integration/             # Qdrant health / connectivity
├── repositories/            # Repository-level tests
├── semantic/                # Semantic indexing unit tests
└── services/                # Service-level tests

alembic/                     # Database migrations
docs/design/                 # Architecture design documents
```

---

## Database Migrations

```bash
# Apply all migrations
docker compose exec api alembic upgrade head

# Create a new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Check current revision
docker compose exec api alembic current
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Full PostgreSQL connection URL (required) |
| `POSTGRES_DB` | — | Database name |
| `POSTGRES_USER` | — | Database user |
| `POSTGRES_PASSWORD` | — | Database password |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant REST endpoint |
| `QDRANT_COLLECTION_NAME` | `memories` | Qdrant collection name |

> The Docker Compose `api` service constructs `DATABASE_URL` internally using `postgres` (the Compose service hostname), overriding any `localhost`-based value in `.env`. The `.env` file's `DATABASE_URL` is used when running directly on the host.

---

## Stopping / Cleaning Up

```bash
# Stop services (preserves volumes)
docker compose down

# Stop and remove all data volumes
docker compose down -v
```

