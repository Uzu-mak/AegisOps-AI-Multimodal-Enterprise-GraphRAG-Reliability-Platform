"""
Graph traversal tests.

Tests get_related_memory_ids() discovery, deduplication, limits, and bounds.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from tests.graph.conftest import make_memory


def _track(request, *memories) -> None:
    for m in memories:
        request.node._graph_test_ids.append(str(m.id))


class TestTraversalViaSharedEntity:

    def test_memories_sharing_incident_are_discoverable(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        """Memory A and Memory B sharing an Incident are connected via traversal."""
        incident = "inc-traverse-001"
        mem_a = make_memory(incident_id=incident)
        mem_b = make_memory(incident_id=incident)
        isolated = make_memory()  # unrelated
        _track(request, mem_a, mem_b, isolated)

        graph_index.project_memory(mem_a)
        graph_index.project_memory(mem_b)
        graph_index.project_memory(isolated)

        related = graph_index.get_related_memory_ids(mem_a.id, max_hops=1)
        related_set = {str(uid) for uid in related}

        assert str(mem_b.id) in related_set, "mem_b shares Incident; should be discoverable"
        assert str(isolated.id) not in related_set, "Isolated memory must not appear"

    def test_memories_sharing_asset_are_discoverable(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        asset = "pump-traverse-99"
        mem_a = make_memory(asset_id=asset)
        mem_b = make_memory(asset_id=asset)
        _track(request, mem_a, mem_b)

        graph_index.project_memory(mem_a)
        graph_index.project_memory(mem_b)

        related = graph_index.get_related_memory_ids(mem_a.id, max_hops=1)
        assert mem_b.id in related

    def test_start_memory_excluded_from_results(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        incident = "inc-traverse-self"
        mem_a = make_memory(incident_id=incident)
        mem_b = make_memory(incident_id=incident)
        _track(request, mem_a, mem_b)

        graph_index.project_memory(mem_a)
        graph_index.project_memory(mem_b)

        related = graph_index.get_related_memory_ids(mem_a.id, max_hops=1)
        assert mem_a.id not in related, "Start memory must not appear in results"

    def test_deduplicated_results(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        """Memory B connected via both Asset and Facility — should appear once."""
        asset = "asset-dedup-1"
        facility = "facility-dedup-1"
        mem_a = make_memory(asset_id=asset, facility_id=facility)
        mem_b = make_memory(asset_id=asset, facility_id=facility)
        _track(request, mem_a, mem_b)

        graph_index.project_memory(mem_a)
        graph_index.project_memory(mem_b)

        related = graph_index.get_related_memory_ids(mem_a.id, max_hops=1)
        # Deduplicated: mem_b should appear exactly once
        count = sum(1 for uid in related if uid == mem_b.id)
        assert count == 1

    def test_two_hop_traversal(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        """
        A → incident ← B, B → facility ← C
        With max_hops=2, C should be discoverable from A.
        """
        incident = "inc-twoHop"
        facility = "fac-twoHop"
        mem_a = make_memory(incident_id=incident)
        mem_b = make_memory(incident_id=incident, facility_id=facility)
        mem_c = make_memory(facility_id=facility)
        _track(request, mem_a, mem_b, mem_c)

        for m in [mem_a, mem_b, mem_c]:
            graph_index.project_memory(m)

        related_1hop = graph_index.get_related_memory_ids(mem_a.id, max_hops=1)
        related_2hop = graph_index.get_related_memory_ids(mem_a.id, max_hops=2)

        # mem_b is 1-hop away
        assert mem_b.id in related_1hop
        # mem_c is 2-hops away
        assert mem_c.id in related_2hop

    def test_limit_respected(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        incident = "inc-limit-test"
        memories = [make_memory(incident_id=incident) for _ in range(5)]
        start = memories[0]
        _track(request, *memories)

        for m in memories:
            graph_index.project_memory(m)

        related = graph_index.get_related_memory_ids(start.id, max_hops=1, limit=2)
        assert len(related) <= 2

    def test_max_hops_validation(
        self, graph_index: Neo4jGraphMemoryIndex
    ):
        with pytest.raises(ValueError, match="max_hops"):
            graph_index.get_related_memory_ids(uuid4(), max_hops=0)

        with pytest.raises(ValueError, match="max_hops"):
            graph_index.get_related_memory_ids(uuid4(), max_hops=6)


class TestTraversalViaSupersedes:

    def test_superseded_memory_reachable_via_supersedes_chain(
        self, graph_index: Neo4jGraphMemoryIndex, request
    ):
        old = make_memory()
        new = make_memory()
        old.status = "superseded"
        _track(request, old, new)
        graph_index.project_supersession(old, new)

        related_from_new = graph_index.get_related_memory_ids(new.id, max_hops=1)
        assert old.id in related_from_new

        related_from_old = graph_index.get_related_memory_ids(old.id, max_hops=1)
        assert new.id in related_from_old

    def test_empty_graph_returns_empty_list(
        self, graph_index: Neo4jGraphMemoryIndex
    ):
        """Traversal on a node with no connections returns empty list."""
        lone_memory = make_memory()
        # Not projected — result should be empty
        result = graph_index.get_related_memory_ids(lone_memory.id, max_hops=1)
        assert result == []
