"""Qdrant-based implementation of SemanticMemoryIndex."""

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams

from app.embeddings.provider import EmbeddingProvider
from app.semantic.index import (
    SemanticIndexError,
    SemanticMemoryIndex,
    SemanticSearchResult,
    VectorRecord,
)
from app.semantic.qdrant_config import COLLECTION_NAME

logger = logging.getLogger(__name__)


class QdrantSemanticIndex(SemanticMemoryIndex):
    """Qdrant-backed semantic memory index implementation."""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_provider: EmbeddingProvider,
        collection_name: str = COLLECTION_NAME,
    ):
        """
        Initialize Qdrant index.

        Args:
            qdrant_client: Connected QdrantClient instance
            embedding_provider: EmbeddingProvider for embedding text
            collection_name: Name of Qdrant collection
        """
        self.client = qdrant_client
        self.embedding_provider = embedding_provider
        self.collection_name = collection_name
        self._ensure_collection_exists()

    def _ensure_collection_exists(self) -> None:
        """Create collection if it doesn't exist."""
        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            # Collection doesn't exist; create it
            logger.info(f"Creating Qdrant collection: {self.collection_name}")
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_provider.get_dimension(),
                        distance=Distance.COSINE,
                    ),
                )
            except Exception as exc:
                raise SemanticIndexError(
                    f"Failed to create collection {self.collection_name}: {exc}"
                ) from exc

    def index_memory(
        self, memory_id: UUID, text: str, record: VectorRecord
    ) -> None:
        """
        Index a memory by embedding its text and storing vector + metadata.

        Args:
            memory_id: UUID of the memory
            text: Text to embed (title + content + context)
            record: VectorRecord with metadata

        Raises:
            SemanticIndexError: If indexing fails (non-fatal)
        """
        try:
            # Generate embedding
            vector = self.embedding_provider.embed_text(text)

            # Use UUID string directly as Qdrant point ID
            point_id = str(memory_id)

            # Create point with vector and payload
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload=record.to_dict(),
            )

            # Upsert point (insert or update)
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point],
            )

            logger.debug(f"Indexed memory {memory_id} in Qdrant")
        except Exception as exc:
            raise SemanticIndexError(
                f"Failed to index memory {memory_id}: {exc}"
            ) from exc

    def get_vector_record(self, memory_id: UUID) -> Optional[VectorRecord]:
        """
        Retrieve metadata stored alongside a vector.
        Returns None if not found in Qdrant.

        Args:
            memory_id: UUID of the memory

        Returns:
            VectorRecord if found, None otherwise
        """
        try:
            point_id = str(memory_id)
            point = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
            )
            if not point:
                return None

            payload = point[0].payload
            return VectorRecord(
                memory_id=UUID(payload["memory_id"]),
                memory_type=payload["memory_type"],
                status=payload["status"],
                asset_id=payload.get("asset_id"),
                facility_id=payload.get("facility_id"),
                source_type=payload["source_type"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                importance=payload["importance"],
                confidence=payload["confidence"],
            )
        except Exception as exc:
            logger.warning(
                f"Failed to get vector record for {memory_id}: {exc}"
            )
            return None

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
            filters: Optional metadata filters

        Returns:
            List of SemanticSearchResult
        """
        try:
            # Search in Qdrant
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=filters,
                limit=limit,
            )

            # Convert to SemanticSearchResult
            results = []
            for sr in search_results:
                payload = sr.payload
                record = VectorRecord(
                    memory_id=UUID(payload["memory_id"]),
                    memory_type=payload["memory_type"],
                    status=payload["status"],
                    asset_id=payload.get("asset_id"),
                    facility_id=payload.get("facility_id"),
                    source_type=payload["source_type"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                    importance=payload["importance"],
                    confidence=payload["confidence"],
                )
                results.append(
                    SemanticSearchResult(
                        memory_id=UUID(payload["memory_id"]),
                        score=sr.score,
                        record=record,
                    )
                )
            return results
        except Exception as exc:
            raise SemanticIndexError(f"Search failed: {exc}") from exc

    def remove_memory(self, memory_id: UUID) -> None:
        """
        Remove a memory's vector record from Qdrant.

        Args:
            memory_id: UUID of memory

        Raises:
            SemanticIndexError: If removal fails (non-fatal)
        """
        try:
            point_id = str(memory_id)
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[point_id]),
            )
            logger.debug(f"Removed memory {memory_id} from Qdrant")
        except Exception as exc:
            raise SemanticIndexError(
                f"Failed to remove memory {memory_id}: {exc}"
            ) from exc

    def mark_inactive(self, memory_id: UUID, new_status: str) -> None:
        """
        Mark a memory as archived/disputed without removing vector.
        Updates status in Qdrant payload only.

        Args:
            memory_id: UUID of memory
            new_status: New status string (e.g., "archived", "disputed")

        Raises:
            SemanticIndexError: If update fails (non-fatal)
        """
        try:
            point_id = str(memory_id)
            # Use set_payload to update only the status field (efficient)
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"status": new_status},
                points=PointIdsList(points=[point_id]),
            )
            logger.debug(f"Marked memory {memory_id} as {new_status} in Qdrant")
        except Exception as exc:
            # HTTP 404 means the point does not exist — treat as idempotent no-op.
            # This is expected when a memory was never indexed (e.g. Qdrant was
            # unavailable at create time). Do not create a point here.
            if getattr(exc, "status_code", None) == 404:
                logger.warning(
                    f"Memory {memory_id} not found in Qdrant; "
                    f"mark_inactive('{new_status}') is a no-op"
                )
                return
            raise SemanticIndexError(
                f"Failed to mark memory {memory_id} as {new_status}: {exc}"
            ) from exc
