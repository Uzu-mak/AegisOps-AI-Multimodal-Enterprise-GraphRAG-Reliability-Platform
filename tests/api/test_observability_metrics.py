from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _FakeSession:
    def __init__(self, values):
        self._values = list(values)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def scalar(self, *_args, **_kwargs):
        if not self._values:
            return None
        return self._values.pop(0)


def _session_factory_for(values):
    def _factory():
        return _FakeSession(values)

    return _factory


def _settings():
    return SimpleNamespace(
        LLM_PROVIDER="test",
        OPENAI_API_KEY=None,
        LLM_MODEL="deterministic-test-v1",
        LLM_TIMEOUT_SECONDS=15.0,
        QDRANT_URL="http://qdrant:6333",
        QDRANT_COLLECTION_NAME="memories",
        NEO4J_URI="bolt://neo4j:7687",
        NEO4J_USERNAME="neo4j",
        NEO4J_PASSWORD="aegisops",
        NEO4J_DATABASE="neo4j",
        KAFKA_BOOTSTRAP_SERVERS="kafka:9092",
        KAFKA_PROJECTION_TOPIC="aegisops.memory.projections.v1",
    )


def test_observability_uses_status_semantics_without_fake_zeroes():
    fake_health = {
        "postgres": {"status": "healthy"},
        "qdrant": {"status": "unavailable"},
        "neo4j": {"status": "unavailable"},
        "llm": {"status": "healthy", "provider": "test", "model": "deterministic-test-v1"},
    }

    with patch("app.core.config.get_settings", return_value=_settings()), patch(
        "app.api.routes.system._collect_service_health", return_value=fake_health
    ), patch(
        "app.db.session.SessionLocal", _session_factory_for([12, 3])
    ), patch(
        "app.api.routes.system.metrics_collector.runtime_snapshot",
        return_value={
            "requests_per_sec": 0.0,
            "error_rate": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "concurrent_requests": 0,
        },
    ), patch(
        "app.api.routes.system.metrics_collector.canonical_write_snapshot",
        return_value={
            "samples": 0,
            "failed_writes": 0,
            "duplicate_writes": 0,
            "rejected_writes": 0,
            "write_p50_ms": None,
            "write_p95_ms": None,
        },
    ), patch(
        "app.api.routes.system.metrics_collector.retrieval_snapshot",
        return_value={"by_mode": {}},
    ), patch(
        "app.api.routes.system.metrics_collector.llm_snapshot",
        return_value={
            "request_count": 0,
            "success_rate": None,
            "failure_rate": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        },
    ):
        response = TestClient(app).get("/api/v1/system/observability")

    assert response.status_code == 200
    body = response.json()

    assert body["api_runtime"]["request_latency_p50"]["status"] == "NOT_INSTRUMENTED"
    assert body["api_runtime"]["request_latency_p50"]["value"] is None

    assert body["scalar_sensor_ingestion"]["events_received"]["status"] == "NOT_CONNECTED"
    assert body["scalar_sensor_ingestion"]["events_received"]["value"] is None

    assert body["vision_pipeline"]["frames_received"]["status"] == "NOT_CONNECTED"
    assert body["vision_pipeline"]["frames_received"]["value"] is None

    assert body["llm"]["request_count"]["status"] == "NOT_INSTRUMENTED"
    assert body["llm"]["request_count"]["value"] is None


def test_projection_metrics_outbox_counts_and_no_consumer_lag_fabrication():
    fake_health = {
        "postgres": {"status": "healthy"},
        "qdrant": {"status": "unavailable"},
        "neo4j": {"status": "unavailable"},
        "llm": {"status": "healthy", "provider": "test", "model": "deterministic-test-v1"},
    }
    now = datetime.now(timezone.utc)

    scalar_values = [
        5,  # pending_outbox
        10,  # published_events
        2,  # kafka_failed_attempts
        3,  # projection_retries
        now - timedelta(minutes=2),  # oldest_pending
        4,  # published_recent
        1,  # qdrant_pending
        1,  # qdrant_failed
        None,  # qdrant_oldest_pending
        2,  # qdrant_completed_recent
        2,  # neo4j_pending
        1,  # neo4j_failed
        None,  # neo4j_oldest_pending
    ]

    with patch("app.core.config.get_settings", return_value=_settings()), patch(
        "app.api.routes.system._collect_service_health", return_value=fake_health
    ), patch(
        "app.db.session.SessionLocal", _session_factory_for(scalar_values)
    ), patch(
        "app.api.routes.system.metrics_collector.retrieval_snapshot",
        return_value={"by_mode": {}, "graph_latency_p50_ms": None, "graph_latency_p95_ms": None},
    ):
        response = TestClient(app).get("/api/v1/system/projection-metrics")

    assert response.status_code == 200
    body = response.json()

    assert body["kafka_outbox"]["pending_outbox_events"]["value"] == 5
    assert body["kafka_outbox"]["published_events"]["value"] == 10

    assert body["kafka_outbox"]["consumer_lag"]["status"] == "NOT_CONNECTED"
    assert "consumers not implemented" in body["kafka_outbox"]["consumer_lag"]["detail"].lower()

    assert body["qdrant"]["recall_at_10"]["status"] == "NOT_INSTRUMENTED"
    assert body["qdrant"]["recall_at_10"]["value"] is None

    assert body["neo4j"]["traversal_latency_p50"]["status"] == "NOT_INSTRUMENTED"
    assert body["neo4j"]["traversal_latency_p50"]["value"] is None
