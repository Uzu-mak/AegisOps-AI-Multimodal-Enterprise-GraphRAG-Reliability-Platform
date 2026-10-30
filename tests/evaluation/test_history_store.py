"""Evaluation history store: round trip and tenant isolation, on SQLite."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.evaluation import store


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    from app.evaluation import datasets

    Base.metadata.create_all(engine, tables=[store.EvalRunRecord.__table__, store.EvalCaseResultRecord.__table__,
                                             datasets.EvalQuestionSetRecord.__table__, datasets.EvalQuestionRecord.__table__])
    yield sessionmaker(engine)
    engine.dispose()


def _payload(run_id: str) -> dict:
    return {
        "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(), "k": 10,
        "embedding_model": "OpenAIEmbedding(dimension=1536)", "modes_run": ["semantic"], "unavailable_modes": {},
        "per_mode": {"semantic": {"recall_at_k": 1.0}}, "failure_taxonomy": {},
        "cases": [{"case_id": "q-001", "question": "Why?", "mode": "semantic", "labeled": True, "recall_at_5": 1.0,
                   "recall_at_k": 1.0, "mrr": 0.5, "groundedness": None, "citation_accuracy": None,
                   "retrieved_memory_ids": ["a", "b"], "latency_ms": 12.0, "error": None}],
    }


def test_a_saved_run_comes_back_in_the_response_shape_with_its_labels(session_factory):
    run_id = str(uuid.uuid4())
    with session_factory() as s:
        store.save_run(s, _payload(run_id), expected={"q-001": ["b"]}, anchors={"q-001": "anchor-1"}, tenant_id=None, llm_model=None, commit="abc1234")
    with session_factory() as s:
        (summary,) = store.list_runs(s, tenant_id=None)
        run = store.get_run(s, uuid.UUID(run_id), tenant_id=None)
    assert summary["question_count"] == 1 and summary["commit"] == "abc1234" and "cases" not in summary
    assert run["k"] == 10 and run["modes_run"] == ["semantic"] and run["persisted"] is True
    assert run["cases"][0]["expected_memory_ids"] == ["b"] and run["cases"][0]["anchor_memory_id"] == "anchor-1"
    assert run["cases"][0]["retrieved_memory_ids"] == ["a", "b"]


def test_runs_are_visible_only_to_their_tenant(session_factory):
    run_id = str(uuid.uuid4())
    with session_factory() as s:
        store.save_run(s, _payload(run_id), expected={}, anchors={}, tenant_id="plant-a", llm_model=None, commit=None)
    with session_factory() as s:
        assert len(store.list_runs(s, tenant_id="plant-a")) == 1
        assert store.list_runs(s, tenant_id="plant-b") == []
        assert store.get_run(s, uuid.UUID(run_id), tenant_id="plant-b") is None


def test_only_writers_admins_and_local_mode_add_to_history():
    from types import SimpleNamespace
    from app.api.routes.evaluation import _may_persist

    assert _may_persist(None)  # local mode
    assert _may_persist(SimpleNamespace(roles=("writer",)))
    assert _may_persist(SimpleNamespace(roles=("admin",)))
    assert not _may_persist(SimpleNamespace(roles=("viewer",)))
