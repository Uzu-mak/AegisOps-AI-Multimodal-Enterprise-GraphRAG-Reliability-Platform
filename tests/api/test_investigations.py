"""Investigation loop: investigate -> cited answer + trace -> record finding linked to incident."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_graph_memory_index, get_semantic_index
from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.main import app
from app.outbox.models import ProjectionOutboxEvent


def _wipe():
    with SessionLocal() as session:
        session.execute(delete(ProjectionOutboxEvent))
        session.execute(delete(MemoryRecord))
        session.commit()


@pytest.fixture
def client():
    _wipe()
    app.dependency_overrides[get_semantic_index] = lambda: None
    app.dependency_overrides[get_graph_memory_index] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.pop(get_semantic_index, None)
    app.dependency_overrides.pop(get_graph_memory_index, None)
    _wipe()


def _create(client, **kw):
    body = {"memory_type": "incident", "title": "t", "content": "c", "source_type": "system",
            "asset_id": "drill-cell-dc3", "facility_id": "bldg-2", "incident_id": "inc-0108",
            "confidence": 0.8, "importance": 0.8, **kw}
    r = client.post("/api/v1/memories", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_investigation_returns_cited_answer_trace_and_critic(client):
    inc = _create(client, title="Oversize fastener holes on drill cell DC-3", content="Hole diameter out of tolerance on frame 42.")
    r = client.post("/api/v1/investigations", json={"question": "Why are drill cell DC-3 holes oversize?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retrieval_mode"] == "keyword_fallback"  # projections overridden to unavailable
    assert [e["memory_id"] for e in body["evidence"]] == [inc["id"]]
    assert [s["type"] for s in body["steps"]] == ["retrieval", "graph_reasoning", "synthesis", "critic"]
    assert "[Memory 1]" in body["answer"]
    assert body["critic"]["is_supported"] is True


def test_finding_inherits_incident_context_and_links_evidence(client):
    inc = _create(client, title="Oversize holes on DC-3", content="Out of tolerance.")
    r = client.post("/api/v1/investigations/findings", json={
        "question": "Why are holes oversize?",
        "memory_type": "diagnosis",
        "title": "Spindle bearing wear on DC-3",
        "content": "Spindle runout above limit explains oversize holes.",
        "evidence_memory_ids": [inc["id"]],
        "anchor_memory_id": inc["id"],
        "confidence": 0.75, "importance": 0.7,
        "answer_was_synthetic": True,
    })
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["memory_type"] == "diagnosis"
    assert rec["incident_id"] == "inc-0108" and rec["asset_id"] == "drill-cell-dc3"
    assert rec["source_type"] == "investigation"
    assert rec["is_synthetic"] is False  # evidence was real data
    assert rec["metadata"]["answer_was_synthetic"] is True
    assert rec["metadata"]["evidence_memory_ids"] == [inc["id"]]


def test_finding_rejected_by_policy_explains_why(client):
    r = client.post("/api/v1/investigations/findings", json={
        "question": "q", "title": "Guess", "content": "Maybe the bearing.", "confidence": 0.3,
    })
    assert r.status_code == 422
    assert "below" in r.json()["detail"] and "evidence" in r.json()["detail"]


def test_investigation_from_a_record_starts_with_it_and_its_incident(client):
    inc = _create(client, title="Thermocouple lag on autoclave AC-2", content="TC-7 trails the cure profile.",
                  asset_id="autoclave-ac2", incident_id="inc-0115")
    obs = _create(client, memory_type="observation", title="TC-7 reading jumps", content="Lead moved at connector.",
                  asset_id="autoclave-ac2", incident_id="inc-0115")
    _create(client, memory_type="observation", title="Nozzle scale on scanner US-1", content="Inspect nozzle.",
            asset_id="ndt-scanner-us1", incident_id=None)
    r = client.post("/api/v1/investigations", json={"question": "inspect the nozzle", "anchor_memory_id": inc["id"]})
    assert r.status_code == 200, r.text
    ev = r.json()["evidence"]
    assert ev[0]["memory_id"] == inc["id"] and ev[0]["retrieval_source"] == "anchor"
    assert ev[1]["memory_id"] == obs["id"] and ev[1]["retrieval_source"] == "context"
    assert "sharing the starting record" in r.json()["steps"][1]["description"]
