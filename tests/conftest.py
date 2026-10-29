from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

# Tests never call a paid, non-deterministic answer model unless asked to:
# the deterministic provider gives repeatable answers and citation checks.
# Set AEGISOPS_TEST_REAL_LLM=1 to exercise the configured model instead.
if os.getenv("AEGISOPS_TEST_REAL_LLM") != "1":
    os.environ["LLM_PROVIDER"] = "test"


# Integration fixtures delete rows: never let a default developer DB receive them.
def pytest_collection_modifyitems(config, items):
    import pytest
    from sqlalchemy.engine import make_url
    url = os.getenv("DATABASE_URL", "")
    safe = bool(os.getenv("AEGISOPS_INTEGRATION_TESTS") == "1" and url and "test" in (make_url(url).database or "").lower())
    if safe:
        return
    mutating = ("tests/services/", "tests/repositories/", "tests/ingestion/", "tests/graph/", "tests/integration/")
    for item in items:
        path = str(item.path).replace("\\", "/")
        if any(part in path for part in mutating) or "/tests/api/" in path:
            item.add_marker(pytest.mark.skip(reason="Use an isolated DATABASE_URL with a test database name; live data is protected"))


import pytest
@pytest.fixture
def isolated_sessions():
    from sqlalchemy import create_engine, event, JSON
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.base import Base
    from app.db.models.memory import MemoryRecord
    from app.outbox.models import ProjectionOutboxEvent
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def functions(db, _):
        db.create_function("pg_try_advisory_xact_lock", 1, lambda _: 1)
        db.create_function("pg_advisory_xact_lock", 1, lambda _: 1)
        db.create_function("hashtextextended", 2, lambda value, seed: 1)
    columns = [MemoryRecord.__table__.c.access_roles, MemoryRecord.__table__.c.metadata, ProjectionOutboxEvent.__table__.c.payload]
    old = [c.type for c in columns]
    try:
        for column in columns:
            column.type = JSON()
        # Production expression indexes are verified against PostgreSQL separately.
        saved_indexes = set(MemoryRecord.__table__.indexes)
        MemoryRecord.__table__.indexes.clear()
        Base.metadata.create_all(engine)
        MemoryRecord.__table__.indexes.update(saved_indexes)
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        if "saved_indexes" in locals():
            MemoryRecord.__table__.indexes.update(saved_indexes)
        for column, column_type in zip(columns, old):
            column.type = column_type
        engine.dispose()
