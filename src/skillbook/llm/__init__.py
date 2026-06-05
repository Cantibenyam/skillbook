"""LLM provider layer."""

from __future__ import annotations

from ..config import DEFAULT_MODEL
from .base import Completion, LLMProvider, Message, MockProvider, OnDelta, Usage

__all__ = [
    "Completion",
    "LLMProvider",
    "Message",
    "MockProvider",
    "OnDelta",
    "Usage",
    "get_provider",
]


def get_provider(model: str | None = None, *, mock: bool = False) -> LLMProvider:
    """Return a provider for ``model`` (``provider/model``), or a MockProvider.

    Importing :class:`LiteLLMProvider` is deferred so the heavy ``litellm`` import
    is only paid when a real provider is actually used (mock/tests stay light).
    """
    model = model or DEFAULT_MODEL
    if mock or model.startswith("mock"):
        return MockProvider(model)
    from .litellm_provider import LiteLLMProvider

    return LiteLLMProvider(model)
