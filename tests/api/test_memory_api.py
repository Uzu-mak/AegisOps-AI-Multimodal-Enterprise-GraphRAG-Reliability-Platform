from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture(autouse=True)
def clean_memories():
    with SessionLocal() as session:
        session.execute(delete(MemoryRecord))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(MemoryRecord))
        session.commit()


@pytest.fixture
def client():
    return TestClient(app)


def test_create_memory_returns_201_and_metadata_mapping(client):
    payload = {
        "memory_type": MemoryType.OBSERVATION.value,
        "title": "API memory",
        "content": "API content",
        "source_type": "sensor",
        "asset_id": "asset-1",
        "confidence": 0.75,
        "importance": 0.5,
        "access_roles": ["ops"],
        "metadata": {"source": "api", "value": 42},
    }

    response = client.post("/api/v1/memories", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["memory_type"] == MemoryType.OBSERVATION.value
    assert body["status"] == MemoryStatus.ACTIVE.value
    assert body["metadata"] == {"source": "api", "value": 42}
    assert body["confidence"] == 0.75
    assert body["importance"] == 0.5


def test_get_memory_by_id_returns_memory(client):
    created = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.RECOMMENDATION.value,
            "title": "Readable memory",
            "content": "Readable content",
            "source_type": "manual",
            "metadata": {"topic": "ops"},
        },
    )
    memory_id = created.json()["id"]

    response = client.get(f"/api/v1/memories/{memory_id}")

    assert response.status_code == 200
    assert response.json()["title"] == "Readable memory"


def test_list_memories_returns_records(client):
    client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.INCIDENT.value,
            "title": "Incident one",
            "content": "Body one",
            "source_type": "sensor",
        },
    )
    client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Observation one",
            "content": "Body two",
            "source_type": "manual",
        },
    )

    response = client.get("/api/v1/memories")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert {item["title"] for item in body["items"]} == {"Incident one", "Observation one"}


def test_patch_memory_updates_allowed_fields(client):
    created = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Before patch",
            "content": "Before content",
            "source_type": "manual",
            "confidence": 0.2,
        },
    )
    memory_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"title": "After patch", "confidence": 0.8, "metadata": {"patched": True}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "After patch"
    assert body["confidence"] == 0.8
    assert body["metadata"] == {"patched": True}


def test_invalid_create_returns_422(client):
    response = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "",
            "content": "Body",
            "source_type": "sensor",
        },
    )

    assert response.status_code == 422


def test_archive_memory_returns_200(client):
    created = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Archive me",
            "content": "Body",
            "source_type": "sensor",
        },
    )
    memory_id = created.json()["id"]

    response = client.post(f"/api/v1/memories/{memory_id}/archive")

    assert response.status_code == 200
    assert response.json()["status"] == MemoryStatus.ARCHIVED.value


def test_dispute_memory_returns_200(client):
    created = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.DIAGNOSIS.value,
            "title": "Dispute me",
            "content": "Body",
            "source_type": "sensor",
        },
    )
    memory_id = created.json()["id"]

    response = client.post(f"/api/v1/memories/{memory_id}/dispute")

    assert response.status_code == 200
    assert response.json()["status"] == MemoryStatus.DISPUTED.value


def test_invalid_lifecycle_transition_returns_409(client):
    original = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Original",
            "content": "Body",
            "source_type": "sensor",
        },
    ).json()
    replacement = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.RECOMMENDATION.value,
            "title": "Replacement",
            "content": "Body",
            "source_type": "manual",
        },
    ).json()

    client.post(f"/api/v1/memories/{original['id']}/supersede", json={"replacement": {"memory_type": MemoryType.RECOMMENDATION.value, "title": "Replacement", "content": "Body", "source_type": "manual"}})
    response = client.post(f"/api/v1/memories/{original['id']}/archive")

    assert response.status_code == 409


def test_supersede_memory_returns_200(client):
    original = client.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Original",
            "content": "Body",
            "source_type": "sensor",
        },
    ).json()

    response = client.post(
        f"/api/v1/memories/{original['id']}/supersede",
        json={
            "replacement": {
                "memory_type": MemoryType.RECOMMENDATION.value,
                "title": "Replacement",
                "content": "Body",
                "source_type": "manual",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_memory"]["status"] == MemoryStatus.SUPERSEDED.value
    assert body["replacement"]["status"] == MemoryStatus.ACTIVE.value
    assert body["replacement"]["supersedes_memory_id"] == original["id"]


def test_get_missing_memory_returns_404(client):
    response = client.get(f"/api/v1/memories/{uuid4()}")

    assert response.status_code == 404


def test_health_endpoint_preserved(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}
