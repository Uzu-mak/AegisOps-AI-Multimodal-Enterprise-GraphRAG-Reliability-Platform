# PHASE 3 — Slice 1 Implementation

Date: 2026-09-01
Reference: docs/design/PHASE_3_EVENT_DRIVEN_ARCHITECTURE_REVIEW.md
Scope: Stabilization and UI foundation only (no Kafka/RabbitMQ implementation)

---

## 1. What Was Changed

### Backend defect fixes

1. Search dependency construction fixed
- Refactored search route dependency wiring to use FastAPI DI providers, not manual constructor misuse.
- Added DI providers for:
  - Hybrid retriever construction
  - LLM provider selection
- Search routes now accept injected dependencies through `Depends(...)`.

Files:
- app/api/deps.py
- app/api/routes/search.py

2. Working Memory promotion payload boundary fixed
- Enforced public API payload key as `metadata`.
- Added a dedicated helper used by UI promotion flow.
- Kept internal service/ORM translation boundary intact (`metadata` -> `memory_metadata` inside API/service boundary).

Files:
- ui/working_memory_payload.py (new)
- ui/pages/07_working_memory.py

3. API degraded-mode handling improved
- Capability-specific search endpoints now return explicit `503` when required projection capability is unavailable:
  - semantic mode requires Qdrant
  - graph mode requires Neo4j
  - hybrid mode requires at least one projection backend
  - graph-related requires Neo4j
- Canonical memory CRUD path remains available when projection stores are unavailable.

Files:
- app/api/routes/search.py

4. Docker Compose startup dependency corrected
- API now depends only on PostgreSQL health (canonical dependency).
- Removed API hard dependency on Qdrant/Neo4j health.
- Added API healthcheck using Python stdlib probe (no curl dependency assumption).
- UI now depends on API health.

Files:
- docker-compose.yml

5. Existing outbox runtime preserved
- Outbox model/worker behavior was not redesigned.
- No Kafka/RabbitMQ publication was added in this slice.

---

## 2. Architecture After Slice 1

- PostgreSQL remains canonical source of truth.
- Qdrant and Neo4j remain derived projection stores.
- Service layer owns transactions and business rules.
- Repository layer remains persistence-only.
- API layer remains HTTP boundary.
- Search/retrieval routes now use proper DI wiring.
- Projection-store outages are surfaced as capability-specific degradation instead of canonical API startup failure.

---

## 3. Bugs Fixed

1. Search DI misuse fixed
- Removed manual dependency constructor invocation path from search routes.
- Replaced with proper injected dependencies.

2. Working Memory promotion request boundary fixed
- Promotion payload now uses API contract key `metadata`.

3. Compose dependency fragility fixed
- API startup no longer waits on Qdrant/Neo4j health.

---

## 4. Shared UI System Completed

Added reusable shared UI framework:
- consistent sidebar/navigation block
- page header helper
- status badge helper
- health cards
- metric card helper
- table helper
- loading state helper
- empty/warning/error/unavailable state helpers
- runtime health fetch helper
- capability gate helper

Files:
- ui/framework.py (new)

---

## 5. UI Pages Reviewed and Updated

Updated:
- ui/app.py
- ui/pages/03_semantic_search.py
- ui/pages/04_graph_explorer.py
- ui/pages/05_hybrid_graphrag.py
- ui/pages/06_incident_triage.py
- ui/pages/07_working_memory.py
- ui/pages/08_evaluation.py
- ui/pages/09_system_health.py

### Capability and gating behavior

03 Semantic Search
- Uses real API endpoint.
- Shows explicit unavailable state when Qdrant capability is down.
- Displays latency if provided.

04 Graph Explorer
- Uses real Neo4j-backed endpoint.
- Shows explicit unavailable state when Neo4j is down.
- Does not fabricate relationships.

05 Hybrid / GraphRAG
- Distinguishes retrieval versus generated answer path.
- Uses implemented backend endpoints only.
- Shows clear messaging when in deterministic provider mode.

06 Incident Triage
- Uses real memory creation and retrieval endpoints.
- Clearly states no diagnosis generation is performed.

07 Working Memory
- Promotion flow now maps to valid canonical memory create payload.
- Distinguishes temporary UI state from persisted memory.
- Renamed "Agent" framing to avoid implying unimplemented autonomous runtime.

08 Evaluation
- Shows only currently measurable retrieval metrics in this UI flow.
- Explicitly marks event-driven observability metrics as unavailable in Slice 1.
- No agent tool-selection evaluation added.

09 System Health
- Shows API, PostgreSQL, Qdrant, Neo4j, LLM statuses.
- Clearly separates canonical-store outage vs projection-store degradation.

---

## 6. Tests Added/Updated

### Added tests

1. Search dependency wiring
- tests/api/test_search_dependency_wiring.py

2. Capability-specific degraded behavior
- tests/api/test_search_capability_degraded.py

3. Canonical memory operations with projections unavailable
- tests/api/test_canonical_operations_when_projections_down.py

4. Working-memory promotion payload contract
- tests/ui/test_working_memory_payload.py

5. UI capability-gating logic
- tests/ui/test_capability_gating.py

### Existing tests intentionally preserved
- Existing repository/service/API tests were not weakened.

---

## 7. Validation Results

Environment constraints:
- `pytest` module is unavailable in local Python runtime.
- Docker Desktop engine is unavailable in this environment.

### PASSED
- Static diagnostics in edited files (`get_errors`): no errors.
- Python compile checks for all changed files:
  - `python -m compileall ...` succeeded.

### NOT RUN
- Phase 1 repository tests
- Phase 1 service tests
- Phase 1 API tests
- New pytest-based tests (due to missing pytest)
- Containerized test runs (due to Docker engine unavailable)

### FAILED
- `python -m pytest ...` failed: `No module named pytest`
- `docker compose ps` failed: Docker Desktop Linux engine pipe unavailable

---

## 8. Remaining Technical Debt (Deferred Beyond Slice 1)

- No Kafka domain-event stream yet.
- No RabbitMQ projection queue/DLQ topology yet.
- Outbox publication audit fields and broker publication service not added.
- Eventing observability metrics (publication latency, DLQ counts, consumer lag) not implemented.
- Some GraphRAG paths still use deterministic provider when real LLM credentials are absent.

---

## 9. Manual Commands to Run Locally

### A) Start infrastructure

```bash
docker compose up -d --build
```

### B) Validate service status

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/system/health
```

### C) Run existing Phase 1/2 tests

```bash
docker compose exec -T api python -m pytest tests/repositories/ -v
docker compose exec -T api python -m pytest tests/services/ -v
docker compose exec -T api python -m pytest tests/api/test_memory_api.py -v
```

### D) Run new Slice 1 tests

```bash
docker compose exec -T api python -m pytest -q \
  tests/api/test_search_dependency_wiring.py \
  tests/api/test_search_capability_degraded.py \
  tests/api/test_canonical_operations_when_projections_down.py \
  tests/ui/test_working_memory_payload.py \
  tests/ui/test_capability_gating.py
```

### E) Run focused search/API behavior tests

```bash
docker compose exec -T api python -m pytest -q tests/api/test_semantic_api_integration.py tests/api/test_graph_api_integration.py
```

### F) Run Streamlit UI

```bash
docker compose up -d ui
# open http://localhost:8501
```

---

## 10. Scope Confirmation

Slice 1 intentionally did NOT implement:
- Kafka
- RabbitMQ
- broker workers
- broker publication services
- agent/tool routing systems

No event broker stack was introduced in this slice.
