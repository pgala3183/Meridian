"""CLI entrypoint: run Meridian benchmarks and write docs/benchmarks reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from meridian.providers.base import MultimodalProvider
from tests.benchmarks.eval_dataset import pin_dataset_checksums
from tests.benchmarks.harness import EvalReport, report_to_dict, run_evaluation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = _REPO_ROOT / "docs" / "benchmarks"


def _build_provider(name: str) -> MultimodalProvider | None:
    """Return a live provider for ``--provider gemini`` or None for offline."""
    if name == "deterministic":
        return None
    if name == "gemini":
        import os

        from meridian.providers.factory import create_provider
        from meridian.providers.types import ProviderConfig, ProviderName

        project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if not project:
            raise SystemExit(
                "GOOGLE_CLOUD_PROJECT (or GCP_PROJECT) must be set for --provider gemini; "
                "also run 'gcloud auth application-default login' for ADC."
            )
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        model = os.getenv("MERIDIAN_GEMINI_MODEL", "gemini-2.5-flash")
        return create_provider(
            ProviderConfig(
                name=ProviderName.GEMINI,
                project=project,
                location=location,
                generation_model=model,
            )
        )
    raise SystemExit(f"Unknown provider: {name!r} (expected 'deterministic' or 'gemini')")


def _fmt(value: object, spec: str = "") -> str:
    """Format a possibly-None metric for markdown tables."""
    if value is None:
        return "n/a"
    if spec:
        return format(value, spec)
    return str(value)


def _write_markdown(report: EvalReport, path: Path) -> None:
    s = report.summary
    n_questions = int(s.get("n_hierarchical", 0))
    n_videos = int(s.get("n_videos", 0))
    k = int(s.get("retrieval_k", 0))
    video_types = sorted(
        {
            result.video_type.replace("_", " ")
            for result in report.results
            if result.mode == "hierarchical" and result.video_type
        }
    )
    video_type_text = ", ".join(video_types)
    has_cached_results = int(s.get("n_hierarchical_cached", 0)) > 0
    cache_headline = (
        f"- Caching: **{s['cached_speedup_vs_cold_hierarchical']:.2f}x** faster on repeat "
        f"queries ({s['cache_hit_rate_on_repeat']:.0%} hit rate)."
        if has_cached_results
        else "- Caching: not measured in this run (`--no-cached`)."
    )
    cached_latency = (
        f"{s['avg_latency_s_hierarchical_cached']:.6f}" if has_cached_results else "n/a"
    )
    cached_delta = (
        f"**{s['cached_speedup_vs_cold_hierarchical']:.3f}x vs cold hierarchical**"
        if has_cached_results
        else "not measured"
    )
    cache_hit_rate = f"{s['cache_hit_rate_on_repeat']:.2%}" if has_cached_results else "n/a"
    lines = [
        "# Meridian benchmark report",
        "",
        f"- Generated (UTC): `{datetime.now(UTC).isoformat()}`",
        f"- Dataset version: `{report.dataset_version}`",
        f"- Provider: `{s.get('provider', 'unknown')}`",
        f"- Scope: **{n_videos} videos**, **{n_questions} questions** "
        f"({s.get('n_answerable', 0)} answerable, {s.get('n_unanswerable', 0)} unanswerable)",
        f"- Judge: {s.get('judge')}",
        "",
        "## Resume headline",
        "",
        f"- Evaluated grounded Q&A on **{n_questions} questions across {n_videos} videos** "
        f"spanning {video_type_text}.",
        f"- Retrieval quality: **recall@{k} {_fmt(s.get('retrieval_recall_at_k'), '.1%')}**, "
        f"MRR {_fmt(s.get('retrieval_mrr'), '.3f')}, "
        f"nDCG@{k} {_fmt(s.get('retrieval_ndcg_at_k'), '.3f')}.",
        f"- Citation grounding: precision {_fmt(s.get('citation_precision'), '.1%')}, "
        f"recall {_fmt(s.get('citation_recall'), '.1%')} against gold timestamp spans.",
        f"- Refusal correctness: {_fmt(s.get('refusal_accuracy_answerable'), '.1%')} answerable, "
        f"{_fmt(s.get('refusal_accuracy_unanswerable'), '.1%')} unanswerable.",
        f"- Cost: **{s['cost_reduction_pct']:.1f}% lower** than the naive full-transcript run.",
        cache_headline,
        f"- Ask latency (cold): p50 {s['ask_latency_ms_p50']:.1f} ms, "
        f"p95 {s['ask_latency_ms_p95']:.1f} ms, p99 {s['ask_latency_ms_p99']:.1f} ms.",
        "",
        "## Naive vs hierarchical (measured)",
        "",
        "| Metric | Naive baseline | Hierarchical | Delta |",
        "|---|---:|---:|---:|",
        (
            f"| Avg estimated cost (USD) | {s['avg_cost_usd_naive']:.8f} | "
            f"{s['avg_cost_usd_hierarchical']:.8f} | "
            f"**{s['cost_reduction_pct']:.2f}% reduction** |"
        ),
        (
            f"| Avg latency cold (s) | {s['avg_latency_s_naive']:.6f} | "
            f"{s['avg_latency_s_hierarchical']:.6f} | — |"
        ),
        (f"| Avg latency cached repeat (s) | — | {cached_latency} | {cached_delta} |"),
        (
            f"| Avg quality overall (0-1) | {s['avg_quality_overall_naive']:.4f} | "
            f"{s['avg_quality_overall_hierarchical']:.4f} | — |"
        ),
        f"| Cache hit rate on repeat | — | {cache_hit_rate} | — |",
        "",
        f"## Retrieval quality (recall/MRR/nDCG @ k={k})",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Recall@{k} | {_fmt(s.get('retrieval_recall_at_k'), '.4f')} |",
        f"| MRR | {_fmt(s.get('retrieval_mrr'), '.4f')} |",
        f"| nDCG@{k} | {_fmt(s.get('retrieval_ndcg_at_k'), '.4f')} |",
        f"| Avg retrieval stage latency (ms) | {s.get('retrieval_stage_latency_ms_avg', 0):.4f} |",
        "",
        "## Citation grounding + refusal correctness",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Citation precision | {_fmt(s.get('citation_precision'), '.4f')} |",
        f"| Citation recall | {_fmt(s.get('citation_recall'), '.4f')} |",
        f"| Refusal accuracy (answerable) | {_fmt(s.get('refusal_accuracy_answerable'), '.4f')} |",
        "| Refusal accuracy (unanswerable) | "
        f"{_fmt(s.get('refusal_accuracy_unanswerable'), '.4f')} |",
        f"| Refusal accuracy (overall) | {_fmt(s.get('refusal_accuracy_overall'), '.4f')} |",
        "",
        "## Latency percentiles (hierarchical cold ask)",
        "",
        "| Percentile | Milliseconds |",
        "|---|---:|",
        f"| p50 | {s['ask_latency_ms_p50']:.4f} |",
        f"| p95 | {s['ask_latency_ms_p95']:.4f} |",
        f"| p99 | {s['ask_latency_ms_p99']:.4f} |",
        f"| answer-stage p95 | {s['answer_stage_latency_ms_p95']:.4f} |",
        "",
        "## Breakdown by video type",
        "",
        "| Video type | N | Quality | Recall@k | Citation precision | Refusal acc |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for vtype, row in s.get("by_video_type", {}).items():
        lines.append(
            f"| {vtype} | {row['n']} | {row['quality_overall']:.3f} | "
            f"{_fmt(row['recall_at_k'], '.3f')} | {_fmt(row['citation_precision'], '.3f')} | "
            f"{row['refusal_accuracy']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Breakdown by question type",
            "",
            "| Question type | N | Quality | Recall@k | Refusal acc |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for qtype, row in s.get("by_question_type", {}).items():
        lines.append(
            f"| {qtype} | {row['n']} | {row['quality_overall']:.3f} | "
            f"{_fmt(row['recall_at_k'], '.3f')} | {row['refusal_accuracy']:.3f} |"
        )
    lines.extend(["", "## Stage latency (hierarchical cold, avg seconds)", ""])
    stages = s.get("avg_stage_seconds_hierarchical", {})
    if stages:
        lines.append("| Stage | Seconds |")
        lines.append("|---|---:|")
        for name, sec in stages.items():
            lines.append(f"| `{name}` | {sec:.6f} |")
    else:
        lines.append("_No stage timings recorded._")
    lines.extend(
        [
            "",
            "## Methodology",
            "",
            "- Retrieval relevance is defined by **time-span overlap** between a retrieved chunk",
            "  and the question's gold `relevant_timestamps` (robust to chunking changes).",
            "- Citation precision/recall compare answer citation spans to the same gold spans.",
            "- Refusal accuracy checks the system refuses unanswerable (negative) questions and",
            "  answers answerable ones.",
            "",
            "## Limitations",
            "",
            "- Quality scores use a **heuristic rubric judge** (and optional LLM-as-judge).",
            "  These are approximations, not human ground truth.",
            "- The offline `deterministic` provider avoids live API spend in CI; run",
            "  `--provider gemini` locally to measure real answer quality, latency, and refusal.",
            "- Cost uses provider ``estimate_cost`` with approximate token counts — not invoices.",
            "- Fixtures are synthetic timed transcripts checked into the repo for reproducibility.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "uv sync --extra dev",
            "# Offline (CI-safe):",
            "uv run python -m tests.benchmarks.run_eval",
            "# Live model (costs money, needs ADC + GOOGLE_CLOUD_PROJECT):",
            "uv run python -m tests.benchmarks.run_eval --provider gemini --limit 3 --no-cached",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_chart(report: EvalReport, path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "matplotlib is required for charts; install with: uv sync --extra dev"
        ) from exc

    s = report.summary
    k = int(s.get("retrieval_k", 0))
    has_cached_results = int(s.get("n_hierarchical_cached", 0)) > 0
    fig, axes = plt.subplots(1, 4, figsize=(16, 3.8))

    axes[0].bar(
        ["naive", "hierarchical"],
        [s["avg_cost_usd_naive"], s["avg_cost_usd_hierarchical"]],
        color=["#8c8c8c", "#2a6f97"],
    )
    axes[0].set_title("Avg estimated cost (USD)")
    axes[0].set_ylabel("USD")

    latency_labels = ["naive", "hier cold"]
    latency_values = [s["avg_latency_s_naive"], s["avg_latency_s_hierarchical"]]
    latency_colors = ["#8c8c8c", "#2a6f97"]
    if has_cached_results:
        latency_labels.append("hier cached")
        latency_values.append(s["avg_latency_s_hierarchical_cached"])
        latency_colors.append("#61a5c2")
    axes[1].bar(latency_labels, latency_values, color=latency_colors)
    axes[1].set_title("Avg latency (s)")

    axes[2].bar(
        ["naive", "hierarchical"],
        [s["avg_quality_overall_naive"], s["avg_quality_overall_hierarchical"]],
        color=["#8c8c8c", "#2a6f97"],
    )
    axes[2].set_title("Avg quality overall (0-1)")
    axes[2].set_ylim(0, 1.05)

    def _v(key: str) -> float:
        val = s.get(key)
        return float(val) if val is not None else 0.0

    axes[3].bar(
        [f"recall@{k}", "MRR", f"nDCG@{k}", "cite prec"],
        [
            _v("retrieval_recall_at_k"),
            _v("retrieval_mrr"),
            _v("retrieval_ndcg_at_k"),
            _v("citation_precision"),
        ],
        color=["#2a6f97", "#468faf", "#61a5c2", "#89c2d9"],
    )
    axes[3].set_title("Retrieval + citation quality")
    axes[3].set_ylim(0, 1.05)

    title = (
        f"Meridian eval {report.dataset_version} ({s.get('provider', '?')}): "
        f"recall@{k} {_v('retrieval_recall_at_k'):.0%}, "
        f"{s['cost_reduction_pct']:.1f}% cost down"
    )
    if has_cached_results:
        title += f", {s['cached_speedup_vs_cold_hierarchical']:.2f}x cached speedup"
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Meridian cost/latency/quality eval")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_OUT_DIR,
        help="Directory for markdown/JSON/chart outputs",
    )
    parser.add_argument(
        "--pin-checksums",
        action="store_true",
        help="Rewrite dataset.json fixture checksums before running",
    )
    parser.add_argument(
        "--provider",
        choices=["deterministic", "gemini"],
        default="deterministic",
        help="Answer provider. 'deterministic' is offline; 'gemini' calls Vertex AI (costs money).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only evaluate the first N videos (useful for a smoke run or to cap live spend)",
    )
    parser.add_argument(
        "--no-cached",
        action="store_true",
        help="Skip the warm/cached repeat run (halves answer calls for live providers)",
    )
    parser.add_argument(
        "--check-thresholds",
        action="store_true",
        help="Exit non-zero if measured metrics fall below regression thresholds",
    )
    args = parser.parse_args(argv)

    # Load .env so GOOGLE_CLOUD_PROJECT / GEMINI settings are picked up here the
    # same way the API and worker do (both call load_dotenv at import time).
    if args.provider == "gemini":
        from dotenv import load_dotenv

        load_dotenv()

    if args.pin_checksums:
        pin_dataset_checksums()

    provider = _build_provider(args.provider)
    report = await run_evaluation(
        provider=provider,
        repeat_cached_queries=not args.no_cached,
        max_items=args.limit,
    )
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "latest_results.json"
    md_path = out / "latest_report.md"
    chart_path = out / "latest_chart.png"

    json_path.write_text(json.dumps(report_to_dict(report), indent=2) + "\n", encoding="utf-8")
    _write_markdown(report, md_path)
    _write_chart(report, chart_path)

    s = report.summary
    recall = s.get("retrieval_recall_at_k")
    recall_str = f"{recall:.1%}" if recall is not None else "n/a"
    print(
        f"Eval complete ({s.get('provider')}) — "
        f"recall@{s.get('retrieval_k')} {recall_str}, "
        f"cost reduction {s['cost_reduction_pct']:.2f}%, "
        f"cached speedup {s['cached_speedup_vs_cold_hierarchical']:.3f}x, "
        f"cache hit rate {s['cache_hit_rate_on_repeat']:.2%}"
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {chart_path}")

    if args.check_thresholds:
        from tests.benchmarks.thresholds import check_thresholds

        failures = check_thresholds(s)
        if failures:
            print("\nThreshold check FAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nThreshold check passed.")
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
