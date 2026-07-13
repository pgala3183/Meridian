"""Provider registry / factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meridian.providers.anthropic_provider import AnthropicProvider
from meridian.providers.base import MultimodalProvider, ProviderError
from meridian.providers.gemini_provider import GeminiProvider
from meridian.providers.openai_provider import OpenAIProvider
from meridian.providers.types import ProviderConfig, ProviderName

ProviderBuilder = Callable[..., MultimodalProvider]

_REGISTRY: dict[ProviderName, ProviderBuilder] = {
    ProviderName.GEMINI: GeminiProvider,
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.ANTHROPIC: AnthropicProvider,
}


def available_providers() -> list[str]:
    """Return registered provider names."""
    return [name.value for name in _REGISTRY]


def create_provider(
    config: ProviderConfig | None = None,
    *,
    client: Any | None = None,
) -> MultimodalProvider:
    """Construct a multimodal provider from config.

    Defaults to Gemini on Vertex AI when ``config`` is omitted.
    An optional ``client`` may be injected for tests.
    """
    resolved = config or ProviderConfig()
    try:
        provider_cls = _REGISTRY[resolved.name]
    except KeyError as exc:
        known = ", ".join(available_providers())
        raise ProviderError(
            f"Unknown provider {resolved.name!r}. Known providers: {known}"
        ) from exc
    return provider_cls(resolved, client=client)


def get_default_provider(*, client: Any | None = None) -> MultimodalProvider:
    """Return the default provider (Gemini / Vertex AI)."""
    return create_provider(ProviderConfig(name=ProviderName.GEMINI), client=client)
