"""Lineage of a record: origin, versions, findings derived from it, projection state."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

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
    yield TestClient(app)
    wipe()


def _mk(client, **kw):
    body = {"memory_type": "incident", "title": "Oil cooler leaking", "content": "Oil at the cooler fitting.",
            "source_type": "technician", "confidence": 0.8, "importance": 0.7, **kw}
    r = client.post("/api/v1/memories", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_lineage_shows_versions_findings_and_projection(client):
    old = _mk(client)
    sup = client.post(f"/api/v1/memories/{old['id']}/supersede", json={"replacement": {
        "memory_type": "incident", "title": "Oil cooler leaking (corrected)", "content": "Oil at the cooler inlet fitting.",
        "source_type": "technician", "confidence": 0.8, "importance": 0.7}})
    assert sup.status_code == 200, sup.text
    new = sup.json()["replacement"]
    finding = client.post("/api/v1/investigations/findings", json={
        "question": "Where is the oil coming from?", "memory_type": "diagnosis", "title": "Leak at cooler inlet fitting",
        "content": "The leak is at the cooler inlet fitting.", "evidence_memory_ids": [new["id"]], "confidence": 0.8, "importance": 0.7})
    assert finding.status_code == 201, finding.text

    lin = client.get(f"/api/v1/memories/{new['id']}/lineage").json()
    assert [v["id"] for v in lin["earlier_versions"]] == [old["id"]]
    assert [f["id"] for f in lin["used_by_findings"]] == [finding.json()["id"]]
    assert set(lin["projections"]) == {"qdrant", "neo4j"}
    assert lin["projections"]["qdrant"] is not None  # creating a record queues its projection

    back = client.get(f"/api/v1/memories/{old['id']}/lineage").json()
    assert [v["id"] for v in back["later_versions"]] == [new["id"]]
    derived = client.get(f"/api/v1/memories/{finding.json()['id']}/lineage").json()
    assert [d["id"] for d in derived["derived_from"]] == [new["id"]]


def test_unknown_record_is_404(client):
    assert client.get("/api/v1/memories/00000000-0000-0000-0000-000000000000/lineage").status_code == 404
