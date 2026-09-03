from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_graph_memory_index, get_hybrid_retriever, get_semantic_index
from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.main import app
from app.retrieval.models import RetrievalResult


class FakeRetriever:
    def __init__(self) -> None:
        self.last_query = None

    def retrieve(self, query):
        self.last_query = query

        rec = MemoryRecord()
        rec.id = uuid4()
        rec.memory_type = MemoryType.OBSERVATION.value
        rec.status = MemoryStatus.ACTIVE.value
        rec.title = "Retrieved title"
        rec.content = "Retrieved content"
        rec.asset_id = "asset-1"
        rec.facility_id = "facility-1"
        rec.confidence = 0.9
        rec.importance = 0.7
        rec.source_type = "sensor"
        rec.created_at = datetime.now(timezone.utc)

        return [
            RetrievalResult(
                memory_id=rec.id,
                retrieval_source="semantic",
                semantic_score=0.88,
                canonical_record=rec,
            )
        ]


@pytest.fixture
def client_with_retriever_override() -> TestClient:
    fake = FakeRetriever()

    app.dependency_overrides[get_hybrid_retriever] = lambda: fake
    app.dependency_overrides[get_semantic_index] = lambda: object()
    app.dependency_overrides[get_graph_memory_index] = lambda: object()

    yield TestClient(app)

    app.dependency_overrides.pop(get_hybrid_retriever, None)
    app.dependency_overrides.pop(get_semantic_index, None)
    app.dependency_overrides.pop(get_graph_memory_index, None)


def test_semantic_search_uses_di_retriever(client_with_retriever_override: TestClient):
    response = client_with_retriever_override.post(
        "/api/v1/search/semantic",
        json={"query": "pump vibration", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "semantic"
    assert body["total"] == 1
    result = body["results"][0]
    assert result["title"] == "Retrieved title"
    assert result["memory_type"] == MemoryType.OBSERVATION.value
    assert result["status"] == MemoryStatus.ACTIVE.value
    assert result["asset_id"] == "asset-1"
    assert result["facility_id"] == "facility-1"
    assert result["confidence"] == 0.9
    assert result["content_preview"] == "Retrieved content"


def test_hybrid_search_uses_di_retriever(client_with_retriever_override: TestClient):
    response = client_with_retriever_override.post(
        "/api/v1/search/hybrid",
        json={"query": "bearing wear", "mode": "hybrid", "limit": 5, "graph_hops": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid"
    assert body["total"] == 1
    result = body["results"][0]
    assert result["title"] == "Retrieved title"
    assert result["memory_type"] == MemoryType.OBSERVATION.value
    assert result["status"] == MemoryStatus.ACTIVE.value
