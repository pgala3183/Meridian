"""OpenAI provider adapter."""

from typing import Any

from meridian.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    """Adapter for the OpenAI API."""

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError
