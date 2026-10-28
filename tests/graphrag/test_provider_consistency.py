"""LLM provider selection and deterministic provider evidence accounting."""
from __future__ import annotations

from types import SimpleNamespace

from app.graphrag.context import build_context
from app.graphrag.provider import LLMMessage
from app.graphrag.providers import DeterministicTestProvider, create_llm_provider


def _settings(provider, key):
    return SimpleNamespace(LLM_PROVIDER=provider, OPENAI_API_KEY=key, LLM_MODEL="m", LLM_TIMEOUT_SECONDS=1.0)


def test_deterministic_provider_reports_zero_evidence_when_none_retrieved():
    ctx = build_context(question="why?", results=[])
    resp = DeterministicTestProvider().generate(
        [LLMMessage(role="system", content=ctx.system_prompt), LLMMessage(role="user", content=ctx.user_prompt)]
    )
    assert "Based on 0 retrieved memory records" in resp.content


def test_openai_without_key_falls_back_to_labelled_test_provider():
    assert isinstance(create_llm_provider(_settings("openai", None)), DeterministicTestProvider)


def test_openai_construction_failure_falls_back_instead_of_500(monkeypatch):
    import app.graphrag.providers as providers

    def boom(*_a, **_k):
        raise providers.LLMProviderError("openai package is required")

    monkeypatch.setattr(providers, "OpenAIProvider", boom)
    assert isinstance(create_llm_provider(_settings("openai", "k")), DeterministicTestProvider)
