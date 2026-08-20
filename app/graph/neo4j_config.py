"""Neo4j collection configuration constants and utility functions."""
from __future__ import annotations

from typing import Optional

# Relationship types owned by this projection layer.
# Only these relationships are cleared+rebuilt on re-projection.
# SUPERSEDES is managed separately and is NOT in this list.
OWNED_RELATIONSHIP_TYPES = (
    "ABOUT_ASSET",
    "ABOUT_COMPONENT",
    "PART_OF_INCIDENT",
    "OBSERVED_AT",
    "SOURCED_FROM",
    "BELONGS_TO_TEAM",
)

# Pipe-separated string used in Cypher for multi-type relationship patterns.
OWNED_REL_PATTERN = "|".join(OWNED_RELATIONSHIP_TYPES)

# Constraints to bootstrap on startup.
UNIQUENESS_CONSTRAINTS = [
    ("Memory", "memory_id"),
    ("Asset", "entity_key"),
    ("Component", "entity_key"),
    ("Incident", "entity_key"),
    ("Facility", "entity_key"),
    ("Source", "entity_key"),
    ("Team", "entity_key"),
]


def entity_key(tenant_id: Optional[str], entity_type: str, external_id: str) -> str:
    """
    Build a deterministic, tenant-scoped entity key.

    External IDs such as 'robot-17' may collide across tenants, so we
    namespace them:  '{tenant_id}:{entity_type}:{external_id}'

    If tenant_id is absent the namespace is 'global'.

    Examples:
        entity_key("tenant-a", "asset", "robot-17") -> "tenant-a:asset:robot-17"
        entity_key(None,       "asset", "robot-17") -> "global:asset:robot-17"
    """
    ns = tenant_id or "global"
    return f"{ns}:{entity_type}:{external_id}"


def source_key(
    tenant_id: Optional[str],
    source_type: str,
    source_id: Optional[str],
) -> str:
    """
    Build a deterministic source entity key.

    Uses both source_type and source_id when source_id is present;
    falls back to source_type alone so we never generate a random key.

    Examples:
        source_key("t1", "sensor", "s-99")  -> "t1:source:sensor:s-99"
        source_key("t1", "sensor", None)    -> "t1:source:sensor"
        source_key(None, "manual", None)    -> "global:source:manual"
    """
    ns = tenant_id or "global"
    if source_id:
        return f"{ns}:source:{source_type}:{source_id}"
    return f"{ns}:source:{source_type}"
