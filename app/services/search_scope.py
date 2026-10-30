"""
What a search covered, so "nothing found" is never read as "it didn't happen".

Absence of a record is only evidence of absence within the records that were
searched. Answers carry this scope: how many active records were searchable
and where they came from.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select

from app.db.models.memory import MemoryRecord

logger = logging.getLogger(__name__)


def search_scope(session_factory, tenant_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Counts of active records by source; None if the database can't be read."""
    try:
        stmt = (select(MemoryRecord.source_type, MemoryRecord.is_synthetic, func.count())
                .where(MemoryRecord.status == "active")
                .group_by(MemoryRecord.source_type, MemoryRecord.is_synthetic))
        if tenant_id is not None:
            stmt = stmt.where(MemoryRecord.tenant_id == tenant_id)
        with session_factory() as session:
            rows = session.execute(stmt).all()
    except Exception as exc:  # noqa: BLE001 - scope is informative, never fatal
        logger.warning("search scope unavailable: %s", exc)
        return None
    by_source: dict[str, int] = {}
    sample = 0
    for source_type, is_synthetic, n in rows:
        by_source[source_type] = by_source.get(source_type, 0) + n
        sample += n if is_synthetic else 0
    return {"active_records": sum(by_source.values()), "by_source": by_source, "sample_records": sample}
