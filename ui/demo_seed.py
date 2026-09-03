from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from typing import Any

from ui.api_client import api_get, api_post
from ui.operations_catalog import PLACEHOLDER_DEFAULT_VALUES, placeholder_fields


MemoryRecord = dict[str, Any]


def demo_seed_records() -> list[MemoryRecord]:
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=8)
    t1 = now - timedelta(hours=7, minutes=20)
    t2 = now - timedelta(hours=6, minutes=45)
    t3 = now - timedelta(hours=5, minutes=50)
    t4 = now - timedelta(hours=4, minutes=20)
    t5 = now - timedelta(hours=3, minutes=5)

    return [
        {
            "memory_type": "incident",
            "title": "Repeated Servo Fault - Robot R-17",
            "content": "Robot R-17 triggered recurring servo axis faults during body panel transfer on Line 2.",
            "source_type": "system",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.82,
            "importance": 0.88,
            "observed_at": t0.isoformat(),
        },
        {
            "memory_type": "observation",
            "title": "Servo temperature rise observed on Robot R-17",
            "content": "Servo temperature rose 18C above baseline after third cycle batch.",
            "source_type": "technician",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.77,
            "importance": 0.72,
            "observed_at": t1.isoformat(),
        },
        {
            "memory_type": "diagnosis",
            "title": "Likely intermittent encoder cable fatigue on Robot R-17",
            "content": "Evidence suggests intermittent signal loss on encoder cable bundle near axis bend radius.",
            "source_type": "technician",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.69,
            "importance": 0.81,
            "observed_at": t2.isoformat(),
        },
        {
            "memory_type": "maintenance_action",
            "title": "Re-terminated encoder connector and secured harness",
            "content": "Maintenance re-terminated connector, replaced strain relief clamp, and added cable support.",
            "source_type": "technician",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.86,
            "importance": 0.74,
            "observed_at": t3.isoformat(),
        },
        {
            "memory_type": "recommendation",
            "title": "Add weekly cable bend inspection for Robot R-17",
            "content": "Schedule weekly inspection of servo cable bend radius and harness strain relief for Robot R-17.",
            "source_type": "manual",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.73,
            "importance": 0.79,
            "observed_at": t4.isoformat(),
        },
        {
            "memory_type": "resolution",
            "title": "Servo fault stabilized after harness repair",
            "content": "No further servo faults observed across 240 cycles after harness repair and connector rework.",
            "source_type": "system",
            "asset_id": "robot-r17",
            "facility_id": "west-assembly-plant",
            "component_id": "body-shop-line-2",
            "incident_id": "inc-2026-0042",
            "confidence": 0.9,
            "importance": 0.83,
            "observed_at": t5.isoformat(),
        },
    ]


def seed_fingerprint(record: MemoryRecord) -> tuple[Any, ...]:
    return (
        record.get("memory_type"),
        record.get("title"),
        record.get("source_type"),
        record.get("asset_id"),
        record.get("facility_id"),
        record.get("component_id"),
        record.get("incident_id"),
    )


def plan_seed_records(existing_records: list[MemoryRecord]) -> list[MemoryRecord]:
    existing = {seed_fingerprint(record) for record in existing_records}
    return [record for record in demo_seed_records() if seed_fingerprint(record) not in existing]


def find_placeholder_records(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    placeholders: list[dict[str, Any]] = []
    for record in records:
        fields = placeholder_fields(record)
        if fields:
            placeholders.append(
                {
                    "id": record.get("id"),
                    "memory_type": record.get("memory_type"),
                    "status": record.get("status"),
                    "title": record.get("title"),
                    "fields": fields,
                }
            )
    return placeholders


def is_placeholder_literal(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in PLACEHOLDER_DEFAULT_VALUES


def fetch_all_memories(limit: int = 200) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    offset = 0

    while True:
        response = api_get("/api/v1/memories", params={"limit": limit, "offset": offset})
        if not isinstance(response, dict):
            raise RuntimeError("Failed to fetch canonical memories: unexpected response type")
        if "error" in response:
            raise RuntimeError(f"Failed to fetch canonical memories: {response['error']}")

        items = response.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("Failed to fetch canonical memories: invalid items payload")

        page = [item for item in items if isinstance(item, dict)]
        records.extend(page)

        if len(page) < limit:
            break
        offset += limit

    return records


def seed_via_api() -> int:
    existing_records = fetch_all_memories()
    placeholder_records = find_placeholder_records(existing_records)

    pending_records = plan_seed_records(existing_records)
    already_present_count = len(demo_seed_records()) - len(pending_records)

    created_count = 0
    for record in pending_records:
        created = api_post("/api/v1/memories", record)
        if not isinstance(created, dict) or "error" in created:
            error = created.get("error") if isinstance(created, dict) else "unknown error"
            print(f"API failure while creating '{record.get('title', 'Untitled')}': {error}")
            return 1
        print(f"Created: {record.get('title', 'Untitled')}")
        created_count += 1

    print(f"Already present: {already_present_count}")

    if placeholder_records:
        print("Placeholder records detected:")
        for placeholder in placeholder_records:
            title = placeholder.get("title") or "Untitled"
            fields = ", ".join(placeholder.get("fields", []))
            print(f"- {placeholder.get('id')}: {title} [{fields}]")

    print(f"Created: {created_count}")
    print(f"Already present: {already_present_count}")
    print(f"Placeholder records detected: {len(placeholder_records)}")
    return 0


def main() -> None:
    try:
        exit_code = seed_via_api()
    except Exception as exc:
        print(f"API failure: {exc}")
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
