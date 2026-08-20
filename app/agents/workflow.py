"""
AegisOps Agent Workflow.

Implements a multi-step agent pipeline:
  1. Retrieval Agent  — semantic + hybrid memory retrieval
  2. Graph Reasoning  — Neo4j relationship traversal
  3. Synthesis        — GraphRAG LLM answer generation
  4. Critic           — evidence validation

Uses a simple sequential state machine. LangGraph can be added as an
orchestration layer over this workflow in a future iteration.

Agent state is ephemeral — it is NOT automatically promoted to PostgreSQL.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.agents.critic import RuleBasedCritic
from app.agents.state import AgentStep, AgentStepType, AgentTrace, ToolCall
from app.agents.tools import GraphTraversalTool, RetrievalTool
from app.graphrag.pipeline import GraphRAGPipeline, GraphRAGResponse
from app.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class AegisOpsWorkflow:
    """
    Sequential multi-agent workflow for operational fault triage.

    Steps:
    1. Retrieval (semantic + graph)
    2. Optional graph expansion
    3. GraphRAG synthesis
    4. Critic verification
    5. Return AgentTrace + GraphRAGResponse
    """

    def __init__(
        self,
        retrieval_tool: Optional[RetrievalTool],
        graph_tool: Optional[GraphTraversalTool],
        graphrag_pipeline: GraphRAGPipeline,
        critic: Optional[RuleBasedCritic] = None,
        working_memory_size: int = 50,
    ) -> None:
        self.retrieval_tool = retrieval_tool
        self.graph_tool = graph_tool
        self.graphrag = graphrag_pipeline
        self.critic = critic or RuleBasedCritic()
        self.working_memory_size = working_memory_size

    def run(
        self,
        task: str,
        anchor_memory_id: Optional[str] = None,
    ) -> tuple[AgentTrace, GraphRAGResponse]:
        """
        Execute the agent workflow.

        Returns:
            (AgentTrace, GraphRAGResponse) — trace for inspection,
            response for delivery.
        """
        t_start = time.monotonic()
        trace = AgentTrace(task=task, status="running")
        wm = WorkingMemory(max_items=self.working_memory_size)

        # --- Step 1: Retrieval ---
        if self.retrieval_tool:
            t0 = time.monotonic()
            result = self.retrieval_tool.run(query=task, mode="hybrid", limit=10)
            retrieved_ids = []
            if result.success and result.output:
                for item in result.output:
                    wm.add_evidence(
                        content=f"{item.get('title', '')}: {item.get('content', '')}",
                        evidence_memory_ids=[],
                        source="retrieval",
                    )
                    if item.get("memory_id"):
                        from uuid import UUID
                        try:
                            retrieved_ids.append(UUID(item["memory_id"]))
                        except ValueError:
                            pass

            trace.add_step(
                AgentStep(
                    step_type=AgentStepType.RETRIEVAL,
                    description=f"Retrieved {len(retrieved_ids)} memories",
                    tool_call=ToolCall(
                        tool_name=self.retrieval_tool.name,
                        arguments={"query": task, "mode": "hybrid"},
                        result=result.output,
                        error=result.error,
                        latency_ms=(time.monotonic() - t0) * 1000,
                    ),
                    retrieved_memory_ids=retrieved_ids,
                    working_memory_snapshot=len(wm),
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            )

        # --- Step 2: Graph expansion (optional, using top retrieved memory) ---
        if self.graph_tool and trace.steps and trace.steps[0].retrieved_memory_ids:
            top_id = str(trace.steps[0].retrieved_memory_ids[0])
            t0 = time.monotonic()
            graph_result = self.graph_tool.run(
                memory_id=top_id, max_hops=2, limit=20
            )
            trace.add_step(
                AgentStep(
                    step_type=AgentStepType.GRAPH_REASONING,
                    description=f"Graph expansion found {len(graph_result.output or [])} related memories",
                    tool_call=ToolCall(
                        tool_name=self.graph_tool.name,
                        arguments={"memory_id": top_id, "max_hops": 2},
                        result=graph_result.output,
                        error=graph_result.error,
                        latency_ms=(time.monotonic() - t0) * 1000,
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            )

        # --- Step 3: GraphRAG synthesis ---
        t0 = time.monotonic()
        rag_response = self.graphrag.query(
            question=task,
            anchor_memory_id=anchor_memory_id,
        )
        trace.add_step(
            AgentStep(
                step_type=AgentStepType.SYNTHESIS,
                description=f"GraphRAG synthesis using {len(rag_response.evidence)} evidence items",
                output_summary=rag_response.answer[:200],
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        )

        # --- Step 4: Critic verification ---
        t0 = time.monotonic()
        critic_result = self.critic.verify(
            answer=rag_response.answer,
            evidence=rag_response.evidence,
        )
        trace.critic_result = critic_result
        trace.add_step(
            AgentStep(
                step_type=AgentStepType.CRITIC,
                description=(
                    f"Critic: supported={critic_result.is_supported} "
                    f"confidence={critic_result.confidence:.2f}"
                ),
                output_summary=critic_result.notes,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        )

        trace.final_answer = rag_response.answer
        trace.evidence_memory_ids = [
            e.memory_id
            for r in rag_response.retrieval_results
            if r.canonical_record is not None
            for e in [r]  # flatten
        ]
        trace.total_latency_ms = (time.monotonic() - t_start) * 1000
        trace.status = "complete"

        logger.info(
            f"Agent workflow complete: {len(trace.steps)} steps, "
            f"{trace.total_latency_ms:.1f}ms"
        )

        return trace, rag_response
