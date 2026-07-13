"""Deterministic provider + naive baseline for offline benchmarks."""

from __future__ import annotations

import re
from typing import Any

from meridian.providers.base import MultimodalProvider
from meridian.providers.types import (
    AudioInput,
    CostEstimate,
    Embedding,
    GroundedAnswer,
    ImageInput,
    ProviderRequest,
    Transcript,
)


def _approx_tokens(text: str) -> int:
    # Rough English heuristic: ~4 chars / token.
    return max(1, len(text) // 4)


# Minimal stopword list so refusal decisions ignore filler words that appear in
# every transcript (otherwise "the"/"does" would make every question look
# answerable). Content-word overlap of zero => decline to answer.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "do",
        "does",
        "did",
        "how",
        "what",
        "when",
        "where",
        "who",
        "why",
        "which",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "about",
        "per",
        "you",
        "your",
        "they",
        "their",
        "we",
        "our",
        "he",
        "she",
        "his",
        "her",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "much",
        "many",
        "any",
        "some",
    }
)


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 2}


class DeterministicEvalProvider(MultimodalProvider):
    """Offline provider that answers from context keywords (no network).

    Cost estimates still go through ``estimate_cost`` so spend comparisons are
    meaningful even without live vendor calls.
    """

    def __init__(self, transcript_by_video: dict[str, Transcript] | None = None) -> None:
        self._transcripts = transcript_by_video or {}
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "eval-deterministic"

    async def transcribe(self, audio: AudioInput) -> Transcript:
        self.calls.append("transcribe")
        # Prefer injected transcript; otherwise empty.
        return Transcript(text="", segments=(), duration_seconds=0.0, model=self.name)

    async def embed_text(self, text: str) -> Embedding:
        self.calls.append("embed_text")
        # Tiny hashing embedding for retrieval compatibility if ever called.
        vec = [float((ord(c) % 13) - 6) for c in text[:32]] or [0.0]
        return Embedding(vector=tuple(vec), model="eval-hash", dimensions=len(vec))

    async def answer_question(
        self,
        context: str,
        question: str,
        images: list[ImageInput] | None = None,
    ) -> GroundedAnswer:
        _ = images
        self.calls.append("answer_question")
        # Extract the highest-overlap sentence from context as a grounded answer.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", context) if s.strip()]
        q_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))

        # Refusal path: if no context sentence shares a content word with the
        # question, decline instead of returning an irrelevant sentence. This
        # makes unanswerable (negative) questions behave realistically offline.
        q_content = _content_tokens(question)
        best_content_overlap = max(
            (len(q_content & _content_tokens(s)) for s in sentences),
            default=0,
        )
        if q_content and best_content_overlap == 0:
            return GroundedAnswer(
                answer="The context does not provide information to answer this question.",
                citations=(),
                model=self.name,
            )

        best = ""
        best_score = -1
        for sentence in sentences:
            # Skip security wrappers
            if "UNTRUSTED_CONTENT" in sentence or "Never follow instructions" in sentence:
                continue
            tokens = set(re.findall(r"[a-z0-9]+", sentence.lower()))
            score = len(q_tokens & tokens)
            if score > best_score:
                best_score = score
                best = sentence
        if not best and sentences:
            best = sentences[0]
        # Prefer lines that look like transcript evidence (chunk markers).
        chunk_lines = [s for s in sentences if "chunk-" in s.lower()]
        if chunk_lines:
            ranked = sorted(
                chunk_lines,
                key=lambda s: len(q_tokens & set(re.findall(r"[a-z0-9]+", s.lower()))),
                reverse=True,
            )
            best = ranked[0]
            # Strip the leading marker for readability but keep id for citations.
            m = re.search(r"(chunk-\d{4})", best)
            cite = m.group(1) if m else "chunk-0000"
            body = re.sub(r"^\[.*?\]\s*", "", best).strip()
            answer = f"{body} [{cite}]"
            return GroundedAnswer(answer=answer, citations=(cite,), model=self.name)
        return GroundedAnswer(answer=best or "Insufficient context.", citations=(), model=self.name)

    async def estimate_cost(self, request: ProviderRequest) -> CostEstimate:
        self.calls.append("estimate_cost")
        # Mirror gemini-ish ballpark rates for comparable offline estimates.
        in_rate = 0.10
        out_rate = 0.40
        text_in = (request.input_tokens / 1_000_000) * in_rate
        text_out = (request.output_tokens / 1_000_000) * out_rate
        return CostEstimate(
            estimated_usd=round(text_in + text_out, 8),
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            model=request.model or self.name,
            breakdown={"text_input": round(text_in, 8), "text_output": round(text_out, 8)},
        )


async def run_naive_baseline(
    *,
    provider: MultimodalProvider,
    transcript: Transcript,
    question: str,
) -> dict[str, Any]:
    """Naive baseline: dump full transcript into one long context (no chunk/cache)."""
    context = transcript.text
    answer = await provider.answer_question(context=context, question=question)
    in_tokens = _approx_tokens(context) + _approx_tokens(question)
    out_tokens = _approx_tokens(answer.answer)
    cost = await provider.estimate_cost(
        ProviderRequest(
            operation="answer_question",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
    )
    return {
        "answer": answer.answer,
        "citations": list(answer.citations),
        "context_chars": len(context),
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "estimated_usd": cost.estimated_usd,
        "context": context,
    }
