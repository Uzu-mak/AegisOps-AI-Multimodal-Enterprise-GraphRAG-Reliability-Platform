from ui.framework import capability_available


def test_capability_available_returns_false_when_required_service_missing():
    services = {
        "api": {"status": "healthy"},
        "qdrant": {"status": "unavailable"},
    }

    available, reason = capability_available(services, ["api", "qdrant"])

    assert available is False
    assert "qdrant" in reason.lower()


def test_capability_available_returns_true_when_required_services_present():
    services = {
        "api": {"status": "healthy"},
        "neo4j": {"status": "degraded"},
    }

    available, reason = capability_available(services, ["api", "neo4j"])

    assert available is True
    assert reason == ""
