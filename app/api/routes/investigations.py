"""
Investigations: the operator-facing reasoning loop.

POST /investigations            run the investigation workflow (retrieve once,
                                graph links, cited answer, critic check)
POST /investigations/findings   record a confirmed conclusion as a canonical
                                memory, through the promotion policy, linked to
                                its evidence and (via the anchor) to its incident
"""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.workflow import AegisOpsWorkflow
from app.api.deps import get_hybrid_retriever, get_llm_provider, get_memory_service
from app.api.routes.memories import memory_to_response
from app.api.schemas.memory import MemoryResponse
from app.graphrag.pipeline import GraphRAGPipeline
from app.graphrag.provider import LLMProvider
from app.memory.candidate import MemoryCandidate
from app.memory.promotion import RulesBasedPromotion, promote_candidate
from app.observability.metrics import metrics_collector
from app.retrieval.hybrid import HybridMemoryRetriever
from app.services.exceptions import MemoryNotFoundError
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/v1", tags=["investigations"])

# Findings recorded from investigations must cite evidence and clear the same
# confidence/importance bar as any promoted memory.
FINDING_POLICY = RulesBasedPromotion(min_confidence=0.6, min_importance=0.4, require_evidence=True)


class InvestigationRequest(BaseModel):
    question: str = Field(..., min_length=1)
    anchor_memory_id: Optional[str] = None
    context_limit: int = Field(default=5, ge=1, le=10)


class FindingRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The investigation question the finding answers")
    memory_type: Literal["diagnosis", "recommendation", "observation", "resolution"] = "diagnosis"
    title: str
    content: str
    evidence_memory_ids: list[UUID] = Field(default_factory=list)
    anchor_memory_id: Optional[UUID] = None
    asset_id: Optional[str] = None
    facility_id: Optional[str] = None
    component_id: Optional[str] = None
    incident_id: Optional[str] = None
    confidence: float = Field(default=0.7, ge=0, le=1)
    importance: float = Field(default=0.6, ge=0, le=1)
    answer_was_synthetic: bool = False


@router.post("/investigations")
def run_investigation(
    request: InvestigationRequest,
    retriever: HybridMemoryRetriever = Depends(get_hybrid_retriever),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> dict:
    if request.anchor_memory_id:
        try:
            UUID(request.anchor_memory_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="anchor_memory_id must be a UUID")
    pipeline = GraphRAGPipeline(retriever=retriever, llm_provider=llm_provider, context_limit=request.context_limit)
    trace, rag = AegisOpsWorkflow(graphrag_pipeline=pipeline).run(request.question, request.anchor_memory_id)

    metrics_collector.observe_graphrag_latencies(rag.retrieval_latency_ms, rag.total_latency_ms)
    metrics_collector.observe_llm_call(
        provider="test" if rag.is_synthetic_response else "openai_or_custom",
        model=rag.model_name,
        success=rag.model_name != "error",
        latency_ms=rag.generation_latency_ms,
        prompt_tokens=rag.prompt_tokens,
        completion_tokens=rag.completion_tokens,
    )
    critic = trace.critic_result
    metrics_collector.observe_investigation(trace.total_latency_ms, bool(critic and critic.is_supported))

    return {
        "trace_id": str(trace.trace_id),
        "question": request.question,
        "anchor_memory_id": str(retriever.last_anchor_id) if retriever.last_anchor_id else None,
        "answer": rag.answer,
        "model_name": rag.model_name,
        "is_synthetic_response": rag.is_synthetic_response,
        "retrieval_mode": rag.retrieval_mode,
        "evidence_count": len(rag.evidence),
        "evidence": [
            {
                "memory_id": e.memory_id,
                "memory_type": e.memory_type,
                "title": e.title,
                "content_preview": e.content[:300],
                "retrieval_source": e.retrieval_source,
                "semantic_score": e.semantic_score,
                "asset_id": e.asset_id,
                "facility_id": e.facility_id,
                "confidence": e.confidence,
                "importance": e.importance,
            }
            for e in rag.evidence
        ],
        "steps": [
            {
                "type": step.step_type.value,
                "description": step.description,
                "memory_ids": [str(m) for m in step.retrieved_memory_ids],
                "latency_ms": step.latency_ms,
            }
            for step in trace.steps
        ],
        "critic": {
            "is_supported": critic.is_supported,
            "citations_valid": critic.citations_valid,
            "confidence": critic.confidence,
            "notes": critic.notes,
            "unsupported_claims": critic.unsupported_claims,
        } if critic else None,
        "retrieval_latency_ms": rag.retrieval_latency_ms,
        "generation_latency_ms": rag.generation_latency_ms,
        "total_latency_ms": trace.total_latency_ms,
    }


@router.post("/investigations/findings", status_code=status.HTTP_201_CREATED, response_model=MemoryResponse)
def record_finding(
    request: FindingRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    # Every cited evidence record must exist; inherit context from the anchor.
    evidence_records = []
    for mid in request.evidence_memory_ids:
        try:
            evidence_records.append(service.get_memory(mid))
        except MemoryNotFoundError:
            raise HTTPException(status_code=422, detail=f"Evidence record {mid} does not exist")
    context = {k: getattr(request, k) for k in ("asset_id", "facility_id", "component_id", "incident_id")}
    if request.anchor_memory_id:
        try:
            anchor = service.get_memory(request.anchor_memory_id)
        except MemoryNotFoundError:
            raise HTTPException(status_code=422, detail="Anchor record does not exist")
        for k in context:
            context[k] = context[k] or getattr(anchor, k)

    candidate = MemoryCandidate(
        memory_type=request.memory_type,
        title=request.title.strip(),
        content=request.content.strip(),
        source_type="investigation",
        confidence=request.confidence,
        importance=request.importance,
        # A finding drawn from sample (synthetic) records is itself sample data.
        # Whether the answer text came from the test provider is kept separately.
        is_synthetic=any(bool(getattr(r, "is_synthetic", False)) for r in evidence_records),
        evidence_memory_ids=list(request.evidence_memory_ids),
        promotion_reason=f"Confirmed by operator from investigation: {request.question[:200]}",
        metadata={"investigation_question": request.question,
                  "answer_was_synthetic": request.answer_was_synthetic,
                  "anchor_memory_id": str(request.anchor_memory_id) if request.anchor_memory_id else None},
        **context,
    )
    reasons = FINDING_POLICY.rejection_reasons(candidate)
    if reasons:
        metrics_collector.observe_finding(False)
        raise HTTPException(status_code=422, detail=" ".join(reasons))
    record = promote_candidate(candidate, FINDING_POLICY, service)
    metrics_collector.observe_finding(record is not None)
    return memory_to_response(record)
