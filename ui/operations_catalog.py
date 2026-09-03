from __future__ import annotations

import re
from collections import Counter
from collections import defaultdict
from typing import Any, Callable

from ui.api_client import api_get


MemoryRecord = dict[str, Any]


MEMORY_TYPE_LABELS = {
    "observation": "Observation",
    "incident": "Incident",
    "diagnosis": "Finding",
    "maintenance_action": "Maintenance Action",
    "resolution": "Resolution",
    "recommendation": "Recommendation",
    "document_fact": "Finding",
    "agent_interaction": "Interaction",
    "feedback": "Feedback",
}


STATUS_LABELS = {
    "active": "Active",
    "archived": "Archived",
    "disputed": "Disputed",
    "superseded": "Superseded",
    "pending": "Pending",
    "failed": "Failed",
    "healthy": "Healthy",
    "degraded": "Degraded",
}


_PLACEHOLDER_VALUES = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "{}",
    "[]",
}


PLACEHOLDER_DEFAULT_VALUES = {"string", "null", "none", "n/a", "na"}


def _as_clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in _PLACEHOLDER_VALUES:
        return ""
    if lowered.startswith("string(") or lowered.startswith("varchar("):
        return ""
    if lowered.startswith("<class ") or lowered.endswith("object at 0x"):
        return ""
    return text


def _hyphenate_alpha_numeric(token: str) -> str:
    match = re.fullmatch(r"([A-Za-z]+)[-_]?(\d+)", token)
    if not match:
        return token
    prefix, digits = match.groups()
    return f"{prefix.upper()}-{digits}"


def identifier_title(value: Any) -> str:
    text = _as_clean_text(value)
    if not text:
        return ""
    parts = [p for p in re.split(r"[-_\s]+", text) if p]
    out: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if i + 1 < len(parts) and re.fullmatch(r"[A-Za-z]+", part) and parts[i + 1].isdigit():
            out.append(f"{part.upper()}-{parts[i + 1]}")
            i += 2
            continue
        converted = _hyphenate_alpha_numeric(part)
        if converted != part:
            out.append(converted)
        elif part.isdigit():
            out.append(part)
        else:
            out.append(part.capitalize())
        i += 1
    return " ".join(out)


def humanize_identifier(value: Any) -> str:
    return identifier_title(value)


def load_memory_records(limit: int = 500) -> list[MemoryRecord]:
    return load_memory_records_filtered(limit=limit)


def load_memory_records_filtered(limit: int = 500, status: str | None = None) -> list[MemoryRecord]:
    params: dict[str, Any] = {"limit": limit, "offset": 0}
    if status:
        params["status"] = status
    response = api_get("/api/v1/memories", params=params)
    if isinstance(response, dict):
        items = response.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def has_placeholder_defaults(record: MemoryRecord) -> bool:
    for key in [
        "title",
        "content",
        "asset_id",
        "facility_id",
        "component_id",
        "incident_id",
        "source_type",
    ]:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_DEFAULT_VALUES:
            return True
    return False


def placeholder_fields(record: MemoryRecord) -> list[str]:
    fields: list[str] = []
    for key in [
        "title",
        "content",
        "asset_id",
        "facility_id",
        "component_id",
        "incident_id",
        "source_type",
    ]:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_DEFAULT_VALUES:
            fields.append(key)
    return fields


def format_memory_type(memory_type: Any) -> str:
    return MEMORY_TYPE_LABELS.get(str(memory_type or "").lower(), humanize_identifier(memory_type) or "Unknown")


def format_status(status: Any) -> str:
    status_key = str(status or "unknown").lower()
    return STATUS_LABELS.get(status_key, humanize_identifier(status_key) or "Unknown")


def _unique_options(
    records: list[MemoryRecord],
    value_key: str,
    label_builder: Callable[[MemoryRecord, Any, int], str],
) -> list[dict[str, Any]]:
    counts = Counter(
        record.get(value_key)
        for record in records
        if record.get(value_key) not in (None, "")
    )
    options: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for record in records:
        value = record.get(value_key)
        if value in (None, "") or value in seen:
            continue
        label = label_builder(record, value, counts[value]).strip()
        if not label:
            continue
        seen.add(value)
        options.append(
            {
                "label": label,
                "value": value,
                "record": record,
            }
        )
    return options


def build_facility_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    return _unique_options(
        records,
        "facility_id",
        lambda record, value, count: (
            f"{identifier_title(value)} ({count})" if identifier_title(value) and count > 1 else identifier_title(value)
        ),
    )


def build_area_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    return _unique_options(
        records,
        "component_id",
        lambda record, value, count: (
            f"{identifier_title(value)} ({count})" if identifier_title(value) and count > 1 else identifier_title(value)
        ),
    )


def build_equipment_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    return _unique_options(
        records,
        "asset_id",
        lambda record, value, count: _equipment_label(record, value),
    )


def build_incident_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    grouped: dict[Any, list[MemoryRecord]] = defaultdict(list)
    for record in records:
        incident_id = record.get("incident_id")
        if incident_id in (None, ""):
            continue
        grouped[incident_id].append(record)

    options: list[dict[str, Any]] = []
    for incident_id, group_records in grouped.items():
        preferred_record = next(
            (record for record in group_records if str(record.get("memory_type", "")).lower() == "incident"),
            group_records[0],
        )
        label = _incident_label(preferred_record, incident_id)
        if not label:
            continue
        options.append(
            {
                "label": label,
                "value": incident_id,
                "record": preferred_record,
            }
        )
    return options


def _equipment_display_metadata_name(record: MemoryRecord) -> str:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    candidates = [
        record.get("display_name"),
        record.get("equipment_name"),
        record.get("asset_name"),
        metadata.get("display_name"),
        metadata.get("equipment_name"),
        metadata.get("asset_name"),
    ]
    for candidate in candidates:
        clean = _as_clean_text(candidate)
        if clean:
            return clean
    return ""


def _equipment_label(record: MemoryRecord, value: Any) -> str:
    display_name = _equipment_display_metadata_name(record)
    if display_name:
        return display_name
    return identifier_title(value)


def _incident_label(record: MemoryRecord, value: Any) -> str:
    incident_id = _as_clean_text(value)
    raw_title = _as_clean_text(record.get("title"))
    if raw_title:
        base = raw_title.replace(" - ", " --- ").replace("---", "—")
    elif incident_id:
        id_text = incident_id.removeprefix("inc-")
        base = f"Incident {id_text}" if id_text else "Incident"
    else:
        base = ""
    return base


def filter_records_by_context(
    records: list[MemoryRecord],
    *,
    facility_id: Any | None = None,
    area_id: Any | None = None,
    equipment_id: Any | None = None,
    incident_id: Any | None = None,
) -> list[MemoryRecord]:
    filtered = list(records)
    if facility_id not in (None, ""):
        filtered = [record for record in filtered if record.get("facility_id") == facility_id]
    if area_id not in (None, ""):
        filtered = [record for record in filtered if record.get("component_id") == area_id]
    if equipment_id not in (None, ""):
        filtered = [record for record in filtered if record.get("asset_id") == equipment_id]
    if incident_id not in (None, ""):
        filtered = [record for record in filtered if record.get("incident_id") == incident_id]
    return filtered


def build_cascading_context_options(
    records: list[MemoryRecord],
    *,
    facility_id: Any | None = None,
    area_id: Any | None = None,
    equipment_id: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    by_facility = filter_records_by_context(records, facility_id=facility_id)
    by_area = filter_records_by_context(by_facility, area_id=area_id)
    by_equipment = filter_records_by_context(by_area, equipment_id=equipment_id)
    return {
        "facility": build_facility_options(records),
        "area": build_area_options(by_facility),
        "equipment": build_equipment_options(by_area),
        "incident": build_incident_options(by_equipment),
    }


def build_record_type_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    counts = Counter(
        str(record.get("memory_type", "")).lower()
        for record in records
        if record.get("memory_type")
    )
    options: list[dict[str, Any]] = []
    for memory_type, count in counts.items():
        options.append(
            {
                "label": f"{format_memory_type(memory_type)} ({count})" if count else format_memory_type(memory_type),
                "value": memory_type,
                "record": None,
            }
        )
    return sorted(options, key=lambda item: item["label"])


def build_status_options(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    counts = Counter(
        str(record.get("status", "")).lower()
        for record in records
        if record.get("status")
    )
    options: list[dict[str, Any]] = []
    for status, count in counts.items():
        options.append(
            {
                "label": f"{format_status(status)} ({count})" if count else format_status(status),
                "value": status,
                "record": None,
            }
        )
    return sorted(options, key=lambda item: item["label"])
