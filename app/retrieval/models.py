"""Retrieval result models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
from uuid import UUID


@dataclass
class RetrievalResult:
    """
    A single retrieval result referencing a canonical PostgreSQL memory.

    The canonical_record field is populated after hydration from PostgreSQL.
    Qdrant and Neo4j payloads are NEVER used as authoritative memory content.
    """

    memory_id: UUID
    retrieval_source: Literal["semantic", "graph", "hybrid"]
    semantic_score: Optional[float] = None
    graph_path: Optional[str] = None
    canonical_record: Optional[object] = None  # MemoryRecord once hydrated


@dataclass
class RetrievalQuery:
    """Parameters for a hybrid retrieval request."""

    text: str
    mode: Literal["semantic", "graph", "hybrid"] = "hybrid"
    anchor_memory_id: Optional[UUID] = None
    semantic_limit: int = 10
    graph_limit: int = 50
    final_limit: int = 20
    graph_hops: int = 2
    filters: dict = field(default_factory=dict)
