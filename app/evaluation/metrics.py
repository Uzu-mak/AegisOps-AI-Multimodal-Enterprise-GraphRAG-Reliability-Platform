"""
Evaluation metrics: the single implementation used by the API's evaluation
runs, the console, and the recorded CLI benchmark (evals/run_benchmark.py).

Retrieval metrics take ranked memory IDs and the set judged relevant.
A question with no relevant IDs has nothing to recall; recall is reported as
1.0 (vacuous) and callers exclude such questions from retrieval averages.
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

_CITATION = re.compile(r"\[Memory\s+(\d+)\]")


def recall_at_k(retrieved_ids: list[str], expected_ids: Iterable[str], k: int = 10) -> float:
    """Fraction of expected IDs found in the top-k retrieved IDs."""
    expected = {str(e) for e in expected_ids}
    if not expected:
        return 1.0
    if k <= 0:
        return 0.0
    top_k = {str(r) for r in list(retrieved_ids)[:k]}
    return len(top_k & expected) / len(expected)


def mrr_at_k(retrieved_ids: list[str], expected_ids: Iterable[str], k: Optional[int] = 10) -> float:
    """Reciprocal rank of the first relevant ID within the top-k (k=None: whole list)."""
    expected = {str(e) for e in expected_ids}
    window = list(retrieved_ids) if k is None else list(retrieved_ids)[: max(k, 0)]
    for rank, rid in enumerate(window, start=1):
        if str(rid) in expected:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(retrieved_ids: list[str], expected_ids: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant result over the full list."""
    return mrr_at_k(retrieved_ids, expected_ids, k=None)


def groundedness_score(answer: str) -> float:
    """
    Fraction of substantial sentences (over 30 characters) that cite a [Memory N].

    Heuristic only; use human review or an LLM judge for real answer grading.
    """
    sentences = [s.strip() for s in re.split(r"[.!?]+", answer or "") if len(s.strip()) > 30]
    if not sentences:
        return 1.0
    return sum(1 for s in sentences if _CITATION.search(s)) / len(sentences)


def citation_accuracy(answer: str, evidence_count: int) -> float:
    """Fraction of [Memory N] citations that point at an evidence item that exists."""
    if evidence_count == 0:
        return 1.0
    refs = _CITATION.findall(answer or "")
    if not refs:
        return 1.0
    return sum(1 for r in refs if 1 <= int(r) <= evidence_count) / len(refs)


def median(values: Iterable[float]) -> float:
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def percentile(values: Iterable[float], pct: float) -> float:
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    if pct <= 0:
        return vals[0]
    if pct >= 100:
        return vals[-1]
    position = (len(vals) - 1) * (pct / 100.0)
    lo, hi = int(math.floor(position)), int(math.ceil(position))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (position - lo)
