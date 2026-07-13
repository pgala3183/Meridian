"""Core evaluation harness: hierarchical pipeline vs naive baseline."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from meridian.core.cache import MemoryLRUCache, MultiTierCache
from meridian.core.chunking import HashingEmbedder
from meridian.core.models import PipelineConfig, VideoSource
from meridian.core.pipeline import (
    AnswerStage,
    ExtractMediaStage,
    HierarchyBuildStage,
    KeyframeSelectStage,
    LoadCachedTreeStage,
    PipelineStage,
    RetrieveStage,
    SemanticChunkStage,
    StoreCachedTreeStage,
    TranscribeStage,
    VideoPipeline,
)
from meridian.core.retrieval import build_grounding_context
from meridian.providers.base import MultimodalProvider
from meridian.providers.types import ProviderRequest
from tests.benchmarks.baseline import DeterministicEvalProvider, _approx_tokens, run_naive_baseline
from tests.benchmarks.eval_dataset import EvalItem, EvalQuestion, item_to_media, load_eval_dataset
from tests.benchmarks.judge import HeuristicRubricJudge, JudgeScores


@dataclass
class StageTiming:
    stage: str
    seconds: float


@dataclass
class QuestionResult:
    item_id: str
    question_id: str
    mode: str
    answer: str
    latency_seconds: float
    estimated_usd: float
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    stage_timings: list[StageTiming] = field(default_factory=list)
    quality: dict[str, float] = field(default_factory=dict)
    citation_count: int = 0


@dataclass
class EvalReport:
    dataset_version: str
    results: list[QuestionResult]
    summary: dict[str, Any]


class TimedStage(PipelineStage):
    """Wrap a stage to record wall-clock duration."""

    def __init__(self, inner: PipelineStage, timings: list[StageTiming]) -> None:
        self.inner = inner
        self.name = inner.name
        self._timings = timings

    async def run(self, artifacts):
        start = time.perf_counter()
        out = await self.inner.run(artifacts)
        self._timings.append(
            StageTiming(stage=self.inner.name, seconds=time.perf_counter() - start)
        )
        return out


def _timed_pipeline(
    *,
    provider: MultimodalProvider,
    config: PipelineConfig,
    cache: MultiTierCache[Any],
    embedder: HashingEmbedder,
    question: str,
    media: Any,
    fixture_transcript: Any,
    timings: list[StageTiming],
) -> VideoPipeline:
    stages: list[PipelineStage] = [
        ExtractMediaStage(media=media),
        LoadCachedTreeStage(cache, config),
        TranscribeStage(provider, fixture_transcript=fixture_transcript),
        SemanticChunkStage(config, embedder=embedder),
        KeyframeSelectStage(),
        HierarchyBuildStage(config),
        StoreCachedTreeStage(cache, config),
        RetrieveStage(config, embedder=embedder, question=question),
        AnswerStage(provider, question=question),
    ]
    return VideoPipeline([TimedStage(s, timings) for s in stages])


async def _run_hierarchical_once(
    *,
    item: EvalItem,
    question: EvalQuestion,
    provider: MultimodalProvider,
    cache: MultiTierCache[Any],
    config: PipelineConfig,
    embedder: HashingEmbedder,
) -> QuestionResult:
    timings: list[StageTiming] = []
    media = item_to_media(item)
    pipeline = _timed_pipeline(
        provider=provider,
        config=config,
        cache=cache,
        embedder=embedder,
        question=question.question,
        media=media,
        fixture_transcript=item.transcript,
        timings=timings,
    )
    t0 = time.perf_counter()
    artifacts = await pipeline.run(
        VideoSource(
            video_id=item.item_id,
            content_hash=item.content_hash,
            duration_seconds=item.duration_seconds,
            title=item.title,
        )
    )
    wall = time.perf_counter() - t0
    assert artifacts.answer is not None
    context = build_grounding_context(artifacts.hits) if artifacts.hits else ""
    in_tokens = _approx_tokens(context) + _approx_tokens(question.question)
    out_tokens = _approx_tokens(artifacts.answer.answer)
    cost = await provider.estimate_cost(
        ProviderRequest(
            operation="answer_question",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
    )
    judge = HeuristicRubricJudge()
    scores: JudgeScores = judge.score(
        question=question.question,
        answer=artifacts.answer.answer,
        context=context,
        rubric=question.rubric,
        citation_count=len(artifacts.answer.citations),
    )
    return QuestionResult(
        item_id=item.item_id,
        question_id=question.question_id,
        mode="hierarchical",
        answer=artifacts.answer.answer,
        latency_seconds=wall,
        estimated_usd=cost.estimated_usd,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cache_hit=bool(artifacts.extras.get("cache_hit")),
        stage_timings=timings,
        quality={
            "groundedness": scores.groundedness,
            "correctness": scores.correctness,
            "citation_accuracy": scores.citation_accuracy,
            "overall": scores.overall,
        },
        citation_count=len(artifacts.answer.citations),
    )


async def run_evaluation(
    *,
    provider: MultimodalProvider | None = None,
    repeat_cached_queries: bool = True,
) -> EvalReport:
    """Run full eval: naive baseline + hierarchical (cold) + hierarchical (warm)."""
    from tests.benchmarks.eval_dataset import dataset_version

    items = load_eval_dataset()
    provider = provider or DeterministicEvalProvider()
    config = PipelineConfig(top_k=3, section_group_size=2, cache_enabled=True)
    embedder = HashingEmbedder(dimensions=64)
    results: list[QuestionResult] = []

    # Shared cache across questions for the same video to measure hit rate.
    cache: MultiTierCache[Any] = MultiTierCache(memory=MemoryLRUCache(max_items=64))

    for item in items:
        for question in item.questions:
            # --- Naive baseline ---
            t0 = time.perf_counter()
            naive = await run_naive_baseline(
                provider=provider,
                transcript=item.transcript,
                question=question.question,
            )
            naive_wall = time.perf_counter() - t0
            naive_scores = HeuristicRubricJudge().score(
                question=question.question,
                answer=str(naive["answer"]),
                context=str(naive["context"]),
                rubric=question.rubric,
                citation_count=len(naive["citations"]),
            )
            results.append(
                QuestionResult(
                    item_id=item.item_id,
                    question_id=question.question_id,
                    mode="naive",
                    answer=str(naive["answer"]),
                    latency_seconds=naive_wall,
                    estimated_usd=float(naive["estimated_usd"]),
                    input_tokens=int(naive["input_tokens"]),
                    output_tokens=int(naive["output_tokens"]),
                    cache_hit=False,
                    quality={
                        "groundedness": naive_scores.groundedness,
                        "correctness": naive_scores.correctness,
                        "citation_accuracy": naive_scores.citation_accuracy,
                        "overall": naive_scores.overall,
                    },
                    citation_count=len(naive["citations"]),
                )
            )

            # --- Hierarchical cold ---
            cold = await _run_hierarchical_once(
                item=item,
                question=question,
                provider=provider,
                cache=cache,
                config=config,
                embedder=embedder,
            )
            results.append(cold)

            # --- Hierarchical warm (repeat query / same video index) ---
            if repeat_cached_queries:
                warm = await _run_hierarchical_once(
                    item=item,
                    question=question,
                    provider=provider,
                    cache=cache,
                    config=config,
                    embedder=embedder,
                )
                warm.mode = "hierarchical_cached"
                results.append(warm)

    summary = summarize_results(results)
    return EvalReport(
        dataset_version=dataset_version(),
        results=results,
        summary=summary,
    )


def summarize_results(results: list[QuestionResult]) -> dict[str, Any]:
    """Aggregate before/after metrics actually measured by the harness."""

    def _subset(mode: str) -> list[QuestionResult]:
        return [r for r in results if r.mode == mode]

    naive = _subset("naive")
    hier = _subset("hierarchical")
    cached = _subset("hierarchical_cached")

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    naive_cost = _avg([r.estimated_usd for r in naive])
    hier_cost = _avg([r.estimated_usd for r in hier])
    cost_reduction_pct = ((naive_cost - hier_cost) / naive_cost) * 100.0 if naive_cost > 0 else 0.0

    naive_lat = _avg([r.latency_seconds for r in naive])
    hier_lat = _avg([r.latency_seconds for r in hier])
    cached_lat = _avg([r.latency_seconds for r in cached])
    speedup_cached = (hier_lat / cached_lat) if cached_lat > 0 else 0.0

    cache_hits = sum(1 for r in cached if r.cache_hit)
    cache_hit_rate = (cache_hits / len(cached)) if cached else 0.0

    stage_totals: dict[str, list[float]] = {}
    for r in hier:
        for st in r.stage_timings:
            stage_totals.setdefault(st.stage, []).append(st.seconds)
    stage_avg = {k: _avg(v) for k, v in stage_totals.items()}

    return {
        "n_naive": len(naive),
        "n_hierarchical": len(hier),
        "n_hierarchical_cached": len(cached),
        "avg_cost_usd_naive": round(naive_cost, 8),
        "avg_cost_usd_hierarchical": round(hier_cost, 8),
        "cost_reduction_pct": round(cost_reduction_pct, 2),
        "avg_latency_s_naive": round(naive_lat, 6),
        "avg_latency_s_hierarchical": round(hier_lat, 6),
        "avg_latency_s_hierarchical_cached": round(cached_lat, 6),
        "cached_speedup_vs_cold_hierarchical": round(speedup_cached, 3),
        "cache_hit_rate_on_repeat": round(cache_hit_rate, 4),
        "avg_quality_overall_naive": round(_avg([r.quality.get("overall", 0.0) for r in naive]), 4),
        "avg_quality_overall_hierarchical": round(
            _avg([r.quality.get("overall", 0.0) for r in hier]), 4
        ),
        "avg_stage_seconds_hierarchical": {k: round(v, 6) for k, v in stage_avg.items()},
        "judge": "heuristic_rubric (approximation — not ground truth)",
    }


def report_to_dict(report: EvalReport) -> dict[str, Any]:
    return {
        "dataset_version": report.dataset_version,
        "summary": report.summary,
        "results": [
            {
                **{k: v for k, v in asdict(r).items() if k != "stage_timings"},
                "stage_timings": [asdict(s) for s in r.stage_timings],
            }
            for r in report.results
        ],
    }
