"""
Outbox projection worker — applies pending projection events to Qdrant/Neo4j.

Before this worker existed, the API wrote outbox rows (status=pending) and made
a best-effort synchronous projection, but nothing ever moved those rows to
COMPLETED, and projections that failed while a store was down were never
retried. This worker closes that loop:

    PostgreSQL outbox (pending/retrying)
        → load canonical MemoryRecord from PostgreSQL
        → upsert the *current* canonical state into the projection store
        → mark COMPLETED, or RETRYING/FAILED with bounded retries

Projections are idempotent "make the store match PostgreSQL" upserts, so it is
safe for a row to be applied both synchronously by the API and here.

Run:  python -m app.outbox.projection_worker
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional
from uuid import UUID

from app.core.config import get_settings
from app.core.connections import ProjectionConnections, get_connections
from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.embeddings.factory import create_embedding_provider
from app.outbox.worker import OutboxWorker, ProjectionDeferred

logger = logging.getLogger(__name__)


class ProjectionStoreUnavailable(ProjectionDeferred):
    """Raised so the outbox row is retried rather than marked complete."""


def _load_memory(session_factory: Callable, memory_id: str) -> Optional[MemoryRecord]:
    with session_factory() as session:
        record = session.get(MemoryRecord, UUID(memory_id))
        if record is not None:
            session.expunge(record)
        return record


def build_projection_fns(
    connections: ProjectionConnections,
    session_factory: Callable = SessionLocal,
    embedding_provider: Any = None,
) -> tuple[Callable[[str, str], None], Callable[[str, str], None]]:
    """Return (qdrant_fn, neo4j_fn) that project the canonical state of a memory."""
    embedding_provider = embedding_provider or create_embedding_provider()

    def qdrant_fn(memory_id: str, _operation: str) -> None:
        from app.services.semantic_service import SemanticIndexingService

        index = connections.semantic_index(embedding_provider)
        if index is None:
            raise ProjectionStoreUnavailable("Qdrant unavailable")
        memory = _load_memory(session_factory, memory_id)
        if memory is None:
            return  # nothing canonical to project
        SemanticIndexingService(semantic_index=index, embedding_provider=embedding_provider).index_memory(memory)

    def neo4j_fn(memory_id: str, _operation: str) -> None:
        from app.services.graph_service import GraphProjectionService

        index = connections.graph_index()
        if index is None:
            raise ProjectionStoreUnavailable("Neo4j unavailable")
        memory = _load_memory(session_factory, memory_id)
        if memory is None:
            return
        service = GraphProjectionService(graph_index=index)
        service.project_memory(memory)  # sets node properties incl. status
        if memory.supersedes_memory_id:
            old = _load_memory(session_factory, str(memory.supersedes_memory_id))
            if old is not None:
                service.project_supersession(old, memory)

    return qdrant_fn, neo4j_fn


def run_forever(batch_size: int = 50) -> None:  # pragma: no cover - process loop
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    connections = get_connections()
    qdrant_fn, neo4j_fn = build_projection_fns(connections)
    worker = OutboxWorker(session_factory=SessionLocal, qdrant_fn=qdrant_fn, neo4j_fn=neo4j_fn)
    logger.info("Outbox projection worker started")
    try:
        while True:
            try:
                stats = worker.process_batch(batch_size=batch_size)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Projection batch failed: %s", exc)
                stats = {"completed": 0, "failed": 0, "skipped": 0}
            if not stats["completed"]:
                time.sleep(settings.OUTBOX_WORKER_POLL_SECONDS)
    finally:
        connections.close_all()


if __name__ == "__main__":  # pragma: no cover
    run_forever()
