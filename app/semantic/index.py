from typing import Any, Optional, Protocol
from uuid import UUID
from datetime import datetime


class VectorRecord:
    """Payload stored alongside vector in Qdrant."""

    def __init__(
        self,
        memory_id: UUID,
        memory_type: str,
        status: str,
        asset_id: Optional[str],
        facility_id: Optional[str],
        source_type: str,
        created_at: datetime,
        importance: float,
        confidence: float,
    ):
        self.memory_id = memory_id
        self.memory_type = memory_type
        self.status = status
        self.asset_id = asset_id
        self.facility_id = facility_id
        self.source_type = source_type
        self.created_at = created_at
        self.importance = importance
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        """Convert to Qdrant payload dict."""
        return {
            "memory_id": str(self.memory_id),
            "memory_type": self.memory_type,
            "status": self.status,
            "asset_id": self.asset_id,
            "facility_id": self.facility_id,
            "source_type": self.source_type,
            "created_at": self.created_at.isoformat(),
            "importance": self.importance,
            "confidence": self.confidence,
        }


class SemanticSearchResult:
    """Result from semantic search."""

    def __init__(
        self,
        memory_id: UUID,
        score: float,
        record: VectorRecord,
    ):
        self.memory_id = memory_id
        self.score = score
        self.record = record


class SemanticMemoryIndex(Protocol):
    """
    Vector index for memories.
    Qdrant stores vectors + metadata; PostgreSQL remains canonical.
    """

    def index_memory(self, memory_id: UUID, text: str, record: VectorRecord) -> None:
        """
        Index a memory by embedding its text and storing vector + metadata.

        Args:
            memory_id: UUID of the memory (used as Qdrant point ID)
            text: Text to embed (title + content + context)
            record: VectorRecord with metadata

        Raises:
            SemanticIndexError: If indexing fails (non-fatal)
        """
        ...

    def get_vector_record(self, memory_id: UUID) -> Optional[VectorRecord]:
        """
        Retrieve metadata stored alongside a vector.
        Returns None if not found in Qdrant.
        """
        ...

    def search_similar(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[SemanticSearchResult]:
        """
        Search for semantically similar memories.

        Args:
            query_vector: Embedding vector to search
            limit: Max results
            filters: Optional metadata filters (e.g., {"status": "active"})

        Returns:
            List of results with memory_id, score, and metadata
        """
        ...

    def remove_memory(self, memory_id: UUID) -> None:
        """
        Remove a memory's vector record from Qdrant.
        Called on supersession or explicit deletion.

        Raises:
            SemanticIndexError: If removal fails (non-fatal)
        """
        ...

    def mark_inactive(self, memory_id: UUID, new_status: str) -> None:
        """
        Mark a memory as archived/disputed without removing vector.
        Updates status in Qdrant payload.

        Args:
            memory_id: UUID of memory
            new_status: New status string (e.g., "archived")

        Raises:
            SemanticIndexError: If update fails (non-fatal)
        """
        ...


class SemanticIndexError(Exception):
    """Raised when semantic indexing fails (non-fatal)."""

    pass
