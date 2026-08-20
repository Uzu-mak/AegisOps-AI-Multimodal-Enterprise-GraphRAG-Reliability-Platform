"""
Graph memory index interface and domain types.

PostgreSQL is canonical. Neo4j is a derived graph projection.
Full memory content is never stored as authoritative state in Neo4j.
All traversal results return canonical PostgreSQL memory UUIDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol
from uuid import UUID


class GraphProjectionError(Exception):
    """Raised when graph projection or traversal fails."""


@dataclass
class MemoryNode:
    """
    Minimal traversal metadata stored on a Neo4j Memory node.

    NOT a substitute for the canonical PostgreSQL MemoryRecord.
    Retrieve full memory content from PostgreSQL by memory_id.
    """

    memory_id: UUID
    memory_type: str
    status: str
    tenant_id: Optional[str]


class GraphMemoryIndex(Protocol):
    """
    Protocol for graph-based memory projection.

    Implementations project MemoryRecord data into a graph store as
    deterministic relationship nodes. PostgreSQL remains the canonical
    source of truth; the graph is a derived projection.
    """

    def bootstrap_constraints(self) -> None:
        """
        Create uniqueness constraints using IF NOT EXISTS.
        Safe to call multiple times.

        Raises:
            GraphProjectionError: If constraint creation fails.
        """
        ...

    def project_memory(self, memory) -> None:
        """
        Create or update the graph projection for a single MemoryRecord.

        - Merges a Memory node keyed on memory_id.
        - Removes stale owned relationships (ABOUT_ASSET, ABOUT_COMPONENT,
          PART_OF_INCIDENT, OBSERVED_AT, SOURCED_FROM, BELONGS_TO_TEAM).
        - Recreates relationships from current canonical field values.
        - Only creates entity nodes when the corresponding field is non-None.
        - Idempotent: repeated projection does not duplicate nodes/relationships.

        Raises:
            GraphProjectionError: If projection fails.
        """
        ...

    def project_supersession(self, old_memory, new_memory) -> None:
        """
        Record the supersession relationship in the graph.

        - Projects both old and new Memory nodes.
        - Creates (new)-[:SUPERSEDES]->(old).
        - Old Memory node is retained in Neo4j (historical record).
        - Idempotent: repeated projection does not duplicate SUPERSEDES edge.

        Raises:
            GraphProjectionError: If projection fails.
        """
        ...

    def update_memory_status(self, memory) -> None:
        """
        Update the status property of an existing Memory node.

        Called for archive/dispute lifecycle transitions.
        Does not touch relationships.

        Raises:
            GraphProjectionError: If update fails.
        """
        ...

    def get_memory_node(self, memory_id: UUID) -> Optional[MemoryNode]:
        """
        Retrieve the minimal graph metadata for a memory.

        Returns None if the memory is not in the graph.
        Full content must be fetched from PostgreSQL.

        Raises:
            GraphProjectionError: If retrieval fails.
        """
        ...

    def get_related_memory_ids(
        self,
        memory_id: UUID,
        max_hops: int = 2,
        limit: int = 50,
    ) -> list[UUID]:
        """
        Traverse the graph to find canonically related memory UUIDs.

        Traversal follows approved Phase 3 relationships:
            ABOUT_ASSET, ABOUT_COMPONENT, PART_OF_INCIDENT,
            OBSERVED_AT, SOURCED_FROM, BELONGS_TO_TEAM, SUPERSEDES

        Returns canonical PostgreSQL memory UUIDs — NOT full memory content.
        Callers must fetch content from PostgreSQL.

        Args:
            memory_id: Starting memory UUID.
            max_hops: Maximum number of memory-to-memory hops (1–5).
            limit: Maximum number of results.

        Raises:
            GraphProjectionError: If traversal fails.
            ValueError: If max_hops is out of range.
        """
        ...
