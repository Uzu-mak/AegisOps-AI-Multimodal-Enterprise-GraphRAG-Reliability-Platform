"""PostgreSQL-only endpoints must not wait on unreachable projection stores."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core import connections as conn_mod
from app.core.connections import ProjectionConnections
from app.main import app


def test_memory_list_and_health_are_fast_when_projections_unreachable():
    calls = []

    def slow_failing(_settings):
        calls.append(1)
        time.sleep(0.3)  # stands in for a connect timeout
        raise ConnectionError("unreachable")

    conn_mod.reset_connections(
        ProjectionConnections(qdrant_factory=slow_failing, neo4j_factory=slow_failing)
    )
    try:
        client = TestClient(app)
        client.get("/api/v1/system/health")  # first call pays the timeouts once
        started = time.monotonic()
        for _ in range(5):
            assert client.get("/api/v1/memories", params={"limit": 1}).status_code == 200
            body = client.get("/api/v1/system/health").json()
            assert body["services"]["qdrant"]["status"] == "unavailable"
            assert body["services"]["neo4j"]["status"] == "unavailable"
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"requests waited on projection stores ({elapsed:.2f}s)"
        assert len(calls) == 2  # one attempt per store, then cool-down
    finally:
        conn_mod.reset_connections()
