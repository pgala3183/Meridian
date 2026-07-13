"""Google Gemini provider adapter."""

from typing import Any

from meridian.providers.base import BaseProvider


class GeminiProvider(BaseProvider):
    """Adapter for the Google Gemini API."""

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError
