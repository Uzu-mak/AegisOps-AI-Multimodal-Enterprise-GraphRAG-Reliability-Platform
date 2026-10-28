from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.models.memory import MemoryRecord, MemoryStatus
from app.db.session import SessionLocal
from app.ingestion.work_orders import (
    ExistingRecord,
    ImportOptions,
    WorkOrderImportError,
    detect_mapping,
    parse_datetime,
    parse_work_orders,
    plan_import,
    run_import,
)
from app.main import app
from app.outbox.models import ProjectionOutboxEvent
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.memory_service import RealMemoryService

SAMPLE = Path(__file__).resolve().parents[2] / "app" / "console" / "static" / "samples" / "work-orders-sample.csv"

MAXIMO = """WONUM,DESCRIPTION,LONGDESCRIPTION,ASSETNUM,LOCATION,SITEID,WORKTYPE,STATUS,WOPRIORITY,REPORTDATE,ACTFINISH,PROBLEMCODE,CAUSECODE,REMEDYCODE,ORIGRECORDID,CREW
1001,Pump P-4 seal leak,Mechanical seal leaking at 2 drops/min; seal replaced.,P-4,LINE-2,PLANT1,CM,COMP,1,04/03/2026 08:00,04/03/2026 12:30,LEAK,WEAR,REPLACE,SR-77,Night
1002,Monthly PM conveyor C-1,Lubricated rollers.,C-1,LINE-1,PLANT1,PM,COMP,3,04/05/2026,04/05/2026,,,,,Day
"""

SAP = """Order;Short Text;Equipment;Functional Location;Plant;Order Type;System Status;Priority;Created On;Notification
400001;Gearbox noise on mixer M-2;M-2;FL-MIX-02;1000;PM01;TECO;2;03.04.2026;10000123
"""


# ------------------------------------------------------------- pure parsing

def test_detects_maximo_columns_and_builds_record():
    r = parse_work_orders(MAXIMO, ImportOptions(timezone="UTC"))
    assert r.mapping["wo_number"] == "WONUM" and r.mapping["incident"] == "ORIGRECORDID"
    assert r.unmapped_columns == ["CREW"]
    assert len(r.work_orders) == 2 and not r.issues

    wo = r.work_orders[0].data
    assert wo.memory_type == "maintenance_action"
    assert wo.source_type == "work_order" and wo.source_id == "1001"
    assert wo.title == "WO 1001: Pump P-4 seal leak"
    assert wo.asset_id == "P-4" and wo.component_id == "LINE-2" and wo.facility_id == "PLANT1"
    assert wo.incident_id == "SR-77"
    assert "Cause: WEAR" in wo.content and "Remedy: REPLACE" in wo.content
    assert wo.content.startswith("Mechanical seal leaking")  # long text leads; title not repeated
    assert wo.observed_at.isoformat() == "2026-04-03T12:30:00+00:00"  # month first by default
    assert wo.confidence == 0.9 and wo.importance == 0.9
    assert wo.memory_metadata["extra"] == {"CREW": "Night"}
    assert wo.memory_metadata["work_order"]["work_type_class"] == "corrective"

    pm = r.work_orders[1].data
    assert pm.incident_id is None  # no ticket -> no invented incident
    assert pm.memory_metadata["work_order"]["work_type_class"] == "preventive"


def test_detects_sap_columns_semicolon_and_dotted_dates():
    r = parse_work_orders(SAP, ImportOptions(timezone="Europe/Berlin"))
    wo = r.work_orders[0].data
    assert r.mapping["wo_number"] == "Order" and r.mapping["asset"] == "Equipment"
    assert wo.facility_id == "1000" and wo.incident_id == "10000123"
    assert wo.observed_at.isoformat() == "2026-04-02T22:00:00+00:00"  # 3 Apr local -> UTC
    assert wo.memory_metadata["work_order"]["finished_at"] is None
    assert wo.confidence == 0.8  # TECO counts as closed


def test_day_first_option():
    tz = __import__("zoneinfo").ZoneInfo("UTC")
    assert parse_datetime("04/03/2026", day_first=False, tz=tz).month == 4
    assert parse_datetime("04/03/2026", day_first=True, tz=tz).month == 3
    with pytest.raises(ValueError):
        parse_datetime("sometime", day_first=False, tz=tz)


def test_row_level_problems_are_reported_not_fatal():
    csv = "WONUM,DESCRIPTION,ASSETNUM,ACTFINISH\n,No number,A,\n2,,A,\n3,Fine,A,yesterday\n3,Dup,A,\n4,No asset,,\n"
    r = parse_work_orders(csv)
    msgs = [(i.row, i.level) for i in r.issues]
    assert (1, "error") in msgs and (2, "error") in msgs
    assert (3, "warning") in msgs  # bad date
    assert (4, "warning") in msgs  # duplicate
    assert (5, "warning") in msgs  # no asset
    assert [w.wo_number for w in r.work_orders] == ["3", "4"]


def test_missing_required_columns_returns_mapping_for_a_person_to_fix():
    r = parse_work_orders("Job,What\nJ1,Belt\n")
    assert r.missing_required == ["wo_number", "description"] and not r.work_orders
    r = parse_work_orders("Job,What\nJ1,Belt\n", ImportOptions(column_map={"wo_number": "Job", "description": "What"}))
    assert r.work_orders[0].data.title == "WO J1: Belt"


def test_column_map_validation():
    with pytest.raises(WorkOrderImportError):
        detect_mapping(["a"], {"nonsense": "a"})
    with pytest.raises(WorkOrderImportError):
        detect_mapping(["a"], {"asset": "b"})
    with pytest.raises(WorkOrderImportError):
        parse_work_orders("")


def test_plan_splits_new_changed_unchanged():
    r = parse_work_orders(MAXIMO)
    a, b = r.work_orders
    existing = {
        "PLANT1|1001": ExistingRecord(memory_id="x", fingerprint=a.fingerprint),
        "PLANT1|1002": ExistingRecord(memory_id="y", fingerprint="old"),
    }
    plan = plan_import(r.work_orders, existing)
    assert plan.unchanged == [a] and [w for _, w in plan.supersede] == [b] and not plan.create


def test_sample_export_is_clean_and_synthetic():
    r = parse_work_orders(SAMPLE.read_text(), ImportOptions(is_synthetic=True))
    assert len(r.work_orders) == 30 and not r.issues
    assert all(w.data.is_synthetic for w in r.work_orders)
    assert all(w.wo_number.startswith("SAMPLE-") for w in r.work_orders)


# --------------------------------------------------------- against Postgres

@pytest.fixture
def clean_db():
    def wipe():
        with SessionLocal() as s:
            s.execute(delete(ProjectionOutboxEvent))
            s.execute(delete(MemoryRecord))
            s.commit()
    wipe()
    yield
    wipe()


@pytest.fixture
def service():
    return RealMemoryService(repository=SQLAlchemyMemoryRepository(), session_factory=SessionLocal)


def test_import_is_idempotent_and_supersedes_changes(clean_db, service):
    dry = run_import(service, MAXIMO, dry_run=True)
    assert dry["new"] == 2 and dry["written"] == {"created": 0, "superseded": 0}
    with SessionLocal() as s:
        assert s.scalars(select(MemoryRecord)).all() == []

    first = run_import(service, MAXIMO, dry_run=False)
    assert first["written"] == {"created": 2, "superseded": 0} and first["queued_for_projection"] == 2
    with SessionLocal() as s:
        events = s.scalars(select(ProjectionOutboxEvent)).all()
        assert len(events) == 4 and {e.status for e in events} == {"pending"}

    again = run_import(service, MAXIMO, dry_run=False)
    assert again["unchanged"] == 2 and again["written"] == {"created": 0, "superseded": 0}

    changed = MAXIMO.replace("Lubricated rollers.", "Lubricated rollers; replaced worn belt.")
    third = run_import(service, changed, dry_run=False)
    assert third["changed"] == 1 and third["written"]["superseded"] == 1
    with SessionLocal() as s:
        rows = s.scalars(select(MemoryRecord).where(MemoryRecord.source_id == "1002")).all()
        by_status = {r.status: r for r in rows}
        assert set(by_status) == {MemoryStatus.ACTIVE.value, MemoryStatus.SUPERSEDED.value}
        assert by_status["active"].supersedes_memory_id == by_status["superseded"].id
        assert "replaced worn belt" in by_status["active"].content


def test_api_preview_then_import(clean_db):
    client = TestClient(app)
    r = client.post("/api/v1/imports/work-orders", json={"csv": MAXIMO, "file_name": "wo.csv"})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["new"] == 2
    r = client.post("/api/v1/imports/work-orders", json={"csv": MAXIMO, "dry_run": False, "is_synthetic": True})
    assert r.status_code == 200 and r.json()["written"]["created"] == 2
    recs = client.get("/api/v1/memories", params={"source_type": "work_order"}).json()["items"]
    assert len(recs) == 2 and all(m["is_synthetic"] for m in recs)

    r = client.post("/api/v1/imports/work-orders", json={"csv": "Job,What\nJ1,Belt\n", "dry_run": False})
    assert r.status_code == 422
    r = client.post("/api/v1/imports/work-orders", json={"csv": MAXIMO, "timezone": "Mars/Base"})
    assert r.status_code == 422
