"""System health and status endpoints."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/system/health")
def system_health() -> dict:
    """Check health of all AegisOps services."""
    from app.db.session import SessionLocal
    from app.core.config import get_settings

    settings = get_settings()
    health: dict[str, object] = {}

    # PostgreSQL
    try:
        from sqlalchemy import text
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        health["postgres"] = {"status": "healthy", "host": "postgres"}
    except Exception as exc:
        health["postgres"] = {"status": "unhealthy", "error": str(exc)}

    # Qdrant
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(settings.QDRANT_URL)
        client.get_collections()
        health["qdrant"] = {"status": "healthy", "url": settings.QDRANT_URL}
    except Exception as exc:
        health["qdrant"] = {"status": "unavailable", "error": str(exc)}

    # Neo4j
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        driver.close()
        health["neo4j"] = {"status": "healthy", "uri": settings.NEO4J_URI}
    except Exception as exc:
        health["neo4j"] = {"status": "unavailable", "error": str(exc)}

    # LLM
    health["llm"] = {
        "provider": settings.LLM_PROVIDER,
        "model": settings.OPENAI_MODEL,
        "api_key_set": bool(settings.OPENAI_API_KEY),
    }

    overall = "healthy" if all(
        v.get("status") == "healthy" for v in health.values()
        if isinstance(v, dict) and "status" in v
    ) else "degraded"

    return {"status": overall, "services": health}


@router.get("/system/memory-stats")
def memory_stats() -> dict:
    """Return counts of memories by type and status."""
    from sqlalchemy import func, select
    from app.db.models.memory import MemoryRecord
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            total = session.scalar(select(func.count(MemoryRecord.id)))

            by_status = session.execute(
                select(MemoryRecord.status, func.count(MemoryRecord.id))
                .group_by(MemoryRecord.status)
            ).all()

            by_type = session.execute(
                select(MemoryRecord.memory_type, func.count(MemoryRecord.id))
                .group_by(MemoryRecord.memory_type)
            ).all()

        return {
            "total": total,
            "by_status": {row[0]: row[1] for row in by_status},
            "by_type": {row[0]: row[1] for row in by_type},
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/system/outbox-stats")
def outbox_stats() -> dict:
    """Return projection outbox status counts."""
    try:
        from sqlalchemy import func, select
        from app.outbox.models import ProjectionOutboxEvent
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            rows = session.execute(
                select(
                    ProjectionOutboxEvent.status,
                    ProjectionOutboxEvent.projection_type,
                    func.count(ProjectionOutboxEvent.id).label("count"),
                ).group_by(
                    ProjectionOutboxEvent.status,
                    ProjectionOutboxEvent.projection_type,
                )
            ).all()

        return {
            "events": [
                {"status": r.status, "projection_type": r.projection_type, "count": r.count}
                for r in rows
            ]
        }
    except Exception as exc:
        return {"error": str(exc)}
