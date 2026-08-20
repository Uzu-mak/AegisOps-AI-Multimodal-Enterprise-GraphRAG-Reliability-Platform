"""Tests for agent workflow and critic."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.agents.critic import RuleBasedCritic
from app.agents.state import AgentTrace
from app.graphrag.context import EvidenceItem


class TestRuleBasedCritic:

    def _make_evidence(self, n=2) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                memory_id=str(uuid4()),
                memory_type="observation",
                title=f"Evidence {i+1}",
                content=f"Content {i+1}",
                retrieval_source="semantic",
                semantic_score=0.9,
                graph_path=None,
                asset_id="pump-1",
                facility_id="facility-a",
                confidence=0.85,
                importance=0.75,
            )
            for i in range(n)
        ]

    def test_valid_citations_pass(self):
        critic = RuleBasedCritic()
        evidence = self._make_evidence(2)
        answer = "The pump failed [Memory 1] as observed in maintenance logs [Memory 2]."
        result = critic.verify(answer, evidence)
        assert result.citations_valid is True
        assert result.confidence > 0.5

    def test_invalid_citation_index_flagged(self):
        critic = RuleBasedCritic()
        evidence = self._make_evidence(2)
        answer = "Failure was noted [Memory 99]."  # invalid index
        result = critic.verify(answer, evidence)
        assert result.citations_valid is False
        assert result.confidence < 1.0

    def test_no_evidence_returns_unsupported(self):
        critic = RuleBasedCritic()
        result = critic.verify("Some answer", [])
        assert result.is_supported is False
        assert result.confidence == 0.0

    def test_no_citations_in_answer(self):
        critic = RuleBasedCritic()
        evidence = self._make_evidence(2)
        answer = "The pump failed due to bearing wear and misalignment over time."
        result = critic.verify(answer, evidence)
        assert result.is_supported is False


class TestAgentWorkflow:

    def test_workflow_completes_trace(self):
        from app.agents.workflow import AegisOpsWorkflow
        from app.graphrag.pipeline import GraphRAGPipeline
        from app.graphrag.providers import DeterministicTestProvider

        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []

        pipeline = GraphRAGPipeline(
            retriever=mock_retriever,
            llm_provider=DeterministicTestProvider(),
        )

        workflow = AegisOpsWorkflow(
            retrieval_tool=None,
            graph_tool=None,
            graphrag_pipeline=pipeline,
        )

        trace, response = workflow.run("What caused the pump failure?")
        assert isinstance(trace, AgentTrace)
        assert trace.status == "complete"
        assert trace.final_answer
        assert trace.critic_result is not None
        assert len(trace.steps) >= 2  # at least synthesis + critic

    def test_workflow_records_latency(self):
        from app.agents.workflow import AegisOpsWorkflow
        from app.graphrag.pipeline import GraphRAGPipeline
        from app.graphrag.providers import DeterministicTestProvider

        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        pipeline = GraphRAGPipeline(
            retriever=mock_retriever,
            llm_provider=DeterministicTestProvider(),
        )
        workflow = AegisOpsWorkflow(
            retrieval_tool=None, graph_tool=None, graphrag_pipeline=pipeline
        )
        trace, _ = workflow.run("test task")
        assert trace.total_latency_ms > 0
