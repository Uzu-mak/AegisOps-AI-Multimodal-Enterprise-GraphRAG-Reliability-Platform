from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select
from app.db.models.memory import MemoryRecord
from app.outbox.models import ProjectionOutboxEvent as Event
from app.outbox.worker import OutboxWorker, ProjectionDeferred
from app.outbox.publisher import ProjectionEventPublisher
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.memory_service import MemoryCreateData, RealMemoryService

def service(sf):
    return RealMemoryService(repository=SQLAlchemyMemoryRepository(), session_factory=sf)
def data(**kw):
    return MemoryCreateData(memory_type="observation", title="Original", content="Evidence", source_type="manual", confidence=.8, importance=.7, **kw)

def test_each_mutation_retains_its_event_and_content(isolated_sessions):
    sf=isolated_sessions; svc=service(sf)
    record=svc.create_memory(data=data())
    svc.update_memory(record.id, {"title":"Second"})
    svc.update_memory(record.id, {"title":"Third"})
    with sf() as session:
        rows=session.scalars(select(Event).order_by(Event.memory_version)).all()
        assert len(rows)==6
        assert {r.memory_version for r in rows}=={1,2,3}
        assert {r.payload["title"] for r in rows}=={"Original","Second","Third"}
        assert len({r.event_id for r in rows})==3

def test_deferred_store_does_not_starve_healthy_store(isolated_sessions):
    sf=isolated_sessions; record=service(sf).create_memory(data=data())
    projected=[]
    def unavailable(*_): raise ProjectionDeferred("offline")
    stats=OutboxWorker(sf, unavailable, lambda mid, op: projected.append(mid)).process_batch()
    assert stats["deferred"]==1 and stats["completed"]==1
    assert projected==[str(record.id)]
    with sf() as session:
        pending=session.scalar(select(Event).where(Event.projection_type=="qdrant"))
        assert pending.retry_count==0 and pending.next_attempt_at is not None

def test_network_io_runs_after_claim_transaction_commits(isolated_sessions):
    sf=isolated_sessions; record=service(sf).create_memory(data=data())
    def apply(mid, operation):
        with sf() as session:
            assert session.scalar(select(Event).where(Event.projection_type=="qdrant")).status=="processing"
    OutboxWorker(sf, apply, lambda *_:None).process_batch()

def test_failures_are_scheduled_and_missing_handlers_never_complete(isolated_sessions):
    sf=isolated_sessions; service(sf).create_memory(data=data())
    stats=OutboxWorker(sf, base_backoff_seconds=10).process_batch()
    assert stats["skipped"]==2
    assert not stats["completed"]
    with sf() as session:
        rows=session.scalars(select(Event)).all()
        assert all(row.retry_count==1 and row.status=="retrying" and row.next_attempt_at for row in rows)
    assert not any(OutboxWorker(sf).process_batch().values())

def test_expired_claim_recovers_after_worker_crash(isolated_sessions):
    sf=isolated_sessions; service(sf).create_memory(data=data())
    with sf() as session:
        row=session.scalar(select(Event).where(Event.projection_type=="qdrant"))
        row.status="processing"; row.lease_token=uuid4(); row.lease_until=datetime.now(timezone.utc)-timedelta(seconds=5)
        session.commit()
    assert OutboxWorker(sf, lambda *_:None, lambda *_:None).process_batch()["completed"]==2

def test_broker_receives_each_revision_with_snapshot(isolated_sessions):
    sf=isolated_sessions; svc=service(sf);record=svc.create_memory(data=data());svc.update_memory(record.id,{"title":"Updated"})
    producer=MagicMock(); publisher=ProjectionEventPublisher(session_factory=sf, producer=producer, topic="test")
    assert publisher.publish_batch()["published"]==2
    import json
    events=[json.loads(c.kwargs["value"]) for c in producer.publish.call_args_list]
    assert [e["memory_version"] for e in events]==[1,2]
    assert [e["memory"]["title"] for e in events]==["Original","Updated"]
    assert publisher.publish_batch()["published"]==0

def test_failed_broker_publication_waits_before_retry(isolated_sessions):
    sf=isolated_sessions; service(sf).create_memory(data=data())
    producer=MagicMock();producer.publish.side_effect=RuntimeError("offline")
    publisher=ProjectionEventPublisher(session_factory=sf,producer=producer,topic="test")
    assert publisher.publish_batch()["failed"]==1
    assert publisher.publish_batch()["failed"]==0

def test_unlabelled_questions_do_not_inflate_recall():
    from app.evaluation.runner import EvaluationRunner
    from app.evaluation.models import EvalCase, RetrievalMode
    runner=EvaluationRunner(lambda *_:(None,[],0,0))
    result=runner.evaluate([EvalCase(case_id="label",question="q",expected_memory_ids=["a"]),EvalCase(case_id="open",question="q")],[RetrievalMode.HYBRID])
    assert result.mean_recall_at_k==0

def test_fingerprint_changes_with_extra_fields_and_sample_flag():
    from app.ingestion.work_orders import fingerprint
    first=data(); second=data();second.memory_metadata={"extra":{"shift":"night"}}
    assert fingerprint(first)!=fingerprint(second)
    second=data(is_synthetic=True)
    assert fingerprint(first)!=fingerprint(second)

def test_projection_bootstrap_error_does_not_discard_healthy_connection(monkeypatch):
    from app.core.connections import ProjectionConnections
    driver=MagicMock();settings=SimpleNamespace(PROJECTION_RETRY_SECONDS=15,NEO4J_DATABASE="neo4j",NEO4J_URI="bolt://test")
    manager=ProjectionConnections(settings,neo4j_factory=lambda _:driver)
    monkeypatch.setattr("app.graph.neo4j_impl.Neo4jGraphMemoryIndex.bootstrap_constraints",MagicMock(side_effect=RuntimeError("permissions")))
    assert manager.graph_index() is None
    assert manager.probe("neo4j")["status"]=="healthy"
    assert manager.probe("neo4j")["projection_error"]
    driver.close.assert_not_called()

def test_real_embedding_adapter_checks_dimension():
    from app.embeddings.openai_embedding import OpenAIEmbedding
    client=MagicMock();client.embeddings.create.return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[.1,.2])])
    assert OpenAIEmbedding(dimension=2,client=client).embed_text("bearing wear")==[.1,.2]
    with pytest.raises(ValueError,match="dimension"):
        OpenAIEmbedding(dimension=3,client=client).embed_text("bearing wear")

def test_token_auth_rejects_missing_token_and_readonly_writes(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import json
    monkeypatch.setenv("AUTH_MODE","token")
    monkeypatch.setenv("AUTH_TOKENS_JSON",json.dumps({"test-only":{"tenant_id":"a","roles":["viewer"]}}))
    client=TestClient(app)
    assert client.get("/api/v1/memories").status_code==401
    assert client.post("/api/v1/memories",json={},headers={"Authorization":"Bearer test-only"}).status_code==403

def test_cross_tenant_creation_is_rejected(isolated_sessions):
    from app.core.security import Principal,_identity
    from app.services.exceptions import InvalidMemoryDataError
    token=_identity.set(Principal("tenant-a",("writer",)))
    try:
        with pytest.raises(InvalidMemoryDataError,match="tenant"):
            service(isolated_sessions).create_memory(data=data(tenant_id="tenant-b"))
    finally:_identity.reset(token)

def test_readiness_returns_503_on_unavailable_database(monkeypatch):
    from app import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main,"SessionLocal",MagicMock(side_effect=RuntimeError("offline")))
    assert TestClient(main.app).get("/ready").status_code==503
    assert TestClient(main.app).get("/live").status_code==200
