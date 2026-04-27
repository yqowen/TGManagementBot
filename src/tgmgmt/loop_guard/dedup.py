"""Inbound message deduplication.

Goal: drop messages that we have already processed *recently*, regardless
of whether they were duplicated by a buggy peer bot, by Telegram retries,
or by us crashing and reprocessing the same update.

Strategy: a SET-NX with TTL. Key is a content fingerprint scoped to chat
and sender. The TTL is short (seconds) — we are not building a full
"have I ever seen this" index, just collapsing rapid bursts.
"""
from __future__ import annotations

from dataclasses import dataclass

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike
from tgmgmt.utils.hashing import content_fingerprint


@dataclass(slots=True)
class Deduplicator:
    redis: AsyncRedisLike
    settings: Settings

    def fingerprint(
        self,
        *,
        chat_id: int,
        sender_id: int,
        text: str | None,
        reply_to: int | None,
        media_unique_id: str | None = None,
    ) -> str:
        return content_fingerprint(chat_id, sender_id, text, reply_to, media_unique_id)

    async def seen(self, fingerprint: str) -> bool:
        """Atomic ``SET key 1 NX EX ttl`` — returns True if duplicate."""
        key = self.settings.k("dedup", fingerprint)
        # ``set`` with ``nx=True`` returns None when the key already exists.
        ok = await self.redis.set(key, "1", nx=True, ex=self.settings.dedup_ttl_seconds)
        return ok is None
