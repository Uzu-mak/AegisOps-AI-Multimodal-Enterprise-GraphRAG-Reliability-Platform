"""Retrieval quality metrics — computed from actual benchmark runs only."""
from __future__ import annotations


def recall_at_k(
    retrieved_ids: list[str],
    expected_ids: list[str],
    k: int = 5,
) -> float:
    """Recall@K: fraction of expected IDs found in top-K retrieved IDs."""
    if not expected_ids:
        return 1.0  # Nothing to recall
    top_k = set(retrieved_ids[:k])
    found = sum(1 for eid in expected_ids if eid in top_k)
    return found / len(expected_ids)


def mean_reciprocal_rank(
    retrieved_ids: list[str],
    expected_ids: list[str],
) -> float:
    """MRR: reciprocal of rank of first relevant result."""
    expected_set = set(expected_ids)
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in expected_set:
            return 1.0 / rank
    return 0.0


def groundedness_score(answer: str) -> float:
    """
    Fraction of substantial sentences that contain a [Memory N] citation.

    This is a heuristic metric — for real evaluation use human annotation
    or an LLM judge.
    """
    import re

    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if len(s.strip()) > 30]
    if not sentences:
        return 1.0
    cited = sum(
        1 for s in sentences if re.search(r"\[Memory\s+\d+\]", s)
    )
    return cited / len(sentences)


def citation_accuracy(
    answer: str,
    evidence_count: int,
) -> float:
    """
    Fraction of [Memory N] citations that reference valid evidence indices.
    """
    import re

    if evidence_count == 0:
        return 1.0
    cited_refs = re.findall(r"\[Memory\s+(\d+)\]", answer)
    if not cited_refs:
        return 1.0
    valid = sum(
        1 for r in cited_refs
        if 1 <= int(r) <= evidence_count
    )
    return valid / len(cited_refs)
