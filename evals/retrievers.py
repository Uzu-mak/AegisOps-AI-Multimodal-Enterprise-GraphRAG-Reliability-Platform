from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable
from uuid import UUID

if TYPE_CHECKING:
    from app.embeddings.provider import EmbeddingProvider
    from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
    from app.retrieval.hybrid import HybridMemoryRetriever as ProductionHybridMemoryRetriever
    from app.semantic.qdrant_impl import QdrantSemanticIndex

from app.retrieval.models import RetrievalQuery


def rrf_merge(semantic_ids: Iterable[str], graph_ids: Iterable[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion for combining semantic and graph result lists.

    The production AegisOps system already exposes a hybrid retriever, but this
    helper keeps the standalone evaluation adapter reusable and testable.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[str, float] = {}

    for rank, memory_id in enumerate(list(semantic_ids)):
        scores[str(memory_id)] = scores.get(str(memory_id), 0.0) + 1.0 / (k + rank + 1)

    for rank, memory_id in enumerate(list(graph_ids)):
        scores[str(memory_id)] = scores.get(str(memory_id), 0.0) + 1.0 / (k + rank + 1)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [memory_id for memory_id, _ in ordered]


class BaseRetriever:
    def retrieve(self, query_text: str, k: int) -> list[str]:
        raise NotImplementedError


@dataclass
class VectorRetriever(BaseRetriever):
    semantic_index: Any
    embedding_provider: Any

    def retrieve(self, query_text: str, k: int) -> list[str]:
        vector = self.embedding_provider.embed_text(query_text)
        matches = self.semantic_index.search_similar(query_vector=vector, limit=k)
        return [str(match.memory_id) for match in matches]


@dataclass
class GraphRetriever(BaseRetriever):
    graph_index: Any
    semantic_index: Any = None
    embedding_provider: Any = None
    max_hops: int = 2

    def retrieve(self, query_text: str, k: int) -> list[str]:
        anchor_id: UUID | None = None
        if self.semantic_index is not None and self.embedding_provider is not None:
            vector = self.embedding_provider.embed_text(query_text)
            semantic_hits = self.semantic_index.search_similar(query_vector=vector, limit=1)
            if semantic_hits:
                anchor_id = semantic_hits[0].memory_id

        if anchor_id is None:
            return []

        related = self.graph_index.get_related_memory_ids(
            memory_id=anchor_id,
            max_hops=self.max_hops,
            limit=k,
        )
        return [str(memory_id) for memory_id in related]


@dataclass
class HybridRetriever(BaseRetriever):
    semantic_index: Any = None
    graph_index: Any = None
    embedding_provider: Any = None
    session_factory: Any = None
    fusion_k: int = 60
    production_retriever: Any = None

    def retrieve(self, query_text: str, k: int) -> list[str]:
        if self.production_retriever is not None:
            query = RetrievalQuery(text=query_text, mode="hybrid", final_limit=k)
            results = self.production_retriever.retrieve(query)
            return [str(result.memory_id) for result in results]

        if self.semantic_index is None or self.graph_index is None or self.embedding_provider is None:
            return []

        semantic_ids = VectorRetriever(
            semantic_index=self.semantic_index,
            embedding_provider=self.embedding_provider,
        ).retrieve(query_text, k=max(k, self.fusion_k))
        graph_ids = GraphRetriever(
            graph_index=self.graph_index,
            semantic_index=self.semantic_index,
            embedding_provider=self.embedding_provider,
        ).retrieve(query_text, k=max(k, self.fusion_k))
        return rrf_merge(semantic_ids, graph_ids, k=self.fusion_k)[:k]
