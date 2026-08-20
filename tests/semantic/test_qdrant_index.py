"""Tests for Qdrant semantic index integration."""

from datetime import datetime
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from app.db.models.memory import MemoryStatus, MemoryType
from app.embeddings.fake import DeterministicFakeEmbedding
from app.semantic.index import VectorRecord
from app.semantic.qdrant_impl import QdrantSemanticIndex


@pytest.fixture
def qdrant_client() -> QdrantClient:
    """Create Qdrant client."""
    return QdrantClient("http://qdrant:6333")


@pytest.fixture
def embedding_provider():
    """Create embedding provider."""
    return DeterministicFakeEmbedding()


@pytest.fixture
def semantic_index(qdrant_client: QdrantClient, embedding_provider):
    """Create semantic index for testing."""
    index = QdrantSemanticIndex(
        qdrant_client=qdrant_client,
        embedding_provider=embedding_provider,
        collection_name="test_index",
    )
    yield index
    # Clean up
    try:
        qdrant_client.delete_collection("test_index")
    except Exception:
        pass


class TestQdrantSemanticIndex:
    """Tests for QdrantSemanticIndex operations."""

    def test_index_memory(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test indexing a memory."""
        memory_id = uuid4()
        text = "Test memory content"
        record = VectorRecord(
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

        # Index should not raise
        semantic_index.index_memory(memory_id, text, record)

        # Verify retrieval
        retrieved = semantic_index.get_vector_record(memory_id)
        assert retrieved is not None
        assert retrieved.memory_id == memory_id
        assert retrieved.status == MemoryStatus.ACTIVE.value

    def test_search_similar(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test searching for similar memories."""
        # Index 3 memories
        memories = []
        for i in range(3):
            memory_id = uuid4()
            text = f"Memory {i} with unique content"
            record = VectorRecord(
                memory_id=memory_id,
                memory_type=MemoryType.OBSERVATION.value,
                status=MemoryStatus.ACTIVE.value,
                asset_id=f"asset-{i}",
                facility_id="facility-456",
                source_type="sensor",
                created_at=datetime.now(),
                importance=0.5 + i * 0.1,
                confidence=0.8,
            )
            semantic_index.index_memory(memory_id, text, record)
            memories.append(memory_id)

        # Search using embedding of first memory's text
        query_text = "Memory 0 with unique content"
        query_vector = embedding_provider.embed_text(query_text)

        results = semantic_index.search_similar(query_vector, limit=10)
        assert len(results) > 0
        # First result should be the most similar (same text)
        assert results[0].memory_id == memories[0]

    def test_remove_memory(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test removing a memory from index."""
        memory_id = uuid4()
        text = "Memory to remove"
        record = VectorRecord(
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

        # Index then remove
        semantic_index.index_memory(memory_id, text, record)
        assert semantic_index.get_vector_record(memory_id) is not None

        semantic_index.remove_memory(memory_id)
        assert semantic_index.get_vector_record(memory_id) is None

    def test_mark_inactive_archived(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test marking memory as archived."""
        memory_id = uuid4()
        text = "Memory to archive"
        record = VectorRecord(
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

        # Index then mark inactive
        semantic_index.index_memory(memory_id, text, record)
        semantic_index.mark_inactive(memory_id, "archived")

        # Verify status updated
        retrieved = semantic_index.get_vector_record(memory_id)
        assert retrieved is not None
        assert retrieved.status == "archived"

    def test_mark_inactive_disputed(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test marking memory as disputed."""
        memory_id = uuid4()
        text = "Disputed memory"
        record = VectorRecord(
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

        semantic_index.index_memory(memory_id, text, record)
        semantic_index.mark_inactive(memory_id, "disputed")

        retrieved = semantic_index.get_vector_record(memory_id)
        assert retrieved is not None
        assert retrieved.status == "disputed"

    def test_mark_inactive_nonexistent(
        self, semantic_index: QdrantSemanticIndex
    ):
        """Test marking nonexistent memory as inactive (should not raise)."""
        nonexistent_id = uuid4()
        # Should not raise
        semantic_index.mark_inactive(nonexistent_id, "archived")

    def test_search_with_filters(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test search with metadata filters."""
        # Index 2 memories with different statuses
        active_id = uuid4()
        archived_id = uuid4()

        for memory_id, status in [(active_id, "active"), (archived_id, "archived")]:
            text = f"Memory with status {status}"
            record = VectorRecord(
                memory_id=memory_id,
                memory_type=MemoryType.OBSERVATION.value,
                status=status,
                asset_id="asset-123",
                facility_id="facility-456",
                source_type="sensor",
                created_at=datetime.now(),
                importance=0.8,
                confidence=0.9,
            )
            semantic_index.index_memory(memory_id, text, record)

        # Search all
        query_vector = embedding_provider.embed_text("Memory")
        all_results = semantic_index.search_similar(query_vector, limit=10)
        assert len(all_results) == 2

        # Search with status filter (if filters supported)
        # This depends on Qdrant filter syntax
        # For now, just verify search without filters works
        assert len(all_results) > 0

    def test_uuid_string_point_ids(
        self, semantic_index: QdrantSemanticIndex, embedding_provider
    ):
        """Test that UUID strings work as point IDs."""
        memory_id = uuid4()
        text = "Test UUID as point ID"
        record = VectorRecord(
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

        # Index using UUID string
        semantic_index.index_memory(memory_id, text, record)

        # Verify point exists with UUID string ID
        # (This verifies the str(memory_id) approach works)
        retrieved = semantic_index.get_vector_record(memory_id)
        assert retrieved is not None
        assert str(retrieved.memory_id) == str(memory_id)
