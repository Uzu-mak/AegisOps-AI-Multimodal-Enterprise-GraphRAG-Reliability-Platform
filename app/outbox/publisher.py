"""Kafka projection event contract and outbox publisher."""
from __future__ import annotations

import json
import logging
import time
from importlib import import_module
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol
from uuid import UUID

from sqlalchemy import select, text
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
        stats = {"published": 0, "failed": 0, "skipped": 0}

        with self._session_factory() as session:
            rows = session.scalars(
                select(ProjectionOutboxEvent)
                .where(ProjectionOutboxEvent.kafka_published_at.is_(None))
                .order_by(ProjectionOutboxEvent.occurred_at, ProjectionOutboxEvent.created_at)
                .limit(batch_size * len(ProjectionType))
                .with_for_update(skip_locked=True)
            ).all()

            event_rows: dict[UUID, ProjectionOutboxEvent] = {}
            for row in rows:
                if row.event_id in event_rows:
                    continue
                if not self._claim_event(session, row.event_id):
                    stats["skipped"] += 1
                    continue
                event_rows[row.event_id] = row

            for event_id, row in event_rows.items():
                event = ProjectionEvent.from_outbox(row)
                try:
                    self._producer.publish(
                        topic=self._topic,
                        key=event.message_key.encode("utf-8"),
                        value=event.to_json_bytes(),
                    )
                except Exception as exc:
                    self._mark_failed(session, event_id, str(exc))
                    stats["failed"] += 1
                    continue

                self._mark_published(session, event_id)
                stats["published"] += 1

            session.commit()

        logger.info("ProjectionEventPublisher batch: %s", stats)
        return stats

    def _claim_event(self, session: Session, event_id: UUID) -> bool:
        lock_key = event_id.int & 0x7FFFFFFFFFFFFFFF
        claimed = session.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one()
        return bool(claimed)

    def _mark_published(self, session: Session, event_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        rows = session.scalars(
            select(ProjectionOutboxEvent).where(ProjectionOutboxEvent.event_id == event_id)
        ).all()
        for row in rows:
            row.kafka_publish_status = KafkaPublishStatus.PUBLISHED.value
            row.kafka_error_message = None
            row.kafka_published_at = now
            row.updated_at = now

    def _mark_failed(self, session: Session, event_id: UUID, error_message: str) -> None:
        now = datetime.now(timezone.utc)
        rows = session.scalars(
            select(ProjectionOutboxEvent).where(ProjectionOutboxEvent.event_id == event_id)
        ).all()
        for row in rows:
            row.kafka_publish_status = KafkaPublishStatus.PENDING.value
            row.kafka_retry_count += 1
            row.kafka_error_message = error_message
            row.updated_at = now


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
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

            if stats["published"] == 0 and stats["failed"] == 0:
                time.sleep(settings.OUTBOX_PUBLISHER_POLL_SECONDS)
    finally:
        producer.close()


if __name__ == "__main__":
    main()