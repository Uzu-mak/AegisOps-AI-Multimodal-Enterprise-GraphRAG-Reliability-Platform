"""Integration tests for Qdrant health and collection initialization."""

import pytest
from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.embeddings.fake import DeterministicFakeEmbedding
from app.semantic.index import SemanticIndexError
from app.semantic.qdrant_impl import QdrantSemanticIndex
from app.semantic.qdrant_config import COLLECTION_NAME


@pytest.fixture
def qdrant_client() -> QdrantClient:
    """Create Qdrant client from settings."""
    settings = get_settings()
    return QdrantClient(settings.QDRANT_URL)


@pytest.fixture
def embedding_provider():
    """Create embedding provider."""
    return DeterministicFakeEmbedding()


class TestQdrantHealth:
    """Tests for Qdrant connectivity and health."""

    def test_qdrant_connection(self, qdrant_client: QdrantClient):
        """Test that Qdrant is reachable and returns collections."""
        # Should not raise
        collections = qdrant_client.get_collections()
        assert collections is not None

    def test_collection_creation(
        self, qdrant_client: QdrantClient, embedding_provider
    ):
        """Test that semantic index creates collection on init."""
        # Create index (should auto-create collection)
        index = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name="test_memories",
        )

        # Verify collection exists
        collections = qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]
        assert "test_memories" in collection_names

        # Clean up
        qdrant_client.delete_collection("test_memories")

    def test_collection_already_exists(
        self, qdrant_client: QdrantClient, embedding_provider
    ):
        """Test that semantic index handles existing collections gracefully."""
        # Create twice - second init should not fail
        index1 = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name="test_existing",
        )
        index2 = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name="test_existing",
        )

        # Both should succeed
        assert index1 is not None
        assert index2 is not None

        # Clean up
        qdrant_client.delete_collection("test_existing")

    def test_collection_vector_config(
        self, qdrant_client: QdrantClient, embedding_provider
    ):
        """Test that collection vector config matches embedding dimension."""
        index = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name="test_config",
        )

        collection = qdrant_client.get_collection("test_config")
        assert collection.config.params.vectors.size == embedding_provider.get_dimension()

        # Clean up
        qdrant_client.delete_collection("test_config")
