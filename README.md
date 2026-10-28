# AegisOps

**Operational memory for infrastructure and industrial asset operations.** AegisOps captures observations, incidents, diagnoses, actions, and resolutions, then makes them available through semantic, graph, and hybrid retrieval.

[Quickstart](#quickstart) · [Architecture](#architecture) · [API](#api) · [Testing](#testing) · [Retrieval evaluation](#retrieval-evaluation) · [Configuration](#configuration)

<details>
<summary>At a glance</summary>

| Concern | AegisOps component |
| --- | --- |
| Canonical memory and lifecycle | PostgreSQL |
| Semantic index | Qdrant |
| Entity and relationship projection | Neo4j |
| Durable projection events | PostgreSQL outbox and Kafka |
| HTTP API and OpenAPI docs | FastAPI |
| Operator experience | Web console served by the API at `/console` |
| Projection delivery | Outbox projection worker (PostgreSQL outbox to Qdrant and Neo4j) |
| Evidence-grounded answering | GraphRAG pipeline with configured LLM provider |

</details>

## Architecture

PostgreSQL owns canonical memory content. Qdrant and Neo4j are derived retrieval projections. Every write commits the record and its outbox events in one transaction; the API then makes a best-effort synchronous projection, and the **projection worker** drains the outbox so that any projection missed while a store was down is applied once it returns. The outbox publisher also emits each event to Kafka for downstream consumers (no Kafka consumer group is part of this repository). A successful database commit is never rolled back when an index operation fails.

```mermaid
flowchart LR
    Operator[Operator or client] --> UI[Web console /console]
    Operator --> API[FastAPI]
    UI --> API

    API --> Routes[Memory, search, system routes]
    Routes --> Service[Memory service]
    Service --> Repo[Memory repository]
    Repo --> PG[(PostgreSQL\ncanonical memories)]
    Service --> Outbox[(Projection outbox\nsame transaction)]

    Service -. after commit .-> Semantic[Semantic indexing service]
    Semantic --> Qdrant[(Qdrant\nvector projection)]
    Service -. after commit .-> Graph[Graph projection service]
    Graph --> Neo4j[(Neo4j\ngraph projection)]

    Outbox --> Worker[Projection worker]
    Worker --> Qdrant
    Worker --> Neo4j
    Outbox --> Publisher[Outbox publisher]
    Publisher --> Kafka[(Kafka\nprojection event topic)]
```

### Retrieval path

```mermaid
flowchart TD
    Query[Search request] --> Retriever[Hybrid memory retriever]
    Retriever --> Embed[Embedding provider]
    Embed --> Qdrant[(Qdrant semantic search)]
    Qdrant --> SemanticHits[Memory IDs and scores]
    Retriever --> Neo4j[(Neo4j graph traversal)]
    SemanticHits --> Anchor[Semantic hit can anchor graph expansion]
    Anchor --> Neo4j
    SemanticHits --> Merge[Merge and deduplicate]
    Neo4j --> Merge
    Merge --> Hydrate[Hydrate canonical records]
    Hydrate --> PG[(PostgreSQL)]
    PG --> Response[Retrieval results]
```

**Retrieval contract:** Qdrant and Neo4j return candidate memory IDs. PostgreSQL hydrates the canonical records returned by the API, and only `active` records are returned unless the request sets `include_inactive`, so archived, disputed and superseded memories never become answer evidence by accident. In graph mode, supply an `anchor_memory_id` when the query does not otherwise provide an anchor. When neither projection store returns candidates, GraphRAG falls back to a bounded PostgreSQL keyword match and reports `retrieval_mode: "keyword_fallback"`.

### Memory lifecycle

```mermaid
stateDiagram-v2
    [*] --> active
    active --> archived
    active --> disputed
    active --> superseded: supersede with replacement
    disputed --> active: restore
    disputed --> archived
```

## Quickstart

<details open>
<summary>Start the local stack</summary>

**Requirements:** Docker Desktop or Docker Engine with Compose v2.

1. Configure local environment:

   ```bash
   cp .env.example .env
   ```

   Set a local `POSTGRES_PASSWORD` in `.env`. For anything beyond local development, use managed secrets and rotate credentials.

2. Build and start services:

   ```bash
   docker compose up -d --build
   ```

3. Create or upgrade the database schema:

  ```bash
  docker compose exec -T api alembic upgrade head
  ```

4. Check status and health:

   ```bash
   docker compose ps
   curl http://localhost:8000/health
   curl http://localhost:8000/api/v1/system/health
   ```

5. Open the interactive API documentation:

   - Swagger UI: <http://localhost:8000/docs>
   - ReDoc: <http://localhost:8000/redoc>
   - Web console: <http://localhost:8000/console> (also the redirect target of `/`)
   - Qdrant dashboard: <http://localhost:6333/dashboard>
   - Neo4j Browser: <http://localhost:7474>

</details>

### Compose services

| Service | Purpose | Local endpoint |
| --- | --- | --- |
| `api` | FastAPI memory, retrieval, health, and observability routes | `http://localhost:8000` |
| `postgres` | Canonical memory database and projection outbox | `localhost:5432` |
| `qdrant` | Vector index | `http://localhost:6333` |
| `neo4j` | Graph projection and traversal | `http://localhost:7474`, Bolt `localhost:7687` |
| `kafka` | Projection event transport | `localhost:9092` |
| `outbox-publisher` | Publishes committed outbox events to Kafka | Internal service |
| `projection-worker` | Applies pending outbox events to Qdrant and Neo4j with bounded retries | Internal service |
| `ui` (profile `legacy-ui`) | Previous Streamlit interface, kept for reference | `docker compose --profile legacy-ui up ui`, then `http://localhost:8501` |

## Web console

The API serves an operator console at `/console`: plant overview with a live pipeline schematic, incidents as timelines, record management with lifecycle actions, evidence-cited answers, search, relationship graphs, a retrieval benchmark runner, and system health.

![Plant overview showing the memory pipeline with Neo4j unavailable](docs/images/console-overview.png)

Design follows ANSI/ISA-101 high-performance HMI practice: a calm grey display where colour is reserved for abnormal states, and every state also carries an icon and a word. It targets WCAG 2.2 AA: keyboard operation throughout (press `?` for shortcuts), visible focus, landmarks and a skip link, labelled forms with inline errors, reduced-motion support, light and dark displays, and a stacked layout on phones. It has no build step and no third-party runtime dependencies; fonts are bundled so it renders the same on networks without internet access. Sample data loaded from the console is flagged `is_synthetic` and labelled "Sample data".

![Ask AegisOps answer with cited evidence, dark display](docs/images/console-ask-dark.png)

## Reliability fixes (October 2026)

| Problem | Effect | Fix |
| --- | --- | --- |
| Each request built new Qdrant and Neo4j clients, verified connectivity, re-ran Neo4j constraint bootstrap, and never closed the driver | With a store unreachable, **every** request (including PostgreSQL-only ones like listing memories) took about 35 s, beyond the UI's 10 s timeout, so pages failed to load | `app/core/connections.py`: one cached client per store, 2 s connect timeouts, a 15 s fail-fast window after a failure, one-time bootstrap, cleanup on shutdown. Measured locally: 35 s per request before; about 4 s once, then about 10 ms |
| Outbox rows stayed `pending` forever; nothing applied them | Projections missed during an outage were never retried; backlog metrics only grew | `app/outbox/projection_worker.py` and the `projection-worker` service. Unreachable stores defer events without spending retries |
| Hydration did not filter lifecycle status | Archived, disputed or superseded memories could be cited as evidence | Active-only by default; `include_inactive` to opt in |
| Test LLM provider counted the prompt's own `[Memory N]` instruction as evidence | Reported "1 retrieved record" when none were retrieved | Counts real evidence blocks only |
| `LLM_PROVIDER=openai` with a key but no `openai` package raised in a dependency | GraphRAG returned HTTP 500 | Falls back to the labelled test provider; health reports `active_model` and `synthetic` |
| Qdrant search used `QdrantClient.search()`, removed in newer clients | Upgrading qdrant-client would silently return no semantic results | Uses `query_points()` when available |
| Health and metrics endpoints opened fresh clients (and an unbounded Kafka admin probe) on every call | Slow health checks that themselves timed out | Reuse cached clients; bounded Kafka probe timeouts |

## API

Feature routes are under `/api/v1`; the process health check is at `/health`. The OpenAPI schema at `/docs` is the authoritative source for request and response details.

<details>
<summary>Memory and system routes</summary>

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/memories` | Create a memory |
| `GET` | `/memories` | List and filter memories |
| `GET` | `/memories/{id}` | Fetch one canonical memory |
| `PATCH` | `/memories/{id}` | Update a memory |
| `POST` | `/memories/{id}/archive` | Archive a memory |
| `POST` | `/memories/{id}/dispute` | Mark a memory disputed |
| `POST` | `/memories/{id}/supersede` | Replace a memory and preserve its history |
| `POST` | `/search/semantic` | Search Qdrant and hydrate results from PostgreSQL |
| `POST` | `/search/hybrid` | Run semantic, graph, or hybrid retrieval |
| `POST` | `/search/graph-related` | Traverse graph relationships from a memory anchor |
| `POST` | `/graphrag/query` | Retrieve evidence and generate an answer |
| `GET` | `/system/health` | Check database, index, graph, and LLM health |
| `GET` | `/system/memory-stats` | Count memories by type and status |
| `GET` | `/system/outbox-stats` | Inspect projection outbox status |
| `GET` | `/system/observability` | Read application/runtime metrics |

</details>

<details>
<summary>Create a memory with curl</summary>

```bash
curl -X POST http://localhost:8000/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "memory_type": "observation",
    "title": "Pump vibration elevated",
    "content": "Pump P-102 vibration is above the configured operating threshold.",
    "source_type": "sensor",
    "asset_id": "pump-p102",
    "facility_id": "facility-west",
    "confidence": 0.95,
    "importance": 0.8
  }'
```

</details>

<details>
<summary>Run hybrid retrieval with curl</summary>

```bash
curl -X POST http://localhost:8000/api/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Pump P-102 vibration increased after maintenance",
    "mode": "hybrid",
    "limit": 10,
    "graph_hops": 2
  }'
```

</details>

## Testing

Run tests in the API container so database-backed tests use the same Compose network and environment as the application.

```bash
# Full suite
docker compose exec -T api python -m pytest -q

# Focused suites
docker compose exec -T api python -m pytest tests/api/ -q
docker compose exec -T api python -m pytest tests/services/ -q
docker compose exec -T api python -m pytest tests/retrieval/ tests/semantic/ tests/graph/ -q
docker compose exec -T api python -m pytest tests/evals/ -q
```

> **Embedding note:** the default `DeterministicFakeEmbedding` is a repeatable SHA-256-based test embedding, not a semantic model. It is useful for deterministic integration tests and plumbing checks, but its similarity results should not be interpreted as semantic retrieval quality.

## Retrieval evaluation

Two datasets are intentionally kept separate:

- **Human-labeled gold standard:** `evals/queries.jsonl`. This file is never written by the source-grounded generator.
- **Source-grounded weak supervision:** `data/evaluation/source_grounded_queries.json`, generated from manufacturer source records with canonical memory IDs and a source manifest.

> **These metrics come from a source-grounded / weakly-supervised benchmark. Relevance labels were derived from manufacturer troubleshooting records rather than independently authored human judgments.**

<details>
<summary>Generate and run the source-grounded benchmark</summary>

Rebuild the Compose image first so it contains the current repository files, then generate/import the source records and run the benchmark:

```bash
docker compose up -d --build

docker compose exec -T api python -m evals.source_grounded_dataset \
  --api-url http://localhost:8000 \
  --qdrant-url http://qdrant:6333

docker compose exec -T api python -m evals.run_benchmark \
  --dataset source-grounded --k 10 --repeats 5 --warmup 1
```

The runner validates source metadata, query IDs, relevance IDs, and membership in both the generated corpus and canonical PostgreSQL. It uses a separate Qdrant collection for the source-grounded corpus and rejects retrieval candidates outside that corpus.

The container writes generated datasets and results under `/app/data/evaluation` and `/app/results/evaluation/source_grounded`. Copy them into the checkout to retain them outside the container:

```bash
docker cp aegisops-api:/app/data/evaluation ./data/evaluation
docker cp aegisops-api:/app/results/evaluation/source_grounded ./results/evaluation
```

Each timestamped result directory contains `summary.json`, `summary.csv`, `per_query_results.csv`, `benchmark_metadata.json`, `source_manifest.json`, and `summary.md`.

</details>

<details>
<summary>Run the human-labeled benchmark</summary>

Create `evals/queries.jsonl` from the template, replace all example labels with human judgments referencing canonical PostgreSQL UUIDs, then run:

```bash
docker cp evals/queries.jsonl aegisops-api:/app/evals/queries.jsonl
docker compose exec -T api python -m evals.validate_queries --file evals/queries.jsonl
docker compose exec -T api python -m evals.run_benchmark --dataset human-labeled \
  --queries evals/queries.jsonl --k 10 --repeats 5 --warmup 1
docker cp aegisops-api:/app/evals/results ./evals/results
```

The human-labeled file is not included in the repository by default. The template at `evals/queries.template.jsonl` is not a valid benchmark dataset.

</details>

### Current source-grounded dataset limits

The checked-in seed corpus contains six records derived from one KEYENCE IV4 source page, expanded into ten fixed-template queries per record. These 60 queries are not 60 independent field incidents. Results from the current fake embedding provider validate execution and retrieval plumbing only. Broader retrieval conclusions require more independently sourced manufacturer records and a semantic embedding provider.

See the [evaluation guide](evals/README.md), [generated source manifest](data/evaluation/source_manifest.json), and [latest benchmark summary](results/evaluation/source_grounded/20261005T235309Z/summary.md).

## Database migrations

```bash
# Apply committed migrations
docker compose exec -T api alembic upgrade head

# Inspect the current migration revision
docker compose exec -T api alembic current

# Generate a migration after changing SQLAlchemy models
docker compose exec -T api alembic revision --autogenerate -m "describe change"
```

## Configuration

Compose supplies service hostnames such as `postgres`, `qdrant`, and `neo4j` to containers. When running code directly on the host, use host-published addresses and provide the required environment variables in that shell.

| Variable | Compose default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | constructed from Postgres variables | SQLAlchemy connection string; required by the app |
| `POSTGRES_DB` | `aegisops` in `.env.example` | Database name |
| `POSTGRES_USER` | `aegisops` in `.env.example` | Database user |
| `POSTGRES_PASSWORD` | `change_me` in `.env.example` | Local database password; replace before use |
| `POSTGRES_HOST` | `postgres` | Database hostname inside Compose |
| `POSTGRES_PORT` | `5432` | Database port |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant endpoint |
| `QDRANT_COLLECTION_NAME` | `memories` | Production semantic collection |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j Bolt endpoint |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `aegisops` in Compose | Neo4j local-development password |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka bootstrap address |
| `KAFKA_PROJECTION_TOPIC` | `aegisops.memory.projections.v1` | Projection event topic |
| `LLM_PROVIDER` | `test` in Compose | GraphRAG provider selection |
| `LLM_MODEL` | configured model name | Model identifier for the configured provider |
| `OPENAI_API_KEY` | unset | Provider credential when required |
| `EMBEDDING_PROVIDER` | `fake` | `fake` (SHA-256 test vectors) or `hashed_terms` (lexical term hashing); re-project records after switching |
| `PROJECTION_CONNECT_TIMEOUT_SECONDS` | `2` | Connect timeout for Qdrant, Neo4j and the Kafka health probe |
| `PROJECTION_RETRY_SECONDS` | `15` | After a failed connect, requests skip that store for this long instead of waiting on it again |
| `OUTBOX_WORKER_POLL_SECONDS` | `2.0` | Idle poll interval for the projection worker |

## Project map

<details>
<summary>Expand repository structure</summary>

```text
app/
  agents/          agent workflow, state, tools, and critic
  api/             FastAPI routes, schemas, dependencies, errors
  console/static/  web console (HTML, CSS, JS, self-hosted OFL fonts; no build step)
  core/            application configuration and cached projection-store connections
  db/              SQLAlchemy models, sessions, and base
  embeddings/      embedding provider and deterministic test provider
  evaluation/      application evaluation metrics and models
  graph/           Neo4j graph projection and traversal
  graphrag/        evidence context, answer pipeline, LLM providers
  memory/          candidate memory and promotion logic
  observability/   request, retrieval, and runtime metrics
  outbox/          transactional projection events, Kafka publisher, projection worker
  repositories/    PostgreSQL persistence
  retrieval/       semantic, graph, and hybrid result assembly
  semantic/        Qdrant semantic index
  services/        memory lifecycle and projection services

evals/             reproducible retrieval benchmark and validators
data/evaluation/   source-grounded memory/query dataset and manifest
results/evaluation/ timestamped source-grounded benchmark artifacts
tests/             API, service, storage, graph, retrieval, and eval tests
docs/design/       design notes and service contracts
ui/                legacy Streamlit interface (compose profile legacy-ui)
alembic/           PostgreSQL schema migrations
```

</details>

## Operations

<details>
<summary>Stop services and manage local data</summary>

```bash
# Stop containers but preserve database/index volumes
docker compose down

# Destructive: stop containers and permanently remove local volumes/data
docker compose down -v
```

</details>

## Design references

- [Memory engine design](docs/design/memory-engine-design.md)
- [Memory service contract](docs/design/memory-service-contract-v2.md)
- [Event-driven architecture review](docs/design/PHASE_3_EVENT_DRIVEN_ARCHITECTURE_REVIEW.md)
- [Retrieval evaluation guide](evals/README.md)
