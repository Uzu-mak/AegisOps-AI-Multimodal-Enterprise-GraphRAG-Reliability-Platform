"""
Semantic API integration tests.

Verifies that API endpoints correctly orchestrate PostgreSQL writes and
semantic indexing, and that Qdrant failures never break PostgreSQL operations.

Architecture under test:
  Route → MemoryService (PostgreSQL commit) → SemanticIndexingService (best-effort)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_memory_service
from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.db.session import SessionLocal
from app.main import app
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.memory_service import RealMemoryService
from app.services.semantic_service import SemanticIndexingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_payload(**overrides) -> dict:
    return {
        "memory_type": MemoryType.OBSERVATION.value,
        "title": "Semantic integration test",
        "content": "Test content for semantic indexing",
        "source_type": "sensor",
        "asset_id": "asset-001",
        "confidence": 0.85,
        "importance": 0.75,
        **overrides,
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
def mock_semantic_service() -> MagicMock:
    """Return a mock SemanticIndexingService that records all calls."""
    mock = MagicMock(spec=SemanticIndexingService)
    return mock


@pytest.fixture
def client_with_semantic(mock_semantic_service) -> TestClient:
    """TestClient with a mock SemanticIndexingService injected."""
    def _get_service_override():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=mock_semantic_service,
        )

    app.dependency_overrides[get_memory_service] = _get_service_override
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


@pytest.fixture
def client_no_semantic() -> TestClient:
    """TestClient with semantic indexing disabled (None)."""
    def _get_service_override():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=None,
        )

    app.dependency_overrides[get_memory_service] = _get_service_override
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


@pytest.fixture
def client_failing_semantic() -> TestClient:
    """TestClient with a semantic service that always raises SemanticIndexError."""
    from app.semantic.index import SemanticIndexError

    mock = MagicMock(spec=SemanticIndexingService)
    mock.index_memory.side_effect = SemanticIndexError("Qdrant unavailable")
    mock.update_memory_index.side_effect = SemanticIndexError("Qdrant unavailable")
    mock.archive_memory.side_effect = SemanticIndexError("Qdrant unavailable")
    mock.dispute_memory.side_effect = SemanticIndexError("Qdrant unavailable")
    mock.supersede_memory.side_effect = SemanticIndexError("Qdrant unavailable")

    def _get_service_override():
        return RealMemoryService(
            repository=SQLAlchemyMemoryRepository(),
            session_factory=SessionLocal,
            semantic_indexing_service=mock,
        )

    app.dependency_overrides[get_memory_service] = _get_service_override
    yield TestClient(app)
    app.dependency_overrides.pop(get_memory_service, None)


# ---------------------------------------------------------------------------
# POST /memories — create
# ---------------------------------------------------------------------------

class TestCreateMemorySemanticIndexing:

    def test_create_memory_calls_index_memory(self, client_with_semantic, mock_semantic_service):
        """POST memory → SemanticIndexingService.index_memory() is called once."""
        response = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        assert response.status_code == 201
        mock_semantic_service.index_memory.assert_called_once()

    def test_create_memory_indexed_with_correct_memory_object(
        self, client_with_semantic, mock_semantic_service
    ):
        """The MemoryRecord passed to index_memory matches the created memory."""
        response = client_with_semantic.post(
            "/api/v1/memories", json=_base_payload(title="Exact Title")
        )
        assert response.status_code == 201
        memory_id = response.json()["id"]

        args, _ = mock_semantic_service.index_memory.call_args
        indexed_memory: MemoryRecord = args[0]
        assert str(indexed_memory.id) == memory_id
        assert indexed_memory.title == "Exact Title"

    def test_create_memory_qdrant_failure_returns_201(self, client_failing_semantic):
        """Qdrant failure must NOT prevent HTTP 201 — PostgreSQL is canonical."""
        response = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        assert response.status_code == 201

    def test_create_memory_qdrant_failure_persists_to_postgres(self, client_failing_semantic):
        """Even when Qdrant fails, the memory is stored in PostgreSQL."""
        response = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        assert response.status_code == 201
        memory_id = response.json()["id"]

        # GET directly from PostgreSQL via service (no Qdrant involved)
        get_response = client_failing_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == memory_id

    def test_create_memory_no_semantic_service_returns_201(self, client_no_semantic):
        """When semantic indexing is disabled, memory creation still succeeds."""
        response = client_no_semantic.post("/api/v1/memories", json=_base_payload())
        assert response.status_code == 201


# ---------------------------------------------------------------------------
# GET /memories — retrieval does not touch Qdrant
# ---------------------------------------------------------------------------

class TestGetMemoryNoQdrant:

    def test_get_memory_does_not_call_semantic_index(
        self, client_with_semantic, mock_semantic_service
    ):
        """GET should never call any semantic service method."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        get_resp = client_with_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200

        mock_semantic_service.index_memory.assert_not_called()
        mock_semantic_service.update_memory_index.assert_not_called()

    def test_get_memory_qdrant_unavailable_still_returns_200(self, client_failing_semantic):
        """GET works even if Qdrant is down — data comes from PostgreSQL."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        get_resp = client_failing_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /memories — update
# ---------------------------------------------------------------------------

class TestUpdateMemorySemanticIndexing:

    def test_patch_semantic_fields_calls_update_index(
        self, client_with_semantic, mock_semantic_service
    ):
        """PATCH with semantic fields (title, content) → update_memory_index called."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        patch_resp = client_with_semantic.patch(
            f"/api/v1/memories/{memory_id}",
            json={"title": "Updated Title", "content": "Updated content"},
        )
        assert patch_resp.status_code == 200
        mock_semantic_service.update_memory_index.assert_called_once()

    def test_patch_qdrant_failure_returns_200(self, client_failing_semantic):
        """PATCH semantic failure must NOT prevent HTTP 200."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        patch_resp = client_failing_semantic.patch(
            f"/api/v1/memories/{memory_id}",
            json={"title": "Updated Title"},
        )
        assert patch_resp.status_code == 200

    def test_patch_qdrant_failure_still_updates_postgres(self, client_failing_semantic):
        """PATCH Qdrant failure: PostgreSQL record is still updated."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        client_failing_semantic.patch(
            f"/api/v1/memories/{memory_id}",
            json={"title": "Persisted Update"},
        )

        get_resp = client_failing_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Persisted Update"


# ---------------------------------------------------------------------------
# POST /memories/{id}/archive
# ---------------------------------------------------------------------------

class TestArchiveMemorySemanticIndexing:

    def test_archive_calls_mark_inactive_archived(
        self, client_with_semantic, mock_semantic_service
    ):
        """Archive → SemanticIndexingService.archive_memory() called."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        archive_resp = client_with_semantic.post(f"/api/v1/memories/{memory_id}/archive")
        assert archive_resp.status_code == 200
        mock_semantic_service.archive_memory.assert_called_once()

    def test_archive_qdrant_failure_returns_200(self, client_failing_semantic):
        """Archive Qdrant failure must NOT prevent HTTP 200."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        archive_resp = client_failing_semantic.post(f"/api/v1/memories/{memory_id}/archive")
        assert archive_resp.status_code == 200

    def test_archive_qdrant_failure_status_in_postgres(self, client_failing_semantic):
        """Archive Qdrant failure: PostgreSQL record still shows ARCHIVED status."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        client_failing_semantic.post(f"/api/v1/memories/{memory_id}/archive")

        get_resp = client_failing_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == MemoryStatus.ARCHIVED.value


# ---------------------------------------------------------------------------
# POST /memories/{id}/dispute
# ---------------------------------------------------------------------------

class TestDisputeMemorySemanticIndexing:

    def test_dispute_calls_dispute_memory(
        self, client_with_semantic, mock_semantic_service
    ):
        """Dispute → SemanticIndexingService.dispute_memory() called."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        dispute_resp = client_with_semantic.post(f"/api/v1/memories/{memory_id}/dispute")
        assert dispute_resp.status_code == 200
        mock_semantic_service.dispute_memory.assert_called_once()

    def test_dispute_qdrant_failure_returns_200(self, client_failing_semantic):
        """Dispute Qdrant failure must NOT prevent HTTP 200."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        dispute_resp = client_failing_semantic.post(f"/api/v1/memories/{memory_id}/dispute")
        assert dispute_resp.status_code == 200

    def test_dispute_qdrant_failure_status_in_postgres(self, client_failing_semantic):
        """Dispute Qdrant failure: PostgreSQL record still shows DISPUTED status."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        client_failing_semantic.post(f"/api/v1/memories/{memory_id}/dispute")

        get_resp = client_failing_semantic.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == MemoryStatus.DISPUTED.value


# ---------------------------------------------------------------------------
# POST /memories/{id}/supersede
# ---------------------------------------------------------------------------

class TestSupersededMemorySemanticIndexing:

    def _replacement_payload(self) -> dict:
        return {
            "replacement": {
                "memory_type": MemoryType.OBSERVATION.value,
                "title": "Replacement memory",
                "content": "Updated understanding",
                "source_type": "sensor",
                "asset_id": "asset-001",
                "confidence": 0.9,
                "importance": 0.9,
            }
        }

    def test_supersede_calls_supersede_memory(
        self, client_with_semantic, mock_semantic_service
    ):
        """Supersede → SemanticIndexingService.supersede_memory() called."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        supersede_resp = client_with_semantic.post(
            f"/api/v1/memories/{memory_id}/supersede",
            json=self._replacement_payload(),
        )
        assert supersede_resp.status_code == 200
        mock_semantic_service.supersede_memory.assert_called_once()

    def test_supersede_passes_old_id_and_new_record(
        self, client_with_semantic, mock_semantic_service
    ):
        """supersede_memory receives correct old_memory_id and new MemoryRecord."""
        create_resp = client_with_semantic.post("/api/v1/memories", json=_base_payload())
        old_id = create_resp.json()["id"]
        mock_semantic_service.reset_mock()

        supersede_resp = client_with_semantic.post(
            f"/api/v1/memories/{old_id}/supersede",
            json=self._replacement_payload(),
        )
        assert supersede_resp.status_code == 200
        new_id = supersede_resp.json()["replacement"]["id"]

        args, _ = mock_semantic_service.supersede_memory.call_args
        called_old_id, called_new_memory = args
        assert str(called_old_id) == old_id
        assert str(called_new_memory.id) == new_id

    def test_supersede_qdrant_failure_returns_200(self, client_failing_semantic):
        """Supersede Qdrant failure must NOT prevent HTTP 200."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        memory_id = create_resp.json()["id"]

        supersede_resp = client_failing_semantic.post(
            f"/api/v1/memories/{memory_id}/supersede",
            json=self._replacement_payload(),
        )
        assert supersede_resp.status_code == 200

    def test_supersede_qdrant_failure_postgres_shows_superseded(
        self, client_failing_semantic
    ):
        """Supersede Qdrant failure: both old and new records stored in PostgreSQL."""
        create_resp = client_failing_semantic.post("/api/v1/memories", json=_base_payload())
        old_id = create_resp.json()["id"]

        supersede_resp = client_failing_semantic.post(
            f"/api/v1/memories/{old_id}/supersede",
            json=self._replacement_payload(),
        )
        assert supersede_resp.status_code == 200

        # Old memory: SUPERSEDED in PostgreSQL
        old_get = client_failing_semantic.get(f"/api/v1/memories/{old_id}")
        assert old_get.status_code == 200
        assert old_get.json()["status"] == MemoryStatus.SUPERSEDED.value

        # New memory: ACTIVE in PostgreSQL
        new_id = supersede_resp.json()["replacement"]["id"]
        new_get = client_failing_semantic.get(f"/api/v1/memories/{new_id}")
        assert new_get.status_code == 200
        assert new_get.json()["status"] == MemoryStatus.ACTIVE.value
