"""
Write-side quality flags for operational records.

Flags describe how far a record can carry an answer, not whether it is true:

* ``administrative``  billing or paperwork entries with no technical content
* ``routine_check``   a bare check result ("LEAK CK GOOD"), useful as an
                      outcome but not as an explanation
* ``truncated``       the source system cut the text off (MaintNet marks this)
* ``no_asset``        not linked to an asset, so it cannot be placed in context

Imports store the flags in ``metadata.quality`` (outside the fingerprint, so
re-importing the same file is still a no-op). Records written before the flags
existed get the same flags computed on read; nothing stored is changed.
"""
from __future__ import annotations

import re
from typing import Any, Optional

RULES_VERSION = "quality-rules-1"
FLAG_LABELS = {
    "administrative": "Administrative entry",
    "routine_check": "Routine check result",
    "truncated": "Text cut off at source",
    "no_asset": "No asset linked",
}

_ADMIN = re.compile(r"\b(FOR\s+BILLING|BILLING\s+PURPOSES|SEE\s+(ABOVE|PREVIOUS)\s+(WO|WORK\s*ORDER|ENTRY)|DUPLICATE\s+(ENTRY|WORK\s*ORDER))\b", re.I)
# A routine check is a record whose remedy says nothing beyond "ran it, checks good".
_CHECK_PHRASES = re.compile(
    r"\b(?:(?:OPS|LEAK|POWER|MAGS?|OPERATIONAL|FUNCTIONAL)(?:\s*(?:&|AND)\s*(?:OPS|LEAK|POWER|MAGS?))*\s+(?:CK|CHECK)(?:'?ED)?\s+(?:GOOD|OK|OKAY|PASSED)"
    r"|RAN\s+(?:UP\s+)?(?:A/C|AIRCRAFT|ENGINE|ENG)|RUN[-\s]?UP|PERFORMED\s+(?:GROUND\s+)?RUN(?:\s*UP)?|NO\s+DEFECTS\s+NOTED|CHECKS?\s+GOOD)\b",
    re.I,
)


def _is_routine_check(text: str) -> bool:
    if not _CHECK_PHRASES.search(text):
        return False
    rest = re.findall(r"[A-Za-z]{3,}", _CHECK_PHRASES.sub(" ", text))
    return not [w for w in rest if w.upper() not in {"AND", "THE", "WITH", "ALL"}]


def _remedy_and_desc(content: str, meta: dict[str, Any]) -> tuple[str, str]:
    wo = meta.get("work_order") or {}
    return str(wo.get("remedy") or ""), str(content or "")


def compute_flags(*, content: str, asset_id: Optional[str], source_type: str, meta: Optional[dict[str, Any]]) -> list[str]:
    meta = meta or {}
    flags: list[str] = []
    remedy, text = _remedy_and_desc(content, meta)
    target = remedy or text
    if _ADMIN.search(target):
        flags.append("administrative")
    elif target and _is_routine_check(target):
        flags.append("routine_check")
    truncated = str((meta.get("extra") or {}).get("SOURCE_TRUNCATED") or "").strip()
    if truncated:
        flags.append("truncated")
    if source_type == "work_order" and not asset_id:
        flags.append("no_asset")
    return flags


def quality_flags(record: Any) -> list[str]:
    """Stored flags when the import wrote them, otherwise computed now (read-only)."""
    meta = getattr(record, "memory_metadata", None) or {}
    stored = (meta.get("quality") or {}).get("flags")
    if stored is not None:
        return list(stored)
    return compute_flags(content=getattr(record, "content", ""), asset_id=getattr(record, "asset_id", None),
                         source_type=str(getattr(record, "source_type", "") or ""), meta=meta)
