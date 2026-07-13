# Meridian benchmark report

- Generated (UTC): `2026-07-13T08:38:34.045180+00:00`
- Dataset version: `2026.07.13`
- Provider: `eval-deterministic`
- Scope: **12 videos**, **84 questions** (72 answerable, 12 unanswerable)
- Judge: heuristic_rubric (approximation — not ground truth)

## Resume headline

- Evaluated grounded Q&A on **84 questions across 12 videos** spanning code walkthrough, interview, lecture, news, panel, podcast, product demo, tutorial.
- Retrieval quality: **recall@3 89.8%**, MRR 0.824, nDCG@3 0.835.
- Citation grounding: precision 72.2%, recall 72.2% against gold timestamp spans.
- Refusal correctness: 97.2% answerable, 25.0% unanswerable.
- Cost: **19.1% lower** than the naive full-transcript run.
- Caching: **1.24x** faster on repeat queries (100% hit rate).
- Ask latency (cold): p50 0.6 ms, p95 1.5 ms, p99 2.0 ms.

## Naive vs hierarchical (measured)

| Metric | Naive baseline | Hierarchical | Delta |
|---|---:|---:|---:|
| Avg estimated cost (USD) | 0.00003226 | 0.00002611 | **19.08% reduction** |
| Avg latency cold (s) | 0.000147 | 0.000711 | — |
| Avg latency cached repeat (s) | — | 0.000572 | **1.243x vs cold hierarchical** |
| Avg quality overall (0-1) | 0.5840 | 0.7365 | — |
| Cache hit rate on repeat | — | 100.00% | — |

## Retrieval quality (recall/MRR/nDCG @ k=3)

| Metric | Value |
|---|---:|
| Recall@3 | 0.8981 |
| MRR | 0.8241 |
| nDCG@3 | 0.8348 |
| Avg retrieval stage latency (ms) | 0.1206 |

## Citation grounding + refusal correctness

| Metric | Value |
|---|---:|
| Citation precision | 0.7222 |
| Citation recall | 0.7222 |
| Refusal accuracy (answerable) | 0.9722 |
| Refusal accuracy (unanswerable) | 0.2500 |
| Refusal accuracy (overall) | 0.8690 |

## Latency percentiles (hierarchical cold ask)

| Percentile | Milliseconds |
|---|---:|
| p50 | 0.5871 |
| p95 | 1.4816 |
| p99 | 2.0324 |
| answer-stage p95 | 0.2777 |

## Breakdown by video type

| Video type | N | Quality | Recall@k | Citation precision | Refusal acc |
|---|---:|---:|---:|---:|---:|
| code_walkthrough | 7 | 0.670 | 0.833 | 0.500 | 1.000 |
| interview | 14 | 0.695 | 0.889 | 0.750 | 0.857 |
| lecture | 14 | 0.723 | 0.917 | 0.750 | 0.857 |
| news | 7 | 0.675 | 0.833 | 0.833 | 0.857 |
| panel | 7 | 0.723 | 0.833 | 0.500 | 0.857 |
| podcast | 7 | 0.799 | 1.000 | 0.833 | 0.857 |
| product_demo | 14 | 0.753 | 0.833 | 0.667 | 0.857 |
| tutorial | 14 | 0.815 | 1.000 | 0.833 | 0.857 |

## Breakdown by question type

| Question type | N | Quality | Recall@k | Refusal acc |
|---|---:|---:|---:|---:|
| factual | 69 | 0.769 | 0.913 | 0.986 |
| multi_hop | 2 | 0.645 | 0.833 | 1.000 |
| negative | 12 | 0.586 | n/a | 0.250 |
| timestamp | 1 | 0.479 | 0.000 | 0.000 |

## Stage latency (hierarchical cold, avg seconds)

| Stage | Seconds |
|---|---:|
| `extract_media` | 0.000001 |
| `load_cached_tree` | 0.000032 |
| `transcribe` | 0.000013 |
| `semantic_chunk` | 0.000079 |
| `keyframe_select` | 0.000011 |
| `hierarchy_build` | 0.000026 |
| `store_cached_tree` | 0.000001 |
| `retrieve` | 0.000121 |
| `answer` | 0.000227 |

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
