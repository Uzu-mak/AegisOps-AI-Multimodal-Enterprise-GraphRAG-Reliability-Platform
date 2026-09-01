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

from app.api.deps import (
    get_graph_memory_index,
    get_hybrid_retriever,
    get_llm_provider,
    get_semantic_index,
)
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex
from app.graphrag.pipeline import GraphRAGPipeline
from app.graphrag.provider import LLMProvider
from app.retrieval.hybrid import HybridMemoryRetriever
from app.semantic.qdrant_impl import QdrantSemanticIndex

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
    latency_ms: Optional[float] = None


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
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/search/semantic", response_model=HybridRetrieveResponse)
def semantic_search(
    request: SemanticSearchRequest,
    retriever: HybridMemoryRetriever = Depends(get_hybrid_retriever),
    semantic_index: Optional[QdrantSemanticIndex] = Depends(get_semantic_index),
) -> HybridRetrieveResponse:
    """Semantic vector search via Qdrant, hydrated from PostgreSQL."""
    import time
    from app.retrieval.models import RetrievalQuery

    if semantic_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is unavailable because Qdrant is unavailable",
        )

    t0 = time.monotonic()
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
        latency_ms=(time.monotonic() - t0) * 1000,
    )


@router.post("/search/hybrid", response_model=HybridRetrieveResponse)
def hybrid_retrieve(
    request: HybridRetrieveRequest,
    retriever: HybridMemoryRetriever = Depends(get_hybrid_retriever),
    semantic_index: Optional[QdrantSemanticIndex] = Depends(get_semantic_index),
    graph_index: Optional[Neo4jGraphMemoryIndex] = Depends(get_graph_memory_index),
) -> HybridRetrieveResponse:
    """Hybrid retrieval: Qdrant semantic + Neo4j graph, hydrated from PostgreSQL."""
    import time
    from uuid import UUID as PUUID
    from app.retrieval.models import RetrievalQuery

    if request.mode == "semantic" and semantic_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic retrieval mode is unavailable because Qdrant is unavailable",
        )
    if request.mode == "graph" and graph_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph retrieval mode is unavailable because Neo4j is unavailable",
        )
    if request.mode == "hybrid" and semantic_index is None and graph_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hybrid retrieval is unavailable because both Qdrant and Neo4j are unavailable",
        )

    anchor_id = None
    if request.anchor_memory_id:
        try:
            anchor_id = PUUID(request.anchor_memory_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid anchor_memory_id UUID format",
            )

    t0 = time.monotonic()
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
        latency_ms=(time.monotonic() - t0) * 1000,
    )


@router.post("/search/graph-related", response_model=GraphRelatedResponse)
def graph_related_memories(
    request: GraphRelatedRequest,
    graph_index: Optional[Neo4jGraphMemoryIndex] = Depends(get_graph_memory_index),
) -> GraphRelatedResponse:
    """Return memory UUIDs structurally related in Neo4j."""
    from uuid import UUID as PUUID

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
def graphrag_query(
    request: GraphRAGRequest,
    retriever: HybridMemoryRetriever = Depends(get_hybrid_retriever),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> GraphRAGResponse:
    """Evidence-grounded answer generation using hybrid retrieval + LLM."""
    pipeline = GraphRAGPipeline(
        retriever=retriever,
        llm_provider=llm_provider,
        context_limit=request.context_limit,
    )
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
