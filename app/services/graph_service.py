"""
GraphProjectionService — orchestrates Neo4j graph projection.

Called by MemoryService AFTER PostgreSQL commit succeeds.
Surfaces failures as GraphProjectionError.
MemoryService is responsible for catching GraphProjectionError and
treating it as non-fatal (PostgreSQL transaction is already committed).
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.db.models.memory import MemoryRecord
from app.graph.index import GraphMemoryIndex, GraphProjectionError

logger = logging.getLogger(__name__)


class GraphProjectionService:
    """
    Orchestrates Neo4j graph projection for canonical memories.

    Owned by MemoryService; called after each successful PostgreSQL commit.
    All public methods raise GraphProjectionError on failure.
    MemoryService decides these failures are non-fatal.
    """

    def __init__(self, graph_index: GraphMemoryIndex) -> None:
        self.graph_index = graph_index

    def project_memory(self, memory: MemoryRecord) -> None:
        """
        Project a newly created or updated memory into Neo4j.
        Raises GraphProjectionError on failure (non-fatal at MemoryService level).
        """
        try:
            self.graph_index.project_memory(memory)
            logger.info(f"Graph projection succeeded for memory {memory.id}")
        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Unexpected error projecting memory {memory.id}: {exc}"
            ) from exc

    def update_memory_status(self, memory: MemoryRecord) -> None:
        """
        Update status in Neo4j after archive/dispute lifecycle transition.
        Raises GraphProjectionError on failure.
        """
        try:
            self.graph_index.update_memory_status(memory)
            logger.info(f"Graph status updated for memory {memory.id} -> {memory.status}")
        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Unexpected error updating status for memory {memory.id}: {exc}"
            ) from exc

    def project_supersession(
        self, old_memory: MemoryRecord, new_memory: MemoryRecord
    ) -> None:
        """
        Project supersession: both memories projected; SUPERSEDES edge created.
        Old Memory node is retained historically in Neo4j.
        Raises GraphProjectionError on failure.
        """
        try:
            self.graph_index.project_supersession(old_memory, new_memory)
            logger.info(
                f"Graph supersession projected: {new_memory.id} SUPERSEDES {old_memory.id}"
            )
        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Unexpected error projecting supersession "
                f"{old_memory.id} -> {new_memory.id}: {exc}"
            ) from exc
