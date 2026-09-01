from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_graph_memory_index, get_semantic_index
from app.db.models.memory import MemoryRecord, MemoryType
from app.db.session import SessionLocal
from app.main import app
from app.outbox.models import ProjectionOutboxEvent


@pytest.fixture(autouse=True)
def clean_memories():
    with SessionLocal() as session:
        session.execute(delete(ProjectionOutboxEvent))
        session.execute(delete(MemoryRecord))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(ProjectionOutboxEvent))
        session.execute(delete(MemoryRecord))
        session.commit()


@pytest.fixture
def client_projection_dependencies_unavailable() -> TestClient:
    app.dependency_overrides[get_semantic_index] = lambda: None
    app.dependency_overrides[get_graph_memory_index] = lambda: None

    yield TestClient(app)

    app.dependency_overrides.pop(get_semantic_index, None)
    app.dependency_overrides.pop(get_graph_memory_index, None)


def test_create_memory_succeeds_when_qdrant_and_neo4j_unavailable(
    client_projection_dependencies_unavailable: TestClient,
):
    response = client_projection_dependencies_unavailable.post(
        "/api/v1/memories",
        json={
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Canonical write",
            "content": "Should persist even when projections are unavailable",
            "source_type": "sensor",
            "confidence": 0.9,
            "importance": 0.7,
        },
    )

    assert response.status_code == 201
    assert response.json()["id"]
