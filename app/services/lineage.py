"""
Data lineage for one record: where it came from, its versions, what it was
derived from, what was derived from it, and whether the search indexes have it.

Read-only. Everything comes from canonical PostgreSQL: the import metadata,
supersede links, a finding's evidence list and the projection outbox.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.memory import MemoryRecord
from app.outbox.models import ProjectionOutboxEvent

MAX_CHAIN = 25


def _brief(r: MemoryRecord) -> dict[str, Any]:
    return {"id": str(r.id), "title": r.title, "status": r.status, "memory_type": r.memory_type,
            "source_type": r.source_type, "created_at": r.created_at.isoformat() if r.created_at else None}


def _uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def record_lineage(session: Session, memory_id: UUID) -> Optional[dict[str, Any]]:
    rec = session.get(MemoryRecord, memory_id)
    if rec is None:
        return None
    meta = rec.memory_metadata or {}
    imp = meta.get("import") or {}

    origin = {
        "source_type": rec.source_type,
        "source_id": rec.source_id,
        "source_system": imp.get("source_system"),
        "file_name": imp.get("file_name"),
        "row": imp.get("row"),
        "fingerprint": imp.get("fingerprint"),
        "recorded_at": rec.created_at.isoformat() if rec.created_at else None,
        "is_synthetic": bool(rec.is_synthetic),
        "quality_rules": (meta.get("quality") or {}).get("rules"),
    }

    # Versions: earlier ones through supersedes links, later ones that supersede this.
    earlier, cur, seen = [], rec, {rec.id}
    while cur.supersedes_memory_id and len(earlier) < MAX_CHAIN:
        prev = session.get(MemoryRecord, cur.supersedes_memory_id)
        if prev is None or prev.id in seen:
            break
        earlier.append(_brief(prev)); seen.add(prev.id); cur = prev
    later, cur_id = [], rec.id
    while len(later) < MAX_CHAIN:
        nxt = session.scalars(select(MemoryRecord).where(MemoryRecord.supersedes_memory_id == cur_id).limit(1)).first()
        if nxt is None or nxt.id in seen:
            break
        later.append(_brief(nxt)); seen.add(nxt.id); cur_id = nxt.id

    derived_from = []
    for mid in meta.get("evidence_memory_ids") or []:
        u = _uuid(mid)
        src = session.get(MemoryRecord, u) if u else None
        derived_from.append(_brief(src) if src else {"id": str(mid), "title": None, "status": "missing"})

    # Findings that cite this record. Findings are few, so they are filtered here.
    findings = session.scalars(select(MemoryRecord).where(MemoryRecord.source_type == "investigation").limit(1000)).all()
    used_by = [_brief(f) for f in findings if str(rec.id) in {str(x) for x in (f.memory_metadata or {}).get("evidence_memory_ids") or []}]

    projections = {}
    for target in ("qdrant", "neo4j"):
        ev = session.scalars(select(ProjectionOutboxEvent)
                             .where(ProjectionOutboxEvent.memory_id == rec.id, ProjectionOutboxEvent.projection_type == target)
                             .order_by(ProjectionOutboxEvent.created_at.desc()).limit(1)).first()
        projections[target] = None if ev is None else {
            "status": ev.status, "operation": ev.operation, "memory_version": ev.memory_version,
            "queued_at": ev.created_at.isoformat() if ev.created_at else None,
            "completed_at": ev.completed_at.isoformat() if ev.completed_at else None,
            "error": ev.error_message,
        }

    return {"record": _brief(rec), "revision": rec.revision, "origin": origin, "earlier_versions": earlier,
            "later_versions": later, "derived_from": derived_from, "used_by_findings": used_by, "projections": projections}
