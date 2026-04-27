"""Distributed token-bucket rate limiter.

A single Lua script performs the canonical "refill, then maybe consume"
sequence atomically. We keep two values per bucket: the current token
count and the last refill timestamp (ms).

Because the script is loaded once via SCRIPT LOAD and cached on the
Redis side, each ``acquire`` is a single round-trip.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike

# KEYS[1] = bucket hash key
# ARGV[1] = capacity (max tokens)
# ARGV[2] = refill rate (tokens / second, float)
# ARGV[3] = now_ms
# ARGV[4] = cost (tokens to take)
# ARGV[5] = ttl_seconds (idle expiry)
#
# Returns: {allowed (0/1), remaining_tokens (rounded down), retry_after_ms}
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    ts = now_ms
end

local elapsed_ms = math.max(0, now_ms - ts)
local refill = (elapsed_ms / 1000.0) * rate
tokens = math.min(capacity, tokens + refill)

local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    local missing = cost - tokens
    if rate > 0 then
        retry_after_ms = math.ceil((missing / rate) * 1000)
    else
        retry_after_ms = -1
    end
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('EXPIRE', key, ttl)
return {allowed, math.floor(tokens), retry_after_ms}
"""


@dataclass(slots=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


class TokenBucketLimiter:
    """Reusable bucket factory. One instance per process is enough."""

    def __init__(self, redis: AsyncRedisLike, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings
        self._sha: str | None = None

    async def _ensure_loaded(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(_TOKEN_BUCKET_LUA)
        return self._sha

    async def acquire(
        self,
        bucket: str,
        *,
        capacity: int,
        rate_per_sec: float,
        cost: int = 1,
        ttl_seconds: int | None = None,
    ) -> RateDecision:
        """Try to consume ``cost`` tokens from ``bucket``.

        ``bucket`` must already be namespaced; callers typically use
        :meth:`make_key`.
        """
        sha = await self._ensure_loaded()
        # Idle TTL: long enough to refill from empty plus a safety margin
        if ttl_seconds is None:
            refill_seconds = int(capacity / max(rate_per_sec, 0.01)) * 2
            ttl_seconds = max(60, refill_seconds)
        ttl = ttl_seconds
        now_ms = int(time.time() * 1000)
        try:
            res = await self._redis.evalsha(
                sha, 1, bucket, capacity, rate_per_sec, now_ms, cost, ttl
            )
        except Exception:
            # NOSCRIPT or fakeredis without script cache → fall back to EVAL
            res = await self._redis.eval(
                _TOKEN_BUCKET_LUA, 1, bucket, capacity, rate_per_sec, now_ms, cost, ttl
            )
            self._sha = None
        allowed, remaining, retry_after_ms = int(res[0]), int(res[1]), int(res[2])
        return RateDecision(bool(allowed), remaining, retry_after_ms)

    # --- Convenience wrappers for the three buckets we use ----------------

    async def check_inbound_sender(self, chat_id: int, sender_id: int) -> RateDecision:
        s = self._settings
        return await self.acquire(
            s.k("rl", "in", chat_id, sender_id),
            capacity=s.rl_per_sender_burst,
            rate_per_sec=s.rl_per_sender_rps,
        )

    async def check_outbound_target(self, chat_id: int, target_id: int | None) -> RateDecision:
        s = self._settings
        target = target_id if target_id is not None else 0
        return await self.acquire(
            s.k("rl", "out", chat_id, target),
            capacity=s.rl_outbound_burst,
            rate_per_sec=s.rl_outbound_rps,
        )

    async def check_outbound_global(self) -> RateDecision:
        s = self._settings
        rate = min(s.rl_global_rps, s.abs_max_outbound_rps)
        return await self.acquire(
            s.k("rl", "out", "global"),
            capacity=s.rl_global_burst,
            rate_per_sec=rate,
        )
