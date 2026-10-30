"""Versioned, reviewed question sets: lifecycle, frozen versions, hash matching to runs (SQLite)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.evaluation import datasets, store
from app.evaluation.datasets import QuestionSetError, dataset_hash, leaks


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[store.EvalRunRecord.__table__, store.EvalCaseResultRecord.__table__,
                                             datasets.EvalQuestionSetRecord.__table__, datasets.EvalQuestionRecord.__table__])
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


QS = [{"question": "What fixed the rough-running engine?", "expected_memory_ids": ["m1", "m2"]},
      {"question": "Was the hangar door replaced?", "expects_no_answer": True}]
TITLES = {"m1": "WO 1: Engine ran rough after start", "m2": "WO 2: Replaced fuel pump"}


def _new(session, **kw):
    return datasets.create_version(session, name="MaintNet engines", questions=QS, author="Jeremiah", titles=TITLES, tenant_id=None, **kw)


def test_lifecycle_draft_review_approve_then_new_version(session):
    v1 = _new(session)
    assert (v1["version"], v1["status"], v1["question_count"]) == (1, "draft", 2)
    with pytest.raises(QuestionSetError):
        _new(session)  # one draft per name at a time
    sid = uuid.UUID(v1["id"])
    datasets.transition(session, sid, action="submit", by="Jeremiah", note=None, tenant_id=None)
    with pytest.raises(QuestionSetError):
        datasets.replace_questions(session, sid, questions=QS[:1], titles=TITLES, tenant_id=None)  # frozen in review
    with pytest.raises(QuestionSetError):
        datasets.transition(session, sid, action="approve", by="jeremiah", note=None, tenant_id=None)  # author can't approve
    ok = datasets.transition(session, sid, action="approve", by="Ama (reliability lead)", note="Labels checked", tenant_id=None)
    assert ok["status"] == "approved" and ok["reviewed_by"] == "Ama (reliability lead)"
    assert [h["status"] for h in ok["history"]] == ["draft", "in_review", "approved"]
    v2 = datasets.create_version(session, name="MaintNet engines", questions=QS[:1], author="Jeremiah", titles=TITLES, tenant_id=None)
    assert v2["version"] == 2 and v2["parent_id"] == v1["id"] and v2["status"] == "draft"


def test_returned_set_goes_back_to_draft_and_can_be_edited(session):
    sid = uuid.UUID(_new(session)["id"])
    datasets.transition(session, sid, action="submit", by="Jeremiah", note=None, tenant_id=None)
    back = datasets.transition(session, sid, action="return", by="Ama", note="Q2 has an answer: WO 7", tenant_id=None)
    assert back["status"] == "draft" and back["review_note"] == "Q2 has an answer: WO 7"
    edited = datasets.replace_questions(session, sid, questions=QS[:1], titles=TITLES, tenant_id=None)
    assert edited["question_count"] == 1 and edited["content_hash"] == dataset_hash(QS[:1])


def test_questions_need_labels_or_an_explicit_no_answer(session):
    with pytest.raises(QuestionSetError):
        datasets.create_version(session, name="x", questions=[{"question": "Why?"}], author="a", titles={}, tenant_id=None)
    with pytest.raises(QuestionSetError):
        datasets.create_version(session, name="y", questions=[{"question": "Why?", "expected_memory_ids": ["m1"], "expects_no_answer": True}],
                                author="a", titles={}, tenant_id=None)


def test_hash_ignores_order_and_spacing_but_not_labels():
    assert dataset_hash(QS) == dataset_hash(list(reversed(QS)))
    assert dataset_hash([{**QS[0], "question": "What  fixed the rough-running engine? "}]) == dataset_hash(QS[:1])
    assert dataset_hash([{**QS[0], "expected_memory_ids": ["m1"]}]) != dataset_hash(QS[:1])


def test_leakage_matches_the_console_rule():
    assert leaks("Engine ran rough after start?", ["WO 1: Engine ran rough after start"])
    assert not leaks("What fixed the rough-running engine?", ["WO 2: Replaced fuel pump"])
    assert leaks("What do we know about: anything", [])


def test_a_run_is_matched_to_the_approved_version_it_measured(session):
    sid = uuid.UUID(_new(session)["id"])
    datasets.transition(session, sid, action="submit", by="Jeremiah", note=None, tenant_id=None)
    datasets.transition(session, sid, action="approve", by="Ama", note=None, tenant_id=None)
    run_id = str(uuid.uuid4())
    cases = []
    for mode in ("semantic", "agentic"):
        for i, q in enumerate(QS):
            cases.append({"case_id": f"q-{i}", "question": q["question"], "mode": mode, "labeled": not q.get("expects_no_answer"),
                          "recall_at_5": 1.0, "recall_at_k": 1.0, "mrr": 1.0, "groundedness": None, "citation_accuracy": None,
                          "retrieved_memory_ids": [], "latency_ms": 1.0, "error": None})
    payload = {"run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(), "k": 10, "embedding_model": "E",
               "modes_run": ["semantic", "agentic"], "unavailable_modes": {}, "per_mode": {}, "failure_taxonomy": {}, "cases": cases}
    store.save_run(session, payload, expected={"q-0": ["m2", "m1"], "q-1": []}, anchors={}, tenant_id=None, llm_model=None, commit=None)
    listed = store.list_runs(session, tenant_id=None)[0]
    assert listed["question_set"]["name"] == "MaintNet engines" and listed["question_set"]["status"] == "approved"
    assert store.get_run(session, uuid.UUID(run_id), tenant_id=None)["question_set"]["version"] == 1


def test_an_unchanged_copy_is_not_saved_as_a_new_version(session):
    sid = uuid.UUID(_new(session)["id"])
    datasets.transition(session, sid, action="submit", by="Jeremiah", note=None, tenant_id=None)
    with pytest.raises(QuestionSetError, match="Nothing changed"):
        _new(session)


def test_a_draft_can_be_discarded_kept_for_the_record_and_never_credited(session):
    v1 = datasets.create_version(session, name="S", questions=QS[:1], author="a", titles=TITLES, tenant_id=None)
    gone = datasets.transition(session, uuid.UUID(v1["id"]), action="discard", by="a", note="duplicate", tenant_id=None)
    assert gone["status"] == "discarded" and gone["question_count"] == 1  # nothing deleted
    assert datasets.sets_by_hash(session, {v1["content_hash"]}, tenant_id=None) == {}
    v2 = datasets.create_version(session, name="S", questions=QS[:1] + QS[1:], author="a", titles=TITLES, tenant_id=None)
    assert v2["version"] == 2 and v2["status"] == "draft"  # the name is free for a new draft
    with pytest.raises(QuestionSetError):
        datasets.transition(session, uuid.UUID(v1["id"]), action="discard", by="a", note=None, tenant_id=None)

