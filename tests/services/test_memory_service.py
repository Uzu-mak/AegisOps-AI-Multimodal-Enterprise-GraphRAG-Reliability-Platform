from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.db.session import SessionLocal
from app.repositories.memory_repository import SQLAlchemyMemoryRepository
from app.services.exceptions import (
    InvalidLifecycleTransitionError,
    InvalidMemoryDataError,
    MemoryNotFoundError,
)
from app.services.memory_service import MemoryCreateData, MemoryService


@pytest.fixture(autouse=True)
def clean_memories():
    with SessionLocal() as session:
        session.execute(delete(MemoryRecord))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(MemoryRecord))
        session.commit()


@pytest.fixture
def service() -> MemoryService:
    return MemoryService(
        repository=SQLAlchemyMemoryRepository(),
        session_factory=SessionLocal,
    )


def make_data(**overrides) -> MemoryCreateData:
    data = MemoryCreateData(
        memory_type=MemoryType.OBSERVATION.value,
        title="Observation title",
        content="Observation content",
        source_type="sensor",
        asset_id="asset-123",
        facility_id="facility-1",
        component_id="component-1",
        incident_id="incident-1",
        source_id="source-1",
        observed_at=None,
        confidence=0.92,
        importance=0.81,
        is_synthetic=False,
        tenant_id="tenant-1",
        team_id="team-1",
        access_roles=["ops", "eng"],
        memory_metadata={"source": "ingest", "value": 7},
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    return data


def test_create_memory_persists_record(service):
    record = service.create_memory(data=make_data())

    assert record.id is not None
    assert record.status == MemoryStatus.ACTIVE.value
    assert record.title == "Observation title"
    assert record.memory_metadata == {"source": "ingest", "value": 7}


def test_get_memory_raises_not_found_for_missing_record(service):
    with pytest.raises(MemoryNotFoundError):
        service.get_memory(uuid4())


def test_archive_memory_moves_active_to_archived(service):
    record = service.create_memory(data=make_data(title="Archive me"))

    archived = service.archive_memory(record.id)

    assert archived.status == MemoryStatus.ARCHIVED.value
    assert archived.id == record.id


def test_rejects_blank_required_fields(service):
    with pytest.raises(InvalidMemoryDataError):
        service.create_memory(data=make_data(title=""))

    with pytest.raises(InvalidMemoryDataError):
        service.create_memory(data=make_data(content=""))

    with pytest.raises(InvalidMemoryDataError):
        service.create_memory(data=make_data(source_type=""))


def test_supersede_memory_creates_linked_successor(service):
    original = service.create_memory(data=make_data(title="Original memory"))

    successor = service.supersede_memory(
        original.id,
        make_data(title="Replacement memory", source_type="manual"),
    )

    old_record, new_record = successor
    assert old_record.status == MemoryStatus.SUPERSEDED.value
    assert new_record.status == MemoryStatus.ACTIVE.value
    assert new_record.supersedes_memory_id == old_record.id
    assert new_record.id != old_record.id


def test_supersede_memory_rolls_back_on_invalid_replacement(service):
    original = service.create_memory(data=make_data(title="Original memory"))

    with pytest.raises(InvalidMemoryDataError):
        service.supersede_memory(
            original.id,
            make_data(title="", source_type="manual"),
        )

    reloaded = service.get_memory(original.id)
    assert reloaded.status == MemoryStatus.ACTIVE.value


def test_supersede_memory_rejects_nonexistent_old_record(service):
    with pytest.raises(MemoryNotFoundError):
        service.supersede_memory(
            uuid4(),
            make_data(title="Replacement"),
        )


def test_archive_rejects_invalid_transition(service):
    original = service.create_memory(data=make_data(title="Original memory"))
    _, _ = service.supersede_memory(
        original.id,
        make_data(title="Replacement memory"),
    )

    with pytest.raises(InvalidLifecycleTransitionError):
        service.archive_memory(original.id)
