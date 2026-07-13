"""Smoke + metric tests for the benchmark harness (offline, no live APIs)."""

from __future__ import annotations

import pytest

from meridian.core.models import Citation, RetrievalHit, SemanticChunk
from tests.benchmarks.eval_dataset import (
    AnswerRubric,
    QuestionType,
    load_eval_dataset,
    pin_dataset_checksums,
)
from tests.benchmarks.harness import run_evaluation, summarize_results
from tests.benchmarks.judge import (
    HeuristicRubricJudge,
    is_refusal,
    refusal_accuracy,
    score_citations,
)
from tests.benchmarks.retrieval_metrics import mrr, ndcg_at_k, recall_at_k, score_retrieval
from tests.benchmarks.thresholds import check_thresholds


def _chunk(chunk_id: str, start: float, end: float) -> SemanticChunk:
    return SemanticChunk(
        chunk_id=chunk_id,
        text=f"chunk {chunk_id}",
        start_seconds=start,
        end_seconds=end,
        sentence_indices=(0,),
    )


def _hit(chunk_id: str, start: float, end: float) -> RetrievalHit:
    return RetrievalHit(chunk=_chunk(chunk_id, start, end), score=1.0, node_id=f"leaf:{chunk_id}")


def test_dataset_is_large_and_diverse() -> None:
    pin_dataset_checksums()
    items = load_eval_dataset()
    n_questions = sum(len(i.questions) for i in items)
    types = {i.video_type.value for i in items}

    assert len(items) >= 10
    assert n_questions >= 80
    # Original three types plus the expansion categories are all present.
    assert {"lecture", "interview", "product_demo"}.issubset(types)
    assert len(types) >= 6
    assert all(i.content_hash.startswith("sha256:") for i in items)
    assert all(i.questions for i in items)
    # Negative (unanswerable) questions exist for refusal evaluation.
    assert any(q.unanswerable for i in items for q in i.questions)
    # Answerable questions carry gold spans for retrieval/citation metrics.
    assert all(
        q.relevant_timestamps
        for i in items
        for q in i.questions
        if q.question_type != QuestionType.NEGATIVE
    )


def test_retrieval_metrics_reward_correct_ranking() -> None:
    gold = [(40.0, 50.0)]
    hits = [_hit("c1", 40.0, 50.0), _hit("c2", 0.0, 10.0), _hit("c3", 90.0, 100.0)]
    assert recall_at_k(hits, gold, k=3) == 1.0
    assert mrr(hits, gold) == 1.0
    assert ndcg_at_k(hits, gold, k=3) == 1.0

    # Relevant chunk buried at rank 3 => lower MRR, recall still 1 at k=3.
    buried = [_hit("c2", 0.0, 10.0), _hit("c3", 90.0, 100.0), _hit("c1", 40.0, 50.0)]
    assert recall_at_k(buried, gold, k=3) == 1.0
    assert mrr(buried, gold) == pytest.approx(1.0 / 3.0)
    assert ndcg_at_k(buried, gold, k=3) < 1.0

    # Missed entirely => zeros.
    missed = [_hit("c2", 0.0, 10.0), _hit("c3", 90.0, 100.0)]
    assert recall_at_k(missed, gold, k=3) == 0.0
    assert mrr(missed, gold) == 0.0


def test_retrieval_metrics_none_for_unanswerable() -> None:
    result = score_retrieval([_hit("c1", 0.0, 10.0)], gold=[], k=3)
    assert result.recall_at_k is None
    assert result.mrr is None
    assert result.ndcg_at_k is None


def test_citation_precision_and_recall() -> None:
    gold = [(40.0, 50.0), (60.0, 70.0)]
    citations = (
        Citation(start_time=41.0, end_time=49.0, transcript_excerpt="x", chunk_id="c1"),
        Citation(start_time=0.0, end_time=5.0, transcript_excerpt="y", chunk_id="c2"),
    )
    scores = score_citations(citations, gold)
    assert scores.precision == pytest.approx(0.5)
    assert scores.recall == pytest.approx(0.5)

    # Unanswerable => not applicable.
    empty = score_citations((), gold=[])
    assert empty.precision is None
    assert empty.recall is None


def test_refusal_detection() -> None:
    assert is_refusal("The context does not provide information about that.")
    assert not is_refusal("The host is Samay Raina.")
    assert refusal_accuracy("I cannot determine that.", unanswerable=True) == 1.0
    assert refusal_accuracy("The answer is 42.", unanswerable=True) == 0.0
    assert refusal_accuracy("The answer is 42.", unanswerable=False) == 1.0


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
    s = report.summary
    assert report.results
    assert "cost_reduction_pct" in s
    assert "cached_speedup_vs_cold_hierarchical" in s
    assert s["n_naive"] > 0
    assert s["n_hierarchical"] > 0
    # New aggregate metrics are present.
    for key in (
        "retrieval_recall_at_k",
        "retrieval_mrr",
        "retrieval_ndcg_at_k",
        "citation_precision",
        "refusal_accuracy_answerable",
        "ask_latency_ms_p95",
        "by_video_type",
        "by_question_type",
    ):
        assert key in s

    empty = summarize_results([])
    assert empty["cost_reduction_pct"] == 0.0


@pytest.mark.asyncio
async def test_regression_gate_thresholds_pass() -> None:
    """PR gate: offline eval must clear conservative quality/latency floors."""
    pin_dataset_checksums()
    report = await run_evaluation()
    failures = check_thresholds(report.summary)
    assert not failures, f"threshold regressions: {[str(f) for f in failures]}"
