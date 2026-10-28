"""
Benchmark retrieval methods.

Every method is the production ``HybridMemoryRetriever`` in a fixed mode, so
recall@k measured here is the recall a user gets from the API and console
(same anchoring, same PostgreSQL hydration, same active-only filtering, same
ranking). There is deliberately no separate benchmark-only retrieval logic.

- vector: mode="semantic" (Qdrant similarity)
- graph:  mode="graph" (Neo4j neighbours of the best vector match)
- hybrid: mode="hybrid" (vector matches, then their graph neighbours)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.retrieval.models import RetrievalQuery


@dataclass
class ModeRetriever:
    production_retriever: Any
    mode: str

    def retrieve(self, query_text: str, k: int) -> list[str]:
        results = self.production_retriever.retrieve(
            RetrievalQuery(text=query_text, mode=self.mode, final_limit=k, semantic_limit=max(10, k))
        )
        return [str(result.memory_id) for result in results]


def build_mode_retrievers(production_retriever: Any, available: dict[str, bool]) -> dict[str, ModeRetriever | None]:
    """Return a retriever per benchmark method, or None when its backends are down."""
    return {
        "vector": ModeRetriever(production_retriever, "semantic") if available.get("qdrant") else None,
        "graph": ModeRetriever(production_retriever, "graph") if available.get("qdrant") and available.get("neo4j") else None,
        "hybrid": ModeRetriever(production_retriever, "hybrid") if available.get("qdrant") and available.get("neo4j") else None,
    }
