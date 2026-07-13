# Meridian benchmark report

- Generated (UTC): `2026-07-13T07:51:06.208537+00:00`
- Dataset version: `2026.07.13`
- Provider: `gemini`
- Scope: **12 videos**, **84 questions** (72 answerable, 12 unanswerable)
- Judge: heuristic_rubric (approximation — not ground truth)

## Resume headline

- Evaluated grounded Q&A on **84 questions across 12 videos** spanning code walkthrough, interview, lecture, news, panel, podcast, product demo, tutorial.
- Retrieval quality: **recall@3 89.8%**, MRR 0.824, nDCG@3 0.835.
- Citation grounding: precision 89.6%, recall 89.8% against gold timestamp spans.
- Refusal correctness: 97.2% answerable, 91.7% unanswerable.
- Cost: **37.2% lower** than the naive full-transcript run.
- Caching: **0.94x** faster on repeat queries (100% hit rate).
- Ask latency (cold): p50 1340.9 ms, p95 3779.5 ms, p99 4488.8 ms.

## Naive vs hierarchical (measured)

| Metric | Naive baseline | Hierarchical | Delta |
|---|---:|---:|---:|
| Avg estimated cost (USD) | 0.00003642 | 0.00002287 | **37.21% reduction** |
| Avg latency cold (s) | 1.855706 | 1.628540 | — |
| Avg latency cached repeat (s) | — | 1.740180 | **0.936x vs cold hierarchical** |
| Avg quality overall (0-1) | 0.8491 | 0.8769 | — |
| Cache hit rate on repeat | — | 100.00% | — |

## Retrieval quality (recall/MRR/nDCG @ k=3)

| Metric | Value |
|---|---:|
| Recall@3 | 0.8981 |
| MRR | 0.8241 |
| nDCG@3 | 0.8348 |
| Avg retrieval stage latency (ms) | 0.3828 |

## Citation grounding + refusal correctness

| Metric | Value |
|---|---:|
| Citation precision | 0.8958 |
| Citation recall | 0.8981 |
| Refusal accuracy (answerable) | 0.9722 |
| Refusal accuracy (unanswerable) | 0.9167 |
| Refusal accuracy (overall) | 0.9643 |

## Latency percentiles (hierarchical cold ask)

| Percentile | Milliseconds |
|---|---:|
| p50 | 1340.8646 |
| p95 | 3779.4720 |
| p99 | 4488.7992 |
| answer-stage p95 | 3778.8209 |

## Breakdown by video type

| Video type | N | Quality | Recall@k | Citation precision | Refusal acc |
|---|---:|---:|---:|---:|---:|
| code_walkthrough | 7 | 0.873 | 0.833 | 0.833 | 1.000 |
| interview | 14 | 0.857 | 0.889 | 0.917 | 0.929 |
| lecture | 14 | 0.863 | 0.917 | 0.917 | 1.000 |
| news | 7 | 0.843 | 0.833 | 0.833 | 0.857 |
| panel | 7 | 0.892 | 0.833 | 0.833 | 1.000 |
| podcast | 7 | 0.918 | 1.000 | 0.917 | 1.000 |
| product_demo | 14 | 0.862 | 0.833 | 0.833 | 0.929 |
| tutorial | 14 | 0.917 | 1.000 | 1.000 | 1.000 |

## Breakdown by question type

| Question type | N | Quality | Recall@k | Refusal acc |
|---|---:|---:|---:|---:|
| factual | 69 | 0.945 | 0.913 | 0.986 |
| multi_hop | 2 | 0.851 | 0.833 | 1.000 |
| negative | 12 | 0.512 | n/a | 0.917 |
| timestamp | 1 | 0.594 | 0.000 | 0.000 |

## Stage latency (hierarchical cold, avg seconds)

| Stage | Seconds |
|---|---:|
| `extract_media` | 0.000003 |
| `load_cached_tree` | 0.000110 |
| `transcribe` | 0.000035 |
| `semantic_chunk` | 0.000251 |
| `keyframe_select` | 0.000011 |
| `hierarchy_build` | 0.000067 |
| `store_cached_tree` | 0.000006 |
| `retrieve` | 0.000383 |
| `answer` | 1.627024 |

## Methodology

- Retrieval relevance is defined by **time-span overlap** between a retrieved chunk
  and the question's gold `relevant_timestamps` (robust to chunking changes).
- Citation precision/recall compare answer citation spans to the same gold spans.
- Refusal accuracy checks the system refuses unanswerable (negative) questions and
  answers answerable ones.

## Limitations

- Quality scores use a **heuristic rubric judge** (and optional LLM-as-judge).
  These are approximations, not human ground truth.
- The offline `deterministic` provider avoids live API spend in CI; run
  `--provider gemini` locally to measure real answer quality, latency, and refusal.
- Cost uses provider ``estimate_cost`` with approximate token counts — not invoices.
- Fixtures are synthetic timed transcripts checked into the repo for reproducibility.

## Reproduce

```bash
uv sync --extra dev
# Offline (CI-safe):
uv run python -m tests.benchmarks.run_eval
# Live model (costs money, needs ADC + GOOGLE_CLOUD_PROJECT):
uv run python -m tests.benchmarks.run_eval --provider gemini --limit 3 --no-cached
```
