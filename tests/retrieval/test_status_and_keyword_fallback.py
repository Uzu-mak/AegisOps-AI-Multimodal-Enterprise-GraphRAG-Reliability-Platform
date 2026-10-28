"""Hybrid retrieval: inactive memories excluded; PostgreSQL keyword fallback."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.retrieval.hybrid import HybridMemoryRetriever, _query_terms
from app.retrieval.models import RetrievalQuery


def _session_factory(records):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)
    session.scalars.return_value.all.return_value = records
    return MagicMock(return_value=session)


def _record(status="active", title="t", content="c", importance=0.5):
    return SimpleNamespace(id=uuid4(), status=status, title=title, content=content,
                           importance=importance, confidence=0.5, memory_type="incident",
                           asset_id=None, facility_id=None)


def _semantic(ids_scores):
    idx = MagicMock()
    idx.search_similar.return_value = [SimpleNamespace(memory_id=i, score=s) for i, s in ids_scores]
    return idx


def test_inactive_memories_are_not_returned_by_default():
    active, archived, disputed = _record(), _record("archived"), _record("disputed")
    retriever = HybridMemoryRetriever(
        semantic_index=_semantic([(active.id, 0.5), (archived.id, 0.9), (disputed.id, 0.8)]),
        graph_index=None,
        embedding_provider=MagicMock(embed_text=MagicMock(return_value=[0.0])),
        session_factory=_session_factory([active, archived, disputed]),
    )
    results = retriever.retrieve(RetrievalQuery(text="q", mode="semantic", final_limit=1))
    assert [r.memory_id for r in results] == [active.id]


def test_include_inactive_returns_everything():
    active, archived = _record(), _record("archived")
    retriever = HybridMemoryRetriever(
        semantic_index=_semantic([(active.id, 0.5), (archived.id, 0.9)]),
        graph_index=None,
        embedding_provider=MagicMock(embed_text=MagicMock(return_value=[0.0])),
        session_factory=_session_factory([active, archived]),
    )
    results = retriever.retrieve(RetrievalQuery(text="q", mode="semantic", include_inactive=True))
    assert {r.memory_id for r in results} == {active.id, archived.id}


def test_keyword_fallback_when_no_projection_available():
    match = _record(title="Robot R7 vision false rejects", content="Glare on bay 3")
    weak = _record(title="Bay 3 lighting", content="New fixtures installed")
    retriever = HybridMemoryRetriever(
        semantic_index=None, graph_index=None, embedding_provider=None,
        session_factory=_session_factory([weak, match]),
    )
    results = retriever.retrieve(
        RetrievalQuery(text="Why does R7 have false rejects?", keyword_fallback=True)
    )
    assert results[0].memory_id == match.id
    assert results[0].retrieval_source == "keyword"
    assert 0 < results[0].keyword_score <= 1
    assert results[0].canonical_record is match


def test_keyword_fallback_is_opt_in():
    retriever = HybridMemoryRetriever(
        semantic_index=None, graph_index=None, embedding_provider=None,
        session_factory=_session_factory([_record(title="glare")]),
    )
    assert retriever.retrieve(RetrievalQuery(text="glare")) == []


def test_query_terms_drop_stopwords_and_duplicates():
    assert _query_terms("Why is the R7 robot rejecting the R7 parts?") == ["r7", "robot", "rejecting", "parts"]
