"""
Graph projection tests.

Tests node creation, relationship creation, optional-field behavior,
and idempotency.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from tests.graph.conftest import make_memory


def _track(request, *memories) -> None:
    """Register memory IDs for cleanup after the test."""
    for m in memories:
        request.node._graph_test_ids.append(str(m.id))


class TestMemoryNodeCreation:

    def test_memory_node_created(self, graph_index: Neo4jGraphMemoryIndex, request):
        memory = make_memory(asset_id="robot-1")
        _track(request, memory)
        graph_index.project_memory(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node is not None
        assert node.memory_id == memory.id

    def test_memory_node_has_correct_type(self, graph_index: Neo4jGraphMemoryIndex, request):
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node.memory_type == memory.memory_type

    def test_memory_node_has_correct_status(self, graph_index: Neo4jGraphMemoryIndex, request):
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node.status == memory.status

    def test_get_memory_node_returns_none_for_unknown(self, graph_index: Neo4jGraphMemoryIndex):
        result = graph_index.get_memory_node(uuid4())
        assert result is None


class TestRelationshipCreation:

    def test_asset_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(asset_id="pump-42")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:ABOUT_ASSET]->(a:Asset) "
                "RETURN a.external_id AS ext_id",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["ext_id"] == "pump-42"

    def test_component_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(component_id="bearing-7")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:ABOUT_COMPONENT]->(c:Component) "
                "RETURN c.external_id AS ext_id",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["ext_id"] == "bearing-7"

    def test_incident_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(incident_id="inc-001")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:PART_OF_INCIDENT]->(i:Incident) "
                "RETURN i.external_id AS ext_id",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["ext_id"] == "inc-001"

    def test_facility_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(facility_id="plant-west")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:OBSERVED_AT]->(f:Facility) "
                "RETURN f.external_id AS ext_id",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["ext_id"] == "plant-west"

    def test_source_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(source_id="sensor-99")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:SOURCED_FROM]->(s:Source) "
                "RETURN s.source_type AS stype",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["stype"] == "sensor"

    def test_team_relationship(self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request):
        memory = make_memory(team_id="ops-team")
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:BELONGS_TO_TEAM]->(t:Team) "
                "RETURN t.external_id AS ext_id",
                id=str(memory.id),
            )
            record = result.single()
        assert record is not None
        assert record["ext_id"] == "ops-team"


class TestOptionalRelationships:

    def test_no_asset_node_when_asset_id_is_none(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        """asset_id=None must NOT create a fake Asset node."""
        memory = make_memory(asset_id=None)
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:ABOUT_ASSET]->() RETURN count(*) AS n",
                id=str(memory.id),
            )
        assert result.single()["n"] == 0

    def test_no_incident_node_when_incident_id_is_none(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        memory = make_memory(incident_id=None)
        _track(request, memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:PART_OF_INCIDENT]->() RETURN count(*) AS n",
                id=str(memory.id),
            )
        assert result.single()["n"] == 0


class TestIdempotency:

    def test_double_projection_creates_one_node(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        memory = make_memory(asset_id="fan-1")
        _track(request, memory)
        graph_index.project_memory(memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id}) RETURN count(m) AS n",
                id=str(memory.id),
            )
        assert result.single()["n"] == 1

    def test_double_projection_creates_one_relationship(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        memory = make_memory(asset_id="fan-2")
        _track(request, memory)
        graph_index.project_memory(memory)
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[r:ABOUT_ASSET]->() RETURN count(r) AS n",
                id=str(memory.id),
            )
        assert result.single()["n"] == 1


class TestUpdateReconciliation:

    def test_stale_asset_edge_removed_on_update(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        """Original asset_id=robot-17; updated to robot-19 → stale edge removed."""
        memory = make_memory(asset_id="robot-17")
        _track(request, memory)
        graph_index.project_memory(memory)

        # Update canonical field
        memory.asset_id = "robot-19"
        graph_index.project_memory(memory)

        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (m:Memory {memory_id: $id})-[:ABOUT_ASSET]->(a:Asset) "
                "RETURN a.external_id AS ext_id ORDER BY ext_id",
                id=str(memory.id),
            )
            assets = [r["ext_id"] for r in result]

        assert "robot-17" not in assets, "Stale edge to robot-17 should be removed"
        assert "robot-19" in assets, "New edge to robot-19 should exist"
        assert len(assets) == 1, "Exactly one ABOUT_ASSET relationship expected"
