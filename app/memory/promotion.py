"""
PromotionPolicy — decides whether a MemoryCandidate should be promoted to
long-term PostgreSQL memory.

The interface is replaceable; a rules-based implementation is provided for
the initial phase. Later phases may use learned or LLM-guided policies.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.memory.candidate import MemoryCandidate
from app.services.memory_service import MemoryCreateData, RealMemoryService

logger = logging.getLogger(__name__)


class PromotionPolicy(Protocol):
    """Replaceable interface for memory promotion decisions."""

    def should_promote(self, candidate: MemoryCandidate) -> bool:
        """Return True if the candidate should be committed to long-term memory."""
        ...

    def build_create_data(self, candidate: MemoryCandidate) -> MemoryCreateData:
        """Convert a MemoryCandidate into MemoryCreateData for the service."""
        ...


class RulesBasedPromotion(PromotionPolicy):
    """
    Deterministic rules-based promotion policy.

    Promotes candidates that pass all configured thresholds.
    Keeps the interface replaceable without LLM dependency.
    """

    def __init__(
        self,
        min_confidence: float = 0.6,
        min_importance: float = 0.4,
        require_non_empty_content: bool = True,
        require_non_empty_title: bool = True,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_importance = min_importance
        self.require_non_empty_content = require_non_empty_content
        self.require_non_empty_title = require_non_empty_title

    def should_promote(self, candidate: MemoryCandidate) -> bool:
        if self.require_non_empty_content and not candidate.content.strip():
            return False
        if self.require_non_empty_title and not candidate.title.strip():
            return False
        if candidate.confidence < self.min_confidence:
            return False
        if candidate.importance < self.min_importance:
            return False
        return True

    def build_create_data(self, candidate: MemoryCandidate) -> MemoryCreateData:
        return MemoryCreateData(
            memory_type=candidate.memory_type,
            title=candidate.title,
            content=candidate.content,
            source_type=candidate.source_type,
            source_id=candidate.source_id,
            asset_id=candidate.asset_id,
            facility_id=candidate.facility_id,
            component_id=candidate.component_id,
            incident_id=candidate.incident_id,
            tenant_id=candidate.tenant_id,
            team_id=candidate.team_id,
            confidence=candidate.confidence,
            importance=candidate.importance,
            is_synthetic=candidate.is_synthetic,
            memory_metadata={
                **candidate.metadata,
                "promotion_reason": candidate.promotion_reason,
                "evidence_memory_ids": [
                    str(mid) for mid in candidate.evidence_memory_ids
                ],
            },
            access_roles=candidate.access_roles,
        )


def promote_candidate(
    candidate: MemoryCandidate,
    policy: PromotionPolicy,
    memory_service: RealMemoryService,
) -> object | None:
    """
    Evaluate and promote a MemoryCandidate to long-term memory if it passes
    the policy.

    Returns the created MemoryRecord on success, None if rejected by policy.
    """
    if not policy.should_promote(candidate):
        logger.info(
            f"Candidate {candidate.candidate_id} rejected by promotion policy "
            f"(confidence={candidate.confidence:.2f} importance={candidate.importance:.2f})"
        )
        return None

    create_data = policy.build_create_data(candidate)
    record = memory_service.create_memory(data=create_data)
    logger.info(
        f"Candidate {candidate.candidate_id} promoted to memory {record.id}"
    )
    return record
