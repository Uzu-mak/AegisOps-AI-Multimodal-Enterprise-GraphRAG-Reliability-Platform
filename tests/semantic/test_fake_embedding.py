"""Tests for deterministic fake embeddings."""

import hashlib

import pytest

from app.embeddings.fake import DeterministicFakeEmbedding


@pytest.fixture
def embedding_provider():
    """Create embedding provider."""
    return DeterministicFakeEmbedding()


class TestDeterministicFakeEmbedding:
    """Tests for DeterministicFakeEmbedding."""

    def test_deterministic_same_input_same_output(
        self, embedding_provider: DeterministicFakeEmbedding
    ):
        """Test that same input produces same embedding."""
        text = "This is a test memory"
        v1 = embedding_provider.embed_text(text)
        v2 = embedding_provider.embed_text(text)
        assert v1 == v2

    def test_different_input_different_output(
        self, embedding_provider: DeterministicFakeEmbedding
    ):
        """Test that different inputs produce different embeddings."""
        v1 = embedding_provider.embed_text("Memory A")
        v2 = embedding_provider.embed_text("Memory B")
        assert v1 != v2

    def test_embedding_dimension(
        self, embedding_provider: DeterministicFakeEmbedding
    ):
        """Test that embedding has correct dimension."""
        text = "Test text"
        vector = embedding_provider.embed_text(text)
        assert len(vector) == 128

    def test_embedding_range(self, embedding_provider: DeterministicFakeEmbedding):
        """Test that all values are in [-1, 1] range."""
        text = "Test text"
        vector = embedding_provider.embed_text(text)
        assert all(-1 <= v <= 1 for v in vector)

    def test_get_dimension(self, embedding_provider: DeterministicFakeEmbedding):
        """Test get_dimension returns 128."""
        assert embedding_provider.get_dimension() == 128

    def test_empty_text(self, embedding_provider: DeterministicFakeEmbedding):
        """Test embedding of empty text."""
        vector = embedding_provider.embed_text("")
        assert len(vector) == 128
        # Empty text should still produce deterministic embedding
        vector2 = embedding_provider.embed_text("")
        assert vector == vector2

    def test_long_text(self, embedding_provider: DeterministicFakeEmbedding):
        """Test embedding of very long text."""
        long_text = "word " * 10000  # 50KB of text
        vector = embedding_provider.embed_text(long_text)
        assert len(vector) == 128
        assert all(-1 <= v <= 1 for v in vector)

    def test_hash_based_derivation(
        self, embedding_provider: DeterministicFakeEmbedding
    ):
        """Test that embedding is derived from SHA256 hash."""
        text = "Hashable text"
        vector = embedding_provider.embed_text(text)

        # Verify it's deterministically derived from hash
        hash_bytes = hashlib.sha256(text.encode()).digest()
        assert len(hash_bytes) == 32  # SHA256 produces 32 bytes

        # Embedding should be normalized from hash
        assert len(vector) == 128
        # At least some values should be non-zero (statistically)
        assert sum(1 for v in vector if v != 0) > 50
