"""
Evaluation runs: interactive retrieval benchmark over the live stack.

Uses the production retriever in each mode (the same definition as the
recorded CLI benchmark, evals/run_benchmark.py) and the single metrics module
app.evaluation.metrics, so numbers here and in the CLI agree for the same
cases. "agentic" runs the full investigation workflow and also scores the
answer's citations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.workflow import AegisOpsWorkflow
from app.api.deps import (
    get_embedding_provider,
    get_graph_memory_index,
    get_hybrid_retriever,
    get_llm_provider,
    get_memory_service,
    get_semantic_index,
)
import logging
import os

from app.core.security import current_principal
from app.db.session import SessionLocal
from app.evaluation import store
from app.evaluation.models import EvalCase, RetrievalMode
from app.evaluation.runner import EvaluationRunner
from app.graphrag.pipeline import GraphRAGPipeline
from app.retrieval.models import RetrievalQuery
from app.services.exceptions import MemoryNotFoundError

router = APIRouter(prefix="/api/v1", tags=["evaluation"])
logger = logging.getLogger(__name__)


def _may_persist(principal) -> bool:
    """Viewers may run evaluations (a read) but not add to the shared history."""
    return principal is None or bool({"writer", "admin"} & set(principal.roles))

Mode = Literal["semantic", "graph", "hybrid", "agentic"]


class EvalCaseIn(BaseModel):
    case_id: Optional[str] = None
    question: str = Field(..., min_length=1)
    expected_memory_ids: list[UUID] = Field(default_factory=list)
    # Optional starting record; used by investigation mode only, so the case is
    # measured the way engineers investigate (from a record).
    anchor_memory_id: Optional[UUID] = None


class EvalRunRequest(BaseModel):
    cases: list[EvalCaseIn] = Field(..., min_length=1, max_length=200)
    modes: list[Mode] = Field(default_factory=lambda: ["semantic", "graph", "hybrid"])
    k: int = Field(default=10, ge=1, le=50)


@router.post("/evaluation/runs")
def run_evaluation(
    request: EvalRunRequest,
    retriever=Depends(get_hybrid_retriever),
    semantic_index=Depends(get_semantic_index),
    graph_index=Depends(get_graph_memory_index),
    llm_provider=Depends(get_llm_provider),
    embedding_provider=Depends(get_embedding_provider),
    service=Depends(get_memory_service),
) -> dict:
    for case in request.cases:
        for mid in case.expected_memory_ids:
            try:
                service.get_memory(mid)
            except MemoryNotFoundError:
                raise HTTPException(status_code=422, detail=f"Expected record {mid} in '{case.question[:60]}' does not exist")

    needs = {"semantic": ("qdrant",), "graph": ("qdrant", "neo4j"), "hybrid": ("qdrant", "neo4j"), "agentic": ()}
    up = {"qdrant": semantic_index is not None, "neo4j": graph_index is not None}
    unavailable = {m: [s for s in needs[m] if not up[s]] for m in request.modes}
    runnable = [m for m in dict.fromkeys(request.modes) if not unavailable[m]]

    workflow = AegisOpsWorkflow(GraphRAGPipeline(retriever=retriever, llm_provider=llm_provider, context_limit=request.k))

    def retrieval_fn(question: str, mode: str, anchor_memory_id: Optional[str] = None):
        if mode == "agentic":
            trace, rag = workflow.run(question, anchor_memory_id)
            return rag.answer, [e.memory_id for e in rag.evidence], rag.retrieval_latency_ms, rag.generation_latency_ms
        results = retriever.retrieve(RetrievalQuery(text=question, mode=mode, final_limit=request.k, semantic_limit=max(10, request.k)))
        return None, [str(r.memory_id) for r in results], 0.0, 0.0

    cases = [
        EvalCase(case_id=c.case_id or f"q-{i + 1:03d}", question=c.question, expected_memory_ids=[str(m) for m in c.expected_memory_ids],
                 anchor_memory_id=str(c.anchor_memory_id) if c.anchor_memory_id else None)
        for i, c in enumerate(request.cases)
    ]
    run = EvaluationRunner(retrieval_fn=retrieval_fn, run_name="console").evaluate(
        cases, [RetrievalMode(m) for m in runnable], k=request.k
    )

    payload = {
        "run_id": str(run.run_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "k": request.k,
        "embedding_model": f"{type(embedding_provider).__name__}(dimension={embedding_provider.get_dimension()})",
        "modes_run": runnable,
        "unavailable_modes": {m: f"needs {', '.join(s)}" for m, s in unavailable.items() if s},
        "per_mode": run.per_mode,
        "failure_taxonomy": run.failure_taxonomy,
        "cases": [
            {
                "case_id": r.case_id,
                "question": r.question,
                "mode": r.mode.value,
                "labeled": r.labeled,
                "recall_at_5": r.recall_at_5,
                "recall_at_k": r.recall_at_k,
                "mrr": r.mrr,
                "groundedness": r.groundedness,
                "citation_accuracy": r.citation_accuracy,
                "retrieved_memory_ids": r.retrieved_memory_ids[: request.k],
                "latency_ms": r.total_latency_ms,
                "error": r.error,
            }
            for r in run.case_results
        ],
    }

    # Keep the run in history. A history failure never fails the run itself.
    principal = current_principal()
    payload["persisted"] = False
    if _may_persist(principal):
        try:
            with SessionLocal() as session:
                store.save_run(
                    session, payload,
                    expected={c.case_id: c.expected_memory_ids for c in cases},
                    anchors={c.case_id: c.anchor_memory_id for c in cases},
                    tenant_id=principal.tenant_id if principal else None,
                    llm_model=getattr(llm_provider, "get_model_name", lambda: None)() if "agentic" in runnable else None,
                    commit=os.getenv("GIT_SHA") or None,
                )
            payload["persisted"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Evaluation run %s not saved to history: %s", payload["run_id"], exc)
    return payload


@router.get("/evaluation/history")
def evaluation_history(limit: int = 50) -> dict:
    """Saved evaluation runs, newest first (summaries without per-case rows)."""
    principal = current_principal()
    with SessionLocal() as session:
        runs = store.list_runs(session, tenant_id=principal.tenant_id if principal else None, limit=max(1, min(limit, 200)))
    return {"runs": runs}


@router.get("/evaluation/history/{run_id}")
def evaluation_run(run_id: UUID) -> dict:
    """One saved run in the same shape as POST /evaluation/runs, plus labels."""
    principal = current_principal()
    with SessionLocal() as session:
        run = store.get_run(session, run_id, tenant_id=principal.tenant_id if principal else None)
    if run is None:
        raise HTTPException(status_code=404, detail="No saved evaluation run with that ID")
    return run
