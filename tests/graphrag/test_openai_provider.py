from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.graphrag.provider import LLMMessage, LLMProviderError
from app.graphrag.providers import (
    DeterministicTestProvider,
    LLMHealthState,
    OpenAIProvider,
    create_llm_provider,
    llm_health_from_settings,
)


def _settings(
    *,
    provider: str,
    model: str = "gpt-5.6-terra",
    api_key: str | None = None,
    timeout: float = 12.0,
):
    return SimpleNamespace(
        LLM_PROVIDER=provider,
        LLM_MODEL=model,
        OPENAI_API_KEY=api_key,
        LLM_TIMEOUT_SECONDS=timeout,
    )


class TestProviderSelection:
    def test_openai_selected_when_configured(self):
        settings = _settings(provider="openai", api_key="test-key")

        from app import graphrag
        from app.graphrag import providers

        original = providers.OpenAIProvider
        providers.OpenAIProvider = lambda api_key, model, timeout_seconds: SimpleNamespace(
            get_model_name=lambda: model,
            marker="openai",
        )
        try:
            provider = create_llm_provider(settings)
        finally:
            providers.OpenAIProvider = original

        assert getattr(provider, "marker", "") == "openai"

    def test_test_provider_selected_without_openai_key(self):
        settings = _settings(provider="openai", api_key=None)
        provider = create_llm_provider(settings)
        assert isinstance(provider, DeterministicTestProvider)

    def test_test_provider_still_works_without_network(self):
        provider = DeterministicTestProvider()
        response = provider.generate([LLMMessage(role="user", content="hello")])
        assert response.content
        assert response.model_name == "deterministic-test-v1"


class TestOpenAIProviderResponsesAPI:
    def test_model_propagated_and_text_extracted(self):
        usage = SimpleNamespace(input_tokens=11, output_tokens=7)
        response = SimpleNamespace(output_text="final answer", usage=usage)

        responses_api = SimpleNamespace(create=MagicMock(return_value=response))
        client = SimpleNamespace(responses=responses_api)

        provider = OpenAIProvider(
            api_key="test-key",
            model="gpt-5.6-terra",
            timeout_seconds=9.0,
            client=client,
        )
        result = provider.generate(
            [
                LLMMessage(role="system", content="sys"),
                LLMMessage(role="user", content="usr"),
            ]
        )

        assert result.model_name == "gpt-5.6-terra"
        assert result.content == "final answer"
        assert result.prompt_tokens == 11
        assert result.completion_tokens == 7
        call = responses_api.create.call_args
        assert call.kwargs["model"] == "gpt-5.6-terra"
        assert call.kwargs["input"][1]["content"][0]["text"] == "usr"

    def test_provider_failure_is_controlled(self):
        responses_api = SimpleNamespace(create=MagicMock(side_effect=RuntimeError("boom")))
        client = SimpleNamespace(responses=responses_api)
        provider = OpenAIProvider(
            api_key="test-key",
            model="gpt-5.6-terra",
            client=client,
        )

        with pytest.raises(LLMProviderError, match="OpenAI response generation failed"):
            provider.generate([LLMMessage(role="user", content="x")])


class TestLLMHealth:
    def test_missing_openai_key_is_unconfigured(self):
        health = llm_health_from_settings(_settings(provider="openai", api_key=None))
        assert health.status == LLMHealthState.UNCONFIGURED
        assert health.provider == "openai"
        assert health.model == "gpt-5.6-terra"

    def test_configured_openai_health_is_healthy(self):
        from app.graphrag import providers

        original = providers.OpenAIProvider
        providers.OpenAIProvider = lambda api_key, model, timeout_seconds: object()
        try:
            health = llm_health_from_settings(_settings(provider="openai", api_key="test-key"))
        finally:
            providers.OpenAIProvider = original

        assert health.status == LLMHealthState.HEALTHY
        assert health.provider == "openai"
        assert health.model == "gpt-5.6-terra"

    def test_openai_init_failure_reports_degraded(self):
        from app.graphrag import providers

        original = providers.OpenAIProvider

        def _raise(*args, **kwargs):
            raise LLMProviderError("openai package is required for OpenAI provider.")

        providers.OpenAIProvider = _raise
        try:
            health = llm_health_from_settings(_settings(provider="openai", api_key="test-key"))
        finally:
            providers.OpenAIProvider = original

        assert health.status == LLMHealthState.DEGRADED
        assert health.provider == "openai"