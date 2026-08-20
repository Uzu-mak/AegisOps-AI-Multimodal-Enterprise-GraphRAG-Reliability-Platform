"""Tests for the projection outbox worker."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.outbox.models import ProjectionOutboxEvent, ProjectionStatus, ProjectionType
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
    e.status = status
    e.retry_count = retry_count
    e.max_retries = max_retries
    e.error_message = None
    e.created_at = datetime.now(timezone.utc)
    e.updated_at = datetime.now(timezone.utc)
    e.completed_at = None
    return e


class TestOutboxWorkerBasic:

    def test_completes_event_on_success(self):
        event = make_event()
        qdrant_fn = MagicMock()

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        session.scalars.return_value.all.return_value = [event]

        worker = OutboxWorker(
            session_factory=MagicMock(return_value=session),
            qdrant_fn=qdrant_fn,
        )
        stats = worker.process_batch()
        assert stats["completed"] == 1
        assert event.status == ProjectionStatus.COMPLETED.value

    def test_marks_retrying_on_failure(self):
        event = make_event()
        qdrant_fn = MagicMock(side_effect=RuntimeError("Qdrant down"))

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        session.scalars.return_value.all.return_value = [event]

        worker = OutboxWorker(
            session_factory=MagicMock(return_value=session),
            qdrant_fn=qdrant_fn,
        )
        stats = worker.process_batch()
        assert event.retry_count == 1
        assert event.status in (
            ProjectionStatus.RETRYING.value,
            ProjectionStatus.FAILED.value,
        )

    def test_fails_event_at_max_retries(self):
        event = make_event(retry_count=3, max_retries=3)

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        session.scalars.return_value.all.return_value = [event]

        worker = OutboxWorker(
            session_factory=MagicMock(return_value=session),
        )
        stats = worker.process_batch()
        assert stats["failed"] == 1
        assert event.status == ProjectionStatus.FAILED.value

    def test_no_handler_marks_completed(self):
        """Events without a registered handler should be marked complete to avoid retry loops."""
        event = make_event(proj_type=ProjectionType.NEO4J.value)

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        session.scalars.return_value.all.return_value = [event]

        worker = OutboxWorker(
            session_factory=MagicMock(return_value=session),
            qdrant_fn=None,
            neo4j_fn=None,
        )
        stats = worker.process_batch()
        assert stats["completed"] == 1

    def test_empty_queue_returns_zero_stats(self):
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        session.scalars.return_value.all.return_value = []

        worker = OutboxWorker(session_factory=MagicMock(return_value=session))
        stats = worker.process_batch()
        assert stats["completed"] == 0
        assert stats["failed"] == 0
