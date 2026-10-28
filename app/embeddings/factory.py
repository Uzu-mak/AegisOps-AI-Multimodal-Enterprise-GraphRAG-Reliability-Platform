"""Select the embedding provider from configuration."""
from __future__ import annotations

import logging

from app.embeddings.provider import EmbeddingProvider

logger = logging.getLogger(__name__)


def create_embedding_provider(name: str | None = None) -> EmbeddingProvider:
    """
    ``fake`` (default): SHA-256 test vectors, fully deterministic, not semantic.
    ``hashed_terms``: lexical term-hashing vectors; similarity tracks shared words.

    Both produce 128-dimensional vectors, so switching keeps the Qdrant
    collection compatible; re-project existing records afterwards so stored
    vectors and query vectors come from the same provider.
    """
    from app.core.config import get_settings

    choice = (name or getattr(get_settings(), "EMBEDDING_PROVIDER", "fake") or "fake").strip().lower()
    if choice in {"hashed_terms", "hashed-terms", "terms"}:
        from app.embeddings.hashed_terms import HashedTermEmbedding

        return HashedTermEmbedding()
    if choice not in {"fake", "test", "deterministic"}:
        logger.warning("Unknown EMBEDDING_PROVIDER=%r; using deterministic fake embedding", choice)
    from app.embeddings.fake import DeterministicFakeEmbedding

    return DeterministicFakeEmbedding()
