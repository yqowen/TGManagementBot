"""Per-chat allow / deny lists for bot identities.

We distinguish three layers:

* **trusted_bot_ids** (static, from env): platform-wide whitelist; bots in
  this set bypass dedup-by-content (they may legitimately post identical
  templated messages) but **never** bypass rate limits or the circuit
  breaker. Trust is not a license to flood.
* **allowlist (Redis set, per chat)**: explicitly permitted bots in a
  given chat.
* **blocklist (Redis set, per chat)**: bots whose updates we drop and who
  should be kicked on next encounter.

All lookups are O(1) Redis SISMEMBER calls.
"""
from __future__ import annotations

from dataclasses import dataclass

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike


@dataclass(slots=True)
class AllowList:
    redis: AsyncRedisLike
    settings: Settings

    def _allow_key(self, chat_id: int) -> str:
        return self.settings.k("allow", chat_id)

    def _block_key(self, chat_id: int) -> str:
        return self.settings.k("block", chat_id)

    async def add_allowed(self, chat_id: int, bot_id: int) -> None:
        await self.redis.sadd(self._allow_key(chat_id), bot_id)

    async def remove_allowed(self, chat_id: int, bot_id: int) -> None:
        await self.redis.srem(self._allow_key(chat_id), bot_id)

    async def is_allowed(self, chat_id: int, bot_id: int) -> bool:
        if bot_id in self.settings.trusted_bot_ids:
            return True
        return bool(await self.redis.sismember(self._allow_key(chat_id), bot_id))

    async def block(self, chat_id: int, bot_id: int) -> None:
        await self.redis.sadd(self._block_key(chat_id), bot_id)

    async def unblock(self, chat_id: int, bot_id: int) -> None:
        await self.redis.srem(self._block_key(chat_id), bot_id)

    async def is_blocked(self, chat_id: int, bot_id: int) -> bool:
        return bool(await self.redis.sismember(self._block_key(chat_id), bot_id))
