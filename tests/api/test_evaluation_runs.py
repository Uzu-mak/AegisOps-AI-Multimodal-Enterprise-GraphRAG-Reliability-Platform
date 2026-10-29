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
from app.evaluation.store import EvalCaseResultRecord, EvalRunRecord


@pytest.fixture
def client():
    def wipe():
        with SessionLocal() as s:
            s.execute(delete(EvalCaseResultRecord)); s.execute(delete(EvalRunRecord))
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


def test_runs_are_saved_and_can_be_reopened(client):
    rec = client.post("/api/v1/memories", json={"memory_type": "incident", "title": "Autoclave AC-2 thermocouple lag",
                                                 "content": "TC-7 lags the cure profile.", "source_type": "system",
                                                 "confidence": 0.8, "importance": 0.8}).json()
    r = client.post("/api/v1/evaluation/runs", json={
        "cases": [{"question": "autoclave thermocouple lag", "expected_memory_ids": [rec["id"]], "anchor_memory_id": rec["id"]}],
        "modes": ["agentic"], "k": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["persisted"] is True
    runs = client.get("/api/v1/evaluation/history").json()["runs"]
    assert [x["run_id"] for x in runs] == [body["run_id"]]
    saved = client.get(f"/api/v1/evaluation/history/{body['run_id']}").json()
    assert saved["per_mode"] == body["per_mode"]
    assert saved["cases"][0]["expected_memory_ids"] == [rec["id"]] and saved["cases"][0]["anchor_memory_id"] == rec["id"]
    assert client.get("/api/v1/evaluation/history/00000000-0000-0000-0000-000000000000").status_code == 404
