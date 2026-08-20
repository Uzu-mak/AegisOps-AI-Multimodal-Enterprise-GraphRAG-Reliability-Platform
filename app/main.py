from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.exception_handlers import register_exception_handlers
from app.api.routes.memories import router as memory_router
from app.api.routes.search import router as search_router
from app.api.routes.system import router as system_router
from app.core.config import get_settings
from app.db.session import SessionLocal

settings = get_settings()
app = FastAPI(
    title="AegisOps",
    description="Operational Memory Engine — PostgreSQL + Qdrant + Neo4j + GraphRAG",
    version="2.0.0",
)
app.include_router(memory_router)
app.include_router(search_router)
app.include_router(system_router)
register_exception_handlers(app)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    db_status = "connected"

    try:
        with SessionLocal() as session:
            session: Session
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, ValueError) as exc:
        db_status = f"disconnected: {exc}"

    if db_status.startswith("connected"):
        return {"status": "ok", "database": "connected"}

    return {"status": "degraded", "database": db_status}
