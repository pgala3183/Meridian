"""Unit tests for semantic chunking."""

from __future__ import annotations

from meridian.core.chunking import (
    HashingEmbedder,
    cosine_similarity,
    semantic_chunk,
    sentences_from_transcript,
)
from meridian.core.models import ChunkingConfig
from tests.fixtures.synthetic_transcript import synthetic_transcript


def test_sentences_from_transcript_preserves_timing() -> None:
    transcript = synthetic_transcript()
    sentences = sentences_from_transcript(transcript)
    assert len(sentences) >= 8
    assert sentences[0].start_seconds == 0.0
    assert sentences[-1].end_seconds == 36.0
    assert all(s.text for s in sentences)


def test_semantic_chunk_splits_topic_shift() -> None:
    transcript = synthetic_transcript()
    sentences = sentences_from_transcript(transcript)
    config = ChunkingConfig(
        similarity_threshold=0.35,
        min_chunk_sentences=2,
        max_chunk_sentences=6,
        depth_percentile=0.6,
    )
    chunks = semantic_chunk(sentences, config, embedder=HashingEmbedder(dimensions=64))
    assert len(chunks) >= 2
    # First chunk should be gardening-heavy; a later chunk should mention rockets.
    joined_early = " ".join(c.text for c in chunks[:1]).lower()
    joined_late = " ".join(c.text for c in chunks[1:]).lower()
    assert "tomato" in joined_early or "garden" in joined_early
    assert "rocket" in joined_late or "thrust" in joined_late or "orbital" in joined_late
    for chunk in chunks:
        assert chunk.start_seconds <= chunk.end_seconds
        assert chunk.embedding is not None
        assert chunk.chunk_id.startswith("chunk-")


def test_cosine_similarity_identical_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_hashing_embedder_is_deterministic() -> None:
    emb = HashingEmbedder(dimensions=32)
    a = emb.embed(["liquid rocket engine"])[0]
    b = emb.embed(["liquid rocket engine"])[0]
    c = emb.embed(["tomato compost garden"])[0]
    assert a == b
    assert cosine_similarity(a, c) < cosine_similarity(a, b)
