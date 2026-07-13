"""Unit tests for the full hierarchical pipeline and cited answers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from meridian.core.cache import MemoryLRUCache, MultiTierCache
from meridian.core.chunking import HashingEmbedder
from meridian.core.models import (
    Citation,
    CitedAnswer,
    PipelineConfig,
    VideoSource,
)
from meridian.core.pipeline import (
    AnswerStage,
    ExtractMediaStage,
    LoadCachedTreeStage,
    StoreCachedTreeStage,
    VideoPipeline,
    build_citations,
    build_default_pipeline,
)
from meridian.providers.types import GroundedAnswer, Transcript
from tests.fixtures.synthetic_transcript import synthetic_media, synthetic_transcript


def _mock_provider(answer_text: str = "Rockets produce thrust [chunk-0001].") -> MagicMock:
    provider = MagicMock()
    provider.name = "mock"
    provider.transcribe = AsyncMock(return_value=synthetic_transcript())
    provider.answer_question = AsyncMock(
        return_value=GroundedAnswer(
            answer=answer_text,
            citations=("chunk-0001",),
            model="mock-model",
        )
    )
    return provider


@pytest.mark.asyncio
async def test_pipeline_produces_cited_answer() -> None:
    media = synthetic_media()
    provider = _mock_provider(
        "Liquid engines make thrust by expelling exhaust [chunk-0001 | 21.00s-31.00s]."
    )
    cache: MultiTierCache[Any] = MultiTierCache(memory=MemoryLRUCache(max_items=16))
    pipeline = build_default_pipeline(
        provider=provider,
        config=PipelineConfig(top_k=3, section_group_size=2),
        cache=cache,
        embedder=HashingEmbedder(),
        question="How is rocket thrust produced?",
        media=media,
        fixture_transcript=synthetic_transcript(),
    )
    result = await pipeline.run(
        VideoSource(
            video_id=media.metadata.video_id,
            content_hash=media.metadata.content_hash,
            duration_seconds=36.0,
            title=media.metadata.title,
        )
    )
    assert result.answer is not None
    assert isinstance(result.answer, CitedAnswer)
    assert result.answer.citations
    for cite in result.answer.citations:
        assert isinstance(cite, Citation)
        assert cite.end_time >= cite.start_time
        assert cite.transcript_excerpt
    assert result.tree is not None
    assert result.chunks
    assert result.keyframes
    assert result.extras.get("cache_hit") is False
    provider.answer_question.assert_awaited()


@pytest.mark.asyncio
async def test_pipeline_cache_skips_reprocessing() -> None:
    media = synthetic_media()
    provider = _mock_provider()
    cache: MultiTierCache[Any] = MultiTierCache(memory=MemoryLRUCache(max_items=16))
    cfg = PipelineConfig(top_k=2, section_group_size=2)
    source = VideoSource(
        video_id=media.metadata.video_id,
        content_hash=media.metadata.content_hash,
        duration_seconds=36.0,
    )
    first = build_default_pipeline(
        provider=provider,
        config=cfg,
        cache=cache,
        embedder=HashingEmbedder(),
        question="What about tomatoes?",
        media=media,
        fixture_transcript=synthetic_transcript(),
    )
    await first.run(source)
    assert provider.transcribe.await_count == 0  # fixture transcript path

    provider2 = _mock_provider("Tomatoes need water [chunk-0000].")
    second = build_default_pipeline(
        provider=provider2,
        config=cfg,
        cache=cache,
        embedder=HashingEmbedder(),
        question="What about tomatoes?",
        media=media,
        fixture_transcript=synthetic_transcript(),
    )
    result = await second.run(source)
    assert result.extras.get("cache_hit") is True
    assert result.answer is not None
    assert result.answer.citations


@pytest.mark.asyncio
async def test_extract_and_cache_stages_unit() -> None:
    media = synthetic_media()
    from meridian.core.models import PipelineArtifacts

    artifacts = PipelineArtifacts(
        source=VideoSource(video_id="x", content_hash="h", duration_seconds=1.0)
    )
    artifacts = await ExtractMediaStage(media=media).run(artifacts)
    assert artifacts.media is not None

    cache: MultiTierCache[Any] = MultiTierCache()
    cfg = PipelineConfig()
    artifacts = await LoadCachedTreeStage(cache, cfg).run(artifacts)
    assert artifacts.extras["cache_hit"] is False
    assert artifacts.cache_key is not None


def test_build_citations_requires_structured_fields() -> None:
    from meridian.core.models import RetrievalHit, SemanticChunk

    chunk = SemanticChunk(
        chunk_id="chunk-0002",
        text="Harvest ripe tomatoes when they turn fully red.",
        start_seconds=13.0,
        end_seconds=17.0,
        sentence_indices=(3,),
        embedding=(0.0, 1.0),
    )
    hits = [RetrievalHit(chunk=chunk, score=0.8)]
    raw = GroundedAnswer(answer="Pick red tomatoes.", citations=())
    citations = build_citations(hits, raw)
    assert len(citations) == 1
    assert citations[0].start_time == 13.0
    assert citations[0].end_time == 17.0
    assert "tomatoes" in citations[0].transcript_excerpt.lower()


def test_cited_answer_rejects_empty_citations() -> None:
    with pytest.raises(ValueError, match="at least one Citation"):
        CitedAnswer(answer="nope", citations=())


@pytest.mark.asyncio
async def test_answer_stage_alone() -> None:
    from meridian.core.models import PipelineArtifacts, RetrievalHit, SemanticChunk

    chunk = SemanticChunk(
        chunk_id="chunk-0001",
        text="Thrust is produced by expelling hot exhaust at high velocity.",
        start_seconds=26.0,
        end_seconds=31.0,
        sentence_indices=(6,),
        embedding=(1.0, 0.0),
    )
    provider = _mock_provider("Thrust comes from exhaust [chunk-0001].")
    artifacts = PipelineArtifacts(
        source=VideoSource(video_id="v"),
        hits=(RetrievalHit(chunk=chunk, score=1.0),),
    )
    artifacts = await AnswerStage(provider, question="What produces thrust?").run(artifacts)
    assert artifacts.answer is not None
    assert artifacts.answer.citations[0].chunk_id == "chunk-0001"


@pytest.mark.asyncio
async def test_store_cached_tree_noop_without_tree() -> None:
    from meridian.core.models import PipelineArtifacts

    cache: MultiTierCache[Any] = MultiTierCache()
    artifacts = PipelineArtifacts(source=VideoSource(video_id="v"))
    artifacts.extras["cache_hit"] = False
    out = await StoreCachedTreeStage(cache, PipelineConfig()).run(artifacts)
    assert out.tree is None


def test_video_pipeline_requires_stages() -> None:
    with pytest.raises(ValueError, match="at least one stage"):
        VideoPipeline([])


def test_transcript_type_export() -> None:
    assert isinstance(synthetic_transcript(), Transcript)
