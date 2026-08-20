"""
MemoryCandidate — a structured pre-promotion memory.

A MemoryCandidate holds content that has been flagged as potentially worth
storing in long-term PostgreSQL memory but has not yet been committed.

Candidates are evaluated by a PromotionPolicy before any PostgreSQL write.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class MemoryCandidate:
    """
    Pre-promotion memory candidate.

    Created from working-memory content, operator input, or agent output.
    Does NOT exist in PostgreSQL until promoted.
    """

    candidate_id: UUID = field(default_factory=uuid4)
    memory_type: str = "observation"
    title: str = ""
    content: str = ""
    source_type: str = "operator"
    source_id: Optional[str] = None
    asset_id: Optional[str] = None
    facility_id: Optional[str] = None
    component_id: Optional[str] = None
    incident_id: Optional[str] = None
    tenant_id: Optional[str] = None
    team_id: Optional[str] = None
    confidence: float = 0.5
    importance: float = 0.5
    is_synthetic: bool = False
    metadata: dict = field(default_factory=dict)
    access_roles: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    promotion_reason: str = ""
    evidence_memory_ids: list[UUID] = field(default_factory=list)
