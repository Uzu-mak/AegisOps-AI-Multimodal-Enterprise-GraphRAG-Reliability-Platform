"""Pruning removes only search entries whose record is gone, and only when asked."""
from __future__ import annotations

from types import SimpleNamespace

import app.outbox.projection_worker as pw


class _Session:
    def __init__(self, ids): self.ids = ids
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def scalars(self, _stmt): return SimpleNamespace(all=lambda: self.ids)


class _Qdrant:
    def __init__(self, ids): self.points = list(ids); self.deleted = []
    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        start = offset or 0
        chunk = self.points[start:start + 2]
        nxt = start + 2 if start + 2 < len(self.points) else None
        return [SimpleNamespace(id=i, payload={"memory_id": i}) for i in chunk], nxt
    def delete(self, collection_name, points_selector): self.deleted += list(points_selector.points)


class _Neo:
    def __init__(self, ids): self.ids = ids; self.ran = []
    def session(self, database): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, q, **kw):
        self.ran.append((q, kw))
        if q.startswith("MATCH (m:Memory) RETURN"):
            return [{"id": i} for i in self.ids]
        return SimpleNamespace(consume=lambda: None, single=lambda: {"n": 3})


def _conns(q, n):
    return SimpleNamespace(semantic_index=lambda _e: SimpleNamespace(client=q, collection_name="c"),
                           graph_index=lambda: SimpleNamespace(_driver=n, _database="neo4j"))


def test_dry_run_reports_without_deleting(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "qdrant_client.models", SimpleNamespace(PointIdsList=lambda points: SimpleNamespace(points=points)))
    q, n = _Qdrant(["a", "b", "x", "y", "z"]), _Neo(["a", "x"])
    r = pw.prune_orphans(_conns(q, n), session_factory=lambda: _Session(["a", "b"]), embedding_provider=object(), dry_run=True)
    assert r["qdrant"] == {"orphans": 3, "removed": 0} and r["neo4j"]["orphans"] == 1
    assert q.deleted == [] and not any("DELETE" in qq for qq, _ in n.ran)


def test_apply_removes_only_orphans(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "qdrant_client.models", SimpleNamespace(PointIdsList=lambda points: SimpleNamespace(points=points)))
    q, n = _Qdrant(["a", "b", "x", "y", "z"]), _Neo(["a", "x"])
    r = pw.prune_orphans(_conns(q, n), session_factory=lambda: _Session(["a", "b"]), embedding_provider=object(), dry_run=False)
    assert sorted(q.deleted) == ["x", "y", "z"]
    assert r["neo4j"] == {"orphans": 1, "removed": 1, "unconnected_nodes_removed": 3}
    assert ("MATCH (m:Memory) WHERE m.memory_id IN $ids DETACH DELETE m", {"ids": ["x"]}) in n.ran
