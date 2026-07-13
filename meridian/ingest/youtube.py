"""YouTube ingest helpers (captions → timed transcript)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from meridian.providers.types import Transcript, TranscriptSegment

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PREFIX_RE = re.compile(r"^yt-([A-Za-z0-9_-]{11})$", re.IGNORECASE)


def extract_youtube_id(value: str | None) -> str | None:
    """Extract an 11-char YouTube id from a URL, ``yt-<id>`` token, or bare id."""
    if not value:
        return None
    raw = value.strip()
    prefixed = _PREFIX_RE.match(raw)
    if prefixed:
        return prefixed.group(1)
    if _ID_RE.match(raw):
        return raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _YT_HOSTS and not host.endswith(".youtube.com"):
        return None
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.lstrip("/").split("/")[0]
        return candidate if _ID_RE.match(candidate) else None
    qs = parse_qs(parsed.query)
    if qs.get("v"):
        candidate = qs["v"][0]
        return candidate if _ID_RE.match(candidate) else None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
        return parts[1] if _ID_RE.match(parts[1]) else None
    return None


def fetch_youtube_transcript(video_id: str, *, languages: list[str] | None = None) -> Transcript:
    """Fetch timed captions via youtube-transcript-api (no audio download)."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    langs = languages or ["en", "en-US", "en-GB", "hi", "a.en"]
    api = YouTubeTranscriptApi()
    try:
        # Prefer explicit language list; fall back to any generated/manual track.
        try:
            fetched = api.fetch(video_id, languages=langs)
        except Exception:
            transcript_list = api.list(video_id)
            fetched = transcript_list.find_transcript(langs).fetch()
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
        raise RuntimeError(
            f"Could not fetch YouTube captions for {video_id}: {exc}. "
            "The video needs captions (auto or manual) for Meridian ingest."
        ) from exc
    except Exception as exc:  # library surface varies by version
        raise RuntimeError(f"YouTube transcript fetch failed for {video_id}: {exc}") from exc

    snippets = _snippets_from_fetched(fetched)
    if not snippets:
        raise RuntimeError(f"YouTube captions for {video_id} were empty")

    segments: list[TranscriptSegment] = []
    texts: list[str] = []
    for item in snippets:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        duration = float(item.get("duration", 0.0))
        end = start + max(duration, 0.01)
        segments.append(TranscriptSegment(text=text, start_seconds=start, end_seconds=end))
        texts.append(text)

    duration_seconds = float(segments[-1].end_seconds or 0.0) if segments else None
    return Transcript(
        text=" ".join(texts),
        segments=tuple(segments),
        duration_seconds=duration_seconds if duration_seconds else None,
        model="youtube-captions",
    )


def _snippets_from_fetched(fetched: Any) -> list[dict[str, Any]]:
    if fetched is None:
        return []
    if isinstance(fetched, list):
        return [dict(x) if not isinstance(x, dict) else x for x in fetched]
    # youtube-transcript-api >=1.0 FetchedTranscript
    to_raw = getattr(fetched, "to_raw_data", None)
    if callable(to_raw):
        raw = to_raw()
        return list(raw) if raw else []
    snippets = getattr(fetched, "snippets", None)
    if snippets is not None:
        out: list[dict[str, Any]] = []
        for snip in snippets:
            out.append(
                {
                    "text": getattr(snip, "text", ""),
                    "start": getattr(snip, "start", 0.0),
                    "duration": getattr(snip, "duration", 0.0),
                }
            )
        return out
    return []


def demo_transcript(video_id: str) -> Transcript:
    """Deterministic offline transcript for non-YouTube / unit-test jobs."""
    lines = [
        (0.0, 8.0, f"Meridian demo content for video {video_id}."),
        (
            8.0,
            22.0,
            "A CPU cache stores frequently used data closer to the processor "
            "to reduce average memory latency.",
        ),
        (
            22.0,
            34.0,
            "Clicking a citation seeks the player to that timestamp automatically.",
        ),
        (
            50.0,
            62.0,
            "On a cache miss the system fetches the block from slower main memory.",
        ),
        (
            70.0,
            88.0,
            "First we run offline evals on a labeled set, then shadow traffic, "
            "then a small A/B test before launch.",
        ),
    ]
    segments = tuple(
        TranscriptSegment(text=text, start_seconds=start, end_seconds=end)
        for start, end, text in lines
    )
    return Transcript(
        text=" ".join(t for _, _, t in lines),
        segments=segments,
        duration_seconds=88.0,
        model="meridian-demo-fixture",
    )
