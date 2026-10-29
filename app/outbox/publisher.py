"""Kafka projection event contract and outbox publisher."""
from __future__ import annotations

import json
import logging
import time
from importlib import import_module
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text, or_, update, exists
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.outbox.models import KafkaPublishStatus, ProjectionOutboxEvent, ProjectionType

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


class ProjectionEventType(str, Enum):
    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    MEMORY_ARCHIVED = "MEMORY_ARCHIVED"
    MEMORY_DISPUTED = "MEMORY_DISPUTED"
    MEMORY_SUPERSEDED = "MEMORY_SUPERSEDED"


@dataclass(frozen=True)
class ProjectionEvent:
    event_id: UUID
    event_type: ProjectionEventType
    memory_id: UUID
    memory_version: int
    occurred_at: datetime
    schema_version: int = 1
    memory: dict | None = None

    @property
    def message_key(self) -> str:
        return str(self.memory_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "memory_id": str(self.memory_id),
            "memory_version": self.memory_version,
            "occurred_at": self.occurred_at.isoformat(),
            "schema_version": self.schema_version,
            **({"memory": self.memory} if self.memory else {}),
        }

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_outbox(cls, row: ProjectionOutboxEvent) -> "ProjectionEvent":
        occurred_at = row.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        return cls(
            event_id=row.event_id,
            event_type=ProjectionEventType(row.event_type),
            memory_id=row.memory_id,
            memory_version=row.memory_version,
            occurred_at=occurred_at,
            schema_version=row.schema_version,
            memory=getattr(row, "payload", None),
        )


class KafkaPublisherClient(Protocol):
    def publish(self, *, topic: str, key: bytes, value: bytes) -> None: ...

    def close(self) -> None: ...


class KafkaProjectionProducer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        ack_timeout_seconds: float,
    ) -> None:
        kafka_module = import_module("kafka")
        kafka_producer_cls = getattr(kafka_module, "KafkaProducer")

        self._ack_timeout_seconds = ack_timeout_seconds
        self._producer = kafka_producer_cls(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            acks="all",
            key_serializer=None,
            value_serializer=None,
        )

    def publish(self, *, topic: str, key: bytes, value: bytes) -> None:
        future = self._producer.send(topic, key=key, value=value)
        future.get(timeout=self._ack_timeout_seconds)
        self._producer.flush()

    def close(self) -> None:
        self._producer.close()


class ProjectionEventPublisher:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        producer: KafkaPublisherClient,
        topic: str,
    ) -> None:
        self._session_factory = session_factory
        self._producer = producer
        self._topic = topic

    def publish_batch(self, batch_size: int = 50) -> dict[str, int]:
        total = {"published": 0, "failed": 0, "skipped": 0}
        for _ in range(batch_size):
            result = self._publish_next()
            for key in total:
                total[key] += result[key]
            if not any(result.values()):
                break
        return total

    def _publish_next(self) -> dict[str, int]:
        """Claim both deliveries of a logical event, commit, then perform broker I/O."""
        stats = {"published": 0, "failed": 0, "skipped": 0}
        now, token = datetime.now(timezone.utc), uuid4()
        jobs = []
        earlier = aliased(ProjectionOutboxEvent)
        with self._session_factory() as session:
            rows = session.scalars(select(ProjectionOutboxEvent).where(
                ProjectionOutboxEvent.kafka_published_at.is_(None),
                ~exists(select(earlier.id).where(earlier.memory_id == ProjectionOutboxEvent.memory_id,
                    earlier.memory_version < ProjectionOutboxEvent.memory_version,
                    earlier.kafka_published_at.is_(None))),
                or_(ProjectionOutboxEvent.kafka_next_attempt_at.is_(None), ProjectionOutboxEvent.kafka_next_attempt_at <= now),
                or_(ProjectionOutboxEvent.kafka_lease_until.is_(None), ProjectionOutboxEvent.kafka_lease_until < now),
            ).order_by(ProjectionOutboxEvent.occurred_at, ProjectionOutboxEvent.memory_version)
              .limit(2).with_for_update(skip_locked=True)).all()
            seen = set()
            for row in rows:
                if row.event_id in seen:
                    continue
                seen.add(row.event_id)
                lock_key = row.event_id.int & 0x7FFFFFFFFFFFFFFF
                if not session.execute(text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}).scalar_one():
                    stats["skipped"] += 1; continue
                # Another publisher may have leased the companion delivery row.
                companions = session.scalars(select(ProjectionOutboxEvent).where(
                    ProjectionOutboxEvent.event_id == row.event_id).with_for_update(skip_locked=True)).all()
                if len(companions) != 2:
                    stats["skipped"] += 1; continue
                if any(c.kafka_lease_until and c.kafka_lease_until.replace(tzinfo=timezone.utc) > now for c in companions):
                    stats["skipped"] += 1; continue
                for companion in companions:
                    companion.kafka_lease_token = token
                    companion.kafka_lease_until = now + timedelta(minutes=10)
                jobs.append((ProjectionEvent.from_outbox(row), row.kafka_retry_count or 0))
            session.commit()
        for event, retries in jobs:
            error = None
            try:
                self._producer.publish(topic=self._topic, key=event.message_key.encode(), value=event.to_json_bytes())
            except Exception as exc:
                error = type(exc).__name__ + ": broker publication failed"
            with self._session_factory() as session:
                rows = session.scalars(select(ProjectionOutboxEvent).where(
                    ProjectionOutboxEvent.event_id == event.event_id,
                    ProjectionOutboxEvent.kafka_lease_token == token,
                ).with_for_update()).all()
                for row in rows:
                    row.kafka_lease_token = row.kafka_lease_until = None
                    row.updated_at = datetime.now(timezone.utc)
                    if error is None:
                        row.kafka_publish_status = "published"
                        row.kafka_published_at = row.updated_at
                        row.kafka_error_message = None
                    else:
                        row.kafka_retry_count = (row.kafka_retry_count or 0) + 1
                        row.kafka_error_message = error
                        row.kafka_next_attempt_at = row.updated_at + timedelta(seconds=min(300, 2 ** min(retries + 1, 8)))
                session.commit()
            stats["published" if error is None else "failed"] += 1
        return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.KAFKA_ENABLED:
        logger.info("Kafka publication disabled by configuration")
        return
    producer = KafkaProjectionProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id=settings.KAFKA_CLIENT_ID,
        ack_timeout_seconds=settings.KAFKA_ACK_TIMEOUT_SECONDS,
    )
    publisher = ProjectionEventPublisher(
        session_factory=SessionLocal,
        producer=producer,
        topic=settings.KAFKA_PROJECTION_TOPIC,
    )

    try:
        while True:
            try:
                stats = publisher.publish_batch()
            except Exception as exc:
                logger.warning("Kafka outbox publish batch failed: %s", exc)
                stats = {"published": 0, "failed": 1, "skipped": 0}

            if stats["published"] == 0:
                time.sleep(settings.OUTBOX_PUBLISHER_POLL_SECONDS)
    finally:
        producer.close()


if __name__ == "__main__":
    main()