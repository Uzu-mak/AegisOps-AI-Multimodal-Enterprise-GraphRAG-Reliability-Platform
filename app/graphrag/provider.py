"""
LLM provider interface for GraphRAG.

Using a Protocol allows swapping providers without changing pipeline code.
A DeterministicTestProvider is included so the system runs without any API key.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int


class LLMProvider(Protocol):
    """Replaceable interface for LLM generation."""

    def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a response from the model."""
        ...

    def get_model_name(self) -> str:
        """Return the model identifier."""
        ...
