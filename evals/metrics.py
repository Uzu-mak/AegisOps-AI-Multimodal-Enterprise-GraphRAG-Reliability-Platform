from __future__ import annotations

import math
from typing import Iterable


def recall_at_k(result_ids: list[str], relevant_ids: set[str] | list[str], k: int = 10) -> float:
    """Fraction of relevant memory IDs found in the top-k candidate list."""
    if k <= 0 or not result_ids or not relevant_ids:
        return 0.0

    relevant = {str(item) for item in relevant_ids}
    top_k = {str(item) for item in result_ids[:k]}
    if not relevant:
        return 0.0
    return len(top_k & relevant) / len(relevant)


def mrr_at_k(result_ids: list[str], relevant_ids: set[str] | list[str], k: int = 10) -> float:
    """Mean reciprocal rank (MRR) for the first relevant item in the top-k."""
    if k <= 0 or not result_ids or not relevant_ids:
        return 0.0

    relevant = {str(item) for item in relevant_ids}
    for rank, item in enumerate(result_ids[:k], start=1):
        if str(item) in relevant:
            return 1.0 / rank
    return 0.0


def median(values: Iterable[float]) -> float:
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    midpoint = len(vals) // 2
    if len(vals) % 2:
        return vals[midpoint]
    return (vals[midpoint - 1] + vals[midpoint]) / 2.0


def percentile(values: Iterable[float], pct: float) -> float:
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    if pct <= 0:
        return vals[0]
    if pct >= 100:
        return vals[-1]

    position = (len(vals) - 1) * (pct / 100.0)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return vals[lower_index]

    fraction = position - lower_index
    return vals[lower_index] + (vals[upper_index] - vals[lower_index]) * fraction
