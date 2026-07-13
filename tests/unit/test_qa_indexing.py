"""Tests for YouTube id parsing and offline indexing → ask."""

from __future__ import annotations

import os

os.environ["MERIDIAN_ENV"] = "test"

import pytest

from meridian.api.qa import answer_question
from meridian.ingest.youtube import demo_transcript, extract_youtube_id
from meridian.storage.local_backend import LocalObjectStore
from meridian.workers.indexing import build_context_tree, load_context_tree, persist_index


def test_extract_youtube_id_from_url_and_prefix() -> None:
    assert extract_youtube_id("https://www.youtube.com/watch?v=c35fpGWqXnk") == "c35fpGWqXnk"
    assert extract_youtube_id("yt-c35fpGWqXnk") == "c35fpGWqXnk"
    assert extract_youtube_id("c35fpGWqXnk") == "c35fpGWqXnk"
    assert extract_youtube_id("nope") is None
    assert extract_youtube_id("https://example.com/watch?v=c35fpGWqXnk") is None


@pytest.mark.asyncio
async def test_index_and_ask_extractive(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    transcript = demo_transcript("demo-vid")
    tree = build_context_tree("demo-vid", transcript)
    assert len(tree.chunks) >= 1
    persist_index(store, video_id="demo-vid", transcript=transcript, tree=tree)
    loaded = load_context_tree(store, "demo-vid")
    assert loaded.video_id == "demo-vid"

    answer, citations, model = await answer_question(
        object_store=store,
        video_id="demo-vid",
        question="What does the cache do for memory latency?",
        provider=None,
    )
    assert "cache" in answer.lower() or "processor" in answer.lower()
    assert citations
    assert citations[0].end_time >= citations[0].start_time
    assert model == "meridian-extractive"
