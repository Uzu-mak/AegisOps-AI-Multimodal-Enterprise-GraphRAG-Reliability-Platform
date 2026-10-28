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


def reproject_all(
    connections: ProjectionConnections,
    session_factory: Callable = SessionLocal,
    embedding_provider: Any = None,
) -> dict[str, Any]:
    """
    Re-project every canonical record into Qdrant and Neo4j.

    Use after changing EMBEDDING_PROVIDER (stored vectors must come from the
    same provider as query vectors) or after restoring a projection store.
    Stores that are unreachable are skipped and reported, not treated as done.
    """
    from sqlalchemy import select

    qdrant_fn, neo4j_fn = build_projection_fns(connections, session_factory, embedding_provider)
    with session_factory() as session:
        ids = [str(i) for i in session.scalars(select(MemoryRecord.id)).all()]
    report: dict[str, Any] = {"records": len(ids)}
    for name, fn in (("qdrant", qdrant_fn), ("neo4j", neo4j_fn)):
        done, errors = 0, []
        for memory_id in ids:
            try:
                fn(memory_id, "project")
                done += 1
            except ProjectionStoreUnavailable as exc:
                errors = [str(exc)]
                done = None
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{memory_id}: {exc}")
        report[name] = {"projected": done, "errors": errors[:5], "error_count": len(errors)}
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    parser = argparse.ArgumentParser(description="AegisOps outbox projection worker")
    parser.add_argument("--reproject-all", action="store_true",
                        help="Re-project every record once (e.g. after changing EMBEDDING_PROVIDER) and exit.")
    args = parser.parse_args(argv)
    if args.reproject_all:
        logging.basicConfig(level=logging.WARNING)
        connections = get_connections()
        try:
            print(json.dumps(reproject_all(connections), indent=2))
        finally:
            connections.close_all()
        return 0
    run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
