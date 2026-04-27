"""Conversation- and pair-level timeouts.

Two independent stop-gaps:

1. **Conversation timeout** (``conversation_active``): per ``(chat,
   root_message_id)`` we refresh a TTL on every observed message; once
   the key expires, the conversation is considered closed and we will
   not chime in even if the peer keeps replying.
2. **Pair timeout** (``pair_active``): per ``(chat, sender_bot)`` —
   limits how long we will continue to engage with a particular peer
   bot in a given chat without human input.

Both are intentionally simple TTL keys; the truth lives in Redis so
multiple bot replicas agree.
"""
from __future__ import annotations

from dataclasses import dataclass

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike


@dataclass(slots=True)
class TimeoutTracker:
    redis: AsyncRedisLike
    settings: Settings

    def _convo_key(self, chat_id: int, root_id: int) -> str:
        return self.settings.k("convo", chat_id, root_id)

    def _pair_key(self, chat_id: int, bot_id: int) -> str:
        return self.settings.k("pair", chat_id, bot_id)

    async def touch_conversation(self, chat_id: int, root_id: int) -> None:
        await self.redis.set(
            self._convo_key(chat_id, root_id),
            "1",
            ex=self.settings.convo_timeout_seconds,
        )

    async def conversation_active(self, chat_id: int, root_id: int) -> bool:
        return bool(await self.redis.get(self._convo_key(chat_id, root_id)))

    async def touch_pair(self, chat_id: int, bot_id: int) -> None:
        await self.redis.set(
            self._pair_key(chat_id, bot_id),
            "1",
            ex=self.settings.pair_timeout_seconds,
        )

    async def pair_active(self, chat_id: int, bot_id: int) -> bool:
        return bool(await self.redis.get(self._pair_key(chat_id, bot_id)))

    async def end_pair(self, chat_id: int, bot_id: int) -> None:
        await self.redis.delete(self._pair_key(chat_id, bot_id))
