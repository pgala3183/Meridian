"""Provider-agnostic multimodal interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from meridian.providers.types import (
    AudioInput,
    CostEstimate,
    Embedding,
    GroundedAnswer,
    ImageInput,
    ProviderRequest,
    Transcript,
)


class ProviderError(Exception):
    """Base error for provider adapter failures."""


class ProviderCapabilityError(ProviderError):
    """Raised when a provider does not support the requested capability."""


class MultimodalProvider(ABC):
    """Lowest-common-denominator interface across AI backends.

    Concrete adapters may expose richer, provider-specific APIs alongside this
    contract. Callers that need portability should stick to these methods;
    callers that need Gemini video-native features may cast/narrow to a
    concrete provider type.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier (e.g. ``gemini``, ``openai``)."""

    @abstractmethod
    async def transcribe(self, audio: AudioInput) -> Transcript:
        """Transcribe audio into normalized text (+ optional segments)."""

    @abstractmethod
    async def embed_text(self, text: str) -> Embedding:
        """Embed text into a dense vector for retrieval."""

    @abstractmethod
    async def answer_question(
        self,
        context: str,
        question: str,
        images: list[ImageInput] | None = None,
    ) -> GroundedAnswer:
        """Answer a question grounded in the given context and optional images."""

    @abstractmethod
    async def estimate_cost(self, request: ProviderRequest) -> CostEstimate:
        """Estimate USD cost for a request without calling the remote API."""
