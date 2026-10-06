from evals.metrics import mrr_at_k, percentile, recall_at_k
from evals.retrievers import rrf_merge


def test_recall_at_k_handles_top_k_overlap():
    result_ids = ["m1", "m2", "m3", "m4"]
    relevant = {"m2", "m4"}

    assert recall_at_k(result_ids, relevant, k=5) == 1.0
    assert recall_at_k(result_ids, relevant, k=2) == 0.5


def test_mrr_at_k_returns_first_relevant_rank():
    result_ids = ["a", "b", "c"]
    relevant = {"b"}

    assert mrr_at_k(result_ids, relevant, k=10) == 0.5
    assert mrr_at_k(["x", "y"], {"z"}, k=10) == 0.0


def test_percentile_is_order_statistic():
    values = [1.0, 5.0, 8.0, 12.0, 20.0]
    assert percentile(values, 50) == 8.0
    assert percentile(values, 90) == 16.8


def test_rrf_merge_prioritizes_overlap_and_rank_signal():
    semantic = ["A", "B", "C"]
    graph = ["B", "D"]

    merged = rrf_merge(semantic, graph, k=60)
    assert merged[0] == "B"
    assert merged[1:5] == ["A", "D", "C"]
