"""Ingest package — source acquisition for video intelligence."""

from meridian.ingest.youtube import (
    demo_transcript,
    extract_youtube_id,
    fetch_youtube_transcript,
)

__all__ = [
    "demo_transcript",
    "extract_youtube_id",
    "fetch_youtube_transcript",
]
