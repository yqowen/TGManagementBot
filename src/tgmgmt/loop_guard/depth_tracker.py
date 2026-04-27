"""Reply-chain depth tracker.

Telegram messages can be linked via ``reply_to_message``. We track the
depth of any message we observe from a bot, plus the depth of any
message *we* send. When we are about to reply, we look up the parent's
depth — if it is already >= ``max_reply_depth`` we refuse, breaking the
loop unilaterally even when the peer ignores its own depth.

We also expose a coarser "conversation root" identifier so the
conversation-timeout component can group messages under a stable key.
"""
from __future__ import annotations

from dataclasses import dataclass

from tgmgmt.config import Settings
from tgmgmt.services.redis_client import AsyncRedisLike


@dataclass(slots=True)
class DepthInfo:
    depth: int
    root_message_id: int


class DepthTracker:
    def __init__(self, redis: AsyncRedisLike, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    def _key(self, chat_id: int, message_id: int) -> str:
        return self._settings.k("depth", chat_id, message_id)

    async def record(
        self,
        *,
        chat_id: int,
        message_id: int,
        reply_to_message_id: int | None,
    ) -> DepthInfo:
        """Compute and store depth for ``message_id``.

        Returns the depth info for the just-recorded message.
        """
        if reply_to_message_id is None:
            info = DepthInfo(depth=0, root_message_id=message_id)
        else:
            parent_raw = await self._redis.hget(
                self._key(chat_id, reply_to_message_id), "d"
            )
            parent_root = await self._redis.hget(
                self._key(chat_id, reply_to_message_id), "r"
            )
            if parent_raw is None:
                # Parent unseen: treat as depth 1 with reply_to as root
                info = DepthInfo(depth=1, root_message_id=reply_to_message_id)
            else:
                info = DepthInfo(
                    depth=int(parent_raw) + 1,
                    root_message_id=int(parent_root) if parent_root else reply_to_message_id,
                )

        key = self._key(chat_id, message_id)
        # Use HSET; expire after 2x the conversation timeout to bound memory.
        await self._redis.hset(key, mapping={"d": info.depth, "r": info.root_message_id})
        await self._redis.expire(key, self._settings.convo_timeout_seconds * 2)
        return info

    async def get(self, chat_id: int, message_id: int) -> DepthInfo | None:
        d = await self._redis.hget(self._key(chat_id, message_id), "d")
        if d is None:
            return None
        r = await self._redis.hget(self._key(chat_id, message_id), "r")
        return DepthInfo(depth=int(d), root_message_id=int(r) if r else message_id)

    def is_too_deep(self, info: DepthInfo) -> bool:
        return info.depth >= self._settings.max_reply_depth
