"""ProjectionConnections: caching, fail-fast cool-down, one-time bootstrap, cleanup."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.connections import ProjectionConnections


def _settings(retry=15.0):
    return SimpleNamespace(
        QDRANT_URL="http://qdrant:6333",
        QDRANT_COLLECTION_NAME="memories",
        NEO4J_URI="bolt://neo4j:7687",
        NEO4J_USERNAME="neo4j",
        NEO4J_PASSWORD="x",
        NEO4J_DATABASE="neo4j",
        PROJECTION_CONNECT_TIMEOUT_SECONDS=2.0,
        PROJECTION_RETRY_SECONDS=retry,
    )


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Driver:
    def __init__(self):
        self.closed = False
        self.verified = 0

    def verify_connectivity(self):
        self.verified += 1

    def close(self):
        self.closed = True


def test_client_is_created_once_and_reused():
    calls = []

    def factory(_s):
        calls.append(1)
        return _Driver()

    conns = ProjectionConnections(_settings(), qdrant_factory=factory, neo4j_factory=factory)
    first = conns.neo4j_driver()
    assert conns.neo4j_driver() is first
    assert len(calls) == 1


def test_failed_connect_fails_fast_during_cooldown_then_retries():
    clock = _Clock()
    attempts = []

    def failing(_s):
        attempts.append(clock.t)
        raise ConnectionError("refused")

    conns = ProjectionConnections(_settings(retry=15), qdrant_factory=failing, neo4j_factory=failing, clock=clock)
    assert conns.qdrant_client() is None
    clock.t += 5
    assert conns.qdrant_client() is None  # inside cool-down: no new attempt
    assert len(attempts) == 1
    clock.t += 11
    assert conns.qdrant_client() is None  # cool-down elapsed: retried
    assert len(attempts) == 2


def test_probe_reports_retry_window_and_error():
    clock = _Clock()

    def failing(_s):
        raise ConnectionError("refused")

    conns = ProjectionConnections(_settings(retry=15), qdrant_factory=failing, neo4j_factory=failing, clock=clock)
    result = conns.probe("neo4j")
    assert result["status"] == "unavailable"
    assert "refused" in result["error"]
    assert result["retry_in_seconds"] == 15.0


def test_probe_failure_invalidates_cached_driver():
    driver = _Driver()

    def broken_verify():
        raise ConnectionError("went away")

    conns = ProjectionConnections(_settings(), qdrant_factory=lambda s: _Driver(), neo4j_factory=lambda s: driver)
    assert conns.probe("neo4j")["status"] == "healthy"
    driver.verify_connectivity = broken_verify
    assert conns.probe("neo4j")["status"] == "unavailable"
    assert driver.closed is True


def test_graph_constraints_bootstrapped_once(monkeypatch):
    bootstraps = []

    class FakeIndex:
        def __init__(self, driver, database):
            self.driver = driver

        def bootstrap_constraints(self):
            bootstraps.append(1)

    import app.graph.neo4j_impl as neo4j_impl

    monkeypatch.setattr(neo4j_impl, "Neo4jGraphMemoryIndex", FakeIndex)
    conns = ProjectionConnections(_settings(), qdrant_factory=lambda s: _Driver(), neo4j_factory=lambda s: _Driver())
    a = conns.graph_index()
    b = conns.graph_index()
    assert a is b
    assert len(bootstraps) == 1


def test_close_all_closes_resources():
    q, n = _Driver(), _Driver()
    conns = ProjectionConnections(_settings(), qdrant_factory=lambda s: q, neo4j_factory=lambda s: n)
    conns.qdrant_client()
    conns.neo4j_driver()
    conns.close_all()
    assert q.closed and n.closed


def test_qdrant_factory_uses_supported_client_constructor(monkeypatch):
    from app.core.connections import _default_qdrant_factory
    from unittest.mock import MagicMock
    import qdrant_client
    actual=qdrant_client.QdrantClient
    client=MagicMock()
    def constructor(*args, **kwargs):
        import inspect
        supported=inspect.signature(actual.__init__).parameters
        assert "check_compatibility" not in kwargs or "check_compatibility" in supported
        return client
    monkeypatch.setattr(qdrant_client,"QdrantClient",constructor)
    assert _default_qdrant_factory(_settings()) is client
