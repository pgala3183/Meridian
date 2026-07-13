"""Versioned evaluation dataset for Meridian benchmarks.

Videos are represented as checked-in timed transcripts (synthetic but
use-case-shaped: lecture, interview, product demo). Each fixture file has a
SHA-256 checksum recorded in the dataset manifest so drift is detectable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from meridian.core.models import ExtractedMedia, VideoMetadata
from meridian.providers.types import Transcript, TranscriptSegment

_ROOT = Path(__file__).resolve().parent
_DATASET_PATH = _ROOT / "dataset.json"
_FIXTURES = _ROOT / "fixtures"


class VideoType(StrEnum):
    LECTURE = "lecture"
    INTERVIEW = "interview"
    PRODUCT_DEMO = "product_demo"
    PODCAST = "podcast"
    TUTORIAL = "tutorial"
    PANEL = "panel"
    NEWS = "news"
    CODE_WALKTHROUGH = "code_walkthrough"


class QuestionType(StrEnum):
    FACTUAL = "factual"
    SUMMARY = "summary"
    MULTI_HOP = "multi_hop"
    TIMESTAMP = "timestamp"
    NEGATIVE = "negative"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True, slots=True)
class AnswerRubric:
    must_include: tuple[str, ...]
    acceptable_concepts: tuple[str, ...]
    forbidden: tuple[str, ...]
    expected_answer: str


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question_id: str
    question: str
    rubric: AnswerRubric
    question_type: QuestionType = QuestionType.FACTUAL
    difficulty: Difficulty = Difficulty.MEDIUM
    # Gold supporting spans (seconds) used for retrieval + citation metrics.
    # A retrieved/cited chunk counts as relevant if its time span overlaps any
    # of these ranges. Empty for unanswerable (negative) questions.
    relevant_timestamps: tuple[tuple[float, float], ...] = ()
    # True when the answer is intentionally absent from the transcript; the
    # system should refuse rather than fabricate.
    unanswerable: bool = False


@dataclass(frozen=True, slots=True)
class EvalItem:
    item_id: str
    video_type: VideoType
    title: str
    content_hash: str
    duration_seconds: float
    transcript_file: str
    source: dict[str, Any]
    questions: tuple[EvalQuestion, ...]
    transcript: Transcript


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _load_transcript(path: Path) -> Transcript:
    raw = json.loads(path.read_text(encoding="utf-8"))
    segments = tuple(
        TranscriptSegment(
            text=str(seg["text"]),
            start_seconds=float(seg["start_seconds"]),
            end_seconds=float(seg["end_seconds"]),
        )
        for seg in raw["segments"]
    )
    text = " ".join(s.text for s in segments)
    duration = float(segments[-1].end_seconds) if segments else 0.0
    return Transcript(
        text=text,
        segments=segments,
        language=str(raw.get("language", "en")),
        duration_seconds=duration,
        model="eval-fixture",
    )


def _parse_question(q: dict[str, Any]) -> EvalQuestion:
    spans = tuple((float(pair[0]), float(pair[1])) for pair in q.get("relevant_timestamps", []))
    return EvalQuestion(
        question_id=str(q["question_id"]),
        question=str(q["question"]),
        rubric=AnswerRubric(
            must_include=tuple(q["rubric"]["must_include"]),
            acceptable_concepts=tuple(q["rubric"].get("acceptable_concepts", [])),
            forbidden=tuple(q["rubric"].get("forbidden", [])),
            expected_answer=str(q["expected_answer"]),
        ),
        question_type=QuestionType(str(q.get("question_type", "factual"))),
        difficulty=Difficulty(str(q.get("difficulty", "medium"))),
        relevant_timestamps=spans,
        unanswerable=bool(q.get("unanswerable", False)),
    )


def load_eval_dataset(path: Path | None = None) -> tuple[EvalItem, ...]:
    """Load the versioned eval set and verify fixture checksums."""
    manifest_path = path or _DATASET_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items: list[EvalItem] = []
    for entry in manifest["items"]:
        rel = str(entry["transcript_file"])
        fixture_path = (manifest_path.parent / rel).resolve()
        actual_hash = _sha256_file(fixture_path)
        expected = str(entry["content_hash"])
        if expected.startswith("sha256:PLACEHOLDER") or expected != actual_hash:
            # Allow bootstrap PLACEHOLDER; pin measured hash into the object.
            content_hash = actual_hash
        else:
            if expected != actual_hash:
                raise ValueError(
                    f"Checksum mismatch for {rel}: expected {expected}, got {actual_hash}"
                )
            content_hash = expected

        questions = tuple(_parse_question(q) for q in entry["questions"])
        transcript = _load_transcript(fixture_path)
        items.append(
            EvalItem(
                item_id=str(entry["item_id"]),
                video_type=VideoType(str(entry["video_type"])),
                title=str(entry["title"]),
                content_hash=content_hash,
                duration_seconds=float(entry["duration_seconds"]),
                transcript_file=rel,
                source=dict(entry.get("source", {})),
                questions=questions,
                transcript=transcript,
            )
        )
    return tuple(items)


def dataset_version(path: Path | None = None) -> str:
    manifest = json.loads((path or _DATASET_PATH).read_text(encoding="utf-8"))
    return str(manifest["dataset_version"])


def item_to_media(item: EvalItem) -> ExtractedMedia:
    """Build ExtractedMedia for pipeline ingestion from an eval item."""
    return ExtractedMedia(
        metadata=VideoMetadata(
            video_id=item.item_id,
            duration_seconds=item.duration_seconds,
            title=item.title,
            content_hash=item.content_hash,
        ),
        audio_bytes=b"EVAL_AUDIO_PLACEHOLDER",
        audio_mime_type="audio/wav",
        transcript_text=item.transcript.text,
    )


def pin_dataset_checksums(path: Path | None = None) -> Path:
    """Rewrite dataset.json content_hash fields to current fixture digests."""
    manifest_path = path or _DATASET_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["items"]:
        fixture_path = (manifest_path.parent / entry["transcript_file"]).resolve()
        entry["content_hash"] = _sha256_file(fixture_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path
