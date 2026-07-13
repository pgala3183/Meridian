# Meridian benchmark report

- Generated (UTC): `2026-07-13T03:08:10.140623+00:00`
- Dataset version: `2026.07.12`
- Judge: heuristic_rubric (approximation — not ground truth)

## Headline comparison (measured)

| Metric | Naive baseline | Hierarchical | Delta |
|---|---:|---:|---:|
| Avg estimated cost (USD) | 0.00003795 | 0.00002410 | **36.50% reduction** |
| Avg latency cold (s) | 0.000124 | 0.000982 | — |
| Avg latency cached repeat (s) | — | 0.000333 | **2.944x vs cold hierarchical** |
| Avg quality overall (0-1) | 0.5112 | 0.7434 | — |
| Cache hit rate on repeat | — | 100.00% | — |

## Stage latency (hierarchical cold, avg seconds)

| Stage | Seconds |
|---|---:|
| `extract_media` | 0.000001 |
| `load_cached_tree` | 0.000036 |
| `transcribe` | 0.000056 |
| `semantic_chunk` | 0.000423 |
| `keyframe_select` | 0.000012 |
| `hierarchy_build` | 0.000124 |
| `store_cached_tree` | 0.000004 |
| `retrieve` | 0.000123 |
| `answer` | 0.000192 |

## Limitations

- Quality scores use a **heuristic rubric judge** (and optional LLM-as-judge).
  These are approximations, not human ground truth.
- Cost uses provider ``estimate_cost`` with approximate token counts — not invoices.
- Fixtures are synthetic timed transcripts checked into the repo for reproducibility.
- Offline provider avoids live API spend in CI; enable a real provider locally to
  compare vendor latency separately.

## Reproduce

```bash
uv sync --extra dev
uv run python -m tests.benchmarks.run_eval
```
