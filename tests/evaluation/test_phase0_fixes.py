"""Evaluation phase 0: anchored investigation cases, exact read-only POST paths,
and attributable CLI runs. None of these touch a database."""
from __future__ import annotations

import json

from app.evaluation.models import EvalCase, RetrievalMode
from app.evaluation.runner import EvaluationRunner


def test_runner_passes_the_anchor_to_retrieval_functions_that_take_it():
    seen = []

    def retrieve(question, mode, anchor_memory_id=None):
        seen.append((mode, anchor_memory_id))
        return ("Answer [Memory 1].", ["r1"], 1.0, 2.0)

    case = EvalCase(case_id="q1", question="Why?", expected_memory_ids=["r1"], anchor_memory_id="a1")
    run = EvaluationRunner(retrieval_fn=retrieve).evaluate([case], [RetrievalMode.AGENTIC], k=5)
    assert seen == [("agentic", "a1")]
    assert run.case_results[0].recall_at_k == 1.0


def test_two_argument_retrieval_functions_still_work():
    def retrieve(question, mode):
        return (None, ["r1"], 0.0, 0.0)

    case = EvalCase(case_id="q1", question="Why?", expected_memory_ids=["r1"], anchor_memory_id="a1")
    run = EvaluationRunner(retrieval_fn=retrieve).evaluate([case], [RetrievalMode.SEMANTIC], k=5)
    assert run.case_results[0].error is None and run.case_results[0].recall_at_k == 1.0


def test_viewer_writes_under_a_read_only_path_are_refused(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("AUTH_MODE", "token")
    monkeypatch.setenv("AUTH_TOKENS_JSON", json.dumps({"viewer-token": {"tenant_id": "a", "roles": ["viewer"]}}))
    client = TestClient(app)
    auth = {"Authorization": "Bearer viewer-token"}
    # A write nested under a read-only path must not inherit its exemption.
    assert client.post("/api/v1/evaluation/runs/abc/promote", json={}, headers=auth).status_code == 403
    assert client.post("/api/v1/investigations/findings", json={}, headers=auth).status_code == 403
    # The read-only POSTs themselves stay open to viewers (422 = reached validation).
    assert client.post("/api/v1/evaluation/runs", json={}, headers=auth).status_code != 403
    assert client.post("/api/v1/search/hybrid", json={}, headers=auth).status_code != 403


def test_cli_records_the_commit_passed_in_by_the_build(monkeypatch):
    from evals import run_benchmark

    monkeypatch.setenv("GIT_SHA", "abc1234")
    assert run_benchmark._git_commit() == "abc1234"
