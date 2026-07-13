"""Information-retrieval metrics for the eval harness.

Relevance is defined by *time-span overlap* between a retrieved chunk and the
question's gold supporting spans (``relevant_timestamps``). This is robust to
changes in chunking: a chunk counts as relevant if its ``[start, end]`` window
overlaps any gold span, regardless of how the transcript was segmented.

Metrics return ``None`` for unanswerable questions (no gold spans), so callers
can exclude them from retrieval aggregates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import log2

from meridian.core.models import RetrievalHit

GoldSpans = Sequence[tuple[float, float]]


def _overlaps(start: float, end: float, gold: GoldSpans) -> bool:
    """True if ``[start, end]`` overlaps any gold span (half-open intervals)."""
    return any(start < g_end and g_start < end for g_start, g_end in gold)


def relevance_at_ranks(hits: Sequence[RetrievalHit], gold: GoldSpans) -> list[bool]:
    """Binary relevance for each hit, in rank order."""
    return [_overlaps(h.chunk.start_seconds, h.chunk.end_seconds, gold) for h in hits]


def recall_at_k(hits: Sequence[RetrievalHit], gold: GoldSpans, k: int) -> float | None:
    """Fraction of gold spans that have an overlapping chunk in the top-k hits."""
    if not gold:
        return None
    topk = list(hits[:k])
    covered = sum(
        1
        for g_start, g_end in gold
        if any(h.chunk.start_seconds < g_end and g_start < h.chunk.end_seconds for h in topk)
    )
    return covered / len(gold)


def mrr(hits: Sequence[RetrievalHit], gold: GoldSpans) -> float | None:
    """Reciprocal rank of the first relevant hit (0 if none are relevant)."""
    if not gold:
        return None
    for rank, hit in enumerate(hits, start=1):
        if _overlaps(hit.chunk.start_seconds, hit.chunk.end_seconds, gold):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(hits: Sequence[RetrievalHit], gold: GoldSpans, k: int) -> float | None:
    """Binary-relevance nDCG over the top-k hits."""
    if not gold:
        return None
    rels = relevance_at_ranks(list(hits[:k]), gold)
    dcg = sum(1.0 / log2(idx + 1) for idx, rel in enumerate(rels, start=1) if rel)
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg > 0 else 0.0


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """Per-question retrieval quality (``None`` fields = not applicable)."""

    k: int
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None
    num_gold_spans: int
    num_relevant_retrieved: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "k": self.k,
            "recall_at_k": _round(self.recall_at_k),
            "mrr": _round(self.mrr),
            "ndcg_at_k": _round(self.ndcg_at_k),
            "num_gold_spans": self.num_gold_spans,
            "num_relevant_retrieved": self.num_relevant_retrieved,
        }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def score_retrieval(
    hits: Sequence[RetrievalHit],
    gold: GoldSpans,
    k: int,
) -> RetrievalMetrics:
    """Compute recall@k, MRR, and nDCG@k for one question."""
    rels = relevance_at_ranks(list(hits[:k]), gold) if gold else []
    return RetrievalMetrics(
        k=k,
        recall_at_k=recall_at_k(hits, gold, k),
        mrr=mrr(hits, gold),
        ndcg_at_k=ndcg_at_k(hits, gold, k),
        num_gold_spans=len(gold),
        num_relevant_retrieved=sum(1 for r in rels if r),
    )
