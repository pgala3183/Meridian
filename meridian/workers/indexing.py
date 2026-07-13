"""Build and persist a searchable context tree from a transcript."""

from __future__ import annotations

import json
from typing import Any

from meridian.core.chunking import HashingEmbedder, semantic_chunk, sentences_from_transcript
from meridian.core.models import (
    ChunkingConfig,
    ContextTree,
    HierarchyNode,
    PipelineConfig,
    SemanticChunk,
)
from meridian.providers.types import Transcript
from meridian.storage.base import ObjectStore, artifact_key


def build_context_tree(video_id: str, transcript: Transcript) -> ContextTree:
    """Chunk + hierarchy index using the offline hashing embedder (stable for ask)."""
    config = PipelineConfig()
    embedder = HashingEmbedder()
    sentences = sentences_from_transcript(transcript)
    if not sentences:
        raise RuntimeError("Transcript produced no timed sentences to index")
    chunks = semantic_chunk(sentences, config.chunking, embedder=embedder)
    return _hierarchy_from_chunks(video_id, chunks, config)


def persist_index(
    object_store: ObjectStore,
    *,
    video_id: str,
    transcript: Transcript,
    tree: ContextTree,
) -> dict[str, str]:
    """Write transcript + context tree JSON; return artifact URI map."""
    transcript_key = artifact_key(video_id, "transcripts", "full.json")
    tree_key = artifact_key(video_id, "context", "tree.json")

    transcript_payload = {
        "video_id": video_id,
        "text": transcript.text,
        "model": transcript.model,
        "duration_seconds": transcript.duration_seconds,
        "segments": [
            {
                "text": s.text,
                "start_seconds": s.start_seconds,
                "end_seconds": s.end_seconds,
            }
            for s in transcript.segments
        ],
    }
    t_stored = object_store.put_bytes(
        transcript_key,
        json.dumps(transcript_payload).encode("utf-8"),
        content_type="application/json",
    )
    tree_stored = object_store.put_bytes(
        tree_key,
        tree.model_dump_json().encode("utf-8"),
        content_type="application/json",
    )
    return {
        "transcript": t_stored.uri or object_store.uri_for(transcript_key),
        "context_tree": tree_stored.uri or object_store.uri_for(tree_key),
        "transcript_key": transcript_key,
        "context_tree_key": tree_key,
    }


def load_context_tree(object_store: ObjectStore, video_id: str) -> ContextTree:
    """Load the persisted context tree for a video id."""
    key = artifact_key(video_id, "context", "tree.json")
    raw = object_store.get_bytes(key)
    return ContextTree.model_validate_json(raw)


def _hierarchy_from_chunks(
    video_id: str,
    chunks: tuple[SemanticChunk, ...],
    config: PipelineConfig,
) -> ContextTree:
    nodes: dict[str, HierarchyNode] = {}
    for chunk in chunks:
        node_id = f"leaf:{chunk.chunk_id}"
        nodes[node_id] = HierarchyNode(
            node_id=node_id,
            level=0,
            text=chunk.text,
            start_seconds=chunk.start_seconds,
            end_seconds=chunk.end_seconds,
            child_ids=(),
            chunk_id=chunk.chunk_id,
            embedding=chunk.embedding,
        )

    group = max(config.section_group_size, 1)
    section_ids: list[str] = []
    for i in range(0, len(chunks), group):
        group_chunks = chunks[i : i + group]
        section_id = f"section:{i // group:04d}"
        section_ids.append(section_id)
        child_ids = tuple(f"leaf:{c.chunk_id}" for c in group_chunks)
        text = " ".join(c.text for c in group_chunks)
        embedding = _mean_pool([c.embedding for c in group_chunks])
        nodes[section_id] = HierarchyNode(
            node_id=section_id,
            level=1,
            text=text,
            start_seconds=group_chunks[0].start_seconds,
            end_seconds=group_chunks[-1].end_seconds,
            child_ids=child_ids,
            embedding=embedding,
        )

    root_id = f"root:{video_id}"
    nodes[root_id] = HierarchyNode(
        node_id=root_id,
        level=2,
        text=" ".join(nodes[sid].text for sid in section_ids),
        start_seconds=chunks[0].start_seconds if chunks else 0.0,
        end_seconds=chunks[-1].end_seconds if chunks else 0.0,
        child_ids=tuple(section_ids),
        embedding=_mean_pool([nodes[sid].embedding for sid in section_ids]),
    )
    return ContextTree(
        video_id=video_id,
        root_id=root_id,
        nodes=nodes,
        chunks=chunks,
        keyframes=(),
    )


def _mean_pool(
    vectors: list[tuple[float, ...] | None],
) -> tuple[float, ...] | None:
    present = [v for v in vectors if v is not None]
    if not present:
        return None
    dims = len(present[0])
    acc = [0.0] * dims
    for vec in present:
        for i, value in enumerate(vec):
            acc[i] += value
    n = float(len(present))
    return tuple(v / n for v in acc)


def tree_stats(tree: ContextTree) -> dict[str, Any]:
    return {
        "video_id": tree.video_id,
        "chunk_count": len(tree.chunks),
        "node_count": len(tree.nodes),
        "chunking": ChunkingConfig().model_dump(),
    }
