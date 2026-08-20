"""
WorkingMemory — bounded short-term context buffer.

Working memory is ephemeral: it holds the current request context,
retrieved evidence, tool outputs, and temporary hypotheses.

It is NEVER automatically promoted to long-term PostgreSQL memory.
Promotion is an explicit decision via MemoryCandidate + PromotionPolicy.

Implementation: thread-local Python bounded deque. No persistence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4


WorkingItemType = Literal[
    "observation",
    "retrieved_evidence",
    "tool_output",
    "hypothesis",
    "user_input",
    "agent_step",
    "critic_result",
    "context",
]


@dataclass
class WorkingMemoryItem:
    """A single item in working memory."""

    item_id: UUID = field(default_factory=uuid4)
    item_type: WorkingItemType = "context"
    content: str = ""
    source: str = ""
    confidence: float = 0.5
    importance: float = 0.5
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_memory_ids: list[UUID] = field(default_factory=list)


class WorkingMemory:
    """
    Bounded ephemeral working memory.

    Contents are lost when the WorkingMemory instance is discarded.
    To persist content to long-term memory, create a MemoryCandidate
    and pass it through a PromotionPolicy.
    """

    def __init__(self, max_items: int = 50) -> None:
        self._items: deque[WorkingMemoryItem] = deque(maxlen=max_items)
        self.max_items = max_items

    def add(self, item: WorkingMemoryItem) -> None:
        """Add an item; evicts oldest when at capacity."""
        self._items.append(item)

    def add_observation(
        self,
        content: str,
        source: str = "",
        confidence: float = 0.5,
        importance: float = 0.5,
        metadata: Optional[dict] = None,
    ) -> WorkingMemoryItem:
        """Convenience helper for adding an observation."""
        item = WorkingMemoryItem(
            item_type="observation",
            content=content,
            source=source,
            confidence=confidence,
            importance=importance,
            metadata=metadata or {},
        )
        self.add(item)
        return item

    def add_evidence(
        self,
        content: str,
        evidence_memory_ids: list[UUID],
        source: str = "retrieval",
    ) -> WorkingMemoryItem:
        """Add a retrieved evidence item referencing canonical memory UUIDs."""
        item = WorkingMemoryItem(
            item_type="retrieved_evidence",
            content=content,
            source=source,
            evidence_memory_ids=evidence_memory_ids,
        )
        self.add(item)
        return item

    def get_all(self) -> list[WorkingMemoryItem]:
        """Return all items in insertion order."""
        return list(self._items)

    def get_by_type(self, item_type: WorkingItemType) -> list[WorkingMemoryItem]:
        return [i for i in self._items if i.item_type == item_type]

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"WorkingMemory(items={len(self._items)}, max={self.max_items})"
