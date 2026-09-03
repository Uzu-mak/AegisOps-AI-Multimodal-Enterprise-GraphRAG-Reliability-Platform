from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _first_non_empty(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def normalize_incident_triage_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a UI-friendly view over the search result payload.

    The search route currently returns a flat result shape, but this helper also
    tolerates nested canonical payloads so the page keeps rendering if the
    backend response evolves.
    """

    canonical = _as_mapping(result.get("canonical_record"))
    record = _as_mapping(result.get("record"))
    payload = _as_mapping(result.get("payload"))

    sources = (result, canonical, record, payload)

    def pick(*keys: str) -> Any:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return None

    asset_id = pick("asset_id", "assetId")
    component_id = pick("component_id", "componentId", "equipment_id", "equipmentId")
    facility_id = pick("facility_id", "facilityId")
    context_parts = []
    if asset_id:
        context_parts.append(f"Asset: {asset_id}")
    if component_id:
        context_parts.append(f"Equipment: {component_id}")
    if facility_id and not context_parts:
        context_parts.append(f"Facility: {facility_id}")

    content_preview = _first_non_empty(
        pick("content_preview", "contentPreview"),
        pick("content", "body"),
        default="",
    )

    return {
        "memory_id": pick("memory_id", "memoryId"),
        "title": _first_non_empty(pick("title", "name"), default="Untitled memory"),
        "memory_type": _first_non_empty(pick("memory_type", "memoryType"), default="unknown"),
        "status": pick("status", "lifecycle_status", "lifecycleStatus"),
        "confidence": pick("confidence"),
        "asset_id": asset_id,
        "component_id": component_id,
        "facility_id": facility_id,
        "context_label": " · ".join(context_parts),
        "content_preview": content_preview,
        "retrieval_source": pick("retrieval_source", "retrievalSource"),
        "semantic_score": pick("semantic_score", "semanticScore"),
        "graph_path": pick("graph_path", "graphPath"),
    }


def format_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.0%}"
    return "—"
