"""Base protocol / ABC for AI providers."""

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """Provider-agnostic interface for model backends."""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for the given prompt."""
        ...
