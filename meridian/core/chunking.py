"""Semantic transcript chunking via embedding-distance boundary detection.

Algorithm
---------
We treat sentences (with timestamps) as the atomic units — not fixed-time
windows — so topic shifts drive chunk boundaries rather than wall-clock cuts.

1. **Sentence segmentation.** Split the timed transcript into ``TimedSentence``
   atoms. Complexity: O(T) in transcript length T (characters / regex splits).

2. **Embedding.** Encode each of the n sentences with a sentence-transformer
   (or any injected ``SentenceEmbedder``) into R^d. Complexity: O(n · C_emb)
   where C_emb is the cost of one forward pass (typically O(L · d) in token
   length L and width d for a MiniLM-class encoder). In practice this dominates.

3. **Adjacent similarity.** Compute cosine similarity s_i between embeddings
   e_i and e_{i+1} for i = 0..n-2. Complexity: O(n · d).

4. **TextTiling-style depth scores.** For each interior gap i, define
   depth(i) = (s_{i-1} + s_{i+1}) / 2 - s_i when both neighbors exist, else
   the one-sided difference. High depth means the local gap is a sharper
   discontinuity than its neighbors — a candidate topic boundary.
   Complexity: O(n).

5. **Boundary selection.** Mark gaps whose depth exceeds a percentile of the
   depth distribution *or* whose raw similarity falls below
   ``similarity_threshold``. Then enforce ``min_chunk_sentences`` /
   ``max_chunk_sentences`` by merging undersized runs and splitting oversized
   ones at the weakest interior gap. Complexity: O(n) expected; O(n log n)
   if sorting depths for the percentile cut.

6. **Chunk assembly.** Emit ``SemanticChunk`` objects with stable IDs,
   concatenated text, and [start, end] times from the covered sentences.
   Complexity: O(n).

**Overall:** O(n · C_emb + n · d) time and O(n · d) memory. Boundary detection
itself is linear; embedding is the bottleneck. Cache keys must include the
chunking config so identical video + params never re-chunk.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from itertools import pairwise

from meridian.core.models import ChunkingConfig, SemanticChunk, TimedSentence
from meridian.providers.types import Transcript, TranscriptSegment

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


class SentenceEmbedder(ABC):
    """Pluggable embedding backend for chunking (inject fakes in tests)."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one dense vector per input text."""


class HashingEmbedder(SentenceEmbedder):
    """Deterministic bag-of-hashed-tokens embedder for tests / offline runs.

    Not a substitute for sentence-transformers in production, but preserves
    the boundary-detection geometry: similar word sets → similar vectors.
    """

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SentenceTransformerEmbedder(SentenceEmbedder):
    """Production embedder backed by ``sentence-transformers``."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(list(texts), normalize_embeddings=True)  # type: ignore[attr-defined]
        return [list(map(float, row)) for row in vectors]


def sentences_from_transcript(transcript: Transcript) -> tuple[TimedSentence, ...]:
    """Convert a provider transcript into timed sentence atoms."""
    if transcript.segments:
        return _sentences_from_segments(transcript.segments)
    return _sentences_from_plain_text(transcript.text, transcript.duration_seconds or 0.0)


def _sentences_from_segments(
    segments: Sequence[TranscriptSegment],
) -> tuple[TimedSentence, ...]:
    sentences: list[TimedSentence] = []
    idx = 0
    for seg_i, segment in enumerate(segments):
        start = segment.start_seconds if segment.start_seconds is not None else float(idx)
        end = segment.end_seconds if segment.end_seconds is not None else start + 1.0
        parts = [p.strip() for p in _SENTENCE_SPLIT.split(segment.text) if p.strip()]
        if not parts:
            continue
        span = max(end - start, 1e-6)
        step = span / len(parts)
        for j, part in enumerate(parts):
            s0 = start + j * step
            s1 = start + (j + 1) * step
            sentences.append(
                TimedSentence(
                    index=idx,
                    text=part,
                    start_seconds=s0,
                    end_seconds=s1,
                    segment_id=f"seg-{seg_i}",
                )
            )
            idx += 1
    return tuple(sentences)


def _sentences_from_plain_text(text: str, duration: float) -> tuple[TimedSentence, ...]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    if not parts:
        return ()
    span = duration if duration > 0 else float(len(parts))
    step = span / len(parts)
    return tuple(
        TimedSentence(
            index=i,
            text=part,
            start_seconds=i * step,
            end_seconds=(i + 1) * step,
            segment_id=f"seg-{i}",
        )
        for i, part in enumerate(parts)
    )


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; returns 0.0 for zero vectors."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _depth_scores(similarities: Sequence[float]) -> list[float]:
    """TextTiling-inspired depth at each gap between adjacent sentences."""
    n = len(similarities)
    if n == 0:
        return []
    depths: list[float] = []
    for i, s in enumerate(similarities):
        left = similarities[i - 1] if i > 0 else s
        right = similarities[i + 1] if i + 1 < n else s
        depths.append(((left + right) / 2.0) - s)
    return depths


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(math.ceil(pct * len(ordered)) - 1)))
    return ordered[idx]


def _select_boundary_indices(
    similarities: Sequence[float],
    depths: Sequence[float],
    *,
    similarity_threshold: float,
    depth_percentile: float,
    n_sentences: int,
    min_chunk_sentences: int,
    max_chunk_sentences: int,
) -> list[int]:
    """Return sentence indices that *start* a new chunk (always includes 0)."""
    if n_sentences == 0:
        return []
    depth_cut = _percentile(depths, depth_percentile) if depths else 0.0
    candidate_gaps: list[int] = []
    for i, (sim, depth) in enumerate(zip(similarities, depths, strict=True)):
        # gap i sits between sentence i and i+1 → boundary starts at i+1
        if sim < similarity_threshold or depth >= depth_cut:
            candidate_gaps.append(i + 1)

    boundaries = [0]
    last = 0
    for gap in candidate_gaps:
        if gap - last >= min_chunk_sentences:
            boundaries.append(gap)
            last = gap
    # Force splits for oversized chunks
    refined: list[int] = [0]
    boundaries_ext = [*boundaries, n_sentences]
    for start, end in pairwise(boundaries_ext):
        if start == 0 and refined == [0]:
            pass
        elif start not in refined:
            refined.append(start)
        cursor = refined[-1]
        while end - cursor > max_chunk_sentences:
            window_sims = similarities[cursor : end - 1]
            if not window_sims:
                break
            # weakest similarity inside the oversized window
            rel = min(range(len(window_sims)), key=lambda j: window_sims[j])
            split_at = cursor + rel + 1
            if split_at <= cursor or split_at >= end:
                break
            refined.append(split_at)
            cursor = split_at
    if refined[-1] != 0 and n_sentences not in refined:
        pass
    return sorted(set(refined))


def semantic_chunk(
    sentences: Sequence[TimedSentence],
    config: ChunkingConfig | None = None,
    *,
    embedder: SentenceEmbedder | None = None,
) -> tuple[SemanticChunk, ...]:
    """Chunk timed sentences using embedding-distance boundary detection."""
    cfg = config or ChunkingConfig()
    if not sentences:
        return ()

    engine = embedder or SentenceTransformerEmbedder(cfg.embedding_model)
    vectors = engine.embed([s.text for s in sentences])
    if len(vectors) == 1:
        return (_build_chunk(0, sentences, 0, 1, vectors[0]),)

    similarities = [cosine_similarity(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]
    depths = _depth_scores(similarities)
    starts = _select_boundary_indices(
        similarities,
        depths,
        similarity_threshold=cfg.similarity_threshold,
        depth_percentile=cfg.depth_percentile,
        n_sentences=len(sentences),
        min_chunk_sentences=cfg.min_chunk_sentences,
        max_chunk_sentences=cfg.max_chunk_sentences,
    )
    ends = [*starts[1:], len(sentences)]
    chunks: list[SemanticChunk] = []
    for chunk_i, (start, end) in enumerate(zip(starts, ends, strict=True)):
        # Mean-pool embeddings for the chunk vector
        dims = len(vectors[0])
        pooled = [0.0] * dims
        for row in vectors[start:end]:
            for d in range(dims):
                pooled[d] += row[d]
        count = max(end - start, 1)
        pooled = [v / count for v in pooled]
        chunks.append(_build_chunk(chunk_i, sentences, start, end, pooled))
    return tuple(chunks)


def _build_chunk(
    chunk_i: int,
    sentences: Sequence[TimedSentence],
    start: int,
    end: int,
    embedding: Sequence[float],
) -> SemanticChunk:
    covered = sentences[start:end]
    text = " ".join(s.text for s in covered)
    return SemanticChunk(
        chunk_id=f"chunk-{chunk_i:04d}",
        text=text,
        start_seconds=covered[0].start_seconds,
        end_seconds=covered[-1].end_seconds,
        sentence_indices=tuple(s.index for s in covered),
        embedding=tuple(float(v) for v in embedding),
    )
