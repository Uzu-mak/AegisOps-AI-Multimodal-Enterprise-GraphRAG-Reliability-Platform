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


def test_pending_outbox_event_is_published_and_marked_after_ack(isolated_sessions):
    from tests.reliability.test_architecture_fixes import service, data
    from sqlalchemy import select
    sf=isolated_sessions;service(sf).create_memory(data=data())
    producer=RecordingProducer()
    publisher=ProjectionEventPublisher(session_factory=sf,producer=producer,topic="test")
    assert publisher.publish_batch()["published"]==1
    assert len(producer.messages)==1
    with sf() as session:
        assert all(row.kafka_published_at for row in session.scalars(select(ProjectionOutboxEvent)))


def test_kafka_publication_failure_leaves_event_pending(isolated_sessions):
    from tests.reliability.test_architecture_fixes import service, data
    from sqlalchemy import select
    sf=isolated_sessions;service(sf).create_memory(data=data())
    publisher=ProjectionEventPublisher(session_factory=sf,producer=RecordingProducer(fail_times=1),topic="test")
    assert publisher.publish_batch()["failed"]==1
    with sf() as session:
        assert all(row.kafka_published_at is None and row.kafka_retry_count==1 for row in session.scalars(select(ProjectionOutboxEvent)))


def test_failed_event_can_be_retried_with_stable_event_id(isolated_sessions):
    from tests.reliability.test_architecture_fixes import service, data
    from sqlalchemy import select
    sf=isolated_sessions;service(sf).create_memory(data=data())
    producer=RecordingProducer(fail_times=1)
    publisher=ProjectionEventPublisher(session_factory=sf,producer=producer,topic="test")
    publisher.publish_batch()
    with sf() as session:
        rows=session.scalars(select(ProjectionOutboxEvent)).all()
        expected=rows[0].event_id
        for row in rows: row.kafka_next_attempt_at=None
        session.commit()
    assert publisher.publish_batch()["published"]==1
    assert json.loads(producer.messages[0]["value"])["event_id"]==str(expected)
