"""
Process-wide connection management for the projection stores.

Why this exists
---------------
Earlier versions built a brand-new Qdrant client and Neo4j driver on *every*
request (and re-ran Neo4j constraint bootstrap each time). With a store that
was down or still starting, each request blocked on library default timeouts
(~35 s observed) — longer than the UI's HTTP timeout — so pages failed even
for PostgreSQL-only operations such as listing memories.

This module keeps one client per store for the life of the process and adds:

* short connect timeouts (``PROJECTION_CONNECT_TIMEOUT_SECONDS``),
* a failure cool-down (``PROJECTION_RETRY_SECONDS``): after a failed connect,
  callers get "unavailable" immediately instead of re-paying the timeout,
* one-time Neo4j constraint bootstrap and Qdrant collection check,
* explicit ``close_all()`` for the FastAPI lifespan.

PostgreSQL remains the canonical store and is never gated by this module.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class _Slot:
    """State for one lazily-connected, cached resource."""

    resource: Any = None
    last_error: Optional[str] = None
    failed_at: Optional[float] = None
    connected_at: Optional[float] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class ProjectionConnections:
    """Cached, timeout-bounded connections to Qdrant and Neo4j."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        qdrant_factory: Optional[Callable[[Settings], Any]] = None,
        neo4j_factory: Optional[Callable[[Settings], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or get_settings()
        self._qdrant_factory = qdrant_factory or _default_qdrant_factory
        self._neo4j_factory = neo4j_factory or _default_neo4j_factory
        self._clock = clock
        self._qdrant = _Slot()
        self._neo4j = _Slot()
        self._graph_bootstrapped = False
        self._semantic_index: Any = None
        self._graph_index: Any = None

    # ------------------------------------------------------------------ core
    @property
    def retry_seconds(self) -> float:
        return float(self._settings.PROJECTION_RETRY_SECONDS)

    def _get(self, slot: _Slot, factory: Callable[[Settings], Any], name: str) -> Any:
        if slot.resource is not None:
            return slot.resource
        now = self._clock()
        if slot.failed_at is not None and now - slot.failed_at < self.retry_seconds:
            return None  # inside cool-down: fail fast
        with slot.lock:
            if slot.resource is not None:
                return slot.resource
            try:
                slot.resource = factory(self._settings)
                slot.connected_at = self._clock()
                slot.last_error = None
                slot.failed_at = None
                logger.info("Connected to %s", name)
            except Exception as exc:  # noqa: BLE001 — any failure means unavailable
                slot.resource = None
                slot.last_error = f"{type(exc).__name__}: {exc}"
                slot.failed_at = self._clock()
                logger.warning("%s unavailable (retry in %.0fs): %s", name, self.retry_seconds, exc)
        return slot.resource

    def _invalidate(self, slot: _Slot, error: Exception, closer: Optional[Callable[[Any], None]] = None) -> None:
        with slot.lock:
            if slot.resource is not None and closer is not None:
                try:
                    closer(slot.resource)
                except Exception:  # noqa: BLE001
                    pass
            slot.resource = None
            slot.last_error = f"{type(error).__name__}: {error}"
            slot.failed_at = self._clock()

    # --------------------------------------------------------------- clients
    def qdrant_client(self) -> Any:
        return self._get(self._qdrant, self._qdrant_factory, "Qdrant")

    def neo4j_driver(self) -> Any:
        return self._get(self._neo4j, self._neo4j_factory, "Neo4j")

    def semantic_index(self, embedding_provider: Any) -> Any:
        """Return a cached QdrantSemanticIndex, or None when Qdrant is unavailable."""
        client = self.qdrant_client()
        if client is None:
            return None
        if self._semantic_index is not None and self._semantic_index.client is client:
            return self._semantic_index
        try:
            from app.semantic.qdrant_impl import QdrantSemanticIndex

            self._semantic_index = QdrantSemanticIndex(
                qdrant_client=client,
                embedding_provider=embedding_provider,
                collection_name=self._settings.QDRANT_COLLECTION_NAME,
            )
            return self._semantic_index
        except Exception as exc:  # noqa: BLE001
            self._invalidate(self._qdrant, exc, _close_quietly)
            self._semantic_index = None
            return None

    def graph_index(self) -> Any:
        """Return a cached Neo4jGraphMemoryIndex (constraints bootstrapped once)."""
        driver = self.neo4j_driver()
        if driver is None:
            return None
        if self._graph_index is not None and self._graph_bootstrapped:
            return self._graph_index
        try:
            from app.graph.neo4j_impl import Neo4jGraphMemoryIndex

            index = Neo4jGraphMemoryIndex(driver=driver, database=self._settings.NEO4J_DATABASE)
            index.bootstrap_constraints()
            self._graph_index = index
            self._graph_bootstrapped = True
            return index
        except Exception as exc:  # noqa: BLE001
            self._invalidate(self._neo4j, exc, _close_quietly)
            self._graph_index = None
            self._graph_bootstrapped = False
            return None

    # ---------------------------------------------------------------- health
    def probe(self, name: str) -> dict[str, Any]:
        """Cheap liveness probe using the cached client. Never blocks past the connect timeout."""
        if name == "qdrant":
            slot, getter, closer = self._qdrant, self.qdrant_client, _close_quietly
            check = lambda c: c.get_collections()  # noqa: E731
            target = {"url": self._settings.QDRANT_URL}
        elif name == "neo4j":
            slot, getter, closer = self._neo4j, self.neo4j_driver, _close_quietly
            check = lambda d: d.verify_connectivity()  # noqa: E731
            target = {"uri": self._settings.NEO4J_URI}
        else:
            raise ValueError(f"unknown projection store: {name}")

        resource = getter()
        if resource is None:
            retry_in = None
            if slot.failed_at is not None:
                retry_in = max(0.0, self.retry_seconds - (self._clock() - slot.failed_at))
            return {"status": "unavailable", "error": slot.last_error or "not connected",
                    "retry_in_seconds": round(retry_in, 1) if retry_in is not None else None, **target}
        try:
            check(resource)
            return {"status": "healthy", **target}
        except Exception as exc:  # noqa: BLE001
            self._invalidate(slot, exc, closer)
            if name == "neo4j":
                self._graph_index = None
                self._graph_bootstrapped = False
            else:
                self._semantic_index = None
            return {"status": "unavailable", "error": slot.last_error, **target}

    # ------------------------------------------------------------- lifecycle
    def close_all(self) -> None:
        for slot in (self._qdrant, self._neo4j):
            with slot.lock:
                if slot.resource is not None:
                    _close_quietly(slot.resource)
                slot.resource = None
        self._semantic_index = None
        self._graph_index = None
        self._graph_bootstrapped = False


def _close_quietly(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001
            pass


def _default_qdrant_factory(settings: Settings) -> Any:
    from qdrant_client import QdrantClient

    timeout = max(1, int(round(settings.PROJECTION_CONNECT_TIMEOUT_SECONDS)))
    client = QdrantClient(url=settings.QDRANT_URL, timeout=timeout, check_compatibility=False)
    try:
        client.get_collections()
    except Exception:
        _close_quietly(client)
        raise
    return client


def _default_neo4j_factory(settings: Settings) -> Any:
    from neo4j import GraphDatabase

    t = float(settings.PROJECTION_CONNECT_TIMEOUT_SECONDS)
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        connection_timeout=t,
        connection_acquisition_timeout=t * 2,
        max_transaction_retry_time=t * 2,
    )
    try:
        driver.verify_connectivity()
    except Exception:
        _close_quietly(driver)
        raise
    return driver


_connections: Optional[ProjectionConnections] = None
_connections_lock = threading.Lock()


def get_connections() -> ProjectionConnections:
    global _connections
    if _connections is None:
        with _connections_lock:
            if _connections is None:
                _connections = ProjectionConnections()
    return _connections


def reset_connections(new: Optional[ProjectionConnections] = None) -> None:
    """Close and replace the process-wide manager (used by lifespan and tests)."""
    global _connections
    with _connections_lock:
        if _connections is not None:
            _connections.close_all()
        _connections = new
