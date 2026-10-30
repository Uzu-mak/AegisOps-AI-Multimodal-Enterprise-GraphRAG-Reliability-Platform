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


_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the a an and or of to in on at for from with by was were is are be been this that these those it its "
    "after before during then than which who what when where why how not no also into onto over under "
    "record records memory evidence shows show showed according states stated found".split()
)


def _content_words(text: str) -> set[str]:
    # Compare on 5-letter stems so "leaking"/"leak" and "seals"/"seal" match.
    return {w[:5] for w in _WORD.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP}


def weak_citations(answer: str, evidence: list[EvidenceItem], *, min_overlap: float = 0.2) -> list[str]:
    """Cited sentences that share under min_overlap of their content words with the records they cite."""
    normalized = re.sub(
        r"([.!?]+)(\s*)((?:\[Memory\s+\d+\][\s,;]*)+)",
        lambda m: " " + m.group(3).strip() + m.group(1) + m.group(2),
        answer or "",
    )
    weak: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", normalized):
        refs = [int(r) for r in re.findall(r"\[Memory\s+(\d+)\]", sent)]
        refs = [r for r in refs if 1 <= r <= len(evidence)]
        if not refs:
            continue
        words = _content_words(re.sub(r"\[Memory\s+\d+\]", " ", sent))
        if len(words) < 3:
            continue
        cited = set().union(*(_content_words(f"{evidence[r - 1].title} {evidence[r - 1].content}") for r in refs))
        if len(words & cited) / len(words) < min_overlap:
            weak.append(sent.strip()[:160])
    return weak


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
        # Models usually cite after the full stop ("...seal. [Memory 4]").
        # Move such trailing citations before the stop so they count for the
        # sentence they follow, not as a fragment of their own.
        normalized = re.sub(
            r"([.!?]+)(\s*)((?:\[Memory\s+\d+\][\s,;]*)+)",
            lambda m: " " + m.group(3).strip() + m.group(1) + m.group(2),
            answer,
        )
        sentences = re.split(r"[.!?]+", normalized)
        unsupported: list[str] = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            # Skip meta-commentary about evidence availability
            if "insufficient" in sent.lower() or "not provided" in sent.lower():
                continue
            if "synthetic" in sent.lower() or "deterministic" in sent.lower() or "configure openai_api_key" in sent.lower() or "retrieval order without interpretation" in sent.lower() or "retrieved memory records" in sent.lower():
                continue
            # If sentence has no [Memory N] citation, flag it
            if not re.search(r"\[Memory\s+\d+\]", sent):
                if len(sent) > 30:  # Ignore very short sentences
                    unsupported.append(sent[:100])

        citations_valid = len(invalid_citations) == 0
        # Consider supported if at least some citations exist OR answer acknowledges evidence
        has_any_citation = bool(cited_refs)
        is_supported = citations_valid and has_any_citation and not unsupported

        confidence = 1.0
        if invalid_citations:
            confidence -= 0.3 * len(invalid_citations)
        if not has_any_citation and evidence:
            confidence -= 0.2
        confidence -= min(0.5, len(unsupported) * 0.1)
        confidence = max(0.0, min(1.0, confidence))

        return CriticResult(
            is_supported=is_supported,
            unsupported_claims=unsupported[:5],  # Cap for readability
            citations_valid=citations_valid,
            confidence=confidence,
            notes=f"Found {len(cited_refs)} citations; {len(invalid_citations)} invalid.",
            weak_citations=weak_citations(answer, evidence)[:5],
        )
