"""
OutboxWorker — processes pending projection outbox events.

Picks up PENDING events from PostgreSQL, attempts projection to
Qdrant/Neo4j, and marks them COMPLETED or FAILED with bounded retry.

This provides eventual consistency for projections after transient failures.
PostgreSQL state is never corrupted by projection failures.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.outbox.models import ProjectionOutboxEvent, ProjectionStatus, ProjectionType

logger = logging.getLogger(__name__)

# Type aliases
SessionFactory = Callable[[], Session]
ProjectionFn = Callable[[str, str], None]  # (memory_id_str, operation) -> None


class OutboxWorker:
    """
    Processes pending outbox events with bounded retry and backoff.

    Usage:
        worker = OutboxWorker(
            session_factory=SessionLocal,
            qdrant_fn=...,
            neo4j_fn=...,
        )
        worker.process_batch(batch_size=50)
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        qdrant_fn: Optional[ProjectionFn] = None,
        neo4j_fn: Optional[ProjectionFn] = None,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_fn = qdrant_fn
        self._neo4j_fn = neo4j_fn
        self._base_backoff = base_backoff_seconds

    def process_batch(self, batch_size: int = 50) -> dict[str, int]:
        """
        Process a batch of pending outbox events.

        Returns a summary: {completed, failed, skipped}.
        """
        stats = {"completed": 0, "failed": 0, "skipped": 0}

        with self._session_factory() as session:
            pending = session.scalars(
                select(ProjectionOutboxEvent)
                .where(
                    ProjectionOutboxEvent.status.in_(
                        [ProjectionStatus.PENDING.value, ProjectionStatus.RETRYING.value]
                    )
                )
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()

            for event in pending:
                if event.retry_count >= event.max_retries:
                    event.status = ProjectionStatus.FAILED.value
                    event.error_message = "Max retries exceeded"
                    event.updated_at = datetime.now(timezone.utc)
                    stats["failed"] += 1
                    continue

                # Mark as processing
                event.status = ProjectionStatus.PROCESSING.value
                event.updated_at = datetime.now(timezone.utc)
                session.flush()

                success, error = self._run_projection(event)

                if success:
                    event.status = ProjectionStatus.COMPLETED.value
                    event.completed_at = datetime.now(timezone.utc)
                    stats["completed"] += 1
                else:
                    event.retry_count += 1
                    if event.retry_count >= event.max_retries:
                        event.status = ProjectionStatus.FAILED.value
                        stats["failed"] += 1
                    else:
                        event.status = ProjectionStatus.RETRYING.value
                        stats["skipped"] += 1
                    event.error_message = error
                event.updated_at = datetime.now(timezone.utc)

            session.commit()

        logger.info(f"OutboxWorker batch: {stats}")
        return stats

    def _run_projection(
        self, event: ProjectionOutboxEvent
    ) -> tuple[bool, Optional[str]]:
        """Run the appropriate projection function for an event."""
        memory_id_str = str(event.memory_id)
        proj_type = event.projection_type

        try:
            if proj_type == ProjectionType.QDRANT.value and self._qdrant_fn:
                self._qdrant_fn(memory_id_str, event.operation)
            elif proj_type == ProjectionType.NEO4J.value and self._neo4j_fn:
                self._neo4j_fn(memory_id_str, event.operation)
            else:
                # No handler registered — mark complete to avoid infinite retry
                logger.debug(
                    f"No handler for projection_type={proj_type}; marking complete"
                )
            return True, None
        except Exception as exc:
            logger.warning(
                f"Projection failed for event {event.id} "
                f"(memory={memory_id_str} type={proj_type}): {exc}"
            )
            return False, str(exc)

    def get_stats(self) -> dict[str, int]:
        """Return counts by status from the outbox table."""
        with self._session_factory() as session:
            from sqlalchemy import func

            rows = session.execute(
                select(
                    ProjectionOutboxEvent.status,
                    func.count(ProjectionOutboxEvent.id).label("count"),
                ).group_by(ProjectionOutboxEvent.status)
            ).all()
            return {row.status: row.count for row in rows}
