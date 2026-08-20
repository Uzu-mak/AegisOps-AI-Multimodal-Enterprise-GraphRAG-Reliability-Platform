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
from app.graphrag.provider import LLMMessage, LLMProvider
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

    def query(
        self,
        question: str,
        anchor_memory_id: Optional[str] = None,
    ) -> GraphRAGResponse:
        """
        Answer an operational question using hybrid evidence retrieval + LLM.

        Returns a GraphRAGResponse with the answer, evidence items, and
        latency breakdown.
        """
        t_start = time.monotonic()

        # --- Retrieval ---
        t_retrieve = time.monotonic()
        try:
            from uuid import UUID
            anchor_id = UUID(anchor_memory_id) if anchor_memory_id else None
            query = RetrievalQuery(
                text=question,
                mode=self.retrieval_mode,
                anchor_memory_id=anchor_id,
                final_limit=self.context_limit,
            )
            results = self.retriever.retrieve(query)
        except Exception as exc:
            logger.warning(f"GraphRAG retrieval failed: {exc}")
            results = []
        retrieval_ms = (time.monotonic() - t_retrieve) * 1000

        # --- Context construction ---
        ctx: BuiltContext = build_context(
            question=question,
            results=results,
            max_evidence=self.context_limit,
        )

        # --- LLM generation ---
        t_gen = time.monotonic()
        try:
            messages = [
                LLMMessage(role="system", content=ctx.system_prompt),
                LLMMessage(role="user", content=ctx.user_prompt),
            ]
            llm_resp = self.llm.generate(messages, temperature=0.0, max_tokens=1024)
            answer = llm_resp.content
            model_name = llm_resp.model_name
            prompt_tokens = llm_resp.prompt_tokens
            completion_tokens = llm_resp.completion_tokens
            is_synthetic = "deterministic-test" in model_name
        except Exception as exc:
            logger.error(f"GraphRAG LLM generation failed: {exc}")
            answer = f"[LLM generation failed: {exc}]"
            model_name = "error"
            prompt_tokens = 0
            completion_tokens = 0
            is_synthetic = True
        generation_ms = (time.monotonic() - t_gen) * 1000
        total_ms = (time.monotonic() - t_start) * 1000

        logger.info(
            f"GraphRAG query complete: {len(results)} evidence items, "
            f"retrieval={retrieval_ms:.1f}ms generation={generation_ms:.1f}ms"
        )

        return GraphRAGResponse(
            question=question,
            answer=answer,
            evidence=ctx.evidence_items,
            retrieval_results=results,
            retrieval_mode=self.retrieval_mode,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retrieval_latency_ms=retrieval_ms,
            generation_latency_ms=generation_ms,
            total_latency_ms=total_ms,
            is_synthetic_response=is_synthetic,
        )
