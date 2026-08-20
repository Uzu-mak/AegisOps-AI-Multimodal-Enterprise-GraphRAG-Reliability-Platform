"""Shared fixtures and helpers for graph tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from neo4j import Driver, GraphDatabase

from app.core.config import get_settings
from app.db.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex


def make_memory(
    *,
    memory_id=None,
    memory_type: str = MemoryType.OBSERVATION.value,
    status: str = MemoryStatus.ACTIVE.value,
    title: str = "Test memory",
    content: str = "Test content",
    source_type: str = "sensor",
    asset_id: str | None = None,
    component_id: str | None = None,
    incident_id: str | None = None,
    facility_id: str | None = None,
    source_id: str | None = None,
    team_id: str | None = None,
    tenant_id: str | None = "tenant-test",
) -> MemoryRecord:
    """Build a minimal MemoryRecord for graph tests (not persisted to DB)."""
    m = MemoryRecord()
    m.id = memory_id or uuid4()
    m.memory_type = memory_type
    m.status = status
    m.title = title
    m.content = content
    m.source_type = source_type
    m.source_id = source_id
    m.asset_id = asset_id
    m.component_id = component_id
    m.incident_id = incident_id
    m.facility_id = facility_id
    m.team_id = team_id
    m.tenant_id = tenant_id
    m.confidence = 0.8
    m.importance = 0.7
    m.is_synthetic = False
    m.access_roles = []
    m.memory_metadata = {}
    m.supersedes_memory_id = None
    m.created_at = datetime.now(timezone.utc)
    m.observed_at = None
    return m


@pytest.fixture(scope="session")
def neo4j_driver() -> Driver:
    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def graph_index(neo4j_driver: Driver) -> Neo4jGraphMemoryIndex:
    settings = get_settings()
    index = Neo4jGraphMemoryIndex(driver=neo4j_driver, database=settings.NEO4J_DATABASE)
    index.bootstrap_constraints()
    return index


@pytest.fixture(autouse=True)
def cleanup_test_memories(neo4j_driver: Driver, request):
    """
    Delete Memory nodes (and orphaned entity nodes) created during a test.
    Uses a session-scoped list populated by the test itself.
    """
    # Each test can mark memory IDs via the _graph_test_ids list
    test_memory_ids: list[str] = []
    request.node._graph_test_ids = test_memory_ids
    yield
    if test_memory_ids:
        settings = get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            session.run(
                "MATCH (m:Memory) WHERE m.memory_id IN $ids DETACH DELETE m",
                ids=test_memory_ids,
            )
