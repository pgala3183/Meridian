"""Smoke tests for the benchmark harness (offline, no live APIs)."""

from __future__ import annotations

import pytest

from tests.benchmarks.eval_dataset import AnswerRubric, load_eval_dataset, pin_dataset_checksums
from tests.benchmarks.harness import run_evaluation, summarize_results
from tests.benchmarks.judge import HeuristicRubricJudge


def test_dataset_loads_all_video_types() -> None:
    pin_dataset_checksums()
    items = load_eval_dataset()
    types = {i.video_type.value for i in items}
    assert types == {"lecture", "interview", "product_demo"}
    assert all(i.content_hash.startswith("sha256:") for i in items)
    assert all(i.questions for i in items)


def test_heuristic_judge_scores_in_unit_interval() -> None:
    scores = HeuristicRubricJudge().score(
        question="What is a cache?",
        answer="A CPU cache stores frequently used data closer to the processor [chunk-0000].",
        context=(
            "[chunk-0000 | 12.00s-20.00s] A CPU cache stores frequently used data "
            "closer to the processor."
        ),
        rubric=AnswerRubric(
            must_include=("cache", "data"),
            acceptable_concepts=("processor",),
            forbidden=("tomato",),
            expected_answer="A CPU cache stores frequently used data closer to the processor.",
        ),
        citation_count=1,
    )
    assert 0.0 <= scores.overall <= 1.0
    assert scores.citation_accuracy > 0


@pytest.mark.asyncio
async def test_run_evaluation_produces_summary() -> None:
    pin_dataset_checksums()
    report = await run_evaluation()
    assert report.results
    assert "cost_reduction_pct" in report.summary
    assert "cached_speedup_vs_cold_hierarchical" in report.summary
    assert report.summary["n_naive"] > 0
    assert report.summary["n_hierarchical"] > 0
    empty = summarize_results([])
    assert empty["cost_reduction_pct"] == 0.0
