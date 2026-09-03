from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, *_args, **_kwargs):
        return None


def _session_local():
    return _FakeSession()


class _FakeQdrantClient:
    def __init__(self, _url):
        self._url = _url

    def get_collections(self):
        return {"collections": []}


class _FakeDriver:
    def verify_connectivity(self):
        return None

    def close(self):
        return None


def _fake_settings(provider: str, api_key: str | None, model: str = "gpt-5.6-terra"):
    return SimpleNamespace(
        LLM_PROVIDER=provider,
        OPENAI_API_KEY=api_key,
        LLM_MODEL=model,
        LLM_TIMEOUT_SECONDS=15.0,
        QDRANT_URL="http://qdrant:6333",
        NEO4J_URI="bolt://neo4j:7687",
        NEO4J_USERNAME="neo4j",
        NEO4J_PASSWORD="aegisops",
    )


def test_system_health_llm_unconfigured_when_key_missing():
    with patch("app.core.config.get_settings", return_value=_fake_settings("openai", None)), patch(
        "app.db.session.SessionLocal", _session_local
    ), patch("qdrant_client.QdrantClient", _FakeQdrantClient), patch(
        "neo4j.GraphDatabase.driver", return_value=_FakeDriver()
    ):
        response = TestClient(app).get("/api/v1/system/health")

    assert response.status_code == 200
    llm = response.json()["services"]["llm"]
    assert llm["status"] == "unconfigured"
    assert llm["provider"] == "openai"
    assert llm["model"] == "gpt-5.6-terra"


def test_system_health_llm_healthy_when_openai_configured():
    with patch("app.core.config.get_settings", return_value=_fake_settings("openai", "test-key")), patch(
        "app.db.session.SessionLocal", _session_local
    ), patch("qdrant_client.QdrantClient", _FakeQdrantClient), patch(
        "neo4j.GraphDatabase.driver", return_value=_FakeDriver()
    ), patch("app.graphrag.providers.OpenAIProvider", return_value=object()):
        response = TestClient(app).get("/api/v1/system/health")

    assert response.status_code == 200
    llm = response.json()["services"]["llm"]
    assert llm["status"] == "healthy"
    assert llm["provider"] == "openai"
    assert llm["model"] == "gpt-5.6-terra"