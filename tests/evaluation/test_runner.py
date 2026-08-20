"""Tests for evaluation runner and metrics."""
from app.evaluation.metrics import (
    citation_accuracy,
    groundedness_score,
    mean_reciprocal_rank,
    recall_at_k,
)
from app.evaluation.models import EvalCase, RetrievalMode
from app.evaluation.runner import EvaluationRunner


class TestRecallAtK:

    def test_perfect_recall(self):
        assert recall_at_k(["a", "b", "c"], ["a", "b"], k=5) == 1.0

    def test_zero_recall(self):
        assert recall_at_k(["x", "y"], ["a", "b"], k=5) == 0.0

    def test_partial_recall(self):
        assert recall_at_k(["a", "x"], ["a", "b"], k=5) == 0.5

    def test_empty_expected(self):
        assert recall_at_k(["a", "b"], [], k=5) == 1.0

    def test_k_limits_window(self):
        # Expected "b" is at position 6, beyond k=5
        retrieved = ["a", "x", "y", "z", "w", "b"]
        assert recall_at_k(retrieved, ["b"], k=5) == 0.0


class TestMRR:

    def test_first_rank(self):
        assert mean_reciprocal_rank(["a", "b"], ["a"]) == 1.0

    def test_second_rank(self):
        assert mean_reciprocal_rank(["x", "a"], ["a"]) == 0.5

    def test_not_found(self):
        assert mean_reciprocal_rank(["x", "y"], ["a"]) == 0.0


class TestGroundedness:

    def test_fully_grounded(self):
        answer = "The pump failed [Memory 1]. Vibration exceeded threshold [Memory 2]."
        score = groundedness_score(answer)
        assert score == 1.0

    def test_ungrounded(self):
        answer = "The pump failed due to wear. Maintenance is required immediately."
        score = groundedness_score(answer)
        assert score < 1.0


class TestCitationAccuracy:

    def test_valid_citations(self):
        answer = "See [Memory 1] and [Memory 2] for evidence."
        assert citation_accuracy(answer, evidence_count=3) == 1.0

    def test_invalid_citation(self):
        answer = "See [Memory 99] for evidence."
        assert citation_accuracy(answer, evidence_count=3) < 1.0

    def test_no_citations(self):
        answer = "No references."
        assert citation_accuracy(answer, evidence_count=3) == 1.0


class TestEvaluationRunner:

    def test_runner_computes_aggregate_metrics(self):
        def mock_retrieve(question, mode):
            return "Answer with [Memory 1] citation.", ["id-1", "id-2"], 10.0, 50.0

        runner = EvaluationRunner(retrieval_fn=mock_retrieve, run_name="test")
        cases = [
            EvalCase(
                case_id="c1",
                question="What failed?",
                expected_memory_ids=["id-1"],
            ),
        ]
        run = runner.evaluate(cases, modes=[RetrievalMode.HYBRID])

        assert run.total_cases == 1
        assert run.task_success_rate == 1.0
        assert run.mean_recall_at_k > 0

    def test_runner_handles_retrieval_failure(self):
        def failing_retrieve(question, mode):
            raise RuntimeError("Service unavailable")

        runner = EvaluationRunner(retrieval_fn=failing_retrieve)
        cases = [EvalCase(case_id="c1", question="test")]
        run = runner.evaluate(cases, modes=[RetrievalMode.SEMANTIC])

        assert run.failed_cases == 1
        assert run.case_results[0].error is not None
