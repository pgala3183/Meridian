"""Question-aware retrieval over the hierarchical context tree."""

from __future__ import annotations

from collections.abc import Sequence

from meridian.core.chunking import SentenceEmbedder, cosine_similarity
from meridian.core.models import ContextTree, RetrievalHit, SemanticChunk


def retrieve(
    tree: ContextTree,
    question: str,
    *,
    embedder: SentenceEmbedder,
    top_k: int = 4,
) -> tuple[RetrievalHit, ...]:
    """Rank leaf chunks by cosine similarity to the question embedding.

    Hierarchy is used as a coarse filter: if section (level-1) nodes carry
    embeddings, we boost leaf scores by their parent section's similarity so
    retrieval is question-aware at multiple granularities without a full
    tree walk for every leaf.
    """
    if not tree.chunks:
        return ()

    q_vec = embedder.embed([question])[0]
    parent_boost = _section_boosts(tree, q_vec)

    hits: list[RetrievalHit] = []
    for chunk in tree.chunks:
        if chunk.embedding is None:
            continue
        base = cosine_similarity(q_vec, chunk.embedding)
        boost = parent_boost.get(chunk.chunk_id, 0.0)
        score = base + 0.15 * boost
        node_id = f"leaf:{chunk.chunk_id}"
        hits.append(RetrievalHit(chunk=chunk, score=score, node_id=node_id))

    hits.sort(key=lambda h: h.score, reverse=True)
    return tuple(hits[: max(top_k, 0)])


def _section_boosts(
    tree: ContextTree,
    question_vec: Sequence[float],
) -> dict[str, float]:
    """Map chunk_id → parent section similarity (0 if unknown)."""
    boosts: dict[str, float] = {}
    for node in tree.nodes.values():
        if node.level != 1 or node.embedding is None:
            continue
        section_score = cosine_similarity(question_vec, node.embedding)
        for child_id in node.child_ids:
            child = tree.nodes.get(child_id)
            if child is None or child.chunk_id is None:
                continue
            prev = boosts.get(child.chunk_id, 0.0)
            if section_score > prev:
                boosts[child.chunk_id] = section_score
    return boosts


def build_grounding_context(hits: Sequence[RetrievalHit]) -> str:
    """Format retrieved chunks into a citation-friendly context block."""
    blocks: list[str] = []
    for hit in hits:
        chunk: SemanticChunk = hit.chunk
        blocks.append(
            f"[{chunk.chunk_id} | {chunk.start_seconds:.2f}s-{chunk.end_seconds:.2f}s] {chunk.text}"
        )
    return "\n\n".join(blocks)
