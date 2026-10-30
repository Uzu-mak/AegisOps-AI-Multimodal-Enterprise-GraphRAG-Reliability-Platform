"""Absence handling: questions no record answers, and what a search covered."""
from __future__ import annotations

from app.evaluation.metrics import is_abstention
from app.evaluation.models import EvalCase, FailureCategory, RetrievalMode
from app.evaluation.runner import EvaluationRunner
from app.services.search_scope import search_scope


def test_abstention_wording_is_recognised_and_ordinary_answers_are_not():
    for said in ("The evidence is insufficient to determine the cause.",
                 "No records describe a propeller strike on this aircraft.",
                 "The records do not mention an oil cooler replacement.",
                 "I cannot determine whether the repair worked."):
        assert is_abstention(said), said
    assert not is_abstention("The vacuum port seal was replaced [Memory 1].")


def _runner(answer):
    return EvaluationRunner(retrieval_fn=lambda q, mode: (answer if mode == "agentic" else None, ["x"], 1.0, 1.0))


def test_no_answer_question_succeeds_only_when_the_answer_says_so():
    case = EvalCase(case_id="q1", question="Was the hangar door replaced?", expects_no_answer=True)
    good = _runner("No records mention the hangar door.").evaluate([case], [RetrievalMode.AGENTIC], k=5)
    bad = _runner("The hangar door was replaced in May [Memory 1].").evaluate([case], [RetrievalMode.AGENTIC], k=5)
    assert good.case_results[0].success and good.per_mode["agentic"]["abstention_rate"] == 1.0
    assert not bad.case_results[0].success
    assert bad.case_results[0].failure_category == FailureCategory.UNSUPPORTED_CLAIM
    assert bad.per_mode["agentic"]["abstentions"] == [{"question": case.question, "abstained": False, "expects_no_answer": True}]


def test_false_abstention_is_measured_on_answerable_questions():
    case = EvalCase(case_id="q2", question="What fixed it?", expected_memory_ids=["x"])
    run = _runner("The evidence is insufficient.").evaluate([case], [RetrievalMode.AGENTIC], k=5)
    assert run.per_mode["agentic"]["false_abstention_rate"] == 1.0
    assert run.per_mode["agentic"]["abstention_rate"] is None  # no no-answer questions asked


def test_retrieval_only_modes_report_no_abstention():
    case = EvalCase(case_id="q3", question="Anything?", expects_no_answer=True)
    run = _runner("x").evaluate([case], [RetrievalMode.SEMANTIC], k=5)
    assert "abstentions" not in run.per_mode["semantic"] and run.case_results[0].abstained is None


def test_search_scope_is_informative_never_fatal():
    def broken():
        raise RuntimeError("db down")
    assert search_scope(broken) is None
