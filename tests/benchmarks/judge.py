"""Answer quality judges for the eval harness.

LLM-as-judge scores are an **approximation**, not ground truth. Prefer the
heuristic rubric judge for CI reproducibility; enable an LLM judge only when
a live provider is intentionally configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from tests.benchmarks.eval_dataset import AnswerRubric


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
