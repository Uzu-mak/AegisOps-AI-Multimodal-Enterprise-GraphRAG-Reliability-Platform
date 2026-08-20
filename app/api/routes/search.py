"""
Search, retrieval, and GraphRAG API endpoints.

Routes are thin — no business logic, no direct Qdrant/Neo4j calls.
All work is delegated to services/retrievers.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_memory_service, get_settings
from app.core.config import Settings

router = APIRouter(prefix="/api/v1", tags=["search"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class HybridRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid", pattern="^(semantic|graph|hybrid)$")
    limit: int = Field(default=10, ge=1, le=50)
    graph_hops: int = Field(default=2, ge=1, le=5)
    anchor_memory_id: Optional[str] = None


class GraphRelatedRequest(BaseModel):
    memory_id: str
    max_hops: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=20, ge=1, le=100)


class GraphRAGRequest(BaseModel):
    question: str = Field(..., min_length=1)
    anchor_memory_id: Optional[str] = None
    context_limit: int = Field(default=5, ge=1, le=10)


class RetrievalResultOut(BaseModel):
    memory_id: str
    retrieval_source: str
    semantic_score: Optional[float]
    graph_path: Optional[str]
    memory_type: Optional[str]
    title: Optional[str]
    content_preview: Optional[str]
    status: Optional[str]
    asset_id: Optional[str]
    facility_id: Optional[str]
    confidence: Optional[float]
    importance: Optional[float]


class HybridRetrieveResponse(BaseModel):
    results: list[RetrievalResultOut]
    total: int
    mode: str


class GraphRelatedResponse(BaseModel):
    anchor_memory_id: str
    related_memory_ids: list[str]
    total: int


class GraphRAGResponse(BaseModel):
    question: str
    answer: str
    evidence_count: int
    retrieval_mode: str
    model_name: str
    is_synthetic_response: bool
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    evidence: list[dict]


# ---------------------------------------------------------------------------
# Dependencies for retriever/pipeline (constructed lazily)
# ---------------------------------------------------------------------------

def _get_hybrid_retriever():
    """Build HybridMemoryRetriever from current app state."""
    from app.api.deps import (
        get_embedding_provider,
        get_graph_memory_index,
        get_semantic_index,
        get_settings,
    )
    from app.db.session import SessionLocal
    from app.retrieval.hybrid import HybridMemoryRetriever

    settings = get_settings()
    embedding_provider = get_embedding_provider()
    semantic_index = get_semantic_index(
        embedding_provider=embedding_provider, settings=settings
    )
    graph_index = get_graph_memory_index(settings=settings)
    return HybridMemoryRetriever(
        semantic_index=semantic_index,
        graph_index=graph_index,
        embedding_provider=embedding_provider,
        session_factory=SessionLocal,
    )


def _get_graphrag_pipeline(context_limit: int = 5):
    from app.core.config import get_settings
    from app.graphrag.pipeline import GraphRAGPipeline
    from app.graphrag.providers import DeterministicTestProvider, OpenAIProvider

    settings = get_settings()
    if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        llm = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL
        )
    else:
        llm = DeterministicTestProvider()

    retriever = _get_hybrid_retriever()
    return GraphRAGPipeline(
        retriever=retriever,
        llm_provider=llm,
        context_limit=context_limit,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/search/semantic", response_model=HybridRetrieveResponse)
def semantic_search(request: SemanticSearchRequest) -> HybridRetrieveResponse:
    """Semantic vector search via Qdrant, hydrated from PostgreSQL."""
    from app.retrieval.models import RetrievalQuery

    retriever = _get_hybrid_retriever()
    query = RetrievalQuery(
        text=request.query,
        mode="semantic",
        final_limit=request.limit,
    )
    results = retriever.retrieve(query)
    return HybridRetrieveResponse(
        results=_format_results(results),
        total=len(results),
        mode="semantic",
    )


@router.post("/search/hybrid", response_model=HybridRetrieveResponse)
def hybrid_retrieve(request: HybridRetrieveRequest) -> HybridRetrieveResponse:
    """Hybrid retrieval: Qdrant semantic + Neo4j graph, hydrated from PostgreSQL."""
    from uuid import UUID as PUUID
    from app.retrieval.models import RetrievalQuery

    retriever = _get_hybrid_retriever()
    anchor_id = None
    if request.anchor_memory_id:
        try:
            anchor_id = PUUID(request.anchor_memory_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid anchor_memory_id UUID format",
            )

    query = RetrievalQuery(
        text=request.query,
        mode=request.mode,
        anchor_memory_id=anchor_id,
        final_limit=request.limit,
        graph_hops=request.graph_hops,
    )
    results = retriever.retrieve(query)
    return HybridRetrieveResponse(
        results=_format_results(results),
        total=len(results),
        mode=request.mode,
    )


@router.post("/search/graph-related", response_model=GraphRelatedResponse)
def graph_related_memories(request: GraphRelatedRequest) -> GraphRelatedResponse:
    """Return memory UUIDs structurally related in Neo4j."""
    from uuid import UUID as PUUID
    from app.api.deps import get_graph_memory_index, get_settings

    settings = get_settings()
    graph_index = get_graph_memory_index(settings=settings)
    if graph_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j graph index is unavailable",
        )

    try:
        mid = PUUID(request.memory_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid memory_id UUID",
        )

    related = graph_index.get_related_memory_ids(
        mid, max_hops=request.max_hops, limit=request.limit
    )
    return GraphRelatedResponse(
        anchor_memory_id=request.memory_id,
        related_memory_ids=[str(uid) for uid in related],
        total=len(related),
    )


@router.post("/graphrag/query", response_model=GraphRAGResponse)
def graphrag_query(request: GraphRAGRequest) -> GraphRAGResponse:
    """Evidence-grounded answer generation using hybrid retrieval + LLM."""
    pipeline = _get_graphrag_pipeline(context_limit=request.context_limit)
    resp = pipeline.query(
        question=request.question,
        anchor_memory_id=request.anchor_memory_id,
    )
    return GraphRAGResponse(
        question=resp.question,
        answer=resp.answer,
        evidence_count=len(resp.evidence),
        retrieval_mode=resp.retrieval_mode,
        model_name=resp.model_name,
        is_synthetic_response=resp.is_synthetic_response,
        retrieval_latency_ms=resp.retrieval_latency_ms,
        generation_latency_ms=resp.generation_latency_ms,
        total_latency_ms=resp.total_latency_ms,
        evidence=[
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
            for e in resp.evidence
        ],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_results(results) -> list[RetrievalResultOut]:
    out = []
    for r in results:
        rec = r.canonical_record
        out.append(
            RetrievalResultOut(
                memory_id=str(r.memory_id),
                retrieval_source=r.retrieval_source,
                semantic_score=r.semantic_score,
                graph_path=r.graph_path,
                memory_type=str(rec.memory_type) if rec else None,
                title=rec.title if rec else None,
                content_preview=rec.content[:300] if rec else None,
                status=str(rec.status) if rec else None,
                asset_id=rec.asset_id if rec else None,
                facility_id=rec.facility_id if rec else None,
                confidence=float(rec.confidence) if rec else None,
                importance=float(rec.importance) if rec else None,
            )
        )
    return out
