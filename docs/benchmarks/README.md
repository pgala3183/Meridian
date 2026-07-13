# Meridian benchmarks

Reproducible measurements for **cost**, **latency**, and **answer quality** —
the unfinished HALO roadmap item, implemented as a first-class harness.

## What we measure

| Signal | How |
|---|---|
| Answer quality | Heuristic rubric judge (CI default). Optional LLM-as-judge is an approximation, **not** ground truth. |
| Cost | Provider `estimate_cost()` on approximate token counts for naive vs hierarchical contexts. |
| Latency | End-to-end wall clock + per-stage timings for the hierarchical pipeline. |
| Cache | Repeat queries against the same video; report hit rate and speedup vs cold hierarchical. |

## Naive vs hierarchical

The **naive baseline** dumps the entire transcript into one long context (no
semantic chunking, no hierarchy, no cache). The **hierarchical** path is
Meridian's pipeline (chunk → tree → retrieve → cited answer) with multi-tier
cache. Headline deltas in `latest_report.md` are whatever the harness measures
on this machine/CI — we do not hand-write marketing numbers.

## Dataset

Versioned in `tests/benchmarks/dataset.json` with SHA-256 checksums over
checked-in synthetic transcripts covering:

- lecture
- interview
- product_demo

Synthetic fixtures keep eval offline, license-clean, and bit-stable. Replace
with public URLs + checksums when you add real media later.

## Reproduce locally

```bash
uv sync --extra dev
uv run python -m tests.benchmarks.run_eval --pin-checksums
```

Outputs land in this directory:

- `latest_results.json`
- `latest_report.md`
- `latest_chart.png`

## CI

`.github/workflows/benchmarks.yml` runs on a **schedule** (not every PR) so
numbers stay fresh without slowing reviews.

## Limitations

- Rubric/LLM judges approximate human judgment.
- Cost estimates ≠ billed invoices.
- Deterministic offline provider isolates pipeline economics from vendor variance;
  swap in a live provider for production-like latency studies.
- Wall-clock numbers vary by machine; compare modes within the same run.
