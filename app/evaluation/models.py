"""
Evaluation models — structured benchmarking for AegisOps retrieval and RAG.

Metrics are computed ONLY from actual benchmark runs. No fabricated numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class RetrievalMode(str, Enum):
    SEMANTIC = "semantic"
    GRAPH = "graph"
    HYBRID = "hybrid"
    AGENTIC = "agentic"


class FailureCategory(str, Enum):
    RETRIEVAL_FAILURE = "retrieval_failure"
    GRAPH_TRAVERSAL_FAILURE = "graph_traversal_failure"
    CONTEXT_CONSTRUCTION_FAILURE = "context_construction_failure"
    REASONING_FAILURE = "reasoning_failure"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CITATION_FAILURE = "citation_failure"
    INCOMPLETE_ANSWER = "incomplete_answer"
    PROVIDER_FAILURE = "provider_failure"
    NO_FAILURE = "no_failure"


@dataclass
class EvalCase:
    """A single benchmark test case."""

    case_id: str
    question: str
    expected_memory_ids: list[str] = field(default_factory=list)
    expected_answer_keywords: list[str] = field(default_factory=list)
    description: str = ""
    asset_id: Optional[str] = None
    incident_id: Optional[str] = None


@dataclass
class EvalCaseResult:
    """Result of running one EvalCase."""

    case_id: str
    question: str
    mode: RetrievalMode
    retrieved_memory_ids: list[str] = field(default_factory=list)
    answer: str = ""
    success: bool = False
    recall_at_k: float = 0.0  # Recall@K
    mrr: float = 0.0          # Mean Reciprocal Rank
    groundedness: float = 0.0  # Fraction of sentences with citations
    citation_accuracy: float = 0.0
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failure_category: FailureCategory = FailureCategory.NO_FAILURE
    error: Optional[str] = None


@dataclass
class EvalRun:
    """A complete evaluation run across all cases and modes."""

    run_id: UUID = field(default_factory=uuid4)
    run_name: str = ""
    modes_tested: list[RetrievalMode] = field(default_factory=list)
    case_results: list[EvalCaseResult] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Aggregate metrics (computed after all cases)
    mean_recall_at_k: float = 0.0
    mean_mrr: float = 0.0
    mean_groundedness: float = 0.0
    mean_citation_accuracy: float = 0.0
    mean_total_latency_ms: float = 0.0
    task_success_rate: float = 0.0
    total_cases: int = 0
    failed_cases: int = 0
    failure_taxonomy: dict[str, int] = field(default_factory=dict)
