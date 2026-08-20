"""
Agent tools — structured operational analysis tools.

Tools follow a Protocol interface for replaceability and testability.
All tool calls are recorded in AgentTrace for auditability.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    output: Any
    success: bool
    error: str | None = None
    latency_ms: float = 0.0


class Tool(Protocol):
    name: str
    description: str

    def run(self, **kwargs) -> ToolResult:
        ...


class RetrievalTool:
    """Semantic + hybrid memory retrieval tool."""

    name = "memory_retrieval"
    description = (
        "Retrieve relevant operational memory records using semantic and graph search."
    )

    def __init__(self, retriever) -> None:
        self._retriever = retriever

    def run(self, query: str, mode: str = "hybrid", limit: int = 5) -> ToolResult:
        from app.retrieval.models import RetrievalQuery

        t0 = time.monotonic()
        try:
            q = RetrievalQuery(text=query, mode=mode, final_limit=limit)
            results = self._retriever.retrieve(q)
            output = [
                {
                    "memory_id": str(r.memory_id),
                    "source": r.retrieval_source,
                    "score": r.semantic_score,
                    "title": (
                        r.canonical_record.title if r.canonical_record else None
                    ),
                    "content": (
                        r.canonical_record.content[:300]
                        if r.canonical_record
                        else None
                    ),
                }
                for r in results
            ]
            return ToolResult(
                output=output,
                success=True,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                output=None,
                success=False,
                error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )


class GraphTraversalTool:
    """Graph relationship traversal tool."""

    name = "graph_traversal"
    description = (
        "Find memories structurally connected to a given memory via the Neo4j graph."
    )

    def __init__(self, graph_index) -> None:
        self._graph = graph_index

    def run(
        self,
        memory_id: str,
        max_hops: int = 2,
        limit: int = 20,
    ) -> ToolResult:
        t0 = time.monotonic()
        try:
            from uuid import UUID

            related = self._graph.get_related_memory_ids(
                UUID(memory_id), max_hops=max_hops, limit=limit
            )
            output = [str(uid) for uid in related]
            return ToolResult(
                output=output,
                success=True,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                output=None,
                success=False,
                error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
