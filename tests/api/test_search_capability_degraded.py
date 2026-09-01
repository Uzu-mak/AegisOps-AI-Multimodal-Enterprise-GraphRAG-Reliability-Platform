from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_graph_memory_index, get_hybrid_retriever, get_semantic_index
from app.main import app


class EmptyRetriever:
    def retrieve(self, query):
        return []


@pytest.fixture
def client_no_projection_capabilities() -> TestClient:
    app.dependency_overrides[get_hybrid_retriever] = lambda: EmptyRetriever()
    app.dependency_overrides[get_semantic_index] = lambda: None
    app.dependency_overrides[get_graph_memory_index] = lambda: None

    yield TestClient(app)

    app.dependency_overrides.pop(get_hybrid_retriever, None)
    app.dependency_overrides.pop(get_semantic_index, None)
    app.dependency_overrides.pop(get_graph_memory_index, None)


def test_semantic_endpoint_returns_503_when_qdrant_unavailable(
    client_no_projection_capabilities: TestClient,
):
    response = client_no_projection_capabilities.post(
        "/api/v1/search/semantic",
        json={"query": "pump", "limit": 5},
    )

    assert response.status_code == 503
    assert "Qdrant" in response.json()["detail"]


def test_graph_mode_returns_503_when_neo4j_unavailable(
    client_no_projection_capabilities: TestClient,
):
    response = client_no_projection_capabilities.post(
        "/api/v1/search/hybrid",
        json={"query": "pump", "mode": "graph", "limit": 5, "graph_hops": 2},
    )

    assert response.status_code == 503
    assert "Neo4j" in response.json()["detail"]


def test_hybrid_mode_returns_503_when_both_projections_unavailable(
    client_no_projection_capabilities: TestClient,
):
    response = client_no_projection_capabilities.post(
        "/api/v1/search/hybrid",
        json={"query": "pump", "mode": "hybrid", "limit": 5, "graph_hops": 2},
    )

    assert response.status_code == 503
    assert "Qdrant" in response.json()["detail"] and "Neo4j" in response.json()["detail"]


def test_graph_related_returns_503_when_neo4j_unavailable(
    client_no_projection_capabilities: TestClient,
):
    response = client_no_projection_capabilities.post(
        "/api/v1/search/graph-related",
        json={"memory_id": "688f7f1a-8df8-4617-a91d-cd4f951bc3d9", "max_hops": 2, "limit": 10},
    )

    assert response.status_code == 503
    assert "Neo4j" in response.json()["detail"]
