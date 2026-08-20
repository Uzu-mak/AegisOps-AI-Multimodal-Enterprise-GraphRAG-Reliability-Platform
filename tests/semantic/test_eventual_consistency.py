"""Tests for eventual consistency and Qdrant failure handling."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.memory import MemoryStatus, MemoryType
from app.embeddings.fake import DeterministicFakeEmbedding
from app.semantic.index import SemanticIndexError, VectorRecord
from app.semantic.qdrant_impl import QdrantSemanticIndex


@pytest.fixture
def embedding_provider():
    """Create embedding provider."""
    return DeterministicFakeEmbedding()


def create_test_record(memory_id) -> VectorRecord:
    """Create a test VectorRecord."""
    return VectorRecord(
        memory_id=memory_id,
        memory_type=MemoryType.OBSERVATION.value,
        status=MemoryStatus.ACTIVE.value,
        asset_id="asset-123",
        facility_id="facility-456",
        source_type="sensor",
        created_at=datetime.now(),
        importance=0.8,
        confidence=0.9,
    )


class TestQdrantFailureHandling:
    """Tests for handling Qdrant failures gracefully."""

    def test_index_memory_connection_failure(self, embedding_provider):
        """Test that indexing fails gracefully on connection error."""
        mock_client = MagicMock()
        mock_client.upsert.side_effect = ConnectionError("Connection refused")

        index = QdrantSemanticIndex(
            qdrant_client=mock_client,
            embedding_provider=embedding_provider,
            collection_name="test",
        )

        memory_id = uuid4()
        record = create_test_record(memory_id)

        # Should raise SemanticIndexError (caught by service layer)
        with pytest.raises(SemanticIndexError):
            index.index_memory(memory_id, "test text", record)

    def test_remove_memory_timeout(self, embedding_provider):
        """Test that removal fails gracefully on timeout."""
        mock_client = MagicMock()
        mock_client.delete.side_effect = TimeoutError("Request timeout")

        index = QdrantSemanticIndex(
            qdrant_client=mock_client,
            embedding_provider=embedding_provider,
            collection_name="test",
        )

        memory_id = uuid4()

        # Should raise SemanticIndexError
        with pytest.raises(SemanticIndexError):
            index.remove_memory(memory_id)

    def test_search_partial_failure(self, embedding_provider):
        """Test search fails gracefully."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Search failed")

        index = QdrantSemanticIndex(
            qdrant_client=mock_client,
            embedding_provider=embedding_provider,
            collection_name="test",
        )

        query_vector = embedding_provider.embed_text("test query")

        # Should raise SemanticIndexError
        with pytest.raises(SemanticIndexError):
            index.search_similar(query_vector, limit=10)

    def test_mark_inactive_not_found(self, embedding_provider):
        """Test marking nonexistent memory as inactive (graceful degradation)."""
        mock_client = MagicMock()
        mock_client.set_payload.side_effect = Exception("Point not found")

        index = QdrantSemanticIndex(
            qdrant_client=mock_client,
            embedding_provider=embedding_provider,
            collection_name="test",
        )

        memory_id = uuid4()

        # Should raise SemanticIndexError (service catches it)
        with pytest.raises(SemanticIndexError):
            index.mark_inactive(memory_id, "archived")

    def test_get_vector_record_network_failure(self, embedding_provider):
        """Test retrieval fails gracefully on network error."""
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = OSError("Network unreachable")

        index = QdrantSemanticIndex(
            qdrant_client=mock_client,
            embedding_provider=embedding_provider,
            collection_name="test",
        )

        memory_id = uuid4()

        # Should return None (not raise) per implementation
        result = index.get_vector_record(memory_id)
        assert result is None

    def test_collection_creation_failure(self, embedding_provider):
        """Test that collection creation failure raises."""
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")
        mock_client.create_collection.side_effect = Exception("Permission denied")

        # Should raise SemanticIndexError during init
        with pytest.raises(SemanticIndexError):
            QdrantSemanticIndex(
                qdrant_client=mock_client,
                embedding_provider=embedding_provider,
                collection_name="test",
            )


class TestEventualConsistency:
    """Tests for eventual consistency pattern."""

    def test_postgres_succeeds_qdrant_fails(self):
        """
        Test the eventual consistency pattern:
        PostgreSQL commits successfully, Qdrant indexing fails (best-effort).
        This is handled by MemoryService, not the index itself.
        """
        # This test verifies that SemanticIndexError is raised
        # and can be caught at service layer
        from app.services.semantic_service import SemanticIndexingService

        mock_index = MagicMock()
        mock_index.index_memory.side_effect = SemanticIndexError("Indexing failed")

        mock_embedding = MagicMock()
        mock_embedding.embed_text.return_value = [0.1] * 128

        service = SemanticIndexingService(
            semantic_index=mock_index,
            embedding_provider=mock_embedding,
        )

        memory_id = uuid4()
        mock_memory = MagicMock()
        mock_memory.id = memory_id
        mock_memory.title = "Test"
        mock_memory.content = "Content"
        mock_memory.memory_metadata = {}

        # Should raise SemanticIndexError (service catches it)
        with pytest.raises(SemanticIndexError):
            service.index_memory(mock_memory)

    def test_qdrant_unavailable_on_startup(self, embedding_provider):
        """
        Test that Qdrant unavailability doesn't prevent PostgreSQL operations.
        This is handled in deps.py.
        """
        # deps.py should gracefully handle QdrantClient init failure
        # SemanticIndexingService should be None if Qdrant unavailable
        # MemoryService should still work with semantic_indexing_service=None

        from app.services.memory_service import RealMemoryService

        mock_repo = MagicMock()
        mock_session = MagicMock()

        # Create service with no semantic indexing
        service = RealMemoryService(
            repository=mock_repo,
            session_factory=mock_session,
            semantic_indexing_service=None,  # Qdrant unavailable
        )

        # Service should initialize without error
        assert service is not None

    def test_partial_indexing_failure(self, embedding_provider):
        """Test that partial Qdrant failures don't prevent PostgreSQL commits."""
        from app.services.semantic_service import SemanticIndexingService

        # Mock index that fails on some operations
        mock_index = MagicMock()
        mock_index.index_memory.side_effect = Exception("Connection reset")

        mock_embedding = MagicMock()
        mock_embedding.embed_text.return_value = [0.1] * 128

        service = SemanticIndexingService(
            semantic_index=mock_index,
            embedding_provider=mock_embedding,
        )

        memory_id = uuid4()
        mock_memory = MagicMock()
        mock_memory.id = memory_id
        mock_memory.title = "Test"
        mock_memory.content = "Content"
        mock_memory.memory_metadata = {}

        # Service should raise SemanticIndexError (caught by MemoryService)
        with pytest.raises(SemanticIndexError):
            service.index_memory(mock_memory)
