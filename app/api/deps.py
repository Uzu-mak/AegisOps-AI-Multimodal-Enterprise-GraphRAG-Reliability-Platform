from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends
from qdrant_client import QdrantClient

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.embeddings.fake import DeterministicFakeEmbedding
from app.embeddings.provider import EmbeddingProvider
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.semantic.index import SemanticIndexError
from app.semantic.qdrant_impl import QdrantSemanticIndex
from app.services.memory_service import MemoryService, RealMemoryService
from app.services.semantic_service import SemanticIndexingService

logger = logging.getLogger(__name__)


def get_embedding_provider() -> EmbeddingProvider:
    """Return embedding provider (deterministic fake for now)."""
    return DeterministicFakeEmbedding()


def get_qdrant_client(settings: Settings = Depends(get_settings)) -> QdrantClient:
    """
    Create Qdrant client.

    Raises:
        SemanticIndexError: If connection fails (allows graceful degradation)
    """
    try:
        client = QdrantClient(settings.QDRANT_URL)
        # Quick health check
        client.get_collections()
        logger.info(f"Connected to Qdrant at {settings.QDRANT_URL}")
        return client
    except Exception as exc:
        logger.error(f"Failed to connect to Qdrant: {exc}")
        raise SemanticIndexError(f"Qdrant unavailable: {exc}") from exc


def get_semantic_index(
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    settings: Settings = Depends(get_settings),
) -> Optional[QdrantSemanticIndex]:
    """
    Create semantic index if Qdrant available, else return None.

    Returns:
        QdrantSemanticIndex if connected, None if Qdrant unavailable
    """
    try:
        qdrant_client = get_qdrant_client(settings)
    except SemanticIndexError as exc:
        logger.warning(
            f"Semantic indexing disabled (Qdrant unavailable): {exc}"
        )
        return None

    try:
        index = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name=settings.QDRANT_COLLECTION_NAME,
        )
        return index
    except SemanticIndexError as exc:
        logger.warning(f"Failed to initialize semantic index: {exc}")
        return None


def get_semantic_indexing_service(
    semantic_index: Optional[QdrantSemanticIndex] = Depends(get_semantic_index),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> Optional[SemanticIndexingService]:
    """
    Create semantic indexing service if semantic index available.

    Returns:
        SemanticIndexingService if Qdrant available, None otherwise
    """
    if semantic_index is None:
        logger.warning("Semantic indexing service disabled (Qdrant unavailable)")
        return None

    return SemanticIndexingService(
        semantic_index=semantic_index,
        embedding_provider=embedding_provider,
    )


def get_memory_service(
    semantic_indexing_service: Optional[
        SemanticIndexingService
    ] = Depends(get_semantic_indexing_service),
) -> MemoryService:
    """
    Create memory service with optional semantic indexing.

    Semantic indexing is non-fatal; if Qdrant unavailable, PostgreSQL operations
    continue without semantic indexing.
    """
    return RealMemoryService(
        repository=SQLAlchemyMemoryRepository(),
        session_factory=SessionLocal,
        semantic_indexing_service=semantic_indexing_service,
    )


def get_memory_service_dependency(
    service: MemoryService = Depends(get_memory_service),
) -> MemoryService:
    return service
