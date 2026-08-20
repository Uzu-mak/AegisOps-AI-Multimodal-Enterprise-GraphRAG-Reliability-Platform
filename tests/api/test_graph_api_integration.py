"""
Graph API integration tests.

Tests that API endpoints correctly trigger graph projection, that Neo4j
failures do not break PostgreSQL operations, and that Qdrant/Neo4j failures
are isolated from each other.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_memory_service
from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.db.session import SessionLocal
from app.graph.index import GraphProjectionError
from app.main import app
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.graph_service import GraphProjectionService
from app.services.memory_service import RealMemoryService
from app.services.semantic_service import SemanticIndexingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_payload(**overrides) -> dict:
    return {
        "memory_type": MemoryType.OBSERVATION.value,
        "title": "Graph integration test",
        "content": "Test content for graph projection",
        "source_type": "sensor",
        "asset_id": "pump-graph-test",
        "facility_id": "plant-graph",
        "confidence": 0.8,
        "importance": 0.7,
        **overrides,
    }


def _replacement_payload() -> dict:
    return {
        "replacement": {
            "memory_type": MemoryType.OBSERVATION.value,
            "title": "Replacement memory",
            "content": "Updated content",
            "source_type": "sensor",
            "confidence": 0.9,
            "importance": 0.9,
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def mock_graph_service() -> MagicMock:
    return MagicMock(spec=GraphProjectionService)


@pytest.fixture
def mock_semantic_service() -> MagicMock:
    return MagicMock(spec=SemanticIndexingService)


@pytest.fixture
def client_with_graph(mock_graph_service, mock_semantic_service) -> TestClient:
    """Client with both semantic and graph projections mocked."""
    def _get_service():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=mock_semantic_service,
            graph_projection_service=mock_graph_service,
        )
    app.dependency_overrides[get_memory_service] = _get_service
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


@pytest.fixture
def client_failing_graph(mock_semantic_service) -> TestClient:
    """Client where graph projection always raises GraphProjectionError."""
    from app.semantic.index import SemanticIndexError

    failing_graph = MagicMock(spec=GraphProjectionService)
    failing_graph.project_memory.side_effect = GraphProjectionError("Neo4j unavailable")
    failing_graph.update_memory_status.side_effect = GraphProjectionError("Neo4j unavailable")
    failing_graph.project_supersession.side_effect = GraphProjectionError("Neo4j unavailable")

    failing_semantic = MagicMock(spec=SemanticIndexingService)
    failing_semantic.index_memory.side_effect = SemanticIndexError("Qdrant unavailable")

    def _get_service():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=failing_semantic,
            graph_projection_service=failing_graph,
        )
    app.dependency_overrides[get_memory_service] = _get_service
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


@pytest.fixture
def client_qdrant_fails_graph_succeeds(mock_graph_service) -> TestClient:
    """Client where Qdrant fails but Neo4j should still be attempted."""
    from app.services.semantic_service import SemanticIndexingService
    from app.semantic.index import SemanticIndexError

    failing_semantic = MagicMock(spec=SemanticIndexingService)
    failing_semantic.index_memory.side_effect = SemanticIndexError("Qdrant down")

    def _get_service():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=failing_semantic,
            graph_projection_service=mock_graph_service,
        )
    app.dependency_overrides[get_memory_service] = _get_service
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


# ---------------------------------------------------------------------------
# Tests: graph projection is called
# ---------------------------------------------------------------------------

class TestGraphProjectionCalled:

    def test_create_memory_calls_graph_projection(
        self, client_with_graph, mock_graph_service
    ):
        resp = client_with_graph.post("/api/v1/memories", json=_base_payload())
        assert resp.status_code == 201
        mock_graph_service.project_memory.assert_called_once()

    def test_create_memory_graph_called_with_correct_id(
        self, client_with_graph, mock_graph_service
    ):
        resp = client_with_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = resp.json()["id"]
        args, _ = mock_graph_service.project_memory.call_args
        projected: MemoryRecord = args[0]
        assert str(projected.id) == memory_id

    def test_archive_calls_graph_update_status(
        self, client_with_graph, mock_graph_service
    ):
        create_resp = client_with_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_graph_service.reset_mock()

        resp = client_with_graph.post(f"/api/v1/memories/{memory_id}/archive")
        assert resp.status_code == 200
        mock_graph_service.update_memory_status.assert_called_once()

    def test_dispute_calls_graph_update_status(
        self, client_with_graph, mock_graph_service
    ):
        create_resp = client_with_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_graph_service.reset_mock()

        resp = client_with_graph.post(f"/api/v1/memories/{memory_id}/dispute")
        assert resp.status_code == 200
        mock_graph_service.update_memory_status.assert_called_once()

    def test_supersede_calls_graph_project_supersession(
        self, client_with_graph, mock_graph_service
    ):
        create_resp = client_with_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_graph_service.reset_mock()

        resp = client_with_graph.post(
            f"/api/v1/memories/{memory_id}/supersede",
            json=_replacement_payload(),
        )
        assert resp.status_code == 200
        mock_graph_service.project_supersession.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Neo4j failure isolation
# ---------------------------------------------------------------------------

class TestNeo4jFailureIsolation:

    def test_neo4j_failure_returns_201(self, client_failing_graph):
        """Graph projection failure must NOT prevent HTTP 201."""
        resp = client_failing_graph.post("/api/v1/memories", json=_base_payload())
        assert resp.status_code == 201

    def test_neo4j_failure_memory_persists_to_postgres(self, client_failing_graph):
        """Even when Neo4j fails, memory is stored in PostgreSQL."""
        resp = client_failing_graph.post("/api/v1/memories", json=_base_payload())
        assert resp.status_code == 201
        memory_id = resp.json()["id"]

        get_resp = client_failing_graph.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == memory_id

    def test_neo4j_failure_archive_returns_200(self, client_failing_graph):
        resp = client_failing_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = resp.json()["id"]

        archive_resp = client_failing_graph.post(f"/api/v1/memories/{memory_id}/archive")
        assert archive_resp.status_code == 200

    def test_neo4j_failure_postgres_status_still_archived(self, client_failing_graph):
        resp = client_failing_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = resp.json()["id"]

        client_failing_graph.post(f"/api/v1/memories/{memory_id}/archive")

        get_resp = client_failing_graph.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.json()["status"] == MemoryStatus.ARCHIVED.value

    def test_neo4j_failure_supersede_returns_200(self, client_failing_graph):
        resp = client_failing_graph.post("/api/v1/memories", json=_base_payload())
        memory_id = resp.json()["id"]

        supersede_resp = client_failing_graph.post(
            f"/api/v1/memories/{memory_id}/supersede",
            json=_replacement_payload(),
        )
        assert supersede_resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Qdrant/Neo4j mutual isolation
# ---------------------------------------------------------------------------

class TestProjectionMutualIsolation:

    def test_qdrant_failure_does_not_prevent_neo4j_projection(
        self, client_qdrant_fails_graph_succeeds, mock_graph_service
    ):
        """Qdrant failure must not skip Neo4j projection."""
        resp = client_qdrant_fails_graph_succeeds.post(
            "/api/v1/memories", json=_base_payload()
        )
        assert resp.status_code == 201
        # Graph projection should still have been attempted
        mock_graph_service.project_memory.assert_called_once()

    def test_qdrant_failure_postgres_still_succeeds(
        self, client_qdrant_fails_graph_succeeds
    ):
        resp = client_qdrant_fails_graph_succeeds.post(
            "/api/v1/memories", json=_base_payload()
        )
        assert resp.status_code == 201
        memory_id = resp.json()["id"]

        get_resp = client_qdrant_fails_graph_succeeds.get(
            f"/api/v1/memories/{memory_id}"
        )
        assert get_resp.status_code == 200
