"""Re-projection retries transient failures and lists every record that still failed."""
from __future__ import annotations

import app.outbox.projection_worker as pw


def _run(monkeypatch, fn, **kw):
    monkeypatch.setattr(pw, "build_projection_fns", lambda *a, **k: (fn, lambda *_: None))
    return pw.reproject_all(connections=None, only="qdrant", backoff_seconds=0, **kw)


def test_transient_failures_are_retried(monkeypatch):
    calls = {}

    def flaky(memory_id, _op):
        calls[memory_id] = calls.get(memory_id, 0) + 1
        if calls[memory_id] < 3:
            raise RuntimeError("timed out")

    report = _run(monkeypatch, flaky, ids=["a", "b"])
    assert report["qdrant"] == {"projected": 2, "errors": [], "error_count": 0, "failed_ids": []}


def test_every_lasting_failure_is_listed_not_just_the_first_five(monkeypatch):
    def broken(memory_id, _op):
        raise RuntimeError("Connection error.")

    ids = [f"m{i}" for i in range(8)]
    report = _run(monkeypatch, broken, ids=ids, attempts=2)
    assert report["qdrant"]["failed_ids"] == ids and len(report["qdrant"]["errors"]) == 5


def test_unreachable_store_stops_the_run(monkeypatch):
    def down(memory_id, _op):
        raise pw.ProjectionStoreUnavailable("qdrant down")

    report = _run(monkeypatch, down, ids=["a", "b"])
    assert report["qdrant"]["projected"] is None and report["qdrant"]["failed_ids"] == []
