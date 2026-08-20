"""
HybridMemoryRetriever — combines Qdrant semantic retrieval, Neo4j graph
traversal, and PostgreSQL canonical hydration.

Architecture:
    Query
      ↓
    Qdrant semantic retrieval (optional)   →  memory UUIDs + scores
      ↓
    Neo4j graph expansion (optional)       →  related memory UUIDs
      ↓
    merge / deduplicate
      ↓
    PostgreSQL canonical hydration         →  full MemoryRecord
      ↓
    RetrievalResult list

PostgreSQL is ALWAYS the final source of truth for canonical content.
Neither Qdrant nor Neo4j payloads are returned as authoritative memory content.
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from uuid import UUID

from app.db.models.memory import MemoryRecord
from app.embeddings.provider import EmbeddingProvider
from app.graph.index import GraphMemoryIndex
from app.retrieval.models import RetrievalQuery, RetrievalResult
from app.semantic.index import SemanticMemoryIndex

logger = logging.getLogger(__name__)


class HybridMemoryRetriever:
    """
    Combines semantic (Qdrant) and graph (Neo4j) retrieval, hydrates from
    PostgreSQL, and returns unified RetrievalResult objects.

    Each component is optional; the retriever degrades gracefully when a
    projection store is unavailable.
    """

    def __init__(
        self,
        semantic_index: Optional[SemanticMemoryIndex],
        graph_index: Optional[GraphMemoryIndex],
        embedding_provider: Optional[EmbeddingProvider],
        session_factory,  # SQLAlchemy SessionLocal
    ) -> None:
        self.semantic_index = semantic_index
        self.graph_index = graph_index
        self.embedding_provider = embedding_provider
        self.session_factory = session_factory

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        """
        Execute retrieval according to the query mode.

        Returns RetrievalResult list with canonical_record hydrated from
        PostgreSQL.
        """
        t0 = time.monotonic()
        semantic_hits: dict[UUID, float] = {}
        graph_hits: set[UUID] = set()

        # --- Semantic retrieval ---
        if query.mode in ("semantic", "hybrid") and self.semantic_index and self.embedding_provider:
            try:
                vec = self.embedding_provider.embed_text(query.text)
                results = self.semantic_index.search_similar(
                    query_vector=vec,
                    limit=query.semantic_limit,
                )
                semantic_hits = {r.memory_id: r.score for r in results}
                logger.debug(f"Semantic retrieval: {len(semantic_hits)} hits")
            except Exception as exc:
                logger.warning(f"Semantic retrieval failed: {exc}")

        # --- Graph retrieval ---
        if query.mode in ("graph", "hybrid") and self.graph_index:
            try:
                anchor_id = query.anchor_memory_id
                if anchor_id is None and semantic_hits:
                    # Use top semantic hit as graph anchor
                    anchor_id = max(semantic_hits, key=lambda k: semantic_hits[k])

                if anchor_id is not None:
                    related = self.graph_index.get_related_memory_ids(
                        anchor_id,
                        max_hops=query.graph_hops,
                        limit=query.graph_limit,
                    )
                    graph_hits = set(related)
                    logger.debug(f"Graph retrieval: {len(graph_hits)} related memory IDs")
            except Exception as exc:
                logger.warning(f"Graph retrieval failed: {exc}")

        # --- Merge and annotate ---
        all_ids: dict[UUID, RetrievalResult] = {}

        for mid, score in semantic_hits.items():
            all_ids[mid] = RetrievalResult(
                memory_id=mid,
                retrieval_source="semantic",
                semantic_score=score,
            )

        for mid in graph_hits:
            if mid in all_ids:
                # Upgrade to hybrid
                all_ids[mid].retrieval_source = "hybrid"
                all_ids[mid].graph_path = "graph_expansion"
            else:
                all_ids[mid] = RetrievalResult(
                    memory_id=mid,
                    retrieval_source="graph",
                    graph_path="graph_expansion",
                )

        # Sort: semantic score desc first, then graph
        results = sorted(
            all_ids.values(),
            key=lambda r: (r.semantic_score or -1.0),
            reverse=True,
        )
        results = results[: query.final_limit]

        # --- PostgreSQL hydration ---
        if results:
            records = self._hydrate_from_postgres([r.memory_id for r in results])
            for result in results:
                result.canonical_record = records.get(result.memory_id)

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            f"HybridRetrieval mode={query.mode} returned {len(results)} results "
            f"in {elapsed_ms:.1f}ms"
        )
        return results

    def _hydrate_from_postgres(
        self, memory_ids: list[UUID]
    ) -> dict[UUID, MemoryRecord]:
        """Bulk-fetch canonical MemoryRecords from PostgreSQL."""
        if not memory_ids:
            return {}
        try:
            from sqlalchemy import select
            from app.db.models.memory import MemoryRecord as MR

            with self.session_factory() as session:
                stmt = select(MR).where(
                    MR.id.in_(memory_ids)
                )
                rows = session.scalars(stmt).all()
                # Expunge so they can live outside the session
                session.expunge_all()
                return {r.id: r for r in rows}
        except Exception as exc:
            logger.error(f"PostgreSQL hydration failed: {exc}")
            return {}
