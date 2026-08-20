"""Neo4j health and bootstrap integration tests."""
from __future__ import annotations

import pytest
from neo4j import Driver, GraphDatabase

from app.core.config import get_settings
from app.graph.neo4j_config import UNIQUENESS_CONSTRAINTS
from app.graph.neo4j_impl import Neo4jGraphMemoryIndex


@pytest.fixture(scope="module")
def neo4j_driver() -> Driver:
    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def graph_index(neo4j_driver: Driver) -> Neo4jGraphMemoryIndex:
    settings = get_settings()
    return Neo4jGraphMemoryIndex(driver=neo4j_driver, database=settings.NEO4J_DATABASE)


class TestNeo4jHealth:

    def test_driver_connects(self, neo4j_driver: Driver):
        """Neo4j driver can connect and verify connectivity."""
        neo4j_driver.verify_connectivity()  # raises if unreachable

    def test_database_reachable(self, neo4j_driver: Driver):
        """Database is reachable and returns a result."""
        settings = get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run("RETURN 1 AS n")
            record = result.single()
        assert record["n"] == 1

    def test_bootstrap_constraints_succeeds(self, graph_index: Neo4jGraphMemoryIndex):
        """Constraint bootstrap completes without error."""
        graph_index.bootstrap_constraints()  # must not raise

    def test_bootstrap_constraints_idempotent(self, graph_index: Neo4jGraphMemoryIndex):
        """Repeated constraint bootstrap does not raise."""
        graph_index.bootstrap_constraints()
        graph_index.bootstrap_constraints()

    def test_constraints_created(self, neo4j_driver: Driver):
        """At least one uniqueness constraint exists for each expected label."""
        settings = get_settings()
        with neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run("SHOW CONSTRAINTS YIELD labelsOrTypes, properties")
            existing = [
                (row["labelsOrTypes"][0], row["properties"][0])
                for row in result
                if row["labelsOrTypes"] and row["properties"]
            ]

        expected_labels = {label for label, _ in UNIQUENESS_CONSTRAINTS}
        found_labels = {label for label, _ in existing}
        for label in expected_labels:
            assert label in found_labels, f"Missing constraint for label: {label}"
