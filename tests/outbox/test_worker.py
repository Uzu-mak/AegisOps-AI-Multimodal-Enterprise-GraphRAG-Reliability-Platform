"""Tests for the projection outbox worker."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.outbox.models import ProjectionOutboxEvent, ProjectionStatus, ProjectionType
from app.outbox.publisher import ProjectionEventType
from app.outbox.worker import OutboxWorker


def make_event(
    status=ProjectionStatus.PENDING.value,
    proj_type=ProjectionType.QDRANT.value,
    retry_count=0,
    max_retries=3,
) -> ProjectionOutboxEvent:
    e = ProjectionOutboxEvent()
    e.id = uuid4()
    e.memory_id = uuid4()
    e.projection_type = proj_type
    e.operation = "project"
    e.event_id = uuid4()
    e.event_type = ProjectionEventType.MEMORY_CREATED.value
    e.memory_version = 1
    e.schema_version = 1
    e.status = status
    e.retry_count = retry_count
    e.max_retries = max_retries
    e.error_message = None
    e.occurred_at = datetime.now(timezone.utc)
    e.kafka_publish_status = "pending"
    e.kafka_retry_count = 0
    e.kafka_error_message = None
    e.created_at = datetime.now(timezone.utc)
    e.updated_at = datetime.now(timezone.utc)
    e.completed_at = None
    e.kafka_published_at = None
    return e


def test_worker_retries_without_false_completion(isolated_sessions):
    from tests.reliability.test_architecture_fixes import service, data
    sf = isolated_sessions
    service(sf).create_memory(data=data())
    worker = OutboxWorker(sf)
    result = worker.process_batch()
    assert result["completed"] == 0
    assert result["skipped"] == 2
