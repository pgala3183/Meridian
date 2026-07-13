"""Google Gemini provider via Vertex AI (google-genai client)."""

from __future__ import annotations

import asyncio
import base64
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

# Default Vertex list prices (USD / 1M tokens) — approximate; override via config.
_DEFAULT_INPUT_PER_M = 0.10
_DEFAULT_OUTPUT_PER_M = 0.40
_DEFAULT_AUDIO_PER_MIN = 0.006
_DEFAULT_EMBED_PER_M = 0.025


class GeminiProvider(MultimodalProvider):
    """Gemini adapter authenticated through Vertex AI (service accounts / ADC).

    Uses ``google.genai.Client(vertexai=True, ...)`` so traffic is attributed to
    the GCP project for Cloud Billing and Monitoring — not the consumer Gemini API.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None and not config.project:
            raise ValueError(
                "Gemini/Vertex provider requires config.project when no client is injected"
            )
        self._config = config
        self._client = client

    @property
    def name(self) -> str:
        return "gemini"

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=self._config.project,
                location=self._config.location,
            )
        return self._client

    async def transcribe(self, audio: AudioInput) -> Transcript:
        client = self._get_client()
        model = self._config.generation_model
        prompt = (
            "Transcribe the audio verbatim. Return only the transcript text "
            "with no preamble or commentary."
        )
        contents: list[Any] = [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": audio.mime_type,
                            "data": base64.b64encode(audio.data).decode("ascii"),
                        }
                    },
                ],
            }
        ]
        try:
            response = await self._generate(client, model=model, contents=contents)
        except Exception as exc:
            raise ProviderError(f"Gemini transcription failed: {exc}") from exc

        text = _extract_text(response).strip()
        return Transcript(
            text=text,
            segments=(TranscriptSegment(text=text),) if text else (),
            model=model,
        )

    async def embed_text(self, text: str) -> Embedding:
        client = self._get_client()
        model = self._config.embedding_model
        try:
            response = await self._embed(client, model=model, text=text)
        except Exception as exc:
            raise ProviderError(f"Gemini embedding failed: {exc}") from exc

        values = _extract_embedding_values(response)
        return Embedding(vector=tuple(values), model=model, dimensions=len(values))

    async def answer_question(
        self,
        context: str,
        question: str,
        images: list[ImageInput] | None = None,
    ) -> GroundedAnswer:
        client = self._get_client()
        model = self._config.generation_model
        parts: list[dict[str, Any]] = [
            {
                "text": (
                    "Answer the question using only the provided context. "
                    "If the context is insufficient, say so. Cite relevant "
                    "snippets in square brackets when possible.\n\n"
                    f"Context:\n{context}\n\nQuestion:\n{question}"
                )
            }
        ]
        for image in images or []:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image.mime_type,
                        "data": base64.b64encode(image.data).decode("ascii"),
                    }
                }
            )
        contents = [{"role": "user", "parts": parts}]
        try:
            response = await self._generate(client, model=model, contents=contents)
        except Exception as exc:
            raise ProviderError(f"Gemini answer_question failed: {exc}") from exc

        answer = _extract_text(response).strip()
        return GroundedAnswer(
            answer=answer,
            citations=_extract_citations(answer),
            model=model,
        )

    async def estimate_cost(self, request: ProviderRequest) -> CostEstimate:
        model = request.model or self._config.generation_model
        input_rate = self._config.input_price_per_million or _DEFAULT_INPUT_PER_M
        output_rate = self._config.output_price_per_million or _DEFAULT_OUTPUT_PER_M
        audio_rate = self._config.audio_price_per_minute or _DEFAULT_AUDIO_PER_MIN

        input_tokens = request.input_tokens
        output_tokens = request.output_tokens
        text_in = (input_tokens / 1_000_000) * input_rate
        text_out = (output_tokens / 1_000_000) * output_rate
        audio = (request.audio_seconds / 60.0) * audio_rate
        embed = 0.0
        if request.operation == "embed_text":
            embed = (input_tokens / 1_000_000) * _DEFAULT_EMBED_PER_M
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
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            breakdown=breakdown,
        )

    async def _generate(self, client: Any, *, model: str, contents: list[Any]) -> Any:
        aio = getattr(client, "aio", None)
        if aio is not None:
            return await aio.models.generate_content(model=model, contents=contents)
        return await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=contents,
        )

    async def _embed(self, client: Any, *, model: str, text: str) -> Any:
        aio = getattr(client, "aio", None)
        if aio is not None:
            return await aio.models.embed_content(model=model, contents=text)
        return await asyncio.to_thread(
            client.models.embed_content,
            model=model,
            contents=text,
        )


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text
    candidates = getattr(response, "candidates", None) or []
    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(str(part_text))
    if chunks:
        return "".join(chunks)
    if isinstance(response, dict):
        return str(response.get("text", ""))
    return ""


def _extract_embedding_values(response: Any) -> list[float]:
    embeddings = getattr(response, "embeddings", None)
    if embeddings:
        first = embeddings[0]
        values = getattr(first, "values", None)
        if values is not None:
            return [float(v) for v in values]
    embedding = getattr(response, "embedding", None)
    if embedding is not None:
        values = getattr(embedding, "values", embedding)
        if values is not None and not callable(values):
            return [float(v) for v in values]
    if isinstance(response, dict):
        raw = response.get("embeddings") or response.get("embedding") or []
        if isinstance(raw, dict):
            raw = raw.get("values", [])
        if raw and isinstance(raw[0], dict):
            raw = raw[0].get("values", [])
        return [float(v) for v in raw]
    raise ProviderError("Gemini embedding response missing vector values")


def _extract_citations(answer: str) -> tuple[str, ...]:
    """Pull simple [citation] markers out of model text when present."""
    import re

    found = re.findall(r"\[([^\]]+)\]", answer)
    return tuple(found)
