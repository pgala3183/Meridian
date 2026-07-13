"""OpenAI provider adapter (text, vision, whisper, embeddings)."""

from __future__ import annotations

import base64
import io
from typing import Any

from meridian.providers.base import MultimodalProvider, ProviderError
from meridian.providers.types import (
    AudioInput,
    CostEstimate,
    Embedding,
    GroundedAnswer,
    ImageInput,
    ProviderConfig,
    ProviderRequest,
    Transcript,
    TranscriptSegment,
)

_DEFAULT_INPUT_PER_M = 2.50
_DEFAULT_OUTPUT_PER_M = 10.00
_DEFAULT_EMBED_PER_M = 0.02
_DEFAULT_AUDIO_PER_MIN = 0.006


class OpenAIProvider(MultimodalProvider):
    """Secondary adapter: chat + vision + Whisper transcription + embeddings.

    Intentionally thinner than Gemini — no video-native Vertex features.
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
        return "openai"

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {}
            if self._config.openai_api_key:
                kwargs["api_key"] = self._config.openai_api_key
            if self._config.openai_base_url:
                kwargs["base_url"] = self._config.openai_base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def transcribe(self, audio: AudioInput) -> Transcript:
        client = self._get_client()
        model = self._config.openai_transcription_model
        filename = audio.filename or f"audio.{_extension_for(audio.mime_type)}"
        buffer = io.BytesIO(audio.data)
        buffer.name = filename
        try:
            result = await client.audio.transcriptions.create(
                model=model,
                file=buffer,
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI transcription failed: {exc}") from exc

        text = str(getattr(result, "text", "") or "").strip()
        return Transcript(
            text=text,
            segments=(TranscriptSegment(text=text),) if text else (),
            language=getattr(result, "language", None),
            model=model,
        )

    async def embed_text(self, text: str) -> Embedding:
        client = self._get_client()
        model = self._config.openai_embedding_model
        try:
            result = await client.embeddings.create(model=model, input=text)
        except Exception as exc:
            raise ProviderError(f"OpenAI embedding failed: {exc}") from exc

        try:
            vector = tuple(float(v) for v in result.data[0].embedding)
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI embedding response missing vector") from exc
        return Embedding(vector=vector, model=model, dimensions=len(vector))

    async def answer_question(
        self,
        context: str,
        question: str,
        images: list[ImageInput] | None = None,
    ) -> GroundedAnswer:
        client = self._get_client()
        model = self._config.openai_generation_model
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Answer using only the provided context. If insufficient, say so.\n\n"
                    f"Context:\n{context}\n\nQuestion:\n{question}"
                ),
            }
        ]
        for image in images or []:
            b64 = base64.b64encode(image.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.mime_type};base64,{b64}"},
                }
            )
        try:
            result = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI answer_question failed: {exc}") from exc

        try:
            answer = str(result.choices[0].message.content or "").strip()
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI chat response missing content") from exc

        return GroundedAnswer(answer=answer, model=model)

    async def estimate_cost(self, request: ProviderRequest) -> CostEstimate:
        model = request.model or self._config.openai_generation_model
        input_rate = self._config.input_price_per_million or _DEFAULT_INPUT_PER_M
        output_rate = self._config.output_price_per_million or _DEFAULT_OUTPUT_PER_M
        audio_rate = self._config.audio_price_per_minute or _DEFAULT_AUDIO_PER_MIN

        text_in = (request.input_tokens / 1_000_000) * input_rate
        text_out = (request.output_tokens / 1_000_000) * output_rate
        audio = (request.audio_seconds / 60.0) * audio_rate
        embed = 0.0
        if request.operation == "embed_text":
            embed = (request.input_tokens / 1_000_000) * _DEFAULT_EMBED_PER_M
            text_in = 0.0
            text_out = 0.0
        elif request.operation == "transcribe":
            text_in = 0.0
            text_out = 0.0

        breakdown = {
            "text_input": round(text_in, 8),
            "text_output": round(text_out, 8),
            "audio": round(audio, 8),
            "embedding": round(embed, 8),
        }
        return CostEstimate(
            estimated_usd=round(sum(breakdown.values()), 8),
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            model=model,
            breakdown=breakdown,
        )


def _extension_for(mime_type: str) -> str:
    mapping = {
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
    }
    return mapping.get(mime_type, "wav")
