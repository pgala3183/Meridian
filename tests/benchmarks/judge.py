"""Answer quality judges for the eval harness.

LLM-as-judge scores are an **approximation**, not ground truth. Prefer the
heuristic rubric judge for CI reproducibility; enable an LLM judge only when
a live provider is intentionally configured.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from meridian.core.models import Citation
from tests.benchmarks.eval_dataset import AnswerRubric

GoldSpans = Sequence[tuple[float, float]]

# Phrases that signal the model declined to answer (used for refusal accuracy).
_REFUSAL_PATTERNS = (
    "does not provide",
    "does not contain",
    "does not mention",
    "not provide information",
    "no information",
    "insufficient context",
    "context is insufficient",
    "cannot determine",
    "can't determine",
    "not enough context",
    "not mentioned",
    "not discussed",
    "not stated",
    "unable to answer",
    "i don't know",
    "i do not know",
)


@dataclass(frozen=True, slots=True)
class JudgeScores:
    """Per-answer quality dimensions in ``[0, 1]``."""

    groundedness: float
    correctness: float
    citation_accuracy: float

    @property
    def overall(self) -> float:
        return (self.groundedness + self.correctness + self.citation_accuracy) / 3.0


class AnswerJudge(Protocol):
    def score(
        self,
        *,
        question: str,
        answer: str,
        context: str,
        rubric: AnswerRubric,
        citation_count: int,
    ) -> JudgeScores: ...


class HeuristicRubricJudge:
    """Deterministic offline judge based on rubric keyword coverage.

    This is intentionally simple and reproducible. It approximates
    correctness/groundedness for CI; it is not a substitute for human review.
    """

    def score(
        self,
        *,
        question: str,
        answer: str,
        context: str,
        rubric: AnswerRubric,
        citation_count: int,
    ) -> JudgeScores:
        _ = question
        text = answer.lower()
        ctx = context.lower()

        must_hits = sum(1 for t in rubric.must_include if t.lower() in text)
        must_score = must_hits / max(len(rubric.must_include), 1)

        concept_hits = sum(1 for t in rubric.acceptable_concepts if t.lower() in text)
        concept_score = (
            concept_hits / max(len(rubric.acceptable_concepts), 1)
            if rubric.acceptable_concepts
            else 0.0
        )

        forbidden_hits = sum(1 for t in rubric.forbidden if t.lower() in text)
        forbidden_penalty = min(1.0, 0.35 * forbidden_hits)

        # Overlap with expected answer tokens (coarse correctness proxy).
        expected_tokens = set(re.findall(r"[a-z0-9]+", rubric.expected_answer.lower()))
        answer_tokens = set(re.findall(r"[a-z0-9]+", text))
        overlap = len(expected_tokens & answer_tokens) / max(len(expected_tokens), 1)

        correctness = max(
            0.0,
            min(1.0, 0.55 * must_score + 0.25 * overlap + 0.20 * concept_score - forbidden_penalty),
        )

        # Groundedness: answer tokens that also appear in context.
        if not answer_tokens:
            groundedness = 0.0
        else:
            groundedness = len(answer_tokens & set(re.findall(r"[a-z0-9]+", ctx))) / len(
                answer_tokens
            )

        # Citation accuracy: presence of citations when context was retrieved.
        if citation_count <= 0:
            citation_accuracy = 0.0
        else:
            citation_accuracy = 1.0 if citation_count > 0 else 0.0
            # Prefer answers that mention timestamps or chunk ids.
            if re.search(r"\d+(?:\.\d+)?s|chunk-\d+", answer, re.I):
                citation_accuracy = min(1.0, citation_accuracy + 0.15)

        return JudgeScores(
            groundedness=round(min(1.0, groundedness), 4),
            correctness=round(correctness, 4),
            citation_accuracy=round(min(1.0, citation_accuracy), 4),
        )


@dataclass(frozen=True, slots=True)
class CitationScores:
    """Citation grounding vs gold spans (``None`` = not applicable)."""

    precision: float | None
    recall: float | None
    count: int
    supported: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "citation_precision": _round(self.precision),
            "citation_recall": _round(self.recall),
            "citation_count": self.count,
            "citations_supported": self.supported,
        }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _citation_overlaps(citation: Citation, gold: GoldSpans) -> bool:
    return any(
        citation.start_time < g_end and g_start < citation.end_time for g_start, g_end in gold
    )


def score_citations(citations: Sequence[Citation], gold: GoldSpans) -> CitationScores:
    """Precision/recall of citations against gold supporting spans.

    - precision: cited spans overlapping a gold span / total citations.
    - recall: gold spans covered by at least one citation / total gold spans.

    Both are ``None`` for unanswerable questions (no gold spans) since a correct
    refusal should carry no citations.
    """
    if not gold:
        return CitationScores(precision=None, recall=None, count=len(citations), supported=0)

    supported = sum(1 for c in citations if _citation_overlaps(c, gold))
    precision = (supported / len(citations)) if citations else 0.0
    covered = sum(
        1
        for g_start, g_end in gold
        if any(c.start_time < g_end and g_start < c.end_time for c in citations)
    )
    recall = covered / len(gold)
    return CitationScores(
        precision=precision,
        recall=recall,
        count=len(citations),
        supported=supported,
    )


def is_refusal(answer: str) -> bool:
    """Heuristic: did the answer decline to answer / claim missing context?"""
    text = answer.lower()
    return any(pattern in text for pattern in _REFUSAL_PATTERNS)


def refusal_accuracy(answer: str, *, unanswerable: bool) -> float:
    """1.0 when the refusal behavior matches the ground truth, else 0.0.

    Unanswerable questions should be refused; answerable ones should not.
    """
    refused = is_refusal(answer)
    if unanswerable:
        return 1.0 if refused else 0.0
    return 1.0 if not refused else 0.0


class LLMJudge:
    """Optional LLM-as-judge wrapper around a MultimodalProvider.

    Explicitly approximate — model self-grading is biased. Use for exploratory
    analysis; report heuristic scores as the CI baseline.
    """

    def __init__(self, provider: object) -> None:
        self._provider = provider

    def score(
        self,
        *,
        question: str,
        answer: str,
        context: str,
        rubric: AnswerRubric,
        citation_count: int,
    ) -> JudgeScores:
        # Fall back to heuristic if async provider cannot be called sync here.
        # Live LLM judging is invoked from the async harness path when enabled.
        return HeuristicRubricJudge().score(
            question=question,
            answer=answer,
            context=context,
            rubric=rubric,
            citation_count=citation_count,
        )
