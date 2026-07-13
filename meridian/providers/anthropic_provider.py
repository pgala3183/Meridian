"""Anthropic provider adapter (text + vision)."""

from __future__ import annotations

import base64
from typing import Any

from meridian.providers.base import MultimodalProvider, ProviderCapabilityError, ProviderError
from meridian.providers.types import (
    AudioInput,
    CostEstimate,
    Embedding,
    GroundedAnswer,
    ImageInput,
    ProviderConfig,
    ProviderRequest,
    Transcript,
)

_DEFAULT_INPUT_PER_M = 3.00
_DEFAULT_OUTPUT_PER_M = 15.00


class AnthropicProvider(MultimodalProvider):
    """Secondary adapter focused on text and vision Q&A.

    Anthropic does not expose first-party transcription or embeddings APIs.
    Those methods raise ``ProviderCapabilityError`` so callers can fall back
    (e.g. Whisper via OpenAI) rather than silently degrading quality.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._client = client

    @property
    def name(self) -> str:
        return "anthropic"

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            kwargs: dict[str, Any] = {}
            if self._config.anthropic_api_key:
                kwargs["api_key"] = self._config.anthropic_api_key
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def transcribe(self, audio: AudioInput) -> Transcript:
        raise ProviderCapabilityError(
            "Anthropic does not provide a transcription API; "
            "use Gemini or OpenAI for audio transcription."
        )

    async def embed_text(self, text: str) -> Embedding:
        raise ProviderCapabilityError(
            "Anthropic does not provide an embeddings API; "
            "use Gemini or OpenAI for text embeddings."
        )

    async def answer_question(
        self,
        context: str,
        question: str,
        images: list[ImageInput] | None = None,
    ) -> GroundedAnswer:
        client = self._get_client()
        model = self._config.anthropic_generation_model
        content: list[dict[str, Any]] = []
        for image in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime_type,
                        "data": base64.b64encode(image.data).decode("ascii"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    "Answer using only the provided context. If insufficient, say so.\n\n"
                    f"Context:\n{context}\n\nQuestion:\n{question}"
                ),
            }
        )
        try:
            result = await client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:
            raise ProviderError(f"Anthropic answer_question failed: {exc}") from exc

        answer = _extract_message_text(result)
        return GroundedAnswer(answer=answer, model=model)

    async def estimate_cost(self, request: ProviderRequest) -> CostEstimate:
        if request.operation in {"transcribe", "embed_text"}:
            raise ProviderCapabilityError(
                f"Anthropic cannot estimate cost for unsupported operation: {request.operation}"
            )
        model = request.model or self._config.anthropic_generation_model
        input_rate = self._config.input_price_per_million or _DEFAULT_INPUT_PER_M
        output_rate = self._config.output_price_per_million or _DEFAULT_OUTPUT_PER_M
        text_in = (request.input_tokens / 1_000_000) * input_rate
        text_out = (request.output_tokens / 1_000_000) * output_rate
        # Rough vision surcharge: treat each image as ~1k input tokens equivalent
        vision = (request.image_count * 1000 / 1_000_000) * input_rate
        breakdown = {
            "text_input": round(text_in, 8),
            "text_output": round(text_out, 8),
            "vision": round(vision, 8),
        }
        return CostEstimate(
            estimated_usd=round(sum(breakdown.values()), 8),
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            model=model,
            breakdown=breakdown,
        )


def _extract_message_text(result: Any) -> str:
    blocks = getattr(result, "content", None) or []
    chunks: list[str] = []
    for block in blocks:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            text = getattr(block, "text", None)
            if text:
                chunks.append(str(text))
        elif isinstance(block, dict) and block.get("type") == "text":
            chunks.append(str(block.get("text", "")))
    answer = "".join(chunks).strip()
    if not answer:
        raise ProviderError("Anthropic message response missing text content")
    return answer
