# Meridian benchmark report

- Generated (UTC): `2026-07-13T07:22:10.409849+00:00`
- Dataset version: `2026.07.13`
- Provider: `gemini`
- Scope: **3 videos**, **21 questions** (18 answerable, 3 unanswerable)
- Judge: heuristic_rubric (approximation — not ground truth)

## Resume headline

- Evaluated grounded Q&A on **21 questions across 3 videos** spanning interview, lecture, and product demo content.
- Retrieval quality: **recall@3 87.0%**, MRR 0.806, nDCG@3 0.811.
- Citation grounding: precision 86.1%, recall 87.0% against gold timestamp spans.
- Refusal correctness: 94.4% answerable, 100.0% unanswerable.
- Cost: **44.4% lower** than the naive full-transcript run.
- Caching: not measured in this run (`--no-cached`).
- Ask latency (cold): p50 1373.3 ms, p95 2342.0 ms, p99 2529.9 ms.

## Naive vs hierarchical (measured)

| Metric | Naive baseline | Hierarchical | Delta |
|---|---:|---:|---:|
| Avg estimated cost (USD) | 0.00004385 | 0.00002438 | **44.40% reduction** |
| Avg latency cold (s) | 1.552642 | 1.475384 | — |
| Avg latency cached repeat (s) | — | n/a | not measured |
| Avg quality overall (0-1) | 0.8337 | 0.8418 | — |
| Cache hit rate on repeat | — | n/a | — |

## Retrieval quality (recall/MRR/nDCG @ k=3)

| Metric | Value |
|---|---:|
| Recall@3 | 0.8704 |
| MRR | 0.8056 |
| nDCG@3 | 0.8109 |
| Avg retrieval stage latency (ms) | 0.3906 |

## Citation grounding + refusal correctness

| Metric | Value |
|---|---:|
| Citation precision | 0.8611 |
| Citation recall | 0.8704 |
| Refusal accuracy (answerable) | 0.9444 |
| Refusal accuracy (unanswerable) | 1.0000 |
| Refusal accuracy (overall) | 0.9524 |

## Latency percentiles (hierarchical cold ask)

| Percentile | Milliseconds |
|---|---:|
| p50 | 1373.2734 |
| p95 | 2342.0042 |
| p99 | 2529.9227 |
| answer-stage p95 | 2337.9804 |

## Breakdown by video type

| Video type | N | Quality | Recall@k | Citation precision | Refusal acc |
|---|---:|---:|---:|---:|---:|
| interview | 7 | 0.851 | 0.944 | 1.000 | 1.000 |
| lecture | 7 | 0.878 | 1.000 | 1.000 | 1.000 |
| product_demo | 7 | 0.796 | 0.667 | 0.583 | 0.857 |

## Breakdown by question type

| Question type | N | Quality | Recall@k | Refusal acc |
|---|---:|---:|---:|---:|
| factual | 16 | 0.931 | 0.938 | 1.000 |
| multi_hop | 1 | 0.737 | 0.667 | 1.000 |
| negative | 3 | 0.484 | n/a | 1.000 |
| timestamp | 1 | 0.594 | 0.000 | 0.000 |

## Stage latency (hierarchical cold, avg seconds)

| Stage | Seconds |
|---|---:|
| `extract_media` | 0.000005 |
| `load_cached_tree` | 0.000122 |
| `transcribe` | 0.000039 |
| `semantic_chunk` | 0.000284 |
| `keyframe_select` | 0.000010 |
| `hierarchy_build` | 0.000061 |
| `store_cached_tree` | 0.000006 |
| `retrieve` | 0.000391 |
| `answer` | 1.473788 |

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
