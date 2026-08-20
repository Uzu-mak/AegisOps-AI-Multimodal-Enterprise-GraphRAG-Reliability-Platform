from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends
from neo4j import Driver, GraphDatabase
from qdrant_client import QdrantClient

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.embeddings.fake import DeterministicFakeEmbedding
from app.embeddings.provider import EmbeddingProvider
from app.graph.index import GraphProjectionError
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.semantic.index import SemanticIndexError
from app.semantic.qdrant_impl import QdrantSemanticIndex
from app.services.graph_service import GraphProjectionService
from app.services.memory_service import MemoryService, RealMemoryService
from app.services.semantic_service import SemanticIndexingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qdrant / Semantic dependencies
# ---------------------------------------------------------------------------

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
    """Create semantic index if Qdrant available, else return None."""
    try:
        qdrant_client = get_qdrant_client(settings)
    except SemanticIndexError as exc:
        logger.warning(f"Semantic indexing disabled (Qdrant unavailable): {exc}")
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
    """Create semantic indexing service if semantic index available."""
    if semantic_index is None:
        logger.warning("Semantic indexing service disabled (Qdrant unavailable)")
        return None
    return SemanticIndexingService(
        semantic_index=semantic_index,
        embedding_provider=embedding_provider,
    )


# ---------------------------------------------------------------------------
# Neo4j / Graph dependencies
# ---------------------------------------------------------------------------

def get_neo4j_driver(settings: Settings = Depends(get_settings)) -> Optional[Driver]:
    """
    Create Neo4j driver.
    Returns None if Neo4j is unavailable (graceful degradation).
    """
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        logger.info(f"Connected to Neo4j at {settings.NEO4J_URI}")
        return driver
    except Exception as exc:
        logger.warning(f"Neo4j unavailable; graph projection disabled: {exc}")
        return None


def get_graph_memory_index(
    driver: Optional[Driver] = Depends(get_neo4j_driver),
    settings: Settings = Depends(get_settings),
) -> Optional[Neo4jGraphMemoryIndex]:
    """Create Neo4j graph index, bootstrapping constraints. Returns None if unavailable."""
    if driver is None:
        return None
    try:
        index = Neo4jGraphMemoryIndex(driver=driver, database=settings.NEO4J_DATABASE)
        index.bootstrap_constraints()
        return index
    except GraphProjectionError as exc:
        logger.warning(f"Failed to initialize graph index: {exc}")
        return None


def get_graph_projection_service(
    graph_index: Optional[Neo4jGraphMemoryIndex] = Depends(get_graph_memory_index),
) -> Optional[GraphProjectionService]:
    """Create graph projection service if graph index available."""
    if graph_index is None:
        logger.warning("Graph projection service disabled (Neo4j unavailable)")
        return None
    return GraphProjectionService(graph_index=graph_index)


# ---------------------------------------------------------------------------
# Memory service (composes all projections)
# ---------------------------------------------------------------------------

def get_memory_service(
    semantic_indexing_service: Optional[
        SemanticIndexingService
    ] = Depends(get_semantic_indexing_service),
    graph_projection_service: Optional[
        GraphProjectionService
    ] = Depends(get_graph_projection_service),
) -> MemoryService:
    """
    Create memory service with optional semantic and graph projections.
    Both projections are non-fatal: if unavailable, PostgreSQL operations continue.
    """
    return RealMemoryService(
        repository=SQLAlchemyMemoryRepository(),
        session_factory=SessionLocal,
        semantic_indexing_service=semantic_indexing_service,
        graph_projection_service=graph_projection_service,
    )


def get_memory_service_dependency(
    service: MemoryService = Depends(get_memory_service),
) -> MemoryService:
    return service



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
