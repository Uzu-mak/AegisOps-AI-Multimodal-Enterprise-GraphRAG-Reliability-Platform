import hashlib

from app.embeddings.provider import EmbeddingProvider


class DeterministicFakeEmbedding(EmbeddingProvider):
    """
    Deterministic fake embedding for testing.
    Same input always produces same vector.
    Dimension: 128 (small for test speed).

    ⚠️ WARNING: Hash-based vectors are NOT semantic embeddings.
    This class is for testing infrastructure (ranking, filtering, retrieval)
    NOT for testing semantic similarity or quality.
    """

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        """
        Generate deterministic embedding from text hash.
        Same input always produces the same vector.
        """
        hash_bytes = hashlib.sha256(text.encode()).digest()
        vector = []
        for i in range(self.dimension):
            byte_index = i % len(hash_bytes)
            # Normalize to [-1, 1]
            value = (hash_bytes[byte_index] / 128.0) - 1.0
            vector.append(value)
        return vector

    def get_dimension(self) -> int:
        return self.dimension
