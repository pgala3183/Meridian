"""CLI entrypoint: run Meridian benchmarks and write docs/benchmarks reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests.benchmarks.eval_dataset import pin_dataset_checksums
from tests.benchmarks.harness import EvalReport, report_to_dict, run_evaluation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = _REPO_ROOT / "docs" / "benchmarks"


def _write_markdown(report: EvalReport, path: Path) -> None:
    s = report.summary
    lines = [
        "# Meridian benchmark report",
        "",
        f"- Generated (UTC): `{datetime.now(UTC).isoformat()}`",
        f"- Dataset version: `{report.dataset_version}`",
        f"- Judge: {s.get('judge')}",
        "",
        "## Headline comparison (measured)",
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
        (
            f"| Avg latency cached repeat (s) | — | "
            f"{s['avg_latency_s_hierarchical_cached']:.6f} | "
            f"**{s['cached_speedup_vs_cold_hierarchical']:.3f}x vs cold hierarchical** |"
        ),
        (
            f"| Avg quality overall (0-1) | {s['avg_quality_overall_naive']:.4f} | "
            f"{s['avg_quality_overall_hierarchical']:.4f} | — |"
        ),
        f"| Cache hit rate on repeat | — | {s['cache_hit_rate_on_repeat']:.2%} | — |",
        "",
        "## Stage latency (hierarchical cold, avg seconds)",
        "",
    ]
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
            "## Limitations",
            "",
            "- Quality scores use a **heuristic rubric judge** (and optional LLM-as-judge).",
            "  These are approximations, not human ground truth.",
            "- Cost uses provider ``estimate_cost`` with approximate token counts — not invoices.",
            "- Fixtures are synthetic timed transcripts checked into the repo for reproducibility.",
            "- Offline provider avoids live API spend in CI; enable a real provider locally to",
            "  compare vendor latency separately.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "uv sync --extra dev",
            "uv run python -m tests.benchmarks.run_eval",
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
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))

    axes[0].bar(
        ["naive", "hierarchical"],
        [s["avg_cost_usd_naive"], s["avg_cost_usd_hierarchical"]],
        color=["#8c8c8c", "#2a6f97"],
    )
    axes[0].set_title("Avg estimated cost (USD)")
    axes[0].set_ylabel("USD")

    axes[1].bar(
        ["naive", "hier cold", "hier cached"],
        [
            s["avg_latency_s_naive"],
            s["avg_latency_s_hierarchical"],
            s["avg_latency_s_hierarchical_cached"],
        ],
        color=["#8c8c8c", "#2a6f97", "#61a5c2"],
    )
    axes[1].set_title("Avg latency (s)")

    axes[2].bar(
        ["naive", "hierarchical"],
        [s["avg_quality_overall_naive"], s["avg_quality_overall_hierarchical"]],
        color=["#8c8c8c", "#2a6f97"],
    )
    axes[2].set_title("Avg quality overall (0-1)")
    axes[2].set_ylim(0, 1.05)

    fig.suptitle(
        f"Meridian eval {report.dataset_version}: "
        f"{s['cost_reduction_pct']:.1f}% cost ↓, "
        f"{s['cached_speedup_vs_cold_hierarchical']:.2f}x cached speedup",
        fontsize=11,
    )
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
    args = parser.parse_args(argv)

    if args.pin_checksums:
        pin_dataset_checksums()

    report = await run_evaluation()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "latest_results.json"
    md_path = out / "latest_report.md"
    chart_path = out / "latest_chart.png"

    json_path.write_text(json.dumps(report_to_dict(report), indent=2) + "\n", encoding="utf-8")
    _write_markdown(report, md_path)
    _write_chart(report, chart_path)

    s = report.summary
    print(
        f"Eval complete — cost reduction {s['cost_reduction_pct']:.2f}%, "
        f"cached speedup {s['cached_speedup_vs_cold_hierarchical']:.3f}x, "
        f"cache hit rate {s['cache_hit_rate_on_repeat']:.2%}"
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {chart_path}")
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
