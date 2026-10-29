"""PostgreSQL-specific isolation and import concurrency regressions.
Only run in the explicit disposable integration stack.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from app.main import app
from app.api.deps import get_semantic_index, get_graph_memory_index
from app.db.session import SessionLocal
from app.db.models.memory import MemoryRecord
from app.outbox.models import ProjectionOutboxEvent
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.memory_service import RealMemoryService
from app.services.exceptions import MemoryConflictError
from app.ingestion.work_orders import run_import, ImportOptions

@pytest.fixture
def tracked():
    suffix=str(uuid4())
    yield suffix
    with SessionLocal() as session:
        ids=select(MemoryRecord.id).where(MemoryRecord.source_id==suffix)
        session.execute(delete(ProjectionOutboxEvent).where(ProjectionOutboxEvent.memory_id.in_(ids)))
        session.execute(delete(MemoryRecord).where(MemoryRecord.source_id==suffix))
        session.commit()

def test_authenticated_reads_cannot_cross_tenants(monkeypatch, tracked):
    monkeypatch.setenv("AUTH_MODE","token")
    monkeypatch.setenv("AUTH_TOKENS_JSON",json.dumps({
        "token-a":{"tenant_id":"a","roles":["writer"]},
        "token-b":{"tenant_id":"b","roles":["writer"]},
    }))
    app.dependency_overrides[get_semantic_index]=lambda:None
    app.dependency_overrides[get_graph_memory_index]=lambda:None
    try:
        client=TestClient(app)
        body={"memory_type":"observation","title":"Private","content":"Private evidence", "source_type":"test", "source_id":tracked}
        created=client.post("/api/v1/memories",json=body,headers={"Authorization":"Bearer token-a"})
        assert created.status_code==201,created.text
        mid=created.json()["id"]
        assert created.json()["tenant_id"]=="a"
        hidden=client.get(f"/api/v1/memories/{mid}",headers={"Authorization":"Bearer token-b"})
        assert hidden.status_code==404,hidden.text
        listed=client.get("/api/v1/memories",headers={"Authorization":"Bearer token-b"}).json()
        assert mid not in [m["id"] for m in listed["items"]]
        assert client.post(f"/api/v1/memories/{mid}/archive",headers={"Authorization":"Bearer token-b"}).status_code==404
    finally:
        app.dependency_overrides.pop(get_semantic_index,None)
        app.dependency_overrides.pop(get_graph_memory_index,None)

def test_parallel_imports_never_duplicate_active_identity(tracked):
    csv=f"WONUM,DESCRIPTION,ASSETNUM\n{tracked},Bearing inspection,P1\n"
    def apply():
        svc=RealMemoryService(repository=SQLAlchemyMemoryRepository(),session_factory=SessionLocal)
        try:
            return run_import(svc,csv,ImportOptions(source_system="parallel-test"),dry_run=False)
        except MemoryConflictError:
            return {"conflict":True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports=list(pool.map(lambda _:apply(),range(2)))
    with SessionLocal() as session:
        rows=session.scalars(select(MemoryRecord).where(MemoryRecord.source_id==tracked,MemoryRecord.status=="active")).all()
        assert len(rows)==1
    assert sum(r.get("written",{}).get("created",0) for r in reports)==1
