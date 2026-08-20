"""Tests for hybrid memory retrieval."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.retrieval.hybrid import HybridMemoryRetriever
from app.retrieval.models import RetrievalQuery


@pytest.fixture
def mock_embedding_provider():
    p = MagicMock()
    p.embed_text.return_value = [0.1] * 128
    return p


@pytest.fixture
def mock_semantic_index():
    idx = MagicMock()
    idx.search_similar.return_value = []
    return idx


@pytest.fixture
def mock_graph_index():
    gi = MagicMock()
    gi.get_related_memory_ids.return_value = []
    return gi


@pytest.fixture
def mock_session_factory():
    """Session factory that returns empty records."""
    from unittest.mock import MagicMock
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)
    session.scalars.return_value.all.return_value = []

    factory = MagicMock(return_value=session)
    return factory


class TestHybridRetrieverSemanticMode:

    def test_semantic_only_returns_results(
        self, mock_embedding_provider, mock_semantic_index, mock_session_factory
    ):
        from app.semantic.index import SemanticSearchResult, VectorRecord
        from datetime import datetime

        mid = uuid4()
        mock_result = MagicMock()
        mock_result.memory_id = mid
        mock_result.score = 0.9

        mock_semantic_index.search_similar.return_value = [mock_result]

        retriever = HybridMemoryRetriever(
            semantic_index=mock_semantic_index,
            graph_index=None,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(text="test query", mode="semantic", final_limit=5)
        results = retriever.retrieve(query)

        assert len(results) == 1
        assert results[0].memory_id == mid
        assert results[0].semantic_score == 0.9
        assert results[0].retrieval_source == "semantic"

    def test_semantic_mode_skips_graph(
        self, mock_embedding_provider, mock_semantic_index, mock_graph_index, mock_session_factory
    ):
        retriever = HybridMemoryRetriever(
            semantic_index=mock_semantic_index,
            graph_index=mock_graph_index,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(text="test", mode="semantic")
        retriever.retrieve(query)

        mock_graph_index.get_related_memory_ids.assert_not_called()


class TestHybridRetrieverGraphMode:

    def test_graph_only_returns_results(
        self, mock_embedding_provider, mock_semantic_index, mock_graph_index, mock_session_factory
    ):
        anchor = uuid4()
        related_id = uuid4()
        mock_graph_index.get_related_memory_ids.return_value = [related_id]

        retriever = HybridMemoryRetriever(
            semantic_index=mock_semantic_index,
            graph_index=mock_graph_index,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(text="test", mode="graph", anchor_memory_id=anchor)
        results = retriever.retrieve(query)

        assert len(results) == 1
        assert results[0].memory_id == related_id
        assert results[0].retrieval_source == "graph"


class TestHybridRetrieverMerge:

    def test_hybrid_upgrades_overlapping_hits(
        self, mock_embedding_provider, mock_semantic_index, mock_graph_index, mock_session_factory
    ):
        """Memory in both Qdrant and Neo4j should be tagged 'hybrid'."""
        shared_id = uuid4()

        sem_result = MagicMock()
        sem_result.memory_id = shared_id
        sem_result.score = 0.8
        mock_semantic_index.search_similar.return_value = [sem_result]
        mock_graph_index.get_related_memory_ids.return_value = [shared_id]

        retriever = HybridMemoryRetriever(
            semantic_index=mock_semantic_index,
            graph_index=mock_graph_index,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(
            text="test", mode="hybrid", anchor_memory_id=shared_id, final_limit=10
        )
        results = retriever.retrieve(query)

        combined = {r.memory_id: r for r in results}
        assert combined[shared_id].retrieval_source == "hybrid"

    def test_final_limit_respected(
        self, mock_embedding_provider, mock_semantic_index, mock_graph_index, mock_session_factory
    ):
        sem_results = []
        for _ in range(20):
            m = MagicMock()
            m.memory_id = uuid4()
            m.score = 0.5
            sem_results.append(m)
        mock_semantic_index.search_similar.return_value = sem_results

        retriever = HybridMemoryRetriever(
            semantic_index=mock_semantic_index,
            graph_index=None,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(text="test", mode="semantic", final_limit=5)
        results = retriever.retrieve(query)
        assert len(results) <= 5


class TestHybridRetrieverGracefulDegradation:

    def test_semantic_failure_returns_empty_not_raises(
        self, mock_embedding_provider, mock_session_factory
    ):
        broken_idx = MagicMock()
        broken_idx.search_similar.side_effect = RuntimeError("Qdrant down")

        retriever = HybridMemoryRetriever(
            semantic_index=broken_idx,
            graph_index=None,
            embedding_provider=mock_embedding_provider,
            session_factory=mock_session_factory,
        )
        query = RetrievalQuery(text="test", mode="semantic")
        results = retriever.retrieve(query)
        assert results == []

    def test_no_services_returns_empty(self, mock_session_factory):
        retriever = HybridMemoryRetriever(
            semantic_index=None,
            graph_index=None,
            embedding_provider=None,
            session_factory=mock_session_factory,
        )
        results = retriever.retrieve(RetrievalQuery(text="test"))
        assert results == []
