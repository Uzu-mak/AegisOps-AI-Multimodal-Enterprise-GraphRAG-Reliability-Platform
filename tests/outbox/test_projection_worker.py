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


def test_unavailable_store_defers_without_consuming_retries(isolated_sessions):
    from tests.reliability.test_architecture_fixes import service, data
    from sqlalchemy import select
    from app.outbox.models import ProjectionOutboxEvent
    sf=isolated_sessions
    service(sf).create_memory(data=data())
    worker=OutboxWorker(sf, qdrant_fn=MagicMock(side_effect=ProjectionStoreUnavailable("offline")), neo4j_fn=lambda *_:None)
    assert worker.process_batch()["deferred"] == 1
    with sf() as session:
        event=session.scalar(select(ProjectionOutboxEvent).where(ProjectionOutboxEvent.projection_type=="qdrant"))
        assert event.retry_count == 0 and event.status == "pending"


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


def test_reproject_all_reports_unavailable_store_without_claiming_success(monkeypatch):
    import app.outbox.projection_worker as pw

    ids = [uuid4(), uuid4()]
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)
    session.scalars.return_value.all.return_value = ids
    memory = SimpleNamespace(id=ids[0], status="active", supersedes_memory_id=None)
    monkeypatch.setattr(pw, "_load_memory", lambda _sf, _mid: memory)

    semantic_service = MagicMock()
    monkeypatch.setattr("app.services.semantic_service.SemanticIndexingService", lambda **_k: semantic_service)
    conns = SimpleNamespace(semantic_index=lambda _e: object(), graph_index=lambda: None)

    report = pw.reproject_all(conns, session_factory=MagicMock(return_value=session), embedding_provider=MagicMock())
    assert report["records"] == 2
    assert report["qdrant"]["projected"] == 2
    assert report["neo4j"]["projected"] is None  # unavailable, not "0 done"
    assert "Neo4j unavailable" in report["neo4j"]["errors"][0]
