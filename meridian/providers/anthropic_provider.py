"""Anthropic provider adapter."""

from typing import Any

from meridian.providers.base import BaseProvider


class AnthropicProvider(BaseProvider):
    """Adapter for the Anthropic API."""

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError
