"""Tests for GraphRAG pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.graphrag.pipeline import GraphRAGPipeline
from app.graphrag.providers import DeterministicTestProvider
from app.retrieval.models import RetrievalResult


@pytest.fixture
def mock_retriever():
    r = MagicMock()
    r.retrieve.return_value = []
    return r


@pytest.fixture
def test_pipeline(mock_retriever):
    return GraphRAGPipeline(
        retriever=mock_retriever,
        llm_provider=DeterministicTestProvider(),
        context_limit=3,
    )


class TestDeterministicProvider:

    def test_returns_response(self):
        from app.graphrag.provider import LLMMessage
        provider = DeterministicTestProvider()
        resp = provider.generate(
            [LLMMessage(role="user", content="test question")],
        )
        assert resp.content
        assert "SYNTHETIC" in resp.content
        assert resp.model_name == "deterministic-test-v1"

    def test_deterministic_for_same_input(self):
        from app.graphrag.provider import LLMMessage
        provider = DeterministicTestProvider()
        msgs = [LLMMessage(role="user", content="same question")]
        r1 = provider.generate(msgs)
        r2 = provider.generate(msgs)
        assert r1.content == r2.content


class TestGraphRAGPipeline:

    def test_returns_response_with_question(self, test_pipeline):
        resp = test_pipeline.query("What failed on pump P-102?")
        assert resp.question == "What failed on pump P-102?"
        assert resp.answer
        assert resp.model_name

    def test_empty_retrieval_still_generates(self, test_pipeline):
        resp = test_pipeline.query("Any failures?")
        assert resp.answer
        assert resp.evidence == []

    def test_retrieval_latency_recorded(self, test_pipeline):
        resp = test_pipeline.query("test")
        assert resp.retrieval_latency_ms >= 0
        assert resp.generation_latency_ms >= 0
        assert resp.total_latency_ms >= 0

    def test_hydrated_evidence_passed_to_context(self, mock_retriever):
        from app.db.models.memory import MemoryRecord, MemoryType, MemoryStatus
        from datetime import datetime, timezone

        rec = MemoryRecord()
        rec.id = uuid4()
        rec.memory_type = MemoryType.OBSERVATION.value
        rec.status = MemoryStatus.ACTIVE.value
        rec.title = "Test Title"
        rec.content = "Test content for evidence"
        rec.asset_id = "pump-1"
        rec.facility_id = "facility-a"
        rec.source_type = "sensor"
        rec.confidence = 0.9
        rec.importance = 0.8
        rec.created_at = datetime.now(timezone.utc)

        result = RetrievalResult(
            memory_id=rec.id,
            retrieval_source="semantic",
            semantic_score=0.9,
            canonical_record=rec,
        )
        mock_retriever.retrieve.return_value = [result]

        pipeline = GraphRAGPipeline(
            retriever=mock_retriever,
            llm_provider=DeterministicTestProvider(),
            context_limit=3,
        )
        resp = pipeline.query("test with evidence")

        assert len(resp.evidence) == 1
        assert resp.evidence[0].title == "Test Title"
        assert resp.is_synthetic_response  # deterministic provider

    def test_retrieval_failure_returns_response(self, mock_retriever):
        mock_retriever.retrieve.side_effect = RuntimeError("Retrieval failed")
        pipeline = GraphRAGPipeline(
            retriever=mock_retriever,
            llm_provider=DeterministicTestProvider(),
        )
        resp = pipeline.query("test")
        # Should not raise; evidence is empty
        assert resp.answer
        assert resp.evidence == []
