from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends
from neo4j import Driver
from qdrant_client import QdrantClient

from app.core.config import Settings, get_settings
from app.core.connections import get_connections
from app.db.session import SessionLocal
from app.embeddings.factory import create_embedding_provider
from app.embeddings.provider import EmbeddingProvider
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from app.graphrag.provider import LLMProvider
from app.graphrag.providers import create_llm_provider
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.retrieval.hybrid import HybridMemoryRetriever
from app.semantic.index import SemanticIndexError
from app.semantic.qdrant_impl import QdrantSemanticIndex
from app.services.graph_service import GraphProjectionService
from app.services.memory_service import MemoryService, RealMemoryService
from app.services.semantic_service import SemanticIndexingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qdrant / Semantic dependencies
# ---------------------------------------------------------------------------

_embedding_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (see app/embeddings/factory.py)."""
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = create_embedding_provider()
    return _embedding_provider


def get_qdrant_client(settings: Settings = Depends(get_settings)) -> QdrantClient:
    """
    Return the process-wide cached Qdrant client.

    Raises:
        SemanticIndexError: If Qdrant is unavailable (allows graceful degradation).
            Fails fast during the retry cool-down instead of re-paying connect timeouts.
    """
    conns = get_connections()
    client = conns.qdrant_client()
    if client is None:
        raise SemanticIndexError(f"Qdrant unavailable: {conns.probe('qdrant').get('error')}")
    return client


def get_semantic_index(
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> Optional[QdrantSemanticIndex]:
    """Cached semantic index if Qdrant is available, else None."""
    index = get_connections().semantic_index(embedding_provider)
    if index is None:
        logger.debug("Semantic index unavailable (Qdrant down or in retry cool-down)")
    return index


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

def get_neo4j_driver() -> Optional[Driver]:
    """Return the process-wide cached Neo4j driver, or None if unavailable."""
    return get_connections().neo4j_driver()


def get_graph_memory_index() -> Optional[Neo4jGraphMemoryIndex]:
    """Cached Neo4j graph index (constraints bootstrapped once per process), or None."""
    return get_connections().graph_index()


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


# ---------------------------------------------------------------------------
# Search / GraphRAG dependencies
# ---------------------------------------------------------------------------

def get_hybrid_retriever(
    semantic_index: Optional[QdrantSemanticIndex] = Depends(get_semantic_index),
    graph_index: Optional[Neo4jGraphMemoryIndex] = Depends(get_graph_memory_index),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> HybridMemoryRetriever:
    """Create a retriever from DI-provided stores/providers."""
    return HybridMemoryRetriever(
        semantic_index=semantic_index,
        graph_index=graph_index,
        embedding_provider=embedding_provider,
        session_factory=SessionLocal,
    )


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Create config-selected LLM provider."""
    return create_llm_provider(settings)
