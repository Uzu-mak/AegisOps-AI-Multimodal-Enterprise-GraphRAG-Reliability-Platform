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
    only: Optional[str] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
    ids: Optional[list[str]] = None,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> dict[str, Any]:
    """
    Re-project every canonical record into Qdrant and Neo4j.

    Use after changing EMBEDDING_PROVIDER (stored vectors must come from the
    same provider as query vectors) or after restoring a projection store.
    Stores that are unreachable are skipped and reported, not treated as done.

    ``ids`` limits the run to those records (e.g. the ``failed_ids`` of an
    earlier run). Transient failures (timeouts, dropped connections to the
    embedding API) are retried ``attempts`` times with growing backoff; every
    record that still fails is listed in ``failed_ids``.
    """
    from sqlalchemy import select

    qdrant_fn, neo4j_fn = build_projection_fns(connections, session_factory, embedding_provider)
    if ids is None:
        with session_factory() as session:
            ids = [str(i) for i in session.scalars(select(MemoryRecord.id)).all()]
    report: dict[str, Any] = {"records": len(ids)}
    for name, fn in (("qdrant", qdrant_fn), ("neo4j", neo4j_fn)):
        if only and name != only:
            continue
        done, errors, failed = 0, [], []
        unavailable = False
        for memory_id in ids:
            for attempt in range(1, max(1, attempts) + 1):
                try:
                    fn(memory_id, "project")
                    done += 1
                    if progress and done % 250 == 0:
                        progress(name, done, len(ids))
                    break
                except ProjectionStoreUnavailable as exc:
                    errors, failed, done, unavailable = [str(exc)], [], None, True
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt < attempts:
                        time.sleep(backoff_seconds * attempt)
                        continue
                    errors.append(f"{memory_id}: {exc}")
                    failed.append(memory_id)
            if unavailable:
                break
        report[name] = {"projected": done, "errors": errors[:5], "error_count": len(errors), "failed_ids": failed}
    return report


def prune_orphans(
    connections: ProjectionConnections,
    session_factory: Callable = SessionLocal,
    embedding_provider: Any = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Remove search entries whose record no longer exists in PostgreSQL.

    Orphans come from records that were deleted, or from writes made against
    another database (e.g. a test run) that shared these stores. They take
    search slots and are then dropped at hydration, so results look worse than
    the canonical data supports. PostgreSQL is never changed. With dry_run
    (the default) nothing is deleted; the report says what would be.
    """
    from sqlalchemy import select

    with session_factory() as session:
        known = {str(i) for i in session.scalars(select(MemoryRecord.id)).all()}
    report: dict[str, Any] = {"records": len(known), "dry_run": dry_run}

    index = connections.semantic_index(embedding_provider or create_embedding_provider())
    if index is None:
        report["qdrant"] = {"error": "Qdrant unavailable"}
    else:
        orphans, offset = [], None
        while True:
            points, offset = index.client.scroll(collection_name=index.collection_name, limit=1000, offset=offset,
                                                 with_payload=["memory_id"], with_vectors=False)
            orphans += [p.id for p in points if str((p.payload or {}).get("memory_id", p.id)) not in known]
            if offset is None:
                break
        if orphans and not dry_run:
            from qdrant_client.models import PointIdsList

            for i in range(0, len(orphans), 500):
                index.client.delete(collection_name=index.collection_name, points_selector=PointIdsList(points=orphans[i:i + 500]))
        report["qdrant"] = {"orphans": len(orphans), "removed": 0 if dry_run else len(orphans)}

    graph = connections.graph_index()
    if graph is None:
        report["neo4j"] = {"error": "Neo4j unavailable"}
    else:
        with graph._driver.session(database=graph._database) as session:
            ids = [r["id"] for r in session.run("MATCH (m:Memory) RETURN m.memory_id AS id")]
            orphans = [i for i in ids if str(i) not in known]
            removed = loose = 0
            if orphans and not dry_run:
                session.run("MATCH (m:Memory) WHERE m.memory_id IN $ids DETACH DELETE m", ids=orphans).consume()
                removed = len(orphans)
                # Assets, incidents and the like left with no connections only served the orphans.
                loose = session.run("MATCH (n) WHERE NOT n:Memory AND NOT (n)--() DELETE n RETURN count(n) AS n").single()["n"]
        report["neo4j"] = {"orphans": len(orphans), "removed": removed, "unconnected_nodes_removed": loose}
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    parser = argparse.ArgumentParser(description="AegisOps outbox projection worker")
    parser.add_argument("--reproject-all", action="store_true",
                        help="Re-project every record once (e.g. after changing EMBEDDING_PROVIDER) and exit.")
    parser.add_argument("--only", choices=["qdrant", "neo4j"], help="With --reproject-all: re-project one store only.")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="Report search entries whose record is not in PostgreSQL; add --apply to remove them.")
    parser.add_argument("--apply", action="store_true", help="With --prune-orphans: actually remove the orphans.")
    parser.add_argument("--ids", nargs="+", metavar="MEMORY_ID",
                        help="With --reproject-all: only these records (e.g. failed_ids from an earlier run).")
    parser.add_argument("--retry-failed", action="store_true", help="Requeue failed projection jobs without changing canonical records")
    args = parser.parse_args(argv)
    if args.retry_failed:
        from sqlalchemy import update
        from app.outbox.models import ProjectionOutboxEvent
        with SessionLocal() as session:
            result = session.execute(update(ProjectionOutboxEvent).where(ProjectionOutboxEvent.status == "failed").values(status="pending", retry_count=0, next_attempt_at=None, lease_token=None, lease_until=None))
            session.commit()
            print(f"Requeued {result.rowcount} projection jobs")
        return 0
    if args.prune_orphans:
        connections = get_connections()
        try:
            print(json.dumps(prune_orphans(connections, dry_run=not args.apply), indent=2))
        finally:
            connections.close_all()
        return 0
    if args.reproject_all:
        logging.basicConfig(level=logging.WARNING)
        connections = get_connections()
        try:
            import sys

            def show(store: str, done: int, total: int) -> None:
                print(f"{store}: {done}/{total}", file=sys.stderr, flush=True)

            print(json.dumps(reproject_all(connections, only=args.only, progress=show, ids=args.ids), indent=2))
        finally:
            connections.close_all()
        return 0
    run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
