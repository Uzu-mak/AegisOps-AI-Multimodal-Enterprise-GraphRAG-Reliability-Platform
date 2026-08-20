"""
Neo4j implementation of GraphMemoryIndex.

Architecture:
- All writes use MERGE to guarantee idempotency.
- project_memory() first removes stale owned relationships, then recreates
  them from the current canonical MemoryRecord. This ensures graph state
  mirrors PostgreSQL (e.g. asset_id changed: stale edge removed, new one
  created).
- SUPERSEDES is managed separately and is never cleared by project_memory().
- Entity nodes (Asset, Component, etc.) are only created when the
  corresponding MemoryRecord field is non-None.
- Entity identity is tenant-scoped via a deterministic entity_key.
- All traversal results are canonical PostgreSQL memory UUIDs.
  Full content must be fetched from PostgreSQL.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from neo4j import Driver, GraphDatabase

from app.db.models.memory import MemoryRecord
from app.graph.index import GraphMemoryIndex, GraphProjectionError, MemoryNode
from app.graph.neo4j_config import (
    OWNED_REL_PATTERN,
    UNIQUENESS_CONSTRAINTS,
    entity_key,
    source_key,
)

logger = logging.getLogger(__name__)

# Maximum supported max_hops value (keep traversal bounded).
_MAX_HOPS_LIMIT = 5


class Neo4jGraphMemoryIndex(GraphMemoryIndex):
    """Neo4j-backed graph memory index."""

    def __init__(self, driver: Driver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap_constraints(self) -> None:
        """Create uniqueness constraints. Safe to run repeatedly."""
        try:
            with self._driver.session(database=self._database) as session:
                for label, prop in UNIQUENESS_CONSTRAINTS:
                    constraint_name = f"unique_{label.lower()}_{prop}"
                    session.run(
                        f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                    )
            logger.info("Neo4j constraints bootstrapped")
        except Exception as exc:
            raise GraphProjectionError(
                f"Failed to bootstrap Neo4j constraints: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def project_memory(self, memory: MemoryRecord) -> None:
        """
        Idempotently project a MemoryRecord into Neo4j.

        Steps inside a single write transaction:
        1. MERGE Memory node; SET current scalar properties.
        2. DELETE owned relationship types (reconcile stale edges).
        3. Conditionally MERGE entity nodes and relationships.
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.execute_write(self._project_memory_tx, memory)
            logger.debug(f"Projected memory {memory.id} to Neo4j")
        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Failed to project memory {memory.id}: {exc}"
            ) from exc

    def _project_memory_tx(self, tx, memory: MemoryRecord) -> None:
        """Single-transaction projection of one MemoryRecord."""
        memory_id_str = str(memory.id)

        # 1. Merge Memory node; set current properties.
        tx.run(
            """
            MERGE (m:Memory {memory_id: $memory_id})
            SET m.memory_type  = $memory_type,
                m.status       = $status,
                m.tenant_id    = $tenant_id,
                m.created_at   = $created_at,
                m.observed_at  = $observed_at
            """,
            memory_id=memory_id_str,
            memory_type=str(memory.memory_type),
            status=str(memory.status),
            tenant_id=memory.tenant_id,
            created_at=memory.created_at.isoformat() if memory.created_at else None,
            observed_at=memory.observed_at.isoformat() if memory.observed_at else None,
        )

        # 2. Remove stale owned relationships (not SUPERSEDES).
        tx.run(
            f"""
            MATCH (m:Memory {{memory_id: $memory_id}})
            OPTIONAL MATCH (m)-[r:{OWNED_REL_PATTERN}]->()
            DELETE r
            """,
            memory_id=memory_id_str,
        )

        # 3. Recreate relationships from current canonical values.
        tenant = memory.tenant_id

        if memory.asset_id:
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Asset {entity_key: $key})
                  ON CREATE SET e.external_id = $ext_id, e.tenant_id = $tenant_id
                MERGE (m)-[:ABOUT_ASSET]->(e)
                """,
                memory_id=memory_id_str,
                key=entity_key(tenant, "asset", memory.asset_id),
                ext_id=memory.asset_id,
                tenant_id=tenant,
            )

        if memory.component_id:
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Component {entity_key: $key})
                  ON CREATE SET e.external_id = $ext_id, e.tenant_id = $tenant_id
                MERGE (m)-[:ABOUT_COMPONENT]->(e)
                """,
                memory_id=memory_id_str,
                key=entity_key(tenant, "component", memory.component_id),
                ext_id=memory.component_id,
                tenant_id=tenant,
            )

        if memory.incident_id:
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Incident {entity_key: $key})
                  ON CREATE SET e.external_id = $ext_id, e.tenant_id = $tenant_id
                MERGE (m)-[:PART_OF_INCIDENT]->(e)
                """,
                memory_id=memory_id_str,
                key=entity_key(tenant, "incident", memory.incident_id),
                ext_id=memory.incident_id,
                tenant_id=tenant,
            )

        if memory.facility_id:
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Facility {entity_key: $key})
                  ON CREATE SET e.external_id = $ext_id, e.tenant_id = $tenant_id
                MERGE (m)-[:OBSERVED_AT]->(e)
                """,
                memory_id=memory_id_str,
                key=entity_key(tenant, "facility", memory.facility_id),
                ext_id=memory.facility_id,
                tenant_id=tenant,
            )

        if memory.source_type:
            src_key = source_key(tenant, memory.source_type, memory.source_id)
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Source {entity_key: $key})
                  ON CREATE SET e.source_type = $source_type,
                                e.source_id   = $source_id,
                                e.tenant_id   = $tenant_id
                MERGE (m)-[:SOURCED_FROM]->(e)
                """,
                memory_id=memory_id_str,
                key=src_key,
                source_type=memory.source_type,
                source_id=memory.source_id,
                tenant_id=tenant,
            )

        if memory.team_id:
            tx.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})
                MERGE (e:Team {entity_key: $key})
                  ON CREATE SET e.external_id = $ext_id, e.tenant_id = $tenant_id
                MERGE (m)-[:BELONGS_TO_TEAM]->(e)
                """,
                memory_id=memory_id_str,
                key=entity_key(tenant, "team", memory.team_id),
                ext_id=memory.team_id,
                tenant_id=tenant,
            )

    def project_supersession(
        self, old_memory: MemoryRecord, new_memory: MemoryRecord
    ) -> None:
        """
        Project supersession: both memories are projected; a SUPERSEDES edge
        is created from new to old. Old Memory node is retained historically.
        """
        try:
            with self._driver.session(database=self._database) as session:
                session.execute_write(self._project_supersession_tx, old_memory, new_memory)
            logger.debug(
                f"Projected supersession: {new_memory.id} SUPERSEDES {old_memory.id}"
            )
        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Failed to project supersession {old_memory.id} -> {new_memory.id}: {exc}"
            ) from exc

    def _project_supersession_tx(
        self, tx, old_memory: MemoryRecord, new_memory: MemoryRecord
    ) -> None:
        # Project both memories first.
        self._project_memory_tx(tx, new_memory)
        self._project_memory_tx(tx, old_memory)

        # Create SUPERSEDES (idempotent via MERGE).
        tx.run(
            """
            MATCH (old:Memory {memory_id: $old_id})
            MATCH (new:Memory {memory_id: $new_id})
            MERGE (new)-[:SUPERSEDES]->(old)
            """,
            old_id=str(old_memory.id),
            new_id=str(new_memory.id),
        )

    def update_memory_status(self, memory: MemoryRecord) -> None:
        """Update the status property on an existing Memory node."""
        try:
            with self._driver.session(database=self._database) as session:
                session.run(
                    """
                    MERGE (m:Memory {memory_id: $memory_id})
                    SET m.status = $status
                    """,
                    memory_id=str(memory.id),
                    status=str(memory.status),
                )
            logger.debug(f"Updated status of memory {memory.id} to {memory.status}")
        except Exception as exc:
            raise GraphProjectionError(
                f"Failed to update status for memory {memory.id}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_memory_node(self, memory_id: UUID) -> Optional[MemoryNode]:
        """
        Return minimal graph metadata for a memory.
        Returns None if not projected. Full content comes from PostgreSQL.
        """
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    """
                    MATCH (m:Memory {memory_id: $memory_id})
                    RETURN m.memory_id  AS memory_id,
                           m.memory_type AS memory_type,
                           m.status      AS status,
                           m.tenant_id   AS tenant_id
                    """,
                    memory_id=str(memory_id),
                )
                record = result.single()
                if record is None:
                    return None
                return MemoryNode(
                    memory_id=UUID(record["memory_id"]),
                    memory_type=record["memory_type"],
                    status=record["status"],
                    tenant_id=record["tenant_id"],
                )
        except Exception as exc:
            raise GraphProjectionError(
                f"Failed to retrieve memory node {memory_id}: {exc}"
            ) from exc

    def get_related_memory_ids(
        self,
        memory_id: UUID,
        max_hops: int = 2,
        limit: int = 50,
    ) -> list[UUID]:
        """
        Traverse the graph to find related memory UUIDs.

        Two independent traversal strategies are combined:
        1. Entity-mediated hops: Memory → Entity ← Memory (and deeper).
           max_hops controls how many Memory-to-Memory transitions are allowed.
        2. SUPERSEDES chain: bidirectional traversal up to max_hops deep.

        Returns canonical PostgreSQL memory UUIDs sorted for deterministic output.
        Full memory content must be fetched from PostgreSQL.

        The Cypher path-length integer is computed from validated max_hops and
        inserted via f-string (safe: value is a validated integer, never user
        string data).
        """
        if not 1 <= max_hops <= _MAX_HOPS_LIMIT:
            raise ValueError(
                f"max_hops must be between 1 and {_MAX_HOPS_LIMIT}, got {max_hops}"
            )
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")

        start_id = str(memory_id)
        # Each "memory hop" traverses 2 relationship steps: M→Entity←M
        entity_path_len = max_hops * 2

        try:
            with self._driver.session(database=self._database) as session:
                # --- Strategy 1: entity-mediated hops ---
                # The path length integer is validated above; f-string here is safe.
                entity_result = session.run(
                    f"""
                    MATCH (start:Memory {{memory_id: $start_id}})
                    MATCH (start)-[:{OWNED_REL_PATTERN}*1..{entity_path_len}]-(related:Memory)
                    WHERE related.memory_id <> $start_id
                    RETURN DISTINCT related.memory_id AS memory_id
                    ORDER BY memory_id
                    LIMIT $limit
                    """,
                    start_id=start_id,
                    limit=limit,
                )
                entity_ids = {row["memory_id"] for row in entity_result}

                # --- Strategy 2: SUPERSEDES chain ---
                supersedes_result = session.run(
                    f"""
                    MATCH (start:Memory {{memory_id: $start_id}})
                    MATCH (start)-[:SUPERSEDES*1..{max_hops}]-(related:Memory)
                    WHERE related.memory_id <> $start_id
                    RETURN DISTINCT related.memory_id AS memory_id
                    ORDER BY memory_id
                    LIMIT $limit
                    """,
                    start_id=start_id,
                    limit=limit,
                )
                supersedes_ids = {row["memory_id"] for row in supersedes_result}

            combined = entity_ids | supersedes_ids
            combined.discard(start_id)
            return sorted(UUID(uid) for uid in combined)[:limit]

        except GraphProjectionError:
            raise
        except Exception as exc:
            raise GraphProjectionError(
                f"Traversal failed for memory {memory_id}: {exc}"
            ) from exc
