# PHASE 3: Event-Driven Architecture Review (Inspection Only)

Date: 2026-09-01
Scope: Repository inspection and architecture gap analysis only. No implementation changes.

---

## 1) Current Architecture Discovered

### Canonical Data Ownership
- PostgreSQL is the canonical source of truth for memory records and lifecycle state.
- Memory CRUD and lifecycle transitions are handled via `RealMemoryService` with explicit PostgreSQL transaction boundaries.
- Repository methods perform persistence operations but do not own commit/rollback.

### Projection Stores
- Qdrant is used as semantic projection/index only.
- Neo4j is used as graph projection/traversal only.
- Both are treated as derived stores and are non-canonical.

### Outbox and Projection Reliability
- A PostgreSQL `projection_outbox` table exists.
- Memory service writes outbox entries in the same PostgreSQL transaction as canonical writes.
- An `OutboxWorker` exists to process pending/retrying projection events.

### API Surface
- Memory endpoints: create/get/list/update/archive/dispute/supersede.
- Search endpoints: semantic retrieval, hybrid retrieval, graph-related traversal, GraphRAG query.
- System endpoints: health, memory stats, outbox stats.

### UI Surface (Streamlit)
- Multi-page UI exists with pages for overview, memory explorer, semantic search, graph explorer, hybrid/GraphRAG, incident triage, working memory, evaluation, and system health.

---

## 2) Complete Components

### Canonical Transaction Ownership
- Service-layer transaction ownership is implemented for memory operations.
- Repository layer remains non-transaction-owning (no independent commit).

### Core Domain Endpoints
- Memory lifecycle API endpoints are implemented and wired.

### Semantic Projection (Qdrant)
- Indexing/removal/status update paths are implemented.
- Semantic indexing uses upsert semantics and canonical UUID identity.

### Graph Projection (Neo4j)
- Projection uses deterministic, idempotent `MERGE` patterns.
- Traversal returns canonical PostgreSQL memory IDs.

### Outbox Foundation
- Outbox table and processing statuses exist (`pending`, `processing`, `retrying`, `completed`, `failed`).
- Service writes outbox rows in same DB transaction as memory mutations.

### Basic Failure Isolation
- Qdrant/Neo4j failures are handled as non-fatal relative to PostgreSQL canonical commit.

---

## 3) Partial Components

### Transactional Outbox Pattern (Partial)
- Implemented: canonical write + outbox write in one PostgreSQL transaction.
- Missing: robust publication pipeline to message brokers with publication audit metadata.

### Event-Driven Topology (Partial)
- Missing Kafka producer/consumer infrastructure and topic management.
- Missing RabbitMQ broker integration, queue/exchange declaration, DLQ flow.

### Retry and Recovery (Partial)
- Outbox worker has in-table retry states.
- Missing broker-level delayed retry strategy and dead-letter routing guarantees.

### Observability/Evaluation (Partial)
- Retrieval/RAG evaluation exists.
- Missing event/publication/projection pipeline metrics and lag/backlog dashboards required for Phase 3 operations.

---

## 4) Broken / Incomplete Components

### Search Route Dependency Construction Risk
- `search.py` directly invokes dependency constructors intended for FastAPI DI context.
- This can cause graph index construction paths to degrade unexpectedly (driver resolution edge cases).

### Working Memory Promotion Payload Mismatch
- UI promotion payload key and backend schema naming are inconsistent in current code path expectations (`metadata` vs internal `memory_metadata` mapping path), creating potential validation failure risk depending on request shape.

### Compose Readiness Coupling
- API service startup dependencies are coupled to projection services health (Qdrant/Neo4j) despite graceful-degradation target.
- This creates operational fragility where canonical API availability can be blocked by non-canonical projection stores.

### Missing Continuous Outbox Publication Runtime
- Outbox worker/publisher lifecycle is not wired as durable first-class service process in compose/runtime.
- Backlog can accumulate without guaranteed autonomous drain.

### No Kafka/RabbitMQ Stack
- No Kafka service, no RabbitMQ service, no publishers/consumers, no DLQ topology currently exists.

---

## 5) Files Requiring Modification (When Implementation Is Approved)

### Core Backend
- `app/services/memory_service.py`
- `app/outbox/models.py`
- `app/outbox/worker.py`
- `app/api/deps.py`
- `app/api/routes/search.py`
- `app/api/routes/system.py`
- `app/core/config.py`

### Database Migrations
- `alembic/versions/20260819_0002_projection_outbox.py` (or follow-up migration)
- New migration(s) for enriched outbox/event/idempotency schemas

### UI
- `ui/app.py`
- `ui/api_client.py`
- `ui/pages/03_semantic_search.py`
- `ui/pages/04_graph_explorer.py`
- `ui/pages/05_hybrid_graphrag.py`
- `ui/pages/06_incident_triage.py`
- `ui/pages/07_working_memory.py`
- `ui/pages/08_evaluation.py`
- `ui/pages/09_system_health.py`

### Infrastructure and Docs
- `docker-compose.yml`
- `requirements.txt`
- `README.md`
- Targeted test modules under `tests/`

---

## 6) Proposed New Files / Services

### New Runtime Services
- `kafka` broker service
- `rabbitmq` broker service (with management plugin)
- `outbox-publisher` service (polls outbox, publishes, updates publication state)
- `projection-worker-semantic` service (Rabbit consumer)
- `projection-worker-graph` service (Rabbit consumer)
- Optional `domain-consumer` service(s) for Kafka downstream processing validation

### New Backend Modules (Suggested)
- `app/events/domain_event.py`
- `app/events/kafka_publisher.py`
- `app/events/rabbitmq_publisher.py`
- `app/outbox/publisher.py`
- `app/projections/semantic_worker.py`
- `app/projections/graph_worker.py`
- `app/idempotency/store.py`
- `app/telemetry/metrics.py`
- Optional: `app/api/routes/metrics.py`

### New DB Tables (Suggested)
- generalized outbox publication fields (or split tables)
- `processed_kafka_events`
- `processed_rabbit_messages`
- optional projection execution log/audit table

---

## 7) Proposed Transactional Outbox Design

### Core Principles
- Canonical domain row(s) and outbox row(s) commit in one PostgreSQL transaction.
- No distributed transaction across PostgreSQL + Qdrant + Neo4j + brokers.
- At-least-once publication and idempotent consumers.

### Suggested Outbox Schema (Generalized)
- `id` (uuid, pk)
- `stream_type` (`domain` | `projection`)
- `destination` (`kafka` | `rabbitmq`)
- `topic_or_exchange` (text)
- `routing_key` (text, nullable)
- `event_id` (uuid, unique)
- `event_type` (text)
- `aggregate_type` (text)
- `aggregate_id` (uuid)
- `occurred_at` (timestamptz)
- `correlation_id` (text, nullable)
- `schema_version` (int)
- `payload` (jsonb)
- `headers` (jsonb, nullable)
- `status` (`pending`, `publishing`, `published`, `failed`, `dead_lettered`)
- `publish_attempts` (int)
- `next_attempt_at` (timestamptz)
- `published_at` (timestamptz, nullable)
- `last_error` (text, nullable)
- `created_at`, `updated_at` (timestamptz)

### Required Indexes
- `(status, next_attempt_at)`
- `event_id` unique
- `aggregate_id`
- `(destination, topic_or_exchange)`
- `created_at`

---

## 8) Proposed Kafka Topics and Event Flow

### Domain/Event Topics
Option A (single topic):
- `aegisops.domain.events`

Option B (split by bounded context):
- `aegisops.memory.events`
- `aegisops.incident.events`
- `aegisops.maintenance.events`

### Required Event Envelope
Each event includes:
- `event_id`
- `event_type`
- `aggregate_id`
- `occurred_at`
- `correlation_id`
- `schema_version`
- `payload`

### Event Types (Target)
- `memory.created`
- `memory.updated`
- `memory.archived`
- `memory.disputed`
- `memory.superseded`
- `incident.created`
- `diagnosis.created`
- `maintenance_action.created`
- `resolution.created`

### Proposed Domain Event Flow
1. API request -> service validation.
2. Service writes canonical state changes.
3. Service writes outbox domain events in same DB tx.
4. Commit PostgreSQL transaction.
5. Outbox publisher reads pending rows with row-locking.
6. Publisher sends to Kafka.
7. Publisher records successful publication in PostgreSQL.
8. Kafka consumers process with idempotency checks using `event_id`.

---

## 9) Proposed RabbitMQ Exchange / Queue / DLQ Topology

### Exchange
- `aegisops.projection` (topic, durable)

### Routing Keys
- `semantic.index_memory`
- `semantic.remove_memory`
- `graph.project_memory`
- `graph.update_memory`

### Primary Queues
- `q.semantic.index_memory`
- `q.semantic.remove_memory`
- `q.graph.project_memory`
- `q.graph.update_memory`

### Retry Queues
- one retry queue per primary queue with TTL and dead-letter back to primary

### Dead-Letter Queues
- `q.semantic.index_memory.dlq`
- `q.semantic.remove_memory.dlq`
- `q.graph.project_memory.dlq`
- `q.graph.update_memory.dlq`

### Consumer Behavior
- manual ack only after idempotent projection success
- on transient failure: retry with bounded attempts/backoff
- on max attempts: route to DLQ and record terminal failure metadata

---

## 10) Qdrant / Neo4j Projection Flow (Proposed)

1. Canonical mutation commits in PostgreSQL with outbox projection job row.
2. Outbox publisher emits projection job to RabbitMQ.
3. Projection worker consumes message (at-least-once).
4. Worker checks idempotency store by stable message/event id.
5. Worker runs projection:
   - Qdrant operations use canonical PostgreSQL UUID identity.
   - Neo4j operations remain `MERGE`/idempotent.
6. On success: mark processed in idempotency table, ack message, update projection/outbox state.
7. On failure: retry policy applies, then DLQ when limit reached.
8. Canonical PostgreSQL state is never rolled back due to projection failures.

---

## 11) Failure Recovery Strategy

Design target is at-least-once delivery with idempotent consumers (not exactly-once).

### Required Scenarios
1. PostgreSQL commit succeeds while Qdrant is down.
2. PostgreSQL commit succeeds while Neo4j is down.
3. Failed projection job can be retried.
4. Duplicate RabbitMQ delivery does not duplicate Qdrant/Neo4j projection state.
5. Duplicate Kafka event can be consumed safely.
6. Outbox rows cannot be lost between DB commit and publication.
7. Successful outbox publication is recorded.
8. Failed messages eventually reach DLQ after configured retry limit.

### Recovery Mechanisms
- durable outbox in PostgreSQL
- polling publisher with row locking and retry scheduling
- Rabbit retry queues + DLQ
- idempotency ledger tables for consumers
- publication audit fields in outbox
- replay/recovery command path for stuck/failed outbox rows

---

## 12) Idempotency Strategy

### Producer Side
- Every domain/projection message carries immutable `event_id`.
- Outbox enforces uniqueness where appropriate.
- Publication attempts can repeat without changing canonical state.

### Kafka Consumer Side
- Maintain `processed_kafka_events(event_id, consumer_name, processed_at)`.
- Ignore already-processed `event_id`.
- Side effects only execute once per consumer semantics.

### Rabbit Consumer Side
- Maintain `processed_rabbit_messages(message_id/event_id, consumer_name, processed_at)`.
- Ack only after idempotent side effects complete.
- Redelivery is safe and side-effect free on duplicates.

### Projection Side
- Qdrant uses canonical UUID point identity and upsert/update semantics.
- Neo4j uses `MERGE` and deterministic keys.

---

## 13) UI Completion Plan (Backend-Capability-Gated)

### Build Shared UI Framework
Create reusable UI layer for:
- consistent navigation/sidebar
- consistent page title/header
- standard spacing/layout
- reusable metric cards
- reusable status badges
- standard table rendering
- filter components
- loading states
- empty states
- error states
- backend connection-health indicators

### Target Pages to Review and Finish Only If Backend Exists
- `03_semantic_search`
- `04_graph_explorer`
- `05_hybrid_graphrag`
- `06_incident_triage`
- `07_working_memory`
- `08_evaluation`
- `09_system_health`

### Capability Gating Rule
- If backend capability does not exist, page must show explicit:
  - `Not available / backend capability not implemented yet`
- Do not fabricate GraphRAG, agent, ML, or evaluation results.

### Current Readiness Assessment
- Ready/mostly backed by existing APIs: semantic search, graph explorer, hybrid retrieval, incident triage, system health.
- Requires explicit capability gating: working memory “agent trace” maturity, full evaluation telemetry for event pipeline metrics.

---

## 14) Evaluation and Observability Plan

### Metrics to Add
- task completion/correctness
- API latency
- Qdrant indexing latency
- semantic search latency
- event publication latency
- projection latency
- failure count
- retry count
- DLQ count
- outbox backlog
- Kafka consumer lag (where practical)

### Instrumentation Plan
- service-level timing for API endpoints and domain handlers
- publisher metrics for outbox scan latency and publish latency per broker
- worker metrics for projection execution, retries, and DLQ outcomes
- health/metrics endpoints for dashboard consumption
- structured logs with `correlation_id`, `event_id`, `aggregate_id`

### Explicit Non-Goal (Now)
- Do not implement agent tool-selection evaluation yet.
- Agent/tool-routing evaluation deferred until that subsystem exists.

---

## 15) Test Plan

### Transactional Outbox Integrity
- canonical row and outbox row commit atomically
- rollback removes both
- repository layer still does not independently commit

### Broker Publication Reliability
- pending outbox rows are published and marked published
- publisher restarts do not lose rows
- publication retries and terminal failure states are recorded

### Rabbit Projection Reliability
- transient failure -> retry -> eventual success path
- max retry -> DLQ path
- duplicate delivery -> no duplicate projection side effects

### Kafka Domain Event Reliability
- duplicate event -> idempotent consume behavior
- schema versioning and payload compatibility checks

### Projection Failure Isolation
- Qdrant down does not affect canonical commit
- Neo4j down does not affect canonical commit

### UI Capability Gating
- pages with missing backend show explicit Not available state
- no fabricated evaluation/agent outputs

---

## 16) Docker / Runtime Topology Notes

### Current Compose Gaps
- no Kafka service
- no RabbitMQ service
- no dedicated outbox publisher service
- no dedicated projection worker services

### Healthcheck Guidance
- add healthchecks for all brokers and workers
- avoid assuming `curl` exists in images
- use image-native tools (`pg_isready`, broker diagnostics, Python health probes)

### Dependency Handling Guidance
- avoid hard API startup dependency on non-canonical projection services
- canonical API should run with degraded projection availability

---

## 17) Risks and Complexity of Using Kafka + RabbitMQ Together

- increased operational burden (two brokers, two failure domains)
- more complex security and credential management
- higher observability/tracing complexity across dual messaging planes
- larger testing matrix (publication/consumption/retry/DLQ across both)
- event contract governance complexity (schema evolution + compatibility)
- potential partial-success publication scenarios (Kafka success, Rabbit failure)
- increased team cognitive load and incident response complexity

---

## 18) Summary

The repository already has a solid PostgreSQL-canonical core with projection adapters and an initial transactional outbox foundation. The major Phase 3 gap is the absence of brokered event infrastructure (Kafka + RabbitMQ), robust publication auditing, idempotency ledgers, and capability-gated UI/observability for event-driven operations.

This document is inspection-only and intentionally does not implement architecture changes.
