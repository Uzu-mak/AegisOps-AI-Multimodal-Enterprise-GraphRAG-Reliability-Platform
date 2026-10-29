from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.exception_handlers import register_exception_handlers
from app.api.routes.evaluation import router as evaluation_router
from app.api.routes.imports import router as import_router
from app.api.routes.investigations import router as investigation_router
from app.api.routes.memories import router as memory_router
from app.api.routes.search import router as search_router
from app.api.routes.system import router as system_router
from app.core.config import get_settings
from app.core.connections import reset_connections
from app.db.session import SessionLocal
from app.observability.metrics import metrics_collector

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Projection clients connect lazily on first use; close them on shutdown so
    # Neo4j driver pools and Qdrant HTTP sessions are not leaked.
    yield
    reset_connections()


app = FastAPI(
    lifespan=lifespan,
    title="AegisOps",
    description="Operational Memory Engine — PostgreSQL + Qdrant + Neo4j + GraphRAG",
    version="2.0.0",
)
app.include_router(memory_router)
app.include_router(search_router)
app.include_router(investigation_router)
app.include_router(import_router)
app.include_router(evaluation_router)
app.include_router(system_router)
register_exception_handlers(app)
from app.core.security import identity_middleware
app.middleware("http")(identity_middleware)

# Web console (static SPA that talks to /api/v1). Replaces the Streamlit UI.
_CONSOLE_DIR = Path(__file__).resolve().parent / "console" / "static"
app.mount("/console", StaticFiles(directory=_CONSOLE_DIR, html=True), name="console")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/console/")


@app.middleware("http")
async def instrument_http_requests(request: Request, call_next):
    started_at = metrics_collector.request_started()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        metrics_collector.request_finished(started_at, status_code)


@app.get("/live")
def liveness():
    return {"status": "ok"}

@ app.get("/health")
@ app.get("/ready")
def healthcheck():
    """Readiness requires canonical tables and the schema expected by this build."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT revision FROM memories LIMIT 0"))
            session.execute(text("SELECT payload, next_attempt_at FROM projection_outbox LIMIT 0"))
            revision = session.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "20261028_0004":
                raise RuntimeError("Schema upgrade required")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable_or_schema_upgrade_required"})
    return {"status": "ok", "database": "connected", "schema": revision}
