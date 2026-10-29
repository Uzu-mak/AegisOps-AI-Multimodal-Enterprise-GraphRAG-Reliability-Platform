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
    mrr_at_k,
    percentile,
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

# (question, mode) -> (answer or None for retrieval-only modes, ranked memory IDs,
#                       retrieval_ms, generation_ms)
RetrievalFn = Callable[
    [str, str],
    tuple[Optional[str], list[str], float, float],
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
        run = EvalRun(run_id=uuid4(), run_name=self.run_name, modes_tested=modes, k=k)

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
        t_total = time.perf_counter()
        result = EvalCaseResult(
            case_id=case.case_id,
            question=case.question,
            mode=mode,
        )

        try:
            answer, retrieved_ids, retr_ms, gen_ms = self._retrieve(
                case.question, mode.value
            )
            result.answer = answer or ""
            result.retrieved_memory_ids = retrieved_ids
            result.retrieval_latency_ms = retr_ms
            result.generation_latency_ms = gen_ms
            result.labeled = bool(case.expected_memory_ids)

            result.recall_at_5 = recall_at_k(retrieved_ids, case.expected_memory_ids, 5)
            result.recall_at_k = recall_at_k(retrieved_ids, case.expected_memory_ids, k)
            result.mrr = mrr_at_k(retrieved_ids, case.expected_memory_ids, k)
            if answer is not None:
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

        result.total_latency_ms = (time.perf_counter() - t_total) * 1000
        return result

    def _aggregate(self, run: EvalRun) -> None:
        results = run.case_results
        if not results:
            return

        run.total_cases = len(results)
        run.failed_cases = sum(1 for r in results if not r.success)
        run.task_success_rate = 1.0 - (run.failed_cases / run.total_cases)

        labeled = [r for r in results if r.labeled and r.error is None]
        run.mean_recall_at_k = sum(r.recall_at_k for r in labeled) / len(labeled) if labeled else 0.0
        run.mean_mrr = sum(r.mrr for r in labeled) / len(labeled) if labeled else 0.0
        answered = [r for r in results if r.groundedness is not None]
        run.mean_groundedness = sum(r.groundedness for r in answered) / len(answered) if answered else 0.0
        cited = [r for r in results if r.citation_accuracy is not None]
        run.mean_citation_accuracy = sum(r.citation_accuracy for r in cited) / len(cited) if cited else 0.0
        run.mean_total_latency_ms = (
            sum(r.total_latency_ms for r in results) / len(results)
        )

        # Per-mode aggregates (labelled cases only for retrieval metrics)
        def mean(values):
            values = [v for v in values if v is not None]
            return sum(values) / len(values) if values else None

        for mode in run.modes_tested:
            rows = [r for r in results if r.mode == mode]
            labeled = [r for r in rows if r.labeled and r.error is None]
            run.per_mode[mode.value] = {
                "cases": len(rows),
                "labeled_cases": len(labeled),
                "errors": sum(1 for r in rows if r.error),
                "recall_at_5": mean([r.recall_at_5 for r in labeled]),
                "recall_at_k": mean([r.recall_at_k for r in labeled]),
                "mrr": mean([r.mrr for r in labeled]),
                "groundedness": mean([r.groundedness for r in rows]),
                "citation_accuracy": mean([r.citation_accuracy for r in rows]),
                "latency_p50_ms": percentile([r.total_latency_ms for r in rows], 50) if rows else None,
            }

        # Failure taxonomy
        taxonomy: dict[str, int] = {}
        for r in results:
            key = r.failure_category.value
            taxonomy[key] = taxonomy.get(key, 0) + 1
        run.failure_taxonomy = taxonomy
