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
        self.last_anchor_id: Optional[UUID] = None

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
        self.last_anchor_id = None
        if query.mode in ("graph", "hybrid") and self.graph_index:
            try:
                anchor_id = query.anchor_memory_id
                if anchor_id is None and semantic_hits:
                    # Use top semantic hit as graph anchor
                    anchor_id = max(semantic_hits, key=lambda k: semantic_hits[k])
                if anchor_id is None and query.mode == "graph" and self.semantic_index and self.embedding_provider:
                    # Text query in graph-only mode: anchor on the single best
                    # vector match, but return only its graph neighbours. This
                    # is the same definition the benchmark's graph method uses.
                    vec = self.embedding_provider.embed_text(query.text)
                    top = self.semantic_index.search_similar(query_vector=vec, limit=1)
                    if top:
                        anchor_id = top[0].memory_id
                self.last_anchor_id = anchor_id

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
                all_ids[mid].graph_path = f"linked_to:{self.last_anchor_id}"
            else:
                all_ids[mid] = RetrievalResult(
                    memory_id=mid,
                    retrieval_source="graph",
                    graph_path=f"linked_to:{self.last_anchor_id}",
                )

        # Order: vector matches by score; graph-only links come after them.
        results = sorted(
            all_ids.values(),
            key=lambda r: (r.semantic_score if r.semantic_score is not None else -1.0),
            reverse=True,
        )

        # --- PostgreSQL hydration (canonical truth) ---
        # Hydrate every candidate *before* truncating so that inactive
        # records filtered out here do not shrink the final page.
        if results:
            records = self._hydrate_from_postgres([r.memory_id for r in results])
            hydration_failed = records is None
            records = records or {}
            kept: list[RetrievalResult] = []
            for result in results:
                record = records.get(result.memory_id)
                if record is None and not hydration_failed:
                    # Stale projection: the vector or graph store points at a
                    # record PostgreSQL no longer has. It must not take a slot.
                    logger.warning(f"Dropping stale projection hit {result.memory_id}")
                    continue
                # If PostgreSQL itself could not be read, hits are kept without
                # canonical content; GraphRAG context construction skips them.
                if (
                    record is not None
                    and not query.include_inactive
                    and str(record.status) != "active"
                ):
                    continue
                result.canonical_record = record
                kept.append(result)
            results = _rank_graph_only(kept)

        if not results and query.keyword_fallback and query.mode != "graph":
            results = self._keyword_fallback(query)

        results = results[: query.final_limit]

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            f"HybridRetrieval mode={query.mode} returned {len(results)} results "
            f"in {elapsed_ms:.1f}ms"
        )
        return results

    def get_record(self, memory_id: UUID):
        """Canonical record by ID (None if missing or unreadable)."""
        return (self._hydrate_from_postgres([memory_id]) or {}).get(memory_id)

    def context_records(self, anchor, limit: int = 10) -> list[RetrievalResult]:
        """
        Active records sharing the anchor's incident (or, without one, its asset),
        read from PostgreSQL. These are the same links Neo4j projects, so this is
        the canonical fallback when the graph store is unavailable.
        """
        key, value = ("incident_id", anchor.incident_id) if anchor.incident_id else ("asset_id", anchor.asset_id)
        if not value:
            return []
        try:
            from sqlalchemy import select
            from app.db.models.memory import MemoryRecord as MR

            stmt = (
                select(MR)
                .where(getattr(MR, key) == value, MR.status == "active", MR.id != anchor.id)
                .order_by(MR.importance.desc(), MR.created_at.desc())
                .limit(limit)
            )
            with self.session_factory() as session:
                rows = session.scalars(stmt).all()
                session.expunge_all()
        except Exception as exc:
            logger.error(f"PostgreSQL context lookup failed: {exc}")
            return []
        return [RetrievalResult(memory_id=r.id, retrieval_source="context", graph_path=f"same_{key}:{value}", canonical_record=r) for r in rows]

    def _keyword_fallback(self, query: RetrievalQuery) -> list[RetrievalResult]:
        """
        Bounded PostgreSQL keyword match used only when projections returned nothing.

        Scores are the fraction of query terms found in title+content. This is
        lexical matching, not semantic similarity, and is labelled as such
        (retrieval_source="keyword").
        """
        terms = _query_terms(query.text)
        if not terms:
            return []
        try:
            from sqlalchemy import or_, select
            from app.db.models.memory import MemoryRecord as MR

            clauses = []
            for t in terms:
                pattern = f"%{_escape_like(t)}%"
                clauses.append(MR.title.ilike(pattern, escape="\\"))
                clauses.append(MR.content.ilike(pattern, escape="\\"))
            stmt = select(MR).where(or_(*clauses))
            if not query.include_inactive:
                stmt = stmt.where(MR.status == "active")
            stmt = stmt.order_by(MR.created_at.desc()).limit(200)
            with self.session_factory() as session:
                rows = session.scalars(stmt).all()
                session.expunge_all()
        except Exception as exc:
            logger.error(f"PostgreSQL keyword fallback failed: {exc}")
            return []

        scored: list[RetrievalResult] = []
        for rec in rows:
            haystack = f"{rec.title or ''} {rec.content or ''}".lower()
            hits = sum(1 for t in terms if t in haystack)
            if not hits:
                continue
            scored.append(
                RetrievalResult(
                    memory_id=rec.id,
                    retrieval_source="keyword",
                    semantic_score=None,
                    graph_path=None,
                    keyword_score=round(hits / len(terms), 4),
                    canonical_record=rec,
                )
            )
        scored.sort(key=lambda r: (r.keyword_score or 0.0, float(r.canonical_record.importance or 0.0)), reverse=True)
        return scored

    def _hydrate_from_postgres(
        self, memory_ids: list[UUID]
    ) -> Optional[dict[UUID, MemoryRecord]]:
        """Bulk-fetch canonical MemoryRecords from PostgreSQL. None means the read failed."""
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
            return None


_STOPWORDS = frozenset(
    "a an and are as at be by did do does for from has have how in is it its of on or "
    "the this that to was were what when where which who why with".split()
)


def _query_terms(text: str, max_terms: int = 8) -> list[str]:
    import re

    seen: list[str] = []
    for tok in re.findall(r"[a-z0-9][a-z0-9_\-]*", (text or "").lower()):
        if len(tok) < 2 or tok in _STOPWORDS or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= max_terms:
            break
    return seen


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rank_graph_only(results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Neo4j returns linked memory IDs in ID order, which carries no meaning.
    Keep vector-scored results in score order and rank graph-only links by
    canonical importance, then recency, so the order is deterministic and
    puts the most significant related records first.
    """
    scored = [r for r in results if r.semantic_score is not None]
    linked = [r for r in results if r.semantic_score is None]

    def key(r: RetrievalResult):
        rec = r.canonical_record
        importance = float(getattr(rec, "importance", 0.0) or 0.0) if rec is not None else -1.0
        when = getattr(rec, "observed_at", None) or getattr(rec, "created_at", None) if rec is not None else None
        stamp = when.timestamp() if hasattr(when, "timestamp") else 0.0
        return (importance, stamp, str(r.memory_id))

    linked.sort(key=key, reverse=True)
    return scored + linked
