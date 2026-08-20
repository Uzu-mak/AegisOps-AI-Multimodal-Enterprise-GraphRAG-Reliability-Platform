"""
Critic / Verifier — validates that agent answers are supported by evidence.

Checks:
1. All [Memory N] citations reference evidence items that exist in context.
2. Detects unsupported claims (claims not mentioning any evidence).
3. Returns a CriticResult with validation details.

This is a deterministic rule-based critic suitable for Phase 3.
Later phases may use an LLM-based critic.
"""
from __future__ import annotations

import re

from app.agents.state import CriticResult
from app.graphrag.context import EvidenceItem


class RuleBasedCritic:
    """
    Validates GraphRAG or agent answers against evidence items.

    Checks citation validity (referenced Memory IDs exist in evidence) and
    detects sentences that make no reference to any evidence.
    """

    def verify(
        self,
        answer: str,
        evidence: list[EvidenceItem],
    ) -> CriticResult:
        if not evidence:
            return CriticResult(
                is_supported=False,
                notes="No evidence was retrieved; answer cannot be verified.",
                confidence=0.0,
            )

        valid_ids = {e.memory_id for e in evidence}

        # Find all [Memory N] citations in the answer
        cited_refs = re.findall(r"\[Memory\s+(\d+)\]", answer)

        # Check which citations map to valid evidence indices
        invalid_citations: list[str] = []
        for ref in cited_refs:
            idx = int(ref) - 1  # 1-based
            if idx < 0 or idx >= len(evidence):
                invalid_citations.append(f"[Memory {ref}]")

        # Find sentences with no evidence reference
        sentences = re.split(r"[.!?]+", answer)
        unsupported: list[str] = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            # Skip meta-commentary about evidence availability
            if "insufficient" in sent.lower() or "not provided" in sent.lower():
                continue
            if "synthetic" in sent.lower() or "deterministic" in sent.lower():
                continue
            # If sentence has no [Memory N] citation, flag it
            if not re.search(r"\[Memory\s+\d+\]", sent):
                if len(sent) > 30:  # Ignore very short sentences
                    unsupported.append(sent[:100])

        citations_valid = len(invalid_citations) == 0
        # Consider supported if at least some citations exist OR answer acknowledges evidence
        has_any_citation = bool(cited_refs)
        is_supported = citations_valid and (has_any_citation or len(evidence) == 0)

        confidence = 1.0
        if invalid_citations:
            confidence -= 0.3 * len(invalid_citations)
        if not has_any_citation and evidence:
            confidence -= 0.2
        confidence = max(0.0, min(1.0, confidence))

        return CriticResult(
            is_supported=is_supported,
            unsupported_claims=unsupported[:5],  # Cap for readability
            citations_valid=citations_valid,
            confidence=confidence,
            notes=f"Found {len(cited_refs)} citations; {len(invalid_citations)} invalid.",
        )
