"""
AegisOps investigation workflow.

One auditable pass over operational memory:

  1. Retrieval   one hybrid retrieval call (vector matches, then their graph
                 neighbours; PostgreSQL keyword fallback if both stores are down)
  2. Graph links the part of that same result set that came from Neo4j,
                 recorded as its own step so the trace shows what the graph added
  3. Synthesis   GraphRAG answer generated from exactly those results
  4. Critic      rule-based check that every citation points at real evidence

Retrieval happens once; synthesis reuses the retrieved results rather than
searching again. The trace is returned to the caller and is not persisted.
Turning a conclusion into a canonical record is a separate, explicit step
(see app.memory.promotion and POST /api/v1/investigations/findings).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.agents.critic import RuleBasedCritic
from app.agents.state import AgentStep, AgentStepType, AgentTrace
from app.graphrag.pipeline import GraphRAGPipeline, GraphRAGResponse
from app.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class AegisOpsWorkflow:
    def __init__(
        self,
        graphrag_pipeline: GraphRAGPipeline,
        critic: Optional[RuleBasedCritic] = None,
        working_memory_size: int = 50,
    ) -> None:
        self.graphrag = graphrag_pipeline
        self.critic = critic or RuleBasedCritic()
        self.working_memory_size = working_memory_size

    def run(self, task: str, anchor_memory_id: Optional[str] = None) -> tuple[AgentTrace, GraphRAGResponse]:
        t_start = time.monotonic()
        trace = AgentTrace(task=task, status="running")
        wm = WorkingMemory(max_items=self.working_memory_size)

        # 1. Retrieval (single call)
        results, retrieval_ms = self.graphrag.retrieve(task, anchor_memory_id)
        hydrated = [r for r in results if r.canonical_record is not None]
        for r in hydrated:
            rec = r.canonical_record
            wm.add_evidence(
                content=f"{rec.title}: {rec.content}",
                evidence_memory_ids=[r.memory_id],
                source=r.retrieval_source,
            )
        by_source: dict[str, int] = {}
        for r in hydrated:
            by_source[r.retrieval_source] = by_source.get(r.retrieval_source, 0) + 1
        vector_n = by_source.get("semantic", 0) + by_source.get("hybrid", 0)
        keyword_n = by_source.get("keyword", 0)
        parts = []
        if by_source.get("anchor"):
            parts.append("the starting record")
        if vector_n:
            parts.append(f"{vector_n} vector match{'es' if vector_n != 1 else ''}")
        if keyword_n:
            parts.append(f"{keyword_n} keyword match{'es' if keyword_n != 1 else ''} from PostgreSQL")
        trace.add_step(AgentStep(
            step_type=AgentStepType.RETRIEVAL,
            description=("Found " + " and ".join(parts)) if parts else "No matching records found",
            retrieved_memory_ids=[r.memory_id for r in hydrated],
            working_memory_snapshot=len(wm),
            latency_ms=retrieval_ms,
        ))

        # 2. Graph links (same result set, attributed)
        graph_results = [r for r in hydrated if r.retrieval_source in ("graph", "hybrid")]
        context_results = [r for r in hydrated if r.retrieval_source == "context"]
        anchor = getattr(self.graphrag.retriever, "last_anchor_id", None)
        if context_results:
            graph_results = context_results
            graph_desc = (f"Relationship store unavailable; added {len(context_results)} record"
                          f"{'s' if len(context_results) != 1 else ''} sharing the starting record's incident or asset from PostgreSQL")
        elif getattr(self.graphrag.retriever, "graph_index", None) is None:
            graph_desc = "Relationship store unavailable; no graph links added"
        elif anchor is None:
            graph_desc = "No starting record for graph links"
        else:
            graph_desc = f"{len(graph_results)} record{'s' if len(graph_results) != 1 else ''} linked to the top match through shared asset, line, incident, source or supersession"
        trace.add_step(AgentStep(
            step_type=AgentStepType.GRAPH_REASONING,
            description=graph_desc,
            retrieved_memory_ids=[r.memory_id for r in graph_results],
            output_summary=str(anchor) if anchor else "",
        ))

        # 3. Synthesis from exactly those results
        t0 = time.monotonic()
        rag = self.graphrag.answer(task, results, retrieval_ms)
        trace.add_step(AgentStep(
            step_type=AgentStepType.SYNTHESIS,
            description=f"Answer written from {len(rag.evidence)} evidence record{'s' if len(rag.evidence) != 1 else ''} by {rag.model_name}",
            output_summary=rag.answer[:200],
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

        # 4. Critic
        t0 = time.monotonic()
        critic = self.critic.verify(answer=rag.answer, evidence=rag.evidence)
        trace.critic_result = critic
        trace.add_step(AgentStep(
            step_type=AgentStepType.CRITIC,
            description="Citations check out" if critic.is_supported else "Answer is not fully supported by cited evidence",
            output_summary=critic.notes,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

        trace.final_answer = rag.answer
        trace.evidence_memory_ids = [r.memory_id for r in hydrated[: len(rag.evidence)]]
        trace.total_latency_ms = (time.monotonic() - t_start) * 1000
        trace.status = "complete"
        return trace, rag
