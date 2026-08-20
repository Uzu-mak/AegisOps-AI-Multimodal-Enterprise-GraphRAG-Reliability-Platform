"""SemanticIndexingService - orchestrates semantic indexing after PostgreSQL commits."""

import logging
from datetime import datetime
from uuid import UUID

from app.db.models.memory import MemoryRecord
from app.embeddings.provider import EmbeddingProvider
from app.semantic.index import SemanticIndexError, SemanticMemoryIndex, VectorRecord

logger = logging.getLogger(__name__)


class SemanticIndexingService:
    """
    Orchestrates semantic indexing of memories.
    Called by MemoryService AFTER PostgreSQL commit.
    All Qdrant failures are logged but do NOT raise exceptions (best-effort).
    """

    def __init__(
        self,
        semantic_index: SemanticMemoryIndex,
        embedding_provider: EmbeddingProvider,
    ):
        """
        Initialize semantic indexing service.

        Args:
            semantic_index: SemanticMemoryIndex implementation (Qdrant)
            embedding_provider: EmbeddingProvider for text embeddings
        """
        self.semantic_index = semantic_index
        self.embedding_provider = embedding_provider

    def _build_semantic_text(self, memory: MemoryRecord) -> str:
        """
        Build searchable text from memory fields.

        Args:
            memory: MemoryRecord ORM instance

        Returns:
            Combined text for embedding
        """
        parts = []
        if memory.title:
            parts.append(memory.title)
        if memory.content:
            parts.append(memory.content)
        return " ".join(parts)

    def _build_vector_record(self, memory: MemoryRecord) -> VectorRecord:
        """
        Build VectorRecord payload from memory.

        Args:
            memory: MemoryRecord ORM instance

        Returns:
            VectorRecord with metadata
        """
        return VectorRecord(
            memory_id=memory.id,
            memory_type=str(memory.memory_type),
            status=str(memory.status),
            asset_id=memory.asset_id,
            facility_id=memory.facility_id,
            source_type=memory.source_type,
            created_at=memory.created_at,
            importance=float(memory.importance),
            confidence=float(memory.confidence),
        )

    def index_memory(self, memory: MemoryRecord) -> None:
        """
        Index a memory by embedding and storing in Qdrant.
        Called AFTER PostgreSQL commit by MemoryService.
        Raises SemanticIndexError on failure; MemoryService catches and logs.

        Args:
            memory: MemoryRecord to index
        """
        try:
            # Build semantic text
            text = self._build_semantic_text(memory)
            if not text.strip():
                logger.warning(
                    f"Memory {memory.id} has no semantic content to index"
                )
                return

            # Build vector record
            record = self._build_vector_record(memory)

            # Index in Qdrant
            self.semantic_index.index_memory(memory.id, text, record)
            logger.info(f"Indexed memory {memory.id} in Qdrant")
        except SemanticIndexError:
            raise
        except Exception as exc:
            raise SemanticIndexError(
                f"Unexpected error indexing memory {memory.id}: {exc}"
            ) from exc

    def update_memory_index(
        self,
        memory: MemoryRecord,
        semantic_fields_changed: bool = True,
    ) -> None:
        """
        Re-index a memory after update.
        Called AFTER PostgreSQL commit by MemoryService.
        Only re-indexes if semantic fields (title, content, confidence, importance) changed.
        Failure is logged and non-fatal.

        Args:
            memory: MemoryRecord with updated values
            semantic_fields_changed: Whether semantic fields were modified
        """
        if not semantic_fields_changed:
            logger.debug(
                f"Skipping re-index for {memory.id}; only non-semantic fields changed"
            )
            return

        try:
            # Re-embed and re-index
            text = self._build_semantic_text(memory)
            record = self._build_vector_record(memory)
            self.semantic_index.index_memory(memory.id, text, record)
            logger.info(f"Updated index for memory {memory.id}")
        except SemanticIndexError:
            raise
        except Exception as exc:
            raise SemanticIndexError(
                f"Unexpected error updating index for {memory.id}: {exc}"
            ) from exc

    def archive_memory(self, memory_id: UUID) -> None:
        """
        Mark a memory as archived in Qdrant.
        Called AFTER PostgreSQL commit by MemoryService.
        Failure is logged and non-fatal.

        Args:
            memory_id: UUID of memory to archive
        """
        try:
            self.semantic_index.mark_inactive(memory_id, "archived")
            logger.info(f"Archived memory {memory_id} in Qdrant")
        except SemanticIndexError:
            raise
        except Exception as exc:
            raise SemanticIndexError(
                f"Unexpected error archiving memory {memory_id}: {exc}"
            ) from exc

    def dispute_memory(self, memory_id: UUID) -> None:
        """
        Mark a memory as disputed in Qdrant.
        Called AFTER PostgreSQL commit by MemoryService.
        Failure is logged and non-fatal.

        Args:
            memory_id: UUID of memory to dispute
        """
        try:
            self.semantic_index.mark_inactive(memory_id, "disputed")
            logger.info(f"Disputed memory {memory_id} in Qdrant")
        except SemanticIndexError:
            raise
        except Exception as exc:
            raise SemanticIndexError(
                f"Unexpected error disputing memory {memory_id}: {exc}"
            ) from exc

    def supersede_memory(self, old_memory_id: UUID, new_memory: MemoryRecord) -> None:
        """
        Remove old memory from Qdrant index; index new memory.
        Called AFTER PostgreSQL commit by MemoryService.
        PostgreSQL retains both records; old is just removed from search.
        Failure is logged and non-fatal.

        Args:
            old_memory_id: UUID of superseded memory
            new_memory: New MemoryRecord to index
        """
        try:
            # Remove old from index (searchable only; PostgreSQL record remains)
            self.semantic_index.remove_memory(old_memory_id)
            logger.info(f"Removed superseded memory {old_memory_id} from Qdrant")

            # Index new replacement
            self.index_memory(new_memory)
            logger.info(f"Indexed replacement memory {new_memory.id} in Qdrant")
        except SemanticIndexError:
            raise
        except Exception as exc:
            raise SemanticIndexError(
                f"Unexpected error superseding memory {old_memory_id}: {exc}"
            ) from exc
