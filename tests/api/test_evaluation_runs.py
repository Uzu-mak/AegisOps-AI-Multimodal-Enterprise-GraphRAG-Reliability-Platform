"""Server-side evaluation runs: same retriever and metrics as the CLI; honest about unavailable modes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_graph_memory_index, get_semantic_index
from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.main import app
from app.outbox.models import ProjectionOutboxEvent


@pytest.fixture
def client():
    def wipe():
        with SessionLocal() as s:
            s.execute(delete(ProjectionOutboxEvent)); s.execute(delete(MemoryRecord)); s.commit()
    wipe()
    app.dependency_overrides[get_semantic_index] = lambda: None
    app.dependency_overrides[get_graph_memory_index] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    wipe()


def test_unavailable_modes_are_reported_not_scored(client):
    rec = client.post("/api/v1/memories", json={"memory_type": "incident", "title": "Autoclave AC-2 thermocouple lag",
                                                 "content": "TC-7 lags the cure profile.", "source_type": "system",
                                                 "confidence": 0.8, "importance": 0.8}).json()
    r = client.post("/api/v1/evaluation/runs", json={
        "cases": [{"question": "autoclave thermocouple lag", "expected_memory_ids": [rec["id"]]}],
        "modes": ["semantic", "graph", "agentic"], "k": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modes_run"] == ["agentic"]
    assert body["unavailable_modes"] == {"semantic": "needs qdrant", "graph": "needs qdrant, neo4j"}
    assert body["per_mode"]["agentic"]["recall_at_k"] == 1.0  # keyword fallback found it
    assert body["per_mode"]["agentic"]["groundedness"] is not None


def test_unknown_expected_ids_are_rejected(client):
    r = client.post("/api/v1/evaluation/runs", json={
        "cases": [{"question": "q", "expected_memory_ids": ["00000000-0000-0000-0000-000000000000"]}]})
    assert r.status_code == 422
