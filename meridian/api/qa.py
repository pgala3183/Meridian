"""Grounded Q&A against an indexed video (retrieve + Gemini / extractive)."""

from __future__ import annotations

import os
from typing import Any

from meridian.api.schemas.ask import CitationOut
from meridian.core.chunking import HashingEmbedder
from meridian.core.models import Citation, CitedAnswer, ContextTree, RetrievalHit
from meridian.core.pipeline import _CHUNK_REF, build_citations
from meridian.core.retrieval import build_grounding_context, retrieve
from meridian.observability.logging import get_logger
from meridian.providers.base import MultimodalProvider
from meridian.providers.factory import create_provider
from meridian.providers.types import GroundedAnswer, ProviderConfig, ProviderName
from meridian.storage.base import ObjectStore
from meridian.workers.indexing import load_context_tree

logger = get_logger(__name__)


def provider_from_env() -> MultimodalProvider | None:
    """Return a Vertex Gemini provider when a GCP project is configured.

    Skips live calls during pytest, or when ``MERIDIAN_DISABLE_GEMINI`` is set.
    ``MERIDIAN_ENV=test`` alone no longer disables Gemini — that flag was
    blocking local demos that still set ``GOOGLE_CLOUD_PROJECT``.
    """
    if os.getenv("MERIDIAN_DISABLE_GEMINI", "").lower() in {"1", "true", "yes"}:
        logger.info("Gemini disabled via MERIDIAN_DISABLE_GEMINI")
        return None
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project:
        logger.warning(
            "No GOOGLE_CLOUD_PROJECT — using extractive ask fallback. "
            "Set it in .env and restart with ADC (gcloud auth application-default login)."
        )
        return None

    location = (
        os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("MERIDIAN_VERTEX_LOCATION") or "us-central1"
    )
    model = os.getenv("MERIDIAN_GEMINI_MODEL", "gemini-2.5-flash")
    logger.info(
        "Gemini provider ready",
        extra={"project": project, "location": location, "model": model},
    )
    return create_provider(
        ProviderConfig(
            name=ProviderName.GEMINI,
            project=project,
            location=location,
            generation_model=model,
        )
    )


# Char budget for sending the whole transcript to Gemini. gemini-2.5-flash has a
# ~1M-token window; ~600k chars is a safe, generous cap (well under the limit).
_FULL_CONTEXT_CHAR_BUDGET = 600_000


async def answer_question(
    *,
    object_store: ObjectStore,
    video_id: str,
    question: str,
    provider: MultimodalProvider | None = None,
    top_k: int = 8,
) -> tuple[str, list[CitationOut], str | None]:
    """Answer with Gemini over full transcript context (retrieval as fallback)."""
    tree = load_context_tree(object_store, video_id)
    if not tree.chunks:
        raise RuntimeError(f"No indexed chunks for video {video_id}")

    embedder = HashingEmbedder()
    hits = retrieve(tree, question, embedder=embedder, top_k=top_k)
    if not hits:
        # Extremely short indexes may lack embeddings; fall back to first chunks.
        hits = tuple(
            RetrievalHit(chunk=c, score=0.0, node_id=f"leaf:{c.chunk_id}")
            for c in tree.chunks[:top_k]
        )

    resolved = provider if provider is not None else provider_from_env()
    model_name: str | None

    if resolved is not None:
        # Prefer whole-video context when it fits; keeps answers accurate for
        # cross-lingual questions where bag-of-words retrieval misses the mark.
        context, context_mode = _build_answer_context(tree, hits)
        logger.info(
            "Asking provider",
            extra={
                "video_id": video_id,
                "provider": resolved.name,
                "context_mode": context_mode,
                "chunks_in_context": len(tree.chunks) if context_mode == "full" else len(hits),
            },
        )
        raw: GroundedAnswer = await resolved.answer_question(
            context=context,
            question=question,
        )
        # If the model cited chunk ids, resolve them against ALL chunks (the
        # full-context prompt can reference any). Otherwise fall back to the top
        # retrieval hits so we don't emit a citation for every chunk.
        if _answer_has_chunk_refs(raw):
            all_hits = tuple(
                RetrievalHit(chunk=c, score=0.0, node_id=f"leaf:{c.chunk_id}") for c in tree.chunks
            )
            citations = build_citations(all_hits, raw)
        else:
            citations = [
                Citation(
                    start_time=h.chunk.start_seconds,
                    end_time=h.chunk.end_seconds,
                    transcript_excerpt=_excerpt(h.chunk.text),
                    chunk_id=h.chunk.chunk_id,
                )
                for h in hits[:3]
            ]
        cited = CitedAnswer(
            answer=raw.answer,
            citations=tuple(citations),
            model=raw.model,
            retrieved_chunk_ids=tuple(h.chunk.chunk_id for h in hits),
        )
        model_name = cited.model or resolved.name
        answer_text = cited.answer
        citation_models = list(cited.citations)
    else:
        logger.info("Extractive ask fallback (no Gemini provider)", extra={"video_id": video_id})
        citation_models = [
            Citation(
                start_time=h.chunk.start_seconds,
                end_time=h.chunk.end_seconds,
                transcript_excerpt=_excerpt(h.chunk.text),
                chunk_id=h.chunk.chunk_id,
            )
            for h in hits[:3]
        ]
        answer_text = _extractive_answer(question, hits)
        model_name = "meridian-extractive"

    outs = [
        CitationOut(
            start_time=c.start_time,
            end_time=c.end_time,
            transcript_excerpt=c.transcript_excerpt,
            chunk_id=c.chunk_id,
        )
        for c in citation_models
    ]
    # Always expose at least one seekable citation for the UI.
    if not outs and hits:
        h = hits[0]
        outs = [
            CitationOut(
                start_time=h.chunk.start_seconds,
                end_time=h.chunk.end_seconds,
                transcript_excerpt=_excerpt(h.chunk.text),
                chunk_id=h.chunk.chunk_id,
            )
        ]
    return answer_text, outs, model_name


def _answer_has_chunk_refs(raw: GroundedAnswer) -> bool:
    """True if the model referenced any chunk id (inline or via citations)."""
    if raw.citations:
        return True
    return _CHUNK_REF.search(raw.answer) is not None


def _build_answer_context(
    tree: ContextTree,
    hits: tuple[RetrievalHit, ...],
) -> tuple[str, str]:
    """Return (context, mode). Use the whole transcript when it fits the budget."""
    ordered = sorted(tree.chunks, key=lambda c: c.start_seconds)
    full_hits = [RetrievalHit(chunk=c, score=0.0, node_id=f"leaf:{c.chunk_id}") for c in ordered]
    full_context = build_grounding_context(full_hits)
    if len(full_context) <= _FULL_CONTEXT_CHAR_BUDGET:
        return full_context, "full"
    # Long video: fall back to top-k retrieval context.
    return build_grounding_context(hits), "retrieval"


def _excerpt(text: str, limit: int = 280) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _extractive_answer(question: str, hits: Any) -> str:
    top = hits[0].chunk
    return (
        f"Based on the indexed transcript, the most relevant passage "
        f"({top.start_seconds:.0f}s-{top.end_seconds:.0f}s) says:\n\n"
        f"{top.text}"
    )


def load_tree_or_raise(object_store: ObjectStore, video_id: str) -> ContextTree:
    try:
        return load_context_tree(object_store, video_id)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"No context tree found for {video_id}; re-process the video first"
        ) from exc
