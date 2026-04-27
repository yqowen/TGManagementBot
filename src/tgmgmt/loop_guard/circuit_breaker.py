"""Per-(chat, bot) circuit breaker over a sliding time window.

If a bot exceeds ``cb_threshold`` messages within ``cb_window_seconds``
in the same chat, we *trip* the breaker for ``cb_cooldown_seconds``.
While tripped, the loop guard drops all updates from that bot in that
chat and emits an audit event so an operator can intervene.

Implementation: a Redis sorted-set with ts-as-score; we add the current
timestamp, prune entries older than the window, and check the size. A
separate string key marks the cooldown state.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike


class BreakerState(StrEnum):
    CLOSED = "closed"   # normal
    OPEN = "open"       # tripped, drop traffic


@dataclass(slots=True)
class BreakerResult:
    state: BreakerState
    count_in_window: int
    just_tripped: bool


class CircuitBreaker:
    def __init__(self, redis: AsyncRedisLike, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    def _window_key(self, chat_id: int, bot_id: int) -> str:
        return self._settings.k("cb", "win", chat_id, bot_id)

    def _open_key(self, chat_id: int, bot_id: int) -> str:
        return self._settings.k("cb", "open", chat_id, bot_id)

    async def is_open(self, chat_id: int, bot_id: int) -> bool:
        return bool(await self._redis.get(self._open_key(chat_id, bot_id)))

    async def trip(self, chat_id: int, bot_id: int) -> None:
        await self._redis.set(
            self._open_key(chat_id, bot_id),
            "1",
            ex=self._settings.cb_cooldown_seconds,
        )

    async def observe(self, chat_id: int, bot_id: int) -> BreakerResult:
        """Record an event and return the resulting breaker state."""
        s = self._settings
        if await self.is_open(chat_id, bot_id):
            return BreakerResult(BreakerState.OPEN, count_in_window=-1, just_tripped=False)

        now_ms = int(time.time() * 1000)
        win_ms = s.cb_window_seconds * 1000
        wkey = self._window_key(chat_id, bot_id)

        # Use a unique member so identical timestamps don't collapse.
        member = f"{now_ms}:{uuid.uuid4().hex}"
        await self._redis.zadd(wkey, {member: now_ms})
        await self._redis.zremrangebyscore(wkey, 0, now_ms - win_ms)
        await self._redis.expire(wkey, s.cb_window_seconds + 1)
        count = int(await self._redis.zcard(wkey))

        if count > s.cb_threshold:
            await self.trip(chat_id, bot_id)
            return BreakerResult(BreakerState.OPEN, count, just_tripped=True)
        return BreakerResult(BreakerState.CLOSED, count, just_tripped=False)
