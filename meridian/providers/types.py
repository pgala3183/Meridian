"""Shared types for multimodal provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProviderName(StrEnum):
    """Supported provider identifiers used by the factory/registry."""

    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass(frozen=True, slots=True)
class AudioInput:
    """Raw audio payload for transcription."""

    data: bytes
    mime_type: str = "audio/wav"
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class ImageInput:
    """Image payload for grounded multimodal Q&A."""

    data: bytes
    mime_type: str = "image/jpeg"


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A timed span within a transcript."""

    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    """Normalized transcription result across providers."""

    text: str
    segments: tuple[TranscriptSegment, ...] = ()
    language: str | None = None
    duration_seconds: float | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class Embedding:
    """Dense vector embedding for a text input."""

    vector: tuple[float, ...]
    model: str
    dimensions: int


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Answer constrained to supplied context (and optional images)."""

    answer: str
    citations: tuple[str, ...] = ()
    confidence: float | None = None
    model: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Estimated usage cost for a provider request.

    Explicit cost estimation exists so benchmarking and budget gates can run
    without issuing paid calls, and so provider choice can be cost-aware.
    """

    estimated_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    currency: str = "USD"
    model: str | None = None
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Inputs used by ``estimate_cost`` without calling the remote API."""

    operation: str
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    image_count: int = 0
    model: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Runtime configuration for selecting and constructing a provider."""

    name: ProviderName = ProviderName.GEMINI
    # Vertex / Gemini
    project: str | None = None
    location: str = "us-central1"
    generation_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-005"
    # OpenAI
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_generation_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_transcription_model: str = "whisper-1"
    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_generation_model: str = "claude-sonnet-4-20250514"
    # Shared pricing overrides (USD per 1M tokens unless noted)
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    audio_price_per_minute: float | None = None
