"""Benchmark metrics: re-exported from the single implementation in app.evaluation.metrics."""
from app.evaluation.metrics import (  # noqa: F401
    citation_accuracy,
    groundedness_score,
    mean_reciprocal_rank,
    median,
    mrr_at_k,
    percentile,
    recall_at_k,
)
