"""Projection worker: deferral during outages and canonical-state projection."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.outbox.models import ProjectionStatus
from app.outbox.projection_worker import ProjectionStoreUnavailable, build_projection_fns
from app.outbox.worker import OutboxWorker
from tests.outbox.test_worker import make_event


def _session_with(events):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)
    session.scalars.return_value.all.return_value = events
    return MagicMock(return_value=session)


def test_unavailable_store_defers_without_consuming_retries():
    event = make_event(status=ProjectionStatus.PENDING.value)
    worker = OutboxWorker(
        session_factory=_session_with([event]),
        qdrant_fn=MagicMock(side_effect=ProjectionStoreUnavailable("Qdrant unavailable")),
    )
    stats = worker.process_batch()
    assert stats["deferred"] == 1
    assert event.retry_count == 0
    assert event.status == ProjectionStatus.PENDING.value


def test_projection_fns_raise_deferral_when_store_missing():
    conns = SimpleNamespace(semantic_index=lambda _e: None, graph_index=lambda: None)
    qdrant_fn, neo4j_fn = build_projection_fns(conns, session_factory=MagicMock(), embedding_provider=MagicMock())
    for fn in (qdrant_fn, neo4j_fn):
        try:
            fn(str(uuid4()), "project")
        except ProjectionStoreUnavailable:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected deferral")


def test_neo4j_fn_projects_current_canonical_state(monkeypatch):
    memory = SimpleNamespace(id=uuid4(), status="archived", supersedes_memory_id=None)
    graph_index = MagicMock()
    conns = SimpleNamespace(semantic_index=lambda _e: None, graph_index=lambda: graph_index)

    import app.outbox.projection_worker as pw

    monkeypatch.setattr(pw, "_load_memory", lambda _sf, _mid: memory)
    _, neo4j_fn = build_projection_fns(conns, session_factory=MagicMock(), embedding_provider=MagicMock())
    neo4j_fn(str(memory.id), "status_update")
    graph_index.project_memory.assert_called_once_with(memory)
