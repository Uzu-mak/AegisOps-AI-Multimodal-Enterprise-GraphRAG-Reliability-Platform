"""Helpers for working-memory promotion payload mapping."""
from __future__ import annotations

from typing import Any


def build_promotion_payload(
    *,
    memory_type: str,
    title: str,
    content: str,
    source_type: str,
    asset_id: str | None,
    confidence: float,
    importance: float,
) -> dict[str, Any]:
    """Build public API payload for memory promotion.

    The API contract uses `metadata` externally; service/ORM maps it to
    internal memory_metadata at the boundary.
    """
    return {
        "memory_type": memory_type,
        "title": title,
        "content": content,
        "source_type": source_type,
        "asset_id": asset_id,
        "confidence": confidence,
        "importance": importance,
        "metadata": {"promoted_from": "working_memory"},
    }
