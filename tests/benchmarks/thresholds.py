"""Regression thresholds for the eval harness (PR gate).

These are intentionally conservative floors on the **offline deterministic**
run so CI catches real regressions (e.g. a retrieval bug that silently drops
recall) without being flaky. Live-provider numbers are stronger but not gated
because they cost money and vary run to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Minimum acceptable values on the offline deterministic eval.
MIN_RETRIEVAL_RECALL_AT_K = 0.80
MIN_RETRIEVAL_MRR = 0.70
MIN_RETRIEVAL_NDCG_AT_K = 0.70
MIN_CITATION_PRECISION = 0.60
MIN_REFUSAL_ACCURACY_ANSWERABLE = 0.90
MIN_COST_REDUCTION_PCT = 5.0
# Hierarchical answers should be at least as good as the naive baseline.
MIN_QUALITY_UPLIFT_VS_NAIVE = 0.0
# Guard against pathological latency blowups on the cold ask path (ms).
MAX_ASK_LATENCY_MS_P95 = 250.0


@dataclass(frozen=True, slots=True)
class ThresholdFailure:
    metric: str
    value: float | None
    op: str
    bound: float

    def __str__(self) -> str:
        return f"{self.metric}={self.value} (require {self.op} {self.bound})"


def check_thresholds(summary: dict[str, Any]) -> list[ThresholdFailure]:
    """Return a list of failed thresholds (empty => all passed)."""
    failures: list[ThresholdFailure] = []

    def _at_least(metric: str, bound: float) -> None:
        value = summary.get(metric)
        if value is None or float(value) < bound:
            failures.append(ThresholdFailure(metric, value, ">=", bound))

    def _at_most(metric: str, bound: float) -> None:
        value = summary.get(metric)
        if value is None or float(value) > bound:
            failures.append(ThresholdFailure(metric, value, "<=", bound))

    _at_least("retrieval_recall_at_k", MIN_RETRIEVAL_RECALL_AT_K)
    _at_least("retrieval_mrr", MIN_RETRIEVAL_MRR)
    _at_least("retrieval_ndcg_at_k", MIN_RETRIEVAL_NDCG_AT_K)
    _at_least("citation_precision", MIN_CITATION_PRECISION)
    _at_least("refusal_accuracy_answerable", MIN_REFUSAL_ACCURACY_ANSWERABLE)
    _at_least("cost_reduction_pct", MIN_COST_REDUCTION_PCT)
    _at_most("ask_latency_ms_p95", MAX_ASK_LATENCY_MS_P95)

    uplift = summary.get("avg_quality_overall_hierarchical", 0.0) - summary.get(
        "avg_quality_overall_naive", 0.0
    )
    if uplift < MIN_QUALITY_UPLIFT_VS_NAIVE:
        failures.append(
            ThresholdFailure(
                "quality_uplift_vs_naive",
                round(uplift, 4),
                ">=",
                MIN_QUALITY_UPLIFT_VS_NAIVE,
            )
        )

    return failures
