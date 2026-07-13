"""Unit tests for question-aware retrieval."""

from __future__ import annotations

from meridian.core.chunking import HashingEmbedder, semantic_chunk, sentences_from_transcript
from meridian.core.models import (
    ChunkingConfig,
    ContextTree,
    HierarchyNode,
    PipelineConfig,
    RetrievalHit,
    SemanticChunk,
    VideoSource,
)
from meridian.core.pipeline import HierarchyBuildStage, KeyframeSelectStage, PipelineArtifacts
from meridian.core.retrieval import build_grounding_context, retrieve
from tests.fixtures.synthetic_transcript import synthetic_transcript


async def _build_tree() -> ContextTree:
    transcript = synthetic_transcript()
    sentences = sentences_from_transcript(transcript)
    chunks = semantic_chunk(
        sentences,
        ChunkingConfig(min_chunk_sentences=2, max_chunk_sentences=5, similarity_threshold=0.35),
        embedder=HashingEmbedder(),
    )
    artifacts = PipelineArtifacts(
        source=VideoSource(video_id="fixture", duration_seconds=36.0),
        sentences=sentences,
        chunks=chunks,
    )
    artifacts = await KeyframeSelectStage().run(artifacts)
    artifacts = await HierarchyBuildStage(PipelineConfig(section_group_size=2)).run(artifacts)
    assert artifacts.tree is not None
    return artifacts.tree


async def test_retrieve_prefers_topic_aligned_chunk() -> None:
    tree = await _build_tree()
    embedder = HashingEmbedder()
    hits = retrieve(tree, "How does rocket thrust work?", embedder=embedder, top_k=2)
    assert hits
    top_text = hits[0].chunk.text.lower()
    assert any(token in top_text for token in ("rocket", "thrust", "exhaust", "staging", "orbital"))


async def test_build_grounding_context_includes_timestamps() -> None:
    chunk = SemanticChunk(
        chunk_id="chunk-0001",
        text="Staging drops empty tanks.",
        start_seconds=31.0,
        end_seconds=36.0,
        sentence_indices=(7,),
        embedding=(0.1, 0.2),
    )
    ctx = build_grounding_context([RetrievalHit(chunk=chunk, score=0.9)])
    assert "chunk-0001" in ctx
    assert "31.00s-36.00s" in ctx


def test_section_boost_helper_handles_empty_tree() -> None:
    tree = ContextTree(
        video_id="empty",
        root_id="root:empty",
        nodes={
            "root:empty": HierarchyNode(
                node_id="root:empty",
                level=2,
                text="",
                start_seconds=0.0,
                end_seconds=0.0,
            )
        },
        chunks=(),
    )
    assert retrieve(tree, "anything", embedder=HashingEmbedder()) == ()
