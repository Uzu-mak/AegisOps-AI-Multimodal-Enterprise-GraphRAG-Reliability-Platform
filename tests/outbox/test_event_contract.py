from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.outbox.publisher import ProjectionEvent, ProjectionEventType


def test_projection_event_serializes_with_schema_version():
    event = ProjectionEvent(
        event_id=uuid4(),
        event_type=ProjectionEventType.MEMORY_CREATED,
        memory_id=uuid4(),
        memory_version=1,
        occurred_at=datetime.now(timezone.utc),
    )

    payload = event.to_dict()

    assert payload["event_type"] == "MEMORY_CREATED"
    assert payload["memory_version"] == 1
    assert payload["schema_version"] == 1
    assert payload["event_id"]
    assert payload["memory_id"] == event.message_key


def test_projection_event_json_key_is_memory_id():
    memory_id = uuid4()
    event = ProjectionEvent(
        event_id=uuid4(),
        event_type=ProjectionEventType.MEMORY_UPDATED,
        memory_id=memory_id,
        memory_version=3,
        occurred_at=datetime.now(timezone.utc),
    )

    payload = json.loads(event.to_json_bytes().decode("utf-8"))

    assert event.message_key == str(memory_id)
    assert payload["memory_id"] == str(memory_id)
    assert payload["schema_version"] == 1