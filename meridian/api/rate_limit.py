"""Redis token-bucket rate limiter for API spend protection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class RateLimitExceeded(Exception):
    """Raised when a caller exhausts their token bucket."""

    def __init__(self, key: str, retry_after_seconds: float) -> None:
        self.key = key
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded for {key}; retry after {retry_after_seconds:.2f}s")


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Token-bucket parameters."""

    capacity: float = 30.0
    refill_per_second: float = 0.5  # 30 requests / minute sustained
    key_prefix: str = "meridian:rl:"


class TokenBucketRateLimiter:
    """Distributed token bucket using Redis (or an in-memory fallback).

    Each API key / user id maps to a bucket. Real cloud spend makes this
    mandatory — a single runaway client must not burn Vertex / Whisper budget.
    """

    def __init__(
        self,
        config: RateLimitConfig | None = None,
        *,
        redis_client: Any | None = None,
    ) -> None:
        self.config = config or RateLimitConfig()
        self._redis = redis_client
        self._memory: dict[str, tuple[float, float]] = {}  # key -> (tokens, updated_at)

    def allow(self, identity: str, *, cost: float = 1.0) -> None:
        """Consume ``cost`` tokens or raise ``RateLimitExceeded``."""
        if cost <= 0:
            return
        bucket_key = f"{self.config.key_prefix}{identity}"
        if self._redis is not None:
            self._allow_redis(bucket_key, cost)
            return
        self._allow_memory(bucket_key, cost)

    def _allow_memory(self, key: str, cost: float) -> None:
        now = time.monotonic()
        tokens, updated = self._memory.get(key, (self.config.capacity, now))
        elapsed = max(0.0, now - updated)
        tokens = min(self.config.capacity, tokens + elapsed * self.config.refill_per_second)
        if tokens < cost:
            need = cost - tokens
            retry = need / self.config.refill_per_second if self.config.refill_per_second else 60.0
            raise RateLimitExceeded(key, retry)
        self._memory[key] = (tokens - cost, now)

    def _allow_redis(self, key: str, cost: float) -> None:
        # Lua keeps read-modify-write atomic across instances.
        script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill = tonumber(ARGV[2])
        local cost = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])
        local data = redis.call('HMGET', key, 'tokens', 'updated')
        local tokens = tonumber(data[1])
        local updated = tonumber(data[2])
        if tokens == nil then
          tokens = capacity
          updated = now
        end
        local elapsed = math.max(0, now - updated)
        tokens = math.min(capacity, tokens + elapsed * refill)
        if tokens < cost then
          local need = cost - tokens
          local retry = 60
          if refill > 0 then
            retry = need / refill
          end
          return {0, retry, tokens}
        end
        tokens = tokens - cost
        redis.call('HMSET', key, 'tokens', tokens, 'updated', now)
        redis.call('EXPIRE', key, 86400)
        return {1, 0, tokens}
        """
        assert self._redis is not None
        result = self._redis.eval(
            script,
            1,
            key,
            self.config.capacity,
            self.config.refill_per_second,
            cost,
            time.time(),
        )
        allowed = int(result[0]) == 1
        if not allowed:
            raise RateLimitExceeded(key, float(result[1]))
