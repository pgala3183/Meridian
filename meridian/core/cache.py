"""Multi-tier cache: in-memory LRU, Redis (warm), persistent stub."""

from __future__ import annotations

import hashlib
import json
import pickle
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from meridian.core.models import ChunkingConfig, PipelineConfig

T = TypeVar("T")


def content_hash(
    *,
    video_fingerprint: str,
    chunking: ChunkingConfig,
    pipeline: PipelineConfig | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Stable SHA-256 key from video identity + processing parameters.

    Re-running the same video with the same config yields the same key so
    upstream stages never reprocess cached artifacts.
    """
    payload = {
        "video": video_fingerprint,
        "chunking": chunking.model_dump(),
        "pipeline": (pipeline or PipelineConfig()).model_dump(exclude={"cache_enabled"}),
        "extra": extra or {},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def fingerprint_bytes(data: bytes) -> str:
    """Content hash of raw bytes (e.g. video or audio)."""
    return hashlib.sha256(data).hexdigest()


class CacheBackend(ABC, Generic[T]):
    """Abstract cache tier."""

    @abstractmethod
    def get(self, key: str) -> T | None:
        """Return cached value or None on miss."""

    @abstractmethod
    def set(self, key: str, value: T) -> None:
        """Store value under key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove key if present."""

    @abstractmethod
    def clear(self) -> None:
        """Drop all entries in this tier."""


class MemoryLRUCache(CacheBackend[T]):
    """Thread-safe in-process LRU for hot artifacts."""

    def __init__(self, max_items: int = 128) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._max_items = max_items
        self._data: OrderedDict[str, T] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> T | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: T) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._max_items:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class RedisCache(CacheBackend[T]):
    """Shared warm tier backed by Redis (pickle payloads).

    Accepts an injected redis client for tests. When ``client`` is None the
    tier is a no-op miss path so local/dev runs work without Redis.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        prefix: str = "meridian:",
        ttl_seconds: int | None = 86_400,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._ttl = ttl_seconds

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> T | None:
        if self._client is None:
            return None
        raw = self._client.get(self._k(key))
        if raw is None:
            return None
        return cast(T, pickle.loads(raw))  # trusted Meridian cache payloads only

    def set(self, key: str, value: T) -> None:
        if self._client is None:
            return
        payload = pickle.dumps(value)
        full = self._k(key)
        if self._ttl is not None:
            self._client.setex(full, self._ttl, payload)
        else:
            self._client.set(full, payload)

    def delete(self, key: str) -> None:
        if self._client is None:
            return
        self._client.delete(self._k(key))

    def clear(self) -> None:
        # Intentionally not FLUSHDB — too dangerous for a shared Redis.
        return


class PersistentCache(CacheBackend[T]):
    """Durable local-disk tier (stand-in until GCS/Firestore in a later step)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keep filesystem-safe two-level prefix to avoid huge directories.
        safe = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._root / safe[:2] / f"{safe}.pkl"

    def get(self, key: str) -> T | None:
        path = self._path(key)
        if not path.exists():
            return None
        return cast(T, pickle.loads(path.read_bytes()))  # trusted Meridian cache payloads only

    def set(self, key: str, value: T) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(value))

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def clear(self) -> None:
        for path in self._root.rglob("*.pkl"):
            path.unlink(missing_ok=True)


class MultiTierCache(Generic[T]):
    """Read-through / write-through across memory → Redis → persistent."""

    def __init__(
        self,
        memory: MemoryLRUCache[T] | None = None,
        redis: RedisCache[T] | None = None,
        persistent: PersistentCache[T] | None = None,
    ) -> None:
        self.memory = memory or MemoryLRUCache[T]()
        self.redis = redis or RedisCache[T](client=None)
        self.persistent = persistent

    def get(self, key: str) -> T | None:
        value = self.memory.get(key)
        if value is not None:
            return value
        value = self.redis.get(key)
        if value is not None:
            self.memory.set(key, value)
            return value
        if self.persistent is not None:
            value = self.persistent.get(key)
            if value is not None:
                self.redis.set(key, value)
                self.memory.set(key, value)
                return value
        return None

    def set(self, key: str, value: T) -> None:
        self.memory.set(key, value)
        self.redis.set(key, value)
        if self.persistent is not None:
            self.persistent.set(key, value)

    def delete(self, key: str) -> None:
        self.memory.delete(key)
        self.redis.delete(key)
        if self.persistent is not None:
            self.persistent.delete(key)

    def clear(self) -> None:
        self.memory.clear()
        self.redis.clear()
        if self.persistent is not None:
            self.persistent.clear()


def get_cache(
    *,
    redis_client: Any | None = None,
    persistent_root: str | Path | None = None,
    memory_max_items: int = 128,
) -> MultiTierCache[Any]:
    """Construct the default multi-tier cache stack."""
    persistent: PersistentCache[Any] | None = None
    if persistent_root is not None:
        persistent = PersistentCache(persistent_root)
    return MultiTierCache(
        memory=MemoryLRUCache(max_items=memory_max_items),
        redis=RedisCache(client=redis_client),
        persistent=persistent,
    )
