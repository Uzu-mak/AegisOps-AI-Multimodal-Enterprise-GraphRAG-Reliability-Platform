from evals.metrics import mrr_at_k, percentile, recall_at_k
from evals.retrievers import ModeRetriever, build_mode_retrievers


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


def test_mode_retrievers_wrap_production_retriever_in_fixed_modes():
    seen = []

    class Production:
        def retrieve(self, query):
            seen.append((query.mode, query.final_limit))
            return []

    methods = build_mode_retrievers(Production(), {"qdrant": True, "neo4j": True})
    for name in ("vector", "graph", "hybrid"):
        methods[name].retrieve("servo fault", 10)
    assert seen == [("semantic", 10), ("graph", 10), ("hybrid", 10)]


def test_methods_needing_a_down_backend_are_absent():
    methods = build_mode_retrievers(object(), {"qdrant": True, "neo4j": False})
    assert isinstance(methods["vector"], ModeRetriever)
    assert methods["graph"] is None and methods["hybrid"] is None


def test_empty_relevant_set_is_vacuous_and_mrr_respects_k():
    assert recall_at_k(["a"], [], k=5) == 1.0
    assert mrr_at_k(["x", "y", "a"], {"a"}, k=2) == 0.0


def test_citation_after_the_full_stop_counts_for_its_sentence():
    from app.evaluation.metrics import groundedness_score

    cited_after = (
        "Porosity was caused by a hardened, cracked vacuum port seal on line 2. [Memory 4]\n\n"
        "The prior fix replaced all vacuum port seals on lines 1 through 3. [Memory 6]"
    )
    assert groundedness_score(cited_after) == 1.0
    half = "Porosity was caused by a hardened, cracked vacuum port seal. [Memory 4] The resin supplier also changed last spring."
    assert groundedness_score(half) == 0.5
