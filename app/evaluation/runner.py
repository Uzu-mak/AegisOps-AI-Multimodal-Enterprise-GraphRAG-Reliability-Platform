"""
EvaluationRunner — executes benchmark cases and computes aggregate metrics.

Only reports metrics from actual runs. No fabricated numbers.
Supports semantic, graph, hybrid, and agentic modes.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional
from uuid import uuid4

from app.evaluation.metrics import (
    citation_accuracy,
    groundedness_score,
    mean_reciprocal_rank,
    recall_at_k,
)
from app.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    EvalRun,
    FailureCategory,
    RetrievalMode,
)

logger = logging.getLogger(__name__)

# Type for a retrieval function: (question, mode) -> (answer, retrieved_ids, latencies)
RetrievalFn = Callable[
    [str, str],  # question, mode
    tuple[str, list[str], float, float],  # answer, memory_ids, retrieval_ms, gen_ms
]


class EvaluationRunner:
    """
    Runs benchmark cases and aggregates results into an EvalRun.

    Usage:
        runner = EvaluationRunner(retrieval_fn=my_fn)
        run = runner.evaluate(cases, modes=[RetrievalMode.HYBRID], k=5)
    """

    def __init__(
        self,
        retrieval_fn: RetrievalFn,
        run_name: str = "eval_run",
    ) -> None:
        self._retrieve = retrieval_fn
        self.run_name = run_name

    def evaluate(
        self,
        cases: list[EvalCase],
        modes: list[RetrievalMode],
        k: int = 5,
    ) -> EvalRun:
        """
        Run all cases across all modes and return an EvalRun with
        computed aggregate metrics.
        """
        run = EvalRun(run_id=uuid4(), run_name=self.run_name, modes_tested=modes)

        for case in cases:
            for mode in modes:
                result = self._run_case(case, mode, k)
                run.case_results.append(result)

        # Aggregate
        self._aggregate(run)
        return run

    def _run_case(
        self,
        case: EvalCase,
        mode: RetrievalMode,
        k: int,
    ) -> EvalCaseResult:
        t_total = time.monotonic()
        result = EvalCaseResult(
            case_id=case.case_id,
            question=case.question,
            mode=mode,
        )

        try:
            answer, retrieved_ids, retr_ms, gen_ms = self._retrieve(
                case.question, mode.value
            )
            result.answer = answer
            result.retrieved_memory_ids = retrieved_ids
            result.retrieval_latency_ms = retr_ms
            result.generation_latency_ms = gen_ms

            # Compute metrics
            result.recall_at_k = recall_at_k(retrieved_ids, case.expected_memory_ids, k)
            result.mrr = mean_reciprocal_rank(retrieved_ids, case.expected_memory_ids)
            result.groundedness = groundedness_score(answer)
            result.citation_accuracy = citation_accuracy(answer, len(retrieved_ids))

            # Success: at least one expected ID retrieved OR no expected IDs (open question)
            result.success = (
                result.recall_at_k > 0 or not case.expected_memory_ids
            )
            result.failure_category = (
                FailureCategory.NO_FAILURE
                if result.success
                else FailureCategory.RETRIEVAL_FAILURE
            )

        except Exception as exc:
            logger.error(f"Eval case {case.case_id} mode {mode} failed: {exc}")
            result.success = False
            result.error = str(exc)
            result.failure_category = FailureCategory.PROVIDER_FAILURE

        result.total_latency_ms = (time.monotonic() - t_total) * 1000
        return result

    def _aggregate(self, run: EvalRun) -> None:
        results = run.case_results
        if not results:
            return

        run.total_cases = len(results)
        run.failed_cases = sum(1 for r in results if not r.success)
        run.task_success_rate = 1.0 - (run.failed_cases / run.total_cases)

        run.mean_recall_at_k = sum(r.recall_at_k for r in results) / len(results)
        run.mean_mrr = sum(r.mrr for r in results) / len(results)
        run.mean_groundedness = sum(r.groundedness for r in results) / len(results)
        run.mean_citation_accuracy = (
            sum(r.citation_accuracy for r in results) / len(results)
        )
        run.mean_total_latency_ms = (
            sum(r.total_latency_ms for r in results) / len(results)
        )

        # Failure taxonomy
        taxonomy: dict[str, int] = {}
        for r in results:
            key = r.failure_category.value
            taxonomy[key] = taxonomy.get(key, 0) + 1
        run.failure_taxonomy = taxonomy
