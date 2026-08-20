"""
GraphRAG context construction — builds the LLM prompt from canonical evidence.

Only canonical MemoryRecord data (from PostgreSQL) is used as evidence.
Qdrant and Neo4j payloads are projection metadata, not authoritative content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.retrieval.models import RetrievalResult


@dataclass
class EvidenceItem:
    memory_id: str
    memory_type: str
    title: str
    content: str
    retrieval_source: str
    semantic_score: Optional[float]
    graph_path: Optional[str]
    asset_id: Optional[str]
    facility_id: Optional[str]
    confidence: float
    importance: float


@dataclass
class BuiltContext:
    question: str
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    system_prompt: str = ""
    user_prompt: str = ""


def build_context(
    question: str,
    results: list[RetrievalResult],
    max_evidence: int = 5,
) -> BuiltContext:
    """
    Build the LLM context from hybrid retrieval results.

    Evidence items are sourced exclusively from canonical PostgreSQL records
    (canonical_record field). Qdrant/Neo4j metadata is used only for
    provenance annotation.
    """
    ctx = BuiltContext(question=question)

    hydrated = [r for r in results if r.canonical_record is not None][:max_evidence]

    for r in hydrated:
        rec = r.canonical_record
        ctx.evidence_items.append(
            EvidenceItem(
                memory_id=str(rec.id),
                memory_type=str(rec.memory_type),
                title=rec.title or "",
                content=rec.content or "",
                retrieval_source=r.retrieval_source,
                semantic_score=r.semantic_score,
                graph_path=r.graph_path,
                asset_id=rec.asset_id,
                facility_id=rec.facility_id,
                confidence=float(rec.confidence),
                importance=float(rec.importance),
            )
        )

    # Build system prompt
    evidence_blocks = "\n\n".join(
        f"[Memory {i + 1}: {e.memory_id}]\n"
        f"Type: {e.memory_type} | Source: {e.retrieval_source} | "
        f"Confidence: {e.confidence:.2f} | Importance: {e.importance:.2f}\n"
        f"Asset: {e.asset_id or 'N/A'} | Facility: {e.facility_id or 'N/A'}\n"
        f"Title: {e.title}\n"
        f"Content: {e.content}"
        for i, e in enumerate(ctx.evidence_items)
    )

    ctx.system_prompt = (
        "You are AegisOps, an operational intelligence assistant for manufacturing "
        "reliability and infrastructure.\n\n"
        "Answer questions using ONLY the canonical operational memory records "
        "provided below. Cite evidence by [Memory N] references.\n"
        "If the evidence is insufficient, say so explicitly. "
        "Do NOT invent facts beyond the provided records.\n\n"
        f"--- OPERATIONAL MEMORY EVIDENCE ---\n{evidence_blocks or '(No evidence retrieved)'}\n"
        "--- END OF EVIDENCE ---"
    )

    ctx.user_prompt = question
    return ctx
