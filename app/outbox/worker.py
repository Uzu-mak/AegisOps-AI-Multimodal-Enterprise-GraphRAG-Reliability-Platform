"""Leased projection jobs: commit claims before network I/O; recover expired claims."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import uuid4
from sqlalchemy import or_, select
from app.outbox.models import ProjectionOutboxEvent as Event, ProjectionStatus, ProjectionType
logger = logging.getLogger(__name__)
SessionFactory = Callable
ProjectionFn = Callable[[str, str], None]
class ProjectionDeferred(Exception):
    """Store unavailable: reschedule without spending a retry."""
class OutboxWorker:
    def __init__(self, session_factory, qdrant_fn=None, neo4j_fn=None,
                 base_backoff_seconds=2.0, lease_seconds=120, clock=None):
        self._session_factory = session_factory
        self._qdrant_fn, self._neo4j_fn = qdrant_fn, neo4j_fn
        self._base_backoff = base_backoff_seconds
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def process_batch(self, batch_size=50):
        total = dict(completed=0, failed=0, skipped=0, deferred=0)
        for _ in range(batch_size):
            stats = self._process_one()
            for key in total:
                total[key] += stats[key]
            if not any(stats.values()):
                break
        return total

    def _process_one(self):
        stats = dict(completed=0, failed=0, skipped=0, deferred=0)
        now, token = self._clock(), uuid4()
        with self._session_factory() as session:
            rows = session.scalars(select(Event).where(
                or_(Event.status.in_(["pending", "retrying"]),
                    (Event.status == "processing") & (Event.lease_until < now)),
                or_(Event.next_attempt_at.is_(None), Event.next_attempt_at <= now),
            ).order_by(Event.next_attempt_at.asc().nullsfirst(), Event.occurred_at, Event.id)
              .limit(1).with_for_update(skip_locked=True)).all()
            jobs = []
            for row in rows:
                from sqlalchemy import text
                if not session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": row.memory_id.int & 0x7FFFFFFFFFFFFFFF}).scalar_one():
                    stats["skipped"] += 1; continue
                active = session.scalar(select(Event.id).where(Event.memory_id == row.memory_id,
                    Event.id != row.id, Event.status == "processing", Event.lease_until > now).limit(1))
                if active is not None:
                    row.next_attempt_at = now + timedelta(seconds=2)
                    stats["skipped"] += 1; continue
                if row.retry_count >= row.max_retries:
                    row.status = "failed"; stats["failed"] += 1; continue
                row.status, row.lease_token = "processing", token
                row.lease_until = now + timedelta(seconds=self._lease_seconds)
                jobs.append((row.id, str(row.memory_id), row.operation, row.projection_type))
            session.commit()
        for job_id, memory_id, operation, projection_type in jobs:
            error, deferred = None, False
            handler = {"qdrant": self._qdrant_fn, "neo4j": self._neo4j_fn}.get(projection_type)
            try:
                if handler is None:
                    raise RuntimeError(f"No projection handler for {projection_type}")
                handler(memory_id, operation)
            except ProjectionDeferred as exc:
                error, deferred = str(exc), True
            except Exception as exc:
                error = str(exc)
            with self._session_factory() as session:
                row = session.scalar(select(Event).where(Event.id == job_id, Event.lease_token == token).with_for_update())
                if row is None:
                    stats["skipped"] += 1; continue
                now = self._clock()
                row.lease_token = row.lease_until = None
                row.updated_at = now
                if error is None:
                    row.status, row.completed_at, row.error_message = "completed", now, None
                    row.next_attempt_at = None; stats["completed"] += 1
                elif deferred:
                    row.status, row.error_message = "pending", error
                    row.next_attempt_at = now + timedelta(seconds=max(15, self._base_backoff))
                    stats["deferred"] += 1
                else:
                    row.retry_count += 1; row.error_message = error
                    row.status = "failed" if row.retry_count >= row.max_retries else "retrying"
                    row.next_attempt_at = now + timedelta(seconds=min(300, self._base_backoff * 2 ** (row.retry_count - 1)))
                    stats["failed" if row.status == "failed" else "skipped"] += 1
                session.commit()
        return stats

    def get_stats(self):
        from sqlalchemy import func
        with self._session_factory() as session:
            return dict(session.execute(select(Event.status, func.count(Event.id)).group_by(Event.status)).all())
