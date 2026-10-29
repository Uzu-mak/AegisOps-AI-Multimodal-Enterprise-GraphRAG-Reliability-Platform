# Local development and operations

## Docker from the repository / IDE terminal

Requirements: running Docker Desktop with its Linux engine, a configured `.env`,
and adequate memory for PostgreSQL, Qdrant and Neo4j. Keep secrets out of Git.

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
```

Open http://localhost:8000/console/. The one-shot `migrate` service performs additive
schema upgrades before the API and worker start. It never resets databases or
removes volumes. Back up canonical data before a schema upgrade. Revision 0004
refuses duplicate active work-order identities rather than deleting history.

## VS Code / host debugging

Open the repository folder. Select the existing `.venv` interpreter.
Run the task **AegisOps: infrastructure for host debug**, then stop the Docker API
if it already occupies port 8000 (`docker compose stop api`). Start the launch
configuration **AegisOps: local API and console**. PyCharm can run
`scripts/run_local.py` with the same interpreter and repository working directory.
Alternatively:

```powershell
.\.venv\Scripts\python.exe scripts/run_local.py
```

The launcher reads `.env` and converts container service addresses to published
host addresses without printing credentials. Override `QDRANT_HOST_URL`,
`NEO4J_HOST_URI`, `POSTGRES_HOST_PORT`, or `API_PORT` when necessary. Containers use
`QDRANT_CONTAINER_URL` and `NEO4J_CONTAINER_URI`; do not use host `localhost` inside
a container. `/live` is process liveness; `/ready` checks canonical schema readiness.

## Connection status versus index readiness

System health probes the real configured Qdrant API and Neo4j Bolt driver. An open
TCP port or a working browser dashboard does not prove the API container can
connect/authenticate. Projection bootstrap errors are reported separately and no
longer discard a healthy connection. Qdrant dimension mismatch requires a separate
collection for the new embedding configuration and reprojection; Neo4j schema
initialization needs database permissions. Docker logs saying `no connected VM`
mean the WSL engine itself is unavailable, regardless of published-port listeners.

## Authentication

The shipped ports bind to 127.0.0.1. `AUTH_MODE=local` is for trusted local development.
For authenticated use set `AUTH_MODE=token` and set secret `AUTH_TOKENS_JSON` to an
object mapping opaque random tokens to server-owned `tenant_id` and `roles`.
Roles include `viewer`, `writer`, and `admin`, plus record-specific access roles.
Use HTTPS at a reverse proxy before exposing this beyond the computer. The console
prompts for a token and stores it only for the current tab session. Canonical reads
are tenant/access-role scoped; writes cannot assign another tenant. Infrastructure
metrics require admin. CLI imports and workers are trusted administrative processes.

## Embeddings and retrieval

`fake` is deterministic test plumbing; `hashed_terms` is lexical. A real semantic
adapter is available with `EMBEDDING_PROVIDER=openai`, a valid provider credential,
`EMBEDDING_MODEL`, and `EMBEDDING_DIMENSION`. This may incur provider charges.
Non-default embedding providers use separate collection names. Changing a model or
provider must always use a separate compatible collection and a full reprojection;
never compare query vectors with vectors from another embedding model.

```powershell
docker compose exec api python -m app.outbox.projection_worker --reproject-all
```

## Delivery and recovery

Every mutation appends an envelope with a canonical revision and historical content
snapshot. Two delivery rows share its event ID. Envelope fields are never recycled;
projection/Kafka delivery state is separate. Consumers must deduplicate `event_id`:
publication remains at least once. Projections deliberately load current canonical
state rather than replaying old snapshots. Leases recover abandoned work; scheduled
backoff and deferral avoid outage starvation. Do not edit envelope fields manually.
Historical events already collapsed by older builds cannot be reconstructed.

```powershell
docker compose exec api python -m app.outbox.projection_worker --retry-failed
docker compose --profile integration up -d
```

The integration profile enables the publisher. Set `KAFKA_ENABLED=true` for matching
API reporting. Topic creation follows `KAFKA_PROJECTION_TOPIC`; host consumers use
localhost:9092 and container consumers use kafka:9092. No internal Kafka consumer or
RabbitMQ pipeline is required by this architecture.

## Isolated integration tests

Never run destructive database fixtures against the development dataset.

```powershell
docker compose -p aegisops-tests -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
```

This separate project uses a temporary PostgreSQL filesystem and no development
volumes or credentials. Stop/remove its containers with the same `-p` and `-f`
arguments after testing. Ordinary unit regressions can use an unreachable test URL;
`tests/reliability` uses its own in-memory transactions. SQLite tests cannot prove
PostgreSQL locking semantics, so the isolated PostgreSQL suite is also necessary.

## Evaluation interpretation

Record the embedding provider/model/collection and backend availability with every
benchmark. Only labelled cases contribute to retrieval averages. Citation presence
and index validity are heuristics, not proof that an answer is factually supported.
The small checked-in source-grounded dataset remains weakly supervised; obtain
independently reviewed plant questions before asserting production retrieval quality.
