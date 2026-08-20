from typing import Protocol


class EmbeddingProvider(Protocol):
    """
    Replaceability pattern: embedding generation strategy.
    Allows deterministic fakes for tests, real models in production.
    """

    def embed_text(self, text: str) -> list[float]:
        """
        Embed a text string into a vector.

        Args:
            text: The text to embed (title + content + context)

        Returns:
            A list of floats representing the embedding vector

        Raises:
            EmbeddingError: If embedding generation fails
        """
        ...

    def get_dimension(self) -> int:
        """Return the embedding dimension (e.g., 384, 768, 1536)."""
        ...


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""

    pass
