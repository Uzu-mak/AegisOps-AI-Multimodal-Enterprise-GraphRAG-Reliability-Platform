"""Qdrant collection configuration and utilities."""

COLLECTION_NAME = "memories"
EMBEDDING_DIMENSION = 128  # Override for real embeddings (e.g., 768)


def get_collection_config(embedding_dim: int) -> dict:
    """
    Qdrant collection configuration for semantic memories.

    Args:
        embedding_dim: Dimension of embedding vectors

    Returns:
        Collection config dict
    """
    return {
        "name": COLLECTION_NAME,
        "vectors_config": {
            "size": embedding_dim,
            "distance": "Cosine",
        },
        "payload_schema": {
            "memory_id": {"type": "text"},
            "memory_type": {"type": "text"},
            "status": {"type": "text"},
            "asset_id": {"type": "text"},
            "facility_id": {"type": "text"},
            "source_type": {"type": "text"},
            "created_at": {"type": "text"},
            "importance": {"type": "float"},
            "confidence": {"type": "float"},
        },
    }

