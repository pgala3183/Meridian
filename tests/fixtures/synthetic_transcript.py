"""Synthetic public-domain-style transcript fixture for pipeline unit tests.

Two clearly separated topics (gardening, then rockets) so embedding-distance
chunking has a sharp boundary without needing a real video file.
"""

from __future__ import annotations

from meridian.core.models import ExtractedMedia, VideoMetadata
from meridian.providers.types import Transcript, TranscriptSegment

GARDENING_SEGMENTS: tuple[TranscriptSegment, ...] = (
    TranscriptSegment(
        text="Welcome to the community garden tour.",
        start_seconds=0.0,
        end_seconds=3.0,
    ),
    TranscriptSegment(
        text="Today we plant tomatoes in raised beds with compost.",
        start_seconds=3.0,
        end_seconds=8.0,
    ),
    TranscriptSegment(
        text="Water deeply twice a week and mulch to retain moisture.",
        start_seconds=8.0,
        end_seconds=13.0,
    ),
    TranscriptSegment(
        text="Harvest ripe tomatoes when they turn fully red.",
        start_seconds=13.0,
        end_seconds=17.0,
    ),
)

ROCKET_SEGMENTS: tuple[TranscriptSegment, ...] = (
    TranscriptSegment(
        text="Next we switch topics to orbital rocketry.",
        start_seconds=17.0,
        end_seconds=21.0,
    ),
    TranscriptSegment(
        text="A liquid rocket engine burns fuel with liquid oxygen.",
        start_seconds=21.0,
        end_seconds=26.0,
    ),
    TranscriptSegment(
        text="Thrust is produced by expelling hot exhaust at high velocity.",
        start_seconds=26.0,
        end_seconds=31.0,
    ),
    TranscriptSegment(
        text="Staging drops empty tanks to raise the payload mass ratio.",
        start_seconds=31.0,
        end_seconds=36.0,
    ),
)

SYNTHETIC_SEGMENTS: tuple[TranscriptSegment, ...] = GARDENING_SEGMENTS + ROCKET_SEGMENTS


def synthetic_transcript() -> Transcript:
    """Return a timed transcript covering gardening then rocketry."""
    text = " ".join(seg.text for seg in SYNTHETIC_SEGMENTS)
    return Transcript(
        text=text,
        segments=SYNTHETIC_SEGMENTS,
        language="en",
        duration_seconds=36.0,
        model="fixture",
    )


def synthetic_media(*, video_id: str = "fixture-garden-rocket") -> ExtractedMedia:
    """ExtractedMedia stand-in for a short public-domain-style clip."""
    transcript = synthetic_transcript()
    return ExtractedMedia(
        metadata=VideoMetadata(
            video_id=video_id,
            duration_seconds=36.0,
            title="Garden then Rocket (synthetic fixture)",
            content_hash="fixture-hash-garden-rocket-v1",
        ),
        audio_bytes=b"FAKE_WAV_BYTES",
        audio_mime_type="audio/wav",
        transcript_text=transcript.text,
    )
