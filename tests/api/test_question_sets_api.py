"""Question-set API: create a draft, review it, run it, and see the run tied to the approved version."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_graph_memory_index, get_semantic_index
from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.evaluation.datasets import EvalQuestionRecord, EvalQuestionSetRecord
from app.evaluation.store import EvalCaseResultRecord, EvalRunRecord
from app.main import app
from app.outbox.models import ProjectionOutboxEvent


@pytest.fixture
def client():
    def wipe():
        with SessionLocal() as s:
            for model in (EvalCaseResultRecord, EvalRunRecord, EvalQuestionRecord, EvalQuestionSetRecord, ProjectionOutboxEvent, MemoryRecord):
                s.execute(delete(model))
            s.commit()
    wipe()
    app.dependency_overrides[get_semantic_index] = lambda: None
    app.dependency_overrides[get_graph_memory_index] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    wipe()


def test_review_workflow_and_run_matching(client):
    rec = client.post("/api/v1/memories", json={"memory_type": "incident", "title": "Autoclave AC-2 thermocouple lag",
                                                 "content": "TC-7 lags the cure profile.", "source_type": "system",
                                                 "confidence": 0.8, "importance": 0.8}).json()
    qs = [{"question": "Why does the cure profile lag on AC-2?", "expected_memory_ids": [rec["id"]]},
          {"question": "Was the hangar door replaced?", "expects_no_answer": True}]
    created = client.post("/api/v1/evaluation/question-sets", json={"name": "Autoclave", "author": "Jeremiah", "questions": qs})
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert client.post(f"/api/v1/evaluation/question-sets/{sid}/submit", json={"by": "Jeremiah"}).status_code == 200
    assert client.put(f"/api/v1/evaluation/question-sets/{sid}/questions", json={"questions": qs[:1]}).status_code == 409
    assert client.post(f"/api/v1/evaluation/question-sets/{sid}/approve", json={"by": "Jeremiah"}).status_code == 409
    approved = client.post(f"/api/v1/evaluation/question-sets/{sid}/approve", json={"by": "Ama", "note": "ok"})
    assert approved.json()["status"] == "approved"

    run = client.post("/api/v1/evaluation/runs", json={"modes": ["agentic"], "k": 10, "cases": [
        {"question": q["question"], "expected_memory_ids": q.get("expected_memory_ids", []), "expects_no_answer": q.get("expects_no_answer", False)}
        for q in qs]})
    assert run.status_code == 200, run.text
    hist = client.get("/api/v1/evaluation/history").json()["runs"][0]
    assert hist["question_set"] == {"id": sid, "name": "Autoclave", "version": 1, "status": "approved", "reviewed_by": "Ama"}


def test_unknown_expected_record_is_rejected(client):
    r = client.post("/api/v1/evaluation/question-sets", json={"name": "x", "author": "a", "questions": [
        {"question": "q", "expected_memory_ids": ["00000000-0000-0000-0000-000000000000"]}]})
    assert r.status_code == 422
