"""
Agent state models — structured trace for inspectable, auditable agent runs.

Agent state is separate from canonical memory. Tool calls, intermediate results,
and working hypotheses are NOT automatically committed to PostgreSQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4


class AgentStepType(str, Enum):
    RETRIEVAL = "retrieval"
    GRAPH_REASONING = "graph_reasoning"
    TOOL_CALL = "tool_call"
    CRITIC = "critic"
    SYNTHESIS = "synthesis"
    USER_INPUT = "user_input"
    WORKING_MEMORY_UPDATE = "working_memory_update"


@dataclass
class ToolCall:
    """Record of a single tool invocation."""

    tool_name: str
    arguments: dict[str, Any]
    result: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class AgentStep:
    """One step in an agent's execution trace."""

    step_id: UUID = field(default_factory=uuid4)
    step_type: AgentStepType = AgentStepType.TOOL_CALL
    description: str = ""
    tool_call: Optional[ToolCall] = None
    retrieved_memory_ids: list[UUID] = field(default_factory=list)
    working_memory_snapshot: int = 0  # count of items
    output_summary: str = ""
    latency_ms: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class CriticResult:
    """Result from the Critic/Verifier agent."""

    is_supported: bool
    unsupported_claims: list[str] = field(default_factory=list)
    citations_valid: bool = True
    confidence: float = 1.0
    notes: str = ""


@dataclass
class AgentTrace:
    """
    Complete trace of one agent run.

    Stored in memory for inspection; not automatically persisted to PostgreSQL.
    Provides full auditability of reasoning steps, tool calls, and evidence.
    """

    trace_id: UUID = field(default_factory=uuid4)
    task: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    critic_result: Optional[CriticResult] = None
    evidence_memory_ids: list[UUID] = field(default_factory=list)
    total_latency_ms: float = 0.0
    status: str = "pending"  # pending | running | complete | failed
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def add_step(self, step: AgentStep) -> None:
        self.steps.append(step)
