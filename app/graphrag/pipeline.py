"""
GraphRAG pipeline — evidence-grounded query answering over AegisOps memory.

Flow:
    question
       ↓
    HybridMemoryRetriever  (Qdrant + Neo4j + PostgreSQL)
       ↓
    context construction   (canonical PostgreSQL evidence only)
       ↓
    LLMProvider            (replaceable; deterministic test by default)
       ↓
    GraphRAGResponse       (answer + citations + evidence)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.graphrag.context import BuiltContext, EvidenceItem, build_context
from app.graphrag.provider import LLMMessage, LLMProvider, LLMProviderError
from app.retrieval.hybrid import HybridMemoryRetriever
from app.retrieval.models import RetrievalQuery, RetrievalResult

logger = logging.getLogger(__name__)


@dataclass
class GraphRAGResponse:
    question: str
    answer: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    retrieval_results: list[RetrievalResult] = field(default_factory=list)
    retrieval_mode: str = "hybrid"
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    is_synthetic_response: bool = False


class GraphRAGPipeline:
    """
    GraphRAG query pipeline.

    Combines HybridMemoryRetriever with an LLMProvider to produce
    evidence-grounded answers with explicit citations.

    All evidence is sourced from canonical PostgreSQL MemoryRecords.
    The LLM is used ONLY to synthesize language; it cannot override evidence.
    """

    def __init__(
        self,
        retriever: HybridMemoryRetriever,
        llm_provider: LLMProvider,
        context_limit: int = 5,
        retrieval_mode: str = "hybrid",
    ) -> None:
        self.retriever = retriever
        self.llm = llm_provider
        self.context_limit = context_limit
        self.retrieval_mode = retrieval_mode

    def retrieve(self, question: str, anchor_memory_id: Optional[str] = None) -> tuple[list[RetrievalResult], float]:
        """Retrieve evidence once (hybrid, with PostgreSQL keyword fallback). Returns (results, ms)."""
        t0 = time.monotonic()
        try:
            from uuid import UUID

            anchor_id = UUID(anchor_memory_id) if anchor_memory_id else None
            results = self.retriever.retrieve(
                RetrievalQuery(
                    text=question,
                    mode=self.retrieval_mode,
                    anchor_memory_id=anchor_id,
                    final_limit=self.context_limit,
                    keyword_fallback=True,
                )
            )
        except Exception as exc:
            logger.warning(f"GraphRAG retrieval failed: {exc}")
            results = []
        if anchor_memory_id:
            results = self._scope_to_anchor(results, anchor_memory_id)
        return results, (time.monotonic() - t0) * 1000

    def _scope_to_anchor(self, results: list[RetrievalResult], anchor_memory_id: str) -> list[RetrievalResult]:
        """
        An investigation that starts from a record is about that record's context:
        the record itself comes first, then records sharing its incident or asset,
        then everything else in retrieval order. Without Neo4j, the shared-incident
        records are read from PostgreSQL so the scope does not depend on the graph.
        """
        from uuid import UUID

        get = getattr(self.retriever, "get_record", None)
        if get is None:
            return results
        try:
            anchor = get(UUID(anchor_memory_id))
        except Exception:  # noqa: BLE001
            anchor = None
        if anchor is None or str(anchor.status) != "active":
            return results

        by_id = {r.memory_id: r for r in results}
        if getattr(self.retriever, "graph_index", None) is None and hasattr(self.retriever, "context_records"):
            for extra in self.retriever.context_records(anchor):
                by_id.setdefault(extra.memory_id, extra)
        by_id.pop(anchor.id, None)

        def same_context(r: RetrievalResult) -> bool:
            rec = r.canonical_record
            if rec is None:
                return False
            if anchor.incident_id:
                return rec.incident_id == anchor.incident_id
            return bool(anchor.asset_id) and rec.asset_id == anchor.asset_id

        ordered = list(by_id.values())
        scoped = [r for r in ordered if same_context(r)] + [r for r in ordered if not same_context(r)]
        return [RetrievalResult(memory_id=anchor.id, retrieval_source="anchor", canonical_record=anchor)] + scoped

    def answer(self, question: str, results: list[RetrievalResult], retrieval_ms: float = 0.0) -> GraphRAGResponse:
        """Generate an evidence-grounded answer from already-retrieved results."""
        t_start = time.monotonic()
        ctx: BuiltContext = build_context(question=question, results=results, max_evidence=self.context_limit)

        t_gen = time.monotonic()
        try:
            messages = [
                LLMMessage(role="system", content=ctx.system_prompt),
                LLMMessage(role="user", content=ctx.user_prompt),
            ]
            llm_resp = self.llm.generate(messages, temperature=0.0, max_tokens=1024)
            answer, model_name = llm_resp.content, llm_resp.model_name
            prompt_tokens, completion_tokens = llm_resp.prompt_tokens, llm_resp.completion_tokens
            is_synthetic = "deterministic-test" in model_name
        except LLMProviderError as exc:
            logger.warning(f"GraphRAG LLM provider error: {exc}")
            answer, model_name, prompt_tokens, completion_tokens, is_synthetic = (
                f"[LLM generation unavailable: {exc}]", "error", 0, 0, True)
        except Exception as exc:
            logger.error(f"GraphRAG LLM generation failed: {exc}")
            answer, model_name, prompt_tokens, completion_tokens, is_synthetic = (
                "[LLM generation failed due to an unexpected error.]", "error", 0, 0, True)
        generation_ms = (time.monotonic() - t_gen) * 1000

        effective_mode = self.retrieval_mode
        if results and all(r.retrieval_source == "keyword" for r in results):
            effective_mode = "keyword_fallback"

        logger.info(f"GraphRAG answer: {len(ctx.evidence_items)} evidence items, generation={generation_ms:.1f}ms")
        return GraphRAGResponse(
            question=question,
            answer=answer,
            evidence=ctx.evidence_items,
            retrieval_results=results,
            retrieval_mode=effective_mode,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retrieval_latency_ms=retrieval_ms,
            generation_latency_ms=generation_ms,
            total_latency_ms=retrieval_ms + (time.monotonic() - t_start) * 1000,
            is_synthetic_response=is_synthetic,
        )

    def query(self, question: str, anchor_memory_id: Optional[str] = None) -> GraphRAGResponse:
        """Retrieve evidence, then answer from it."""
        results, retrieval_ms = self.retrieve(question, anchor_memory_id)
        return self.answer(question, results, retrieval_ms)
