"""Loop Guard middleware.

Two entry points:

* :meth:`LoopGuard.evaluate_inbound` — invoked from a high-priority
  ``MessageHandler`` (group=-100). Returns a :class:`Decision`; if it is
  not ``ALLOW`` the caller raises ``ApplicationHandlerStop`` and any
  follow-up handlers are skipped.
* :meth:`LoopGuard.gate_outbound` — called *just before* we send any
  message via ``bot.send_message`` / reply. It enforces our own outbound
  rate limit, the conversation timeout, and the maximum reply depth.

The guard is built around explicit decisions rather than exceptions so
the call sites stay readable and we can audit every drop.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from tgmgmt.config import Settings
from tgmgmt.logging_setup import get_logger
from tgmgmt.loop_guard.circuit_breaker import CircuitBreaker
from tgmgmt.loop_guard.dedup import Deduplicator
from tgmgmt.loop_guard.depth_tracker import DepthInfo, DepthTracker
from tgmgmt.loop_guard.rate_limiter import TokenBucketLimiter
from tgmgmt.loop_guard.timeout import TimeoutTracker
from tgmgmt.services.allowlist import AllowList
from tgmgmt.services.audit import AuditLog
from tgmgmt.services.redis_client import AsyncRedisLike

if TYPE_CHECKING:
    from telegram import Message

_log = get_logger("loop_guard")


class Verdict(StrEnum):
    ALLOW = "allow"
    DROP_DEDUP = "drop_dedup"
    DROP_BLOCKED = "drop_blocked"
    DROP_RATE_LIMIT = "drop_rate_limit"
    DROP_BREAKER_OPEN = "drop_breaker_open"
    DROP_DEPTH = "drop_depth"
    DROP_CONVO_CLOSED = "drop_convo_closed"
    DROP_CHAT_NOT_ALLOWED = "drop_chat_not_allowed"


@dataclass(slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    retry_after_ms: int = 0
    depth: DepthInfo | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


class LoopGuard:
    """Composite gate over all inbound and outbound traffic."""

    def __init__(
        self,
        *,
        redis: AsyncRedisLike,
        settings: Settings,
        audit: AuditLog,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.audit = audit
        self.dedup = Deduplicator(redis, settings)
        self.limiter = TokenBucketLimiter(redis, settings)
        self.depth = DepthTracker(redis, settings)
        self.timeouts = TimeoutTracker(redis, settings)
        self.breaker = CircuitBreaker(redis, settings)
        self.allowlist = AllowList(redis=redis, settings=settings)

    # ---------------------- Inbound ------------------------------------

    async def evaluate_inbound(self, message: Message) -> Decision:
        """Decide what to do with a freshly received message."""
        if message.from_user is None or message.chat is None:
            return Decision(Verdict.ALLOW)

        chat_id = message.chat.id
        sender = message.from_user
        sender_id = sender.id
        is_bot_sender = bool(sender.is_bot)

        # 0. Chat allow-list (operational guard, not loop-prevention proper)
        if self.settings.allowed_chat_ids and chat_id not in self.settings.allowed_chat_ids:
            return Decision(Verdict.DROP_CHAT_NOT_ALLOWED, "chat not in allowlist")

        # 1. Hard block-list
        if is_bot_sender and await self.allowlist.is_blocked(chat_id, sender_id):
            await self.audit.emit(
                "loop_guard.drop", reason="blocked", chat_id=chat_id, sender_id=sender_id
            )
            return Decision(Verdict.DROP_BLOCKED, "sender blocked")

        # 2. Circuit breaker — check before counting
        if is_bot_sender and await self.breaker.is_open(chat_id, sender_id):
            return Decision(Verdict.DROP_BREAKER_OPEN, "breaker open")

        # 3. Deduplication — by content
        text = message.text or message.caption
        media_uid = None
        for attr in ("photo", "video", "audio", "document", "sticker", "voice", "animation"):
            obj = getattr(message, attr, None)
            if obj:
                # Photos are a list; take the largest's unique id
                if isinstance(obj, (list, tuple)) and obj:
                    media_uid = getattr(obj[-1], "file_unique_id", None)
                else:
                    media_uid = getattr(obj, "file_unique_id", None)
                break
        # Skip dedup for trusted bots so legitimate templated posts pass.
        if sender_id not in self.settings.trusted_bot_ids:
            fp = self.dedup.fingerprint(
                chat_id=chat_id,
                sender_id=sender_id,
                text=text,
                reply_to=message.reply_to_message.message_id if message.reply_to_message else None,
                media_unique_id=media_uid,
            )
            if await self.dedup.seen(fp):
                return Decision(Verdict.DROP_DEDUP, "duplicate within window")

        # 4. Inbound per-sender rate limit (mostly relevant to bot peers)
        if is_bot_sender:
            rl = await self.limiter.check_inbound_sender(chat_id, sender_id)
            if not rl.allowed:
                # Feed the breaker too: a peer that hits the limiter is loud.
                br = await self.breaker.observe(chat_id, sender_id)
                if br.just_tripped:
                    await self.audit.emit(
                        "loop_guard.breaker_tripped",
                        chat_id=chat_id,
                        bot_id=sender_id,
                        count=br.count_in_window,
                    )
                return Decision(
                    Verdict.DROP_RATE_LIMIT,
                    "inbound rate limit",
                    retry_after_ms=rl.retry_after_ms,
                )
            br = await self.breaker.observe(chat_id, sender_id)
            if br.state.value == "open":
                if br.just_tripped:
                    await self.audit.emit(
                        "loop_guard.breaker_tripped",
                        chat_id=chat_id,
                        bot_id=sender_id,
                        count=br.count_in_window,
                    )
                return Decision(Verdict.DROP_BREAKER_OPEN, "breaker open")

        # 5. Depth tracking — record but do not drop here (drop on outbound).
        depth_info = await self.depth.record(
            chat_id=chat_id,
            message_id=message.message_id,
            reply_to_message_id=(
                message.reply_to_message.message_id if message.reply_to_message else None
            ),
        )
        await self.timeouts.touch_conversation(chat_id, depth_info.root_message_id)
        if is_bot_sender:
            await self.timeouts.touch_pair(chat_id, sender_id)

        return Decision(Verdict.ALLOW, depth=depth_info)

    # ---------------------- Outbound -----------------------------------

    async def gate_outbound(
        self,
        *,
        chat_id: int,
        target_user_id: int | None,
        in_reply_to: Message | None,
    ) -> Decision:
        """Check whether we may send a message right now."""
        # 1. Depth guard: refuse to extend an already-deep reply chain.
        if in_reply_to is not None:
            parent = await self.depth.get(chat_id, in_reply_to.message_id)
            if parent and self.depth.is_too_deep(parent):
                await self.audit.emit(
                    "loop_guard.outbound_drop",
                    reason="depth",
                    chat_id=chat_id,
                    parent_depth=parent.depth,
                )
                return Decision(Verdict.DROP_DEPTH, "max reply depth")

            # 2. Conversation must still be active.
            root_id = parent.root_message_id if parent else in_reply_to.message_id
            if not await self.timeouts.conversation_active(chat_id, root_id):
                return Decision(Verdict.DROP_CONVO_CLOSED, "conversation timed out")

        # 3. Per-target outbound rate limit.
        rl_t = await self.limiter.check_outbound_target(chat_id, target_user_id)
        if not rl_t.allowed:
            return Decision(
                Verdict.DROP_RATE_LIMIT,
                "outbound target rate limit",
                retry_after_ms=rl_t.retry_after_ms,
            )

        # 4. Global outbound rate limit (last line of self-defence).
        rl_g = await self.limiter.check_outbound_global()
        if not rl_g.allowed:
            return Decision(
                Verdict.DROP_RATE_LIMIT,
                "outbound global rate limit",
                retry_after_ms=rl_g.retry_after_ms,
            )

        return Decision(Verdict.ALLOW)

    async def record_outbound(
        self,
        *,
        chat_id: int,
        sent_message_id: int,
        in_reply_to_id: int | None,
    ) -> None:
        """Track our own messages so they participate in depth checks."""
        info = await self.depth.record(
            chat_id=chat_id,
            message_id=sent_message_id,
            reply_to_message_id=in_reply_to_id,
        )
        await self.timeouts.touch_conversation(chat_id, info.root_message_id)
