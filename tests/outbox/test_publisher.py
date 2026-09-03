from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.outbox.models import KafkaPublishStatus, ProjectionOutboxEvent, ProjectionStatus, ProjectionType
from app.outbox.publisher import ProjectionEventPublisher, ProjectionEventType


class RecordingProducer:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.messages: list[dict[str, object]] = []

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("Kafka unavailable")
        self.messages.append({"topic": topic, "key": key, "value": value})

    def close(self) -> None:
        return None


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeExecuteResult:
    def __init__(self, value: bool):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeSession:
    def __init__(self, rows, *, claim_result: bool = True):
        self._rows = rows
        self._claim_result = claim_result
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def scalars(self, statement):
        return FakeScalarResult(self._rows)

    def execute(self, statement, params=None):
        if params and "lock_key" in params:
            return FakeExecuteResult(self._claim_result)
        raise AssertionError("Unexpected execute call")

    def commit(self):
        self.committed = True


def make_rows() -> list[ProjectionOutboxEvent]:
    event_id = uuid4()
    memory_id = uuid4()
    now = datetime.now(timezone.utc)
    rows: list[ProjectionOutboxEvent] = []
    for projection_type in (ProjectionType.QDRANT.value, ProjectionType.NEO4J.value):
        row = ProjectionOutboxEvent()
        row.id = uuid4()
        row.memory_id = memory_id
        row.projection_type = projection_type
        row.operation = "project"
        row.event_id = event_id
        row.event_type = ProjectionEventType.MEMORY_CREATED.value
        row.memory_version = 1
        row.schema_version = 1
        row.status = ProjectionStatus.PENDING.value
        row.retry_count = 0
        row.max_retries = 3
        row.error_message = None
        row.occurred_at = now
        row.kafka_publish_status = KafkaPublishStatus.PENDING.value
        row.kafka_retry_count = 0
        row.kafka_error_message = None
        row.created_at = now
        row.updated_at = now
        row.completed_at = None
        row.kafka_published_at = None
        rows.append(row)
    return rows


def test_pending_outbox_event_is_published_and_marked_after_ack():
    rows = make_rows()
    session = FakeSession(rows)
    producer = RecordingProducer()
    publisher = ProjectionEventPublisher(
        session_factory=lambda: session,
        producer=producer,
        topic="aegisops.memory.projections.v1",
    )

    stats = publisher.publish_batch()

    assert stats["published"] == 1
    assert len(producer.messages) == 1
    assert producer.messages[0]["key"].decode("utf-8") == str(rows[0].memory_id)

    payload = json.loads(producer.messages[0]["value"].decode("utf-8"))
    assert payload["memory_id"] == str(rows[0].memory_id)
    assert payload["schema_version"] == 1

    assert session.committed is True
    assert all(row.kafka_published_at is not None for row in rows)
    assert all(row.kafka_publish_status == KafkaPublishStatus.PUBLISHED.value for row in rows)


def test_kafka_publication_failure_leaves_event_pending():
    rows = make_rows()
    session = FakeSession(rows)
    producer = RecordingProducer(fail_times=1)
    publisher = ProjectionEventPublisher(
        session_factory=lambda: session,
        producer=producer,
        topic="aegisops.memory.projections.v1",
    )

    stats = publisher.publish_batch()

    assert stats["failed"] == 1
    assert producer.messages == []

    assert session.committed is True
    assert all(row.kafka_published_at is None for row in rows)
    assert all(row.kafka_retry_count == 1 for row in rows)
    assert all(row.kafka_error_message == "Kafka unavailable" for row in rows)


def test_failed_event_can_be_retried_with_stable_event_id():
    rows = make_rows()
    original_event_id = rows[0].event_id

    failing_producer = RecordingProducer(fail_times=1)
    publisher = ProjectionEventPublisher(
        session_factory=lambda: FakeSession(rows),
        producer=failing_producer,
        topic="aegisops.memory.projections.v1",
    )
    publisher.publish_batch()

    succeeding_producer = RecordingProducer()
    retry_publisher = ProjectionEventPublisher(
        session_factory=lambda: FakeSession(rows),
        producer=succeeding_producer,
        topic="aegisops.memory.projections.v1",
    )
    stats = retry_publisher.publish_batch()

    assert stats["published"] == 1
    payload = json.loads(succeeding_producer.messages[0]["value"].decode("utf-8"))
    assert payload["event_id"] == str(original_event_id)

    assert len({row.event_id for row in rows}) == 1
    assert rows[0].event_id == original_event_id
    assert all(row.kafka_published_at is not None for row in rows)
