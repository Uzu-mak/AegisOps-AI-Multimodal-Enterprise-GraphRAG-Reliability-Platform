from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.db.session import SessionLocal
from app.repositories.memory_repository import SQLAlchemyMemoryRepository


@pytest.fixture
def session():
    with SessionLocal() as session:
        yield session
        session.rollback()
        session.execute(delete(MemoryRecord))
        session.commit()


@pytest.fixture
def repository() -> SQLAlchemyMemoryRepository:
    return SQLAlchemyMemoryRepository()


def make_memory(**overrides):
    memory = MemoryRecord(
        id=uuid4(),
        memory_type=MemoryType.OBSERVATION.value,
        status=MemoryStatus.ACTIVE.value,
        title="Observation title",
        content="Observation content",
        asset_id="asset-123",
        component_id="component-1",
        incident_id="incident-1",
        source_type="sensor",
        source_id="source-1",
        confidence=0.92,
        importance=0.81,
        is_synthetic=False,
        tenant_id="tenant-1",
        facility_id="facility-1",
        team_id="team-1",
        access_roles=["ops", "eng"],
        memory_metadata={"source": "ingest", "value": 7},
    )

    for field_name, value in overrides.items():
        setattr(memory, field_name, value)

    return memory


def test_create_persists_memory(session, repository):
    memory = make_memory()

    created = repository.create(session, memory)
    session.commit()

    assert created.id == memory.id
    assert session.get(MemoryRecord, memory.id) is not None


def test_get_by_id_returns_memory(session, repository):
    memory = make_memory(title="Lookup memory")
    repository.create(session, memory)
    session.commit()

    fetched = repository.get_by_id(session, memory.id)

    assert fetched is not None
    assert fetched.id == memory.id
    assert fetched.title == "Lookup memory"


def test_list_filters_by_supported_fields(session, repository):
    repo1 = make_memory(
        memory_type=MemoryType.OBSERVATION.value,
        status=MemoryStatus.ACTIVE.value,
        asset_id="asset-1",
        facility_id="facility-1",
        source_type="sensor",
    )
    repo2 = make_memory(
        memory_type=MemoryType.RECOMMENDATION.value,
        status=MemoryStatus.ACTIVE.value,
        asset_id="asset-2",
        facility_id="facility-1",
        source_type="manual",
    )
    repo3 = make_memory(
        memory_type=MemoryType.OBSERVATION.value,
        status=MemoryStatus.ARCHIVED.value,
        asset_id="asset-1",
        facility_id="facility-2",
        source_type="sensor",
    )

    for item in (repo1, repo2, repo3):
        repository.create(session, item)
    session.commit()

    by_type = repository.list(session, memory_type=MemoryType.OBSERVATION.value)
    by_status = repository.list(session, status=MemoryStatus.ARCHIVED.value)
    by_asset = repository.list(session, asset_id="asset-1")
    by_facility = repository.list(session, facility_id="facility-1")
    by_source = repository.list(session, source_type="manual")

    assert len(by_type) == 2
    assert len(by_status) == 1
    assert len(by_asset) == 2
    assert len(by_facility) == 2
    assert len(by_source) == 1


def test_update_persists_changes(session, repository):
    memory = make_memory(title="Before update", content="Original")
    repository.create(session, memory)
    session.commit()

    memory.title = "After update"
    memory.content = "Updated content"
    memory.status = MemoryStatus.DISPUTED.value
    memory.memory_metadata = {"updated": True}

    updated = repository.update(session, memory)
    session.commit()

    reloaded = session.get(MemoryRecord, memory.id)
    assert updated.id == memory.id
    assert reloaded is not None
    assert reloaded.title == "After update"
    assert reloaded.content == "Updated content"
    assert reloaded.status == MemoryStatus.DISPUTED.value
    assert reloaded.memory_metadata == {"updated": True}


def test_get_for_update_returns_row_locked_memory(session, repository):
    memory = make_memory(title="Locked record")
    repository.create(session, memory)
    session.commit()

    locked = repository.get_for_update(session, memory.id)

    assert locked is not None
    assert locked.id == memory.id
    assert locked.title == "Locked record"
