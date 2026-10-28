"""Benchmark must not report unavailable retrieval methods as zero recall."""
from __future__ import annotations

import pytest

import evals.run_benchmark as rb


class _Vector:
    def retrieve(self, query_text, k):
        return ["m1", "m2"]


QUERIES = [{"query_id": "q1", "query_text": "servo fault", "fault_family": "servo", "relevant_memory_ids": ["m1"], "notes": ""}]


@pytest.fixture
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_load_query_rows", lambda _p: QUERIES)
    monkeypatch.setattr(rb, "_is_template_only", lambda *_a: False)
    monkeypatch.setattr(rb, "validate_query_file", lambda *_a, **_k: QUERIES)
    monkeypatch.setattr(rb, "_available_memory_ids", lambda: {"m1", "m2"})
    monkeypatch.setattr(rb, "_memory_count", lambda: 2)
    monkeypatch.setattr(rb, "RESULTS_ROOT", tmp_path)

    def fake_build(semantic_collection=None, backend_status=None):
        backend_status.update({"embedding_model": "HashedTermEmbedding(dimension=128)", "qdrant": "available", "neo4j": "unavailable: refused"})
        return {"vector": _Vector(), "graph": None, "hybrid": None}

    monkeypatch.setattr(rb, "_build_retrievers", fake_build)
    return tmp_path


def test_strict_run_refuses_when_a_backend_is_missing(patched):
    with pytest.raises(RuntimeError, match="graph, hybrid"):
        rb.run_benchmark(patched / "q.jsonl", k=10, repeats=1, warmup=0)


def test_partial_run_marks_missing_methods_not_measured(patched):
    payload = rb.run_benchmark(patched / "q.jsonl", k=10, repeats=1, warmup=0, allow_partial=True)
    summary = payload["summary_by_method"]
    assert summary["vector"]["status"] == "measured"
    assert summary["vector"]["Recall@5"] == 1.0
    assert summary["graph"] == {"status": "unavailable"}
    assert summary["hybrid"] == {"status": "unavailable"}
    assert payload["retriever_configs"]["embedding_model"].startswith("HashedTermEmbedding")
    md = (patched / payload["results_dir"].split("/")[-1] / "summary.md").read_text()
    assert "| graph | not measured" in md
    assert "HashedTermEmbedding" in md
