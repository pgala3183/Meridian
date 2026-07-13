"""Typed models for the hierarchical video-understanding pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Structured grounding pointer back into the source video.

    Every pipeline answer must carry at least one citation so callers can
    jump to the supporting audio/transcript span — not free-floating prose.
    """

    start_time: float = Field(ge=0.0, description="Citation start in seconds")
    end_time: float = Field(ge=0.0, description="Citation end in seconds")
    transcript_excerpt: str = Field(min_length=1)
    segment_id: str | None = None
    chunk_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.end_time < self.start_time:
            msg = f"end_time ({self.end_time}) must be >= start_time ({self.start_time})"
            raise ValueError(msg)


class CitedAnswer(BaseModel):
    """Final pipeline answer with mandatory structured citations."""

    answer: str
    citations: tuple[Citation, ...]
    confidence: float | None = None
    model: str | None = None
    retrieved_chunk_ids: tuple[str, ...] = ()

    def model_post_init(self, __context: Any) -> None:
        if not self.citations:
            raise ValueError("CitedAnswer requires at least one Citation")


class VideoMetadata(BaseModel):
    """Lightweight metadata extracted (or supplied) for a video."""

    video_id: str
    duration_seconds: float = Field(ge=0.0)
    title: str | None = None
    source_path: str | None = None
    content_hash: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class VideoSource(BaseModel):
    """Input reference for a video to process."""

    video_id: str
    path: str | None = None
    content_hash: str | None = None
    duration_seconds: float | None = None
    title: str | None = None


class ExtractedMedia(BaseModel):
    """Audio bytes + metadata produced by the extraction stage."""

    metadata: VideoMetadata
    audio_bytes: bytes
    audio_mime_type: str = "audio/wav"
    # Optional pre-supplied transcript for tests / offline runs
    transcript_text: str | None = None


class TimedSentence(BaseModel):
    """A sentence-level unit with timing, used as the chunking atom."""

    index: int
    text: str
    start_seconds: float
    end_seconds: float
    segment_id: str | None = None


class SemanticChunk(BaseModel):
    """A semantically coherent transcript span."""

    chunk_id: str
    text: str
    start_seconds: float
    end_seconds: float
    sentence_indices: tuple[int, ...]
    embedding: tuple[float, ...] | None = None


class Keyframe(BaseModel):
    """Visual anchor selected near a semantic boundary."""

    keyframe_id: str
    timestamp_seconds: float
    chunk_id: str | None = None
    # Placeholder until real frame extraction is wired; tests may inject bytes.
    image_bytes: bytes | None = None
    mime_type: str = "image/jpeg"


class HierarchyNode(BaseModel):
    """Node in the hierarchical context tree (leaf = chunk, root = video)."""

    node_id: str
    level: int = Field(ge=0, description="0=chunk leaf, higher=coarser summaries")
    text: str
    start_seconds: float
    end_seconds: float
    child_ids: tuple[str, ...] = ()
    chunk_id: str | None = None
    embedding: tuple[float, ...] | None = None


class ContextTree(BaseModel):
    """Hierarchical index over a video's semantic chunks."""

    video_id: str
    root_id: str
    nodes: dict[str, HierarchyNode]
    chunks: tuple[SemanticChunk, ...]
    keyframes: tuple[Keyframe, ...] = ()
    content_hash: str | None = None


class RetrievalHit(BaseModel):
    """A scored chunk returned by question-aware retrieval."""

    chunk: SemanticChunk
    score: float
    node_id: str | None = None


class ChunkingConfig(BaseModel):
    """Parameters that affect semantic chunk identity (hashed into cache keys)."""

    similarity_threshold: float = 0.55
    min_chunk_sentences: int = 2
    max_chunk_sentences: int = 12
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    depth_percentile: float = 0.7


class PipelineConfig(BaseModel):
    """Runtime knobs for the full pipeline."""

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    top_k: int = 4
    section_group_size: int = 3
    cache_enabled: bool = True


@dataclass(slots=True)
class PipelineArtifacts:
    """Intermediate outputs retained across stages (mutable working set)."""

    source: VideoSource
    media: ExtractedMedia | None = None
    transcript_text: str | None = None
    sentences: tuple[TimedSentence, ...] = ()
    chunks: tuple[SemanticChunk, ...] = ()
    keyframes: tuple[Keyframe, ...] = ()
    tree: ContextTree | None = None
    hits: tuple[RetrievalHit, ...] = ()
    answer: CitedAnswer | None = None
    cache_key: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
