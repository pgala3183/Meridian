"""Unit tests for multi-tier caching."""

from __future__ import annotations

from pathlib import Path

from meridian.core.cache import (
    MemoryLRUCache,
    MultiTierCache,
    PersistentCache,
    RedisCache,
    content_hash,
    get_cache,
)
from meridian.core.models import ChunkingConfig, ContextTree, HierarchyNode, PipelineConfig


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.store[key] = value

    def setex(self, key: str, _ttl: int, value: bytes) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _tiny_tree(video_id: str = "v1") -> ContextTree:
    node = HierarchyNode(
        node_id=f"root:{video_id}",
        level=2,
        text="hello",
        start_seconds=0.0,
        end_seconds=1.0,
        child_ids=(),
    )
    return ContextTree(
        video_id=video_id,
        root_id=node.node_id,
        nodes={node.node_id: node},
        chunks=(),
        content_hash="abc",
    )


def test_content_hash_stable_for_same_inputs() -> None:
    cfg = ChunkingConfig(similarity_threshold=0.5)
    a = content_hash(video_fingerprint="vid", chunking=cfg)
    b = content_hash(video_fingerprint="vid", chunking=cfg)
    c = content_hash(video_fingerprint="vid", chunking=ChunkingConfig(similarity_threshold=0.9))
    assert a == b
    assert a != c


def test_memory_lru_evicts_oldest() -> None:
    cache: MemoryLRUCache[str] = MemoryLRUCache(max_items=2)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")
    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("c") == "3"


def test_multi_tier_promotes_persistent_to_memory(tmp_path: Path) -> None:
    persistent: PersistentCache[ContextTree] = PersistentCache(tmp_path)
    cache: MultiTierCache[ContextTree] = MultiTierCache(
        memory=MemoryLRUCache(max_items=8),
        redis=RedisCache(client=None),
        persistent=persistent,
    )
    tree = _tiny_tree()
    cache.set("k1", tree)
    cache.memory.clear()
    loaded = cache.get("k1")
    assert loaded is not None
    assert loaded.video_id == "v1"
    # Promoted into memory
    assert cache.memory.get("k1") is not None


def test_redis_tier_roundtrip() -> None:
    fake = _FakeRedis()
    redis_tier: RedisCache[ContextTree] = RedisCache(client=fake, ttl_seconds=60)
    tree = _tiny_tree("redis-vid")
    redis_tier.set("rk", tree)
    assert "meridian:rk" in fake.store
    assert redis_tier.get("rk") is not None
    assert redis_tier.get("rk").video_id == "redis-vid"  # type: ignore[union-attr]


def test_get_cache_factory(tmp_path: Path) -> None:
    cache = get_cache(persistent_root=tmp_path, memory_max_items=4)
    cache.set("x", {"ok": True})
    assert cache.get("x") == {"ok": True}
    _ = PipelineConfig()  # ensure import used / config hash path stays wired
