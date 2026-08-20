"""
Graph lifecycle tests.

Tests status transitions, supersession, and historical retention.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models.memory import MemoryStatus
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from tests.graph.conftest import make_memory


def _track(request, *memories) -> None:
    for m in memories:
        request.node._graph_test_ids.append(str(m.id))


def _get_settings():
    from app.core.config import get_settings
    return get_settings()


class TestLifecycleTransitions:

    def test_active_memory_retained_in_graph(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node is not None
        assert node.status == MemoryStatus.ACTIVE.value

    def test_disputed_status_reflected_in_graph(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)

        memory.status = MemoryStatus.DISPUTED.value
        graph_index.update_memory_status(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node.status == MemoryStatus.DISPUTED.value

    def test_archived_status_reflected_in_graph(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)

        memory.status = MemoryStatus.ARCHIVED.value
        graph_index.update_memory_status(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node.status == MemoryStatus.ARCHIVED.value

    def test_archived_memory_node_remains_in_graph(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        """Archived memories must not be deleted from Neo4j."""
        memory = make_memory()
        _track(request, memory)
        graph_index.project_memory(memory)
        memory.status = MemoryStatus.ARCHIVED.value
        graph_index.update_memory_status(memory)

        node = graph_index.get_memory_node(memory.id)
        assert node is not None


class TestSupersession:

    def test_supersedes_relationship_created(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        old = make_memory(asset_id="pump-1")
        new = make_memory(asset_id="pump-1")
        old.status = MemoryStatus.SUPERSEDED.value
        new.supersedes_memory_id = old.id
        _track(request, old, new)
        graph_index.project_supersession(old, new)

        settings = _get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (n:Memory {memory_id: $new_id})-[:SUPERSEDES]->(o:Memory {memory_id: $old_id}) "
                "RETURN count(*) AS n",
                new_id=str(new.id),
                old_id=str(old.id),
            )
        assert result.single()["n"] == 1

    def test_old_memory_node_retained_after_supersession(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        """Old Memory node must NOT be deleted from Neo4j on supersession."""
        old = make_memory()
        new = make_memory()
        old.status = MemoryStatus.SUPERSEDED.value
        _track(request, old, new)
        graph_index.project_supersession(old, new)

        old_node = graph_index.get_memory_node(old.id)
        assert old_node is not None
        assert old_node.status == MemoryStatus.SUPERSEDED.value

    def test_new_memory_node_created_after_supersession(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        old = make_memory()
        new = make_memory()
        old.status = MemoryStatus.SUPERSEDED.value
        _track(request, old, new)
        graph_index.project_supersession(old, new)

        new_node = graph_index.get_memory_node(new.id)
        assert new_node is not None
        assert new_node.status == MemoryStatus.ACTIVE.value

    def test_duplicate_supersession_projection_does_not_duplicate_edge(
        self, graph_index: Neo4jGraphMemoryIndex, neo4j_driver, request
    ):
        """Repeated supersession projection must not create duplicate SUPERSEDES edges."""
        old = make_memory()
        new = make_memory()
        old.status = MemoryStatus.SUPERSEDED.value
        _track(request, old, new)
        graph_index.project_supersession(old, new)
        graph_index.project_supersession(old, new)

        settings = _get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (n:Memory {memory_id: $new_id})-[r:SUPERSEDES]->(o:Memory {memory_id: $old_id}) "
                "RETURN count(r) AS n",
                new_id=str(new.id),
                old_id=str(old.id),
            )
        assert result.single()["n"] == 1

    def test_superseded_status_updated_on_old_node(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        old = make_memory()
        new = make_memory()
        old.status = MemoryStatus.SUPERSEDED.value
        _track(request, old, new)
        graph_index.project_supersession(old, new)

        node = graph_index.get_memory_node(old.id)
        assert node.status == MemoryStatus.SUPERSEDED.value
