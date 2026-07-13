"""Composable stages for the hierarchical video-understanding pipeline.

Flow
----
video → extract media → transcribe → semantic chunk → keyframe select
      → hierarchy tree → multi-tier cache → retrieve → cited answer

Each stage is an independently testable class with typed inputs/outputs.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from meridian.core.cache import MultiTierCache, content_hash, fingerprint_bytes
from meridian.core.chunking import (
    HashingEmbedder,
    SentenceEmbedder,
    semantic_chunk,
    sentences_from_transcript,
)
from meridian.core.models import (
    Citation,
    CitedAnswer,
    ContextTree,
    ExtractedMedia,
    HierarchyNode,
    Keyframe,
    PipelineArtifacts,
    PipelineConfig,
    RetrievalHit,
    SemanticChunk,
    TimedSentence,
    VideoMetadata,
    VideoSource,
)
from meridian.core.retrieval import build_grounding_context, retrieve
from meridian.core.security.prompt_guard import PromptGuard
from meridian.providers.base import MultimodalProvider
from meridian.providers.types import AudioInput, GroundedAnswer, Transcript, TranscriptSegment
from meridian.storage.safe_path import scratch_directory

_CHUNK_REF = re.compile(
    r"\[(chunk-\d{4})\s*\|\s*([0-9.]+)s-([0-9.]+)s\]|(?:\[)?(chunk-\d{4})(?:\])?"
)


class PipelineStage(ABC):
    """Base class for a typed, composable pipeline stage."""

    name: str = "stage"

    @abstractmethod
    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        """Transform artifacts in place / return updated artifacts."""


class ExtractMediaStage(PipelineStage):
    """Resolve audio + metadata for a video source.

    Production will shell out to ffmpeg / probe libraries. For now the stage
    accepts pre-extracted ``ExtractedMedia`` already placed on artifacts, or
    synthesizes a minimal payload from ``VideoSource`` for offline tests.

    Any on-disk scratch work uses ``scratch_directory`` so temp files are always
    cleaned up, including when extraction raises.
    """

    name = "extract_media"

    def __init__(self, media: ExtractedMedia | None = None) -> None:
        self._media = media

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if self._media is not None:
            artifacts.media = self._media
            return artifacts
        if artifacts.media is not None:
            return artifacts

        # Scratch sandbox is reserved for future ffmpeg extract; always cleaned up.
        with scratch_directory(prefix="meridian-extract-") as sandbox:
            artifacts.extras["extract_scratch_root"] = str(sandbox.root)
            duration = artifacts.source.duration_seconds or 0.0
            fingerprint = artifacts.source.content_hash or fingerprint_bytes(
                artifacts.source.video_id.encode("utf-8")
            )
            # Placeholder probe file demonstrates sandboxed writes.
            probe = sandbox.open_write("probe.json")
            probe.write_text("{}", encoding="utf-8")
            artifacts.media = ExtractedMedia(
                metadata=VideoMetadata(
                    video_id=artifacts.source.video_id,
                    duration_seconds=duration,
                    title=artifacts.source.title,
                    source_path=artifacts.source.path,
                    content_hash=fingerprint,
                ),
                audio_bytes=b"",
                audio_mime_type="audio/wav",
            )
        return artifacts


def _cache_hit(artifacts: PipelineArtifacts) -> bool:
    return bool(artifacts.extras.get("cache_hit"))


class LoadCachedTreeStage(PipelineStage):
    """Hydrate a prior context tree when the content-hash key hits."""

    name = "load_cached_tree"

    def __init__(
        self,
        cache: MultiTierCache[Any],
        config: PipelineConfig,
    ) -> None:
        self._cache = cache
        self._config = config

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if not self._config.cache_enabled:
            artifacts.extras["cache_hit"] = False
            return artifacts

        fingerprint = (
            (artifacts.media.metadata.content_hash if artifacts.media else None)
            or artifacts.source.content_hash
            or artifacts.source.video_id
        )
        key = content_hash(
            video_fingerprint=fingerprint,
            chunking=self._config.chunking,
            pipeline=self._config,
        )
        artifacts.cache_key = key
        cached = self._cache.get(key)
        if isinstance(cached, ContextTree):
            artifacts.tree = cached
            artifacts.chunks = cached.chunks
            artifacts.keyframes = cached.keyframes
            artifacts.extras["cache_hit"] = True
            return artifacts
        artifacts.extras["cache_hit"] = False
        return artifacts


class TranscribeStage(PipelineStage):
    """Produce a timed transcript via the configured multimodal provider."""

    name = "transcribe"

    def __init__(
        self,
        provider: MultimodalProvider,
        *,
        fixture_transcript: Transcript | None = None,
    ) -> None:
        self._provider = provider
        self._fixture = fixture_transcript

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if _cache_hit(artifacts):
            return artifacts

        if self._fixture is not None:
            transcript = self._fixture
        elif artifacts.media and artifacts.media.transcript_text:
            transcript = _transcript_from_plain(
                artifacts.media.transcript_text,
                artifacts.media.metadata.duration_seconds,
            )
        else:
            if artifacts.media is None:
                raise RuntimeError("TranscribeStage requires ExtractedMedia")
            transcript = await self._provider.transcribe(
                AudioInput(
                    data=artifacts.media.audio_bytes,
                    mime_type=artifacts.media.audio_mime_type,
                    filename=f"{artifacts.source.video_id}.wav",
                )
            )

        artifacts.transcript_text = transcript.text
        artifacts.sentences = sentences_from_transcript(transcript)
        artifacts.extras["transcript"] = transcript
        return artifacts


class SemanticChunkStage(PipelineStage):
    """Split the timed transcript into semantic chunks."""

    name = "semantic_chunk"

    def __init__(
        self,
        config: PipelineConfig,
        *,
        embedder: SentenceEmbedder | None = None,
    ) -> None:
        self._config = config
        self._embedder = embedder or HashingEmbedder()

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if _cache_hit(artifacts):
            return artifacts
        artifacts.chunks = semantic_chunk(
            artifacts.sentences,
            self._config.chunking,
            embedder=self._embedder,
        )
        return artifacts


class KeyframeSelectStage(PipelineStage):
    """Select visual keyframes at semantic chunk boundaries.

    Real frame grabs (ffmpeg seek) land in a later infra step; here we record
    timestamps so the hierarchy and citations share a common time base.
    """

    name = "keyframe_select"

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if _cache_hit(artifacts):
            return artifacts
        frames: list[Keyframe] = []
        for chunk in artifacts.chunks:
            ts = chunk.start_seconds
            frames.append(
                Keyframe(
                    keyframe_id=f"kf-{chunk.chunk_id}",
                    timestamp_seconds=ts,
                    chunk_id=chunk.chunk_id,
                    image_bytes=None,
                )
            )
        artifacts.keyframes = tuple(frames)
        return artifacts


class HierarchyBuildStage(PipelineStage):
    """Build a leaf→section→root context tree over semantic chunks."""

    name = "hierarchy_build"

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if _cache_hit(artifacts):
            return artifacts
        chunks = artifacts.chunks
        nodes: dict[str, HierarchyNode] = {}

        for chunk in chunks:
            node_id = f"leaf:{chunk.chunk_id}"
            nodes[node_id] = HierarchyNode(
                node_id=node_id,
                level=0,
                text=chunk.text,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                child_ids=(),
                chunk_id=chunk.chunk_id,
                embedding=chunk.embedding,
            )

        group = max(self._config.section_group_size, 1)
        section_ids: list[str] = []
        for i in range(0, len(chunks), group):
            group_chunks = chunks[i : i + group]
            section_id = f"section:{i // group:04d}"
            section_ids.append(section_id)
            child_ids = tuple(f"leaf:{c.chunk_id}" for c in group_chunks)
            text = " ".join(c.text for c in group_chunks)
            embedding = _mean_pool([c.embedding for c in group_chunks if c.embedding])
            nodes[section_id] = HierarchyNode(
                node_id=section_id,
                level=1,
                text=text,
                start_seconds=group_chunks[0].start_seconds,
                end_seconds=group_chunks[-1].end_seconds,
                child_ids=child_ids,
                embedding=embedding,
            )

        root_id = f"root:{artifacts.source.video_id}"
        root_text = " ".join(nodes[sid].text for sid in section_ids) if section_ids else ""
        nodes[root_id] = HierarchyNode(
            node_id=root_id,
            level=2,
            text=root_text,
            start_seconds=chunks[0].start_seconds if chunks else 0.0,
            end_seconds=chunks[-1].end_seconds if chunks else 0.0,
            child_ids=tuple(section_ids),
            embedding=_mean_pool([nodes[sid].embedding for sid in section_ids]),
        )

        media_hash = None
        if artifacts.media and artifacts.media.metadata.content_hash:
            media_hash = artifacts.media.metadata.content_hash

        artifacts.tree = ContextTree(
            video_id=artifacts.source.video_id,
            root_id=root_id,
            nodes=nodes,
            chunks=chunks,
            keyframes=artifacts.keyframes,
            content_hash=media_hash,
        )
        return artifacts


class StoreCachedTreeStage(PipelineStage):
    """Write the freshly built context tree into the multi-tier cache."""

    name = "store_cached_tree"

    def __init__(
        self,
        cache: MultiTierCache[Any],
        config: PipelineConfig,
    ) -> None:
        self._cache = cache
        self._config = config

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if not self._config.cache_enabled or _cache_hit(artifacts):
            return artifacts
        if artifacts.tree is None or artifacts.cache_key is None:
            return artifacts
        self._cache.set(artifacts.cache_key, artifacts.tree)
        return artifacts


class RetrieveStage(PipelineStage):
    """Question-aware retrieval over the hierarchical index."""

    name = "retrieve"

    def __init__(
        self,
        config: PipelineConfig,
        *,
        embedder: SentenceEmbedder,
        question: str,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._question = question

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if artifacts.tree is None:
            raise RuntimeError("RetrieveStage requires a ContextTree")
        artifacts.hits = retrieve(
            artifacts.tree,
            self._question,
            embedder=self._embedder,
            top_k=self._config.top_k,
        )
        artifacts.extras["question"] = self._question
        return artifacts


class AnswerStage(PipelineStage):
    """Produce a grounded answer with structured timestamp citations."""

    name = "answer"

    def __init__(
        self,
        provider: MultimodalProvider,
        *,
        question: str,
        prompt_guard: PromptGuard | None = None,
    ) -> None:
        self._provider = provider
        self._question = question
        self._prompt_guard = prompt_guard or PromptGuard()

    async def run(self, artifacts: PipelineArtifacts) -> PipelineArtifacts:
        if not artifacts.hits:
            raise RuntimeError("AnswerStage requires retrieval hits for grounding")

        context = build_grounding_context(artifacts.hits)
        guarded_context = self._prompt_guard.wrap_untrusted(context, label="retrieved_transcript")
        guarded_question = self._prompt_guard.wrap_untrusted(self._question, label="user_question")
        # Questions stay lightly wrapped; primary policy is on transcript context.
        raw: GroundedAnswer = await self._provider.answer_question(
            context=guarded_context,
            question=self._question,
            images=None,
        )
        answer_text = self._prompt_guard.filter_answer(raw.answer)
        if self._prompt_guard.answer_looks_leaky(raw.answer):
            artifacts.extras["prompt_leak_redacted"] = True
        citations = build_citations(artifacts.hits, raw)
        artifacts.answer = CitedAnswer(
            answer=answer_text,
            citations=tuple(citations),
            confidence=raw.confidence,
            model=raw.model,
            retrieved_chunk_ids=tuple(h.chunk.chunk_id for h in artifacts.hits),
        )
        artifacts.extras["prompt_guard_question"] = guarded_question
        return artifacts


class VideoPipeline:
    """Orchestrates an ordered list of stages end-to-end."""

    def __init__(self, stages: Sequence[PipelineStage]) -> None:
        if not stages:
            raise ValueError("VideoPipeline requires at least one stage")
        self.stages = list(stages)

    async def run(self, source: VideoSource) -> PipelineArtifacts:
        artifacts = PipelineArtifacts(source=source)
        for stage in self.stages:
            artifacts = await stage.run(artifacts)
        return artifacts


def build_default_pipeline(
    *,
    provider: MultimodalProvider,
    config: PipelineConfig | None = None,
    cache: MultiTierCache[Any] | None = None,
    embedder: SentenceEmbedder | None = None,
    question: str,
    media: ExtractedMedia | None = None,
    fixture_transcript: Transcript | None = None,
) -> VideoPipeline:
    """Wire the standard stage graph for ingest + Q&A."""
    cfg = config or PipelineConfig()
    emb = embedder or HashingEmbedder()
    cache_tier = cache or MultiTierCache()
    return VideoPipeline(
        [
            ExtractMediaStage(media=media),
            LoadCachedTreeStage(cache_tier, cfg),
            TranscribeStage(provider, fixture_transcript=fixture_transcript),
            SemanticChunkStage(cfg, embedder=emb),
            KeyframeSelectStage(),
            HierarchyBuildStage(cfg),
            StoreCachedTreeStage(cache_tier, cfg),
            RetrieveStage(cfg, embedder=emb, question=question),
            AnswerStage(provider, question=question),
        ]
    )


def build_citations(
    hits: Sequence[RetrievalHit],
    raw: GroundedAnswer,
) -> list[Citation]:
    """Map model output + retrieval hits into structured ``Citation`` objects.

    Prefer chunk IDs referenced in the model answer; always fall back to the
    retrieved hit set so answers never ship without timestamp grounding.
    """
    by_id = {h.chunk.chunk_id: h.chunk for h in hits}
    cited_ids: list[str] = []
    for match in _CHUNK_REF.finditer(raw.answer):
        chunk_id = match.group(1) or match.group(4)
        if chunk_id and chunk_id in by_id and chunk_id not in cited_ids:
            cited_ids.append(chunk_id)
    for token in raw.citations:
        if token in by_id and token not in cited_ids:
            cited_ids.append(token)

    if not cited_ids:
        cited_ids = [h.chunk.chunk_id for h in hits]

    citations: list[Citation] = []
    for chunk_id in cited_ids:
        chunk = by_id[chunk_id]
        citations.append(_citation_from_chunk(chunk))
    return citations


def _citation_from_chunk(chunk: SemanticChunk) -> Citation:
    excerpt = chunk.text if len(chunk.text) <= 280 else chunk.text[:277] + "..."
    return Citation(
        start_time=chunk.start_seconds,
        end_time=chunk.end_seconds,
        transcript_excerpt=excerpt,
        chunk_id=chunk.chunk_id,
        segment_id=None,
    )


def _mean_pool(
    vectors: Sequence[tuple[float, ...] | None],
) -> tuple[float, ...] | None:
    present = [v for v in vectors if v is not None]
    if not present:
        return None
    dims = len(present[0])
    acc = [0.0] * dims
    for vec in present:
        for i, value in enumerate(vec):
            acc[i] += value
    n = float(len(present))
    return tuple(v / n for v in acc)


def _transcript_from_plain(text: str, duration: float) -> Transcript:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    if not parts:
        return Transcript(text=text, duration_seconds=duration)
    span = duration if duration > 0 else float(len(parts))
    step = span / len(parts)
    segments = tuple(
        TranscriptSegment(
            text=part,
            start_seconds=i * step,
            end_seconds=(i + 1) * step,
        )
        for i, part in enumerate(parts)
    )
    return Transcript(text=text, segments=segments, duration_seconds=duration)


# Re-export timed sentence helper for tests / callers.
__all__ = [
    "AnswerStage",
    "ExtractMediaStage",
    "HierarchyBuildStage",
    "KeyframeSelectStage",
    "LoadCachedTreeStage",
    "PipelineStage",
    "RetrieveStage",
    "SemanticChunkStage",
    "StoreCachedTreeStage",
    "TimedSentence",
    "TranscribeStage",
    "VideoPipeline",
    "build_citations",
    "build_default_pipeline",
]
