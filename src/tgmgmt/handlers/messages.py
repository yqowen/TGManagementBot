"""Generic message handler — minimal demo + safe outbound helper.

Real product features should call ``safe_reply`` (or a similar wrapper)
so that every outbound message passes through :class:`LoopGuard.gate_outbound`.
"""
from __future__ import annotations

from telegram import Message, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from tgmgmt.logging_setup import get_logger
from tgmgmt.loop_guard import Decision, LoopGuard
from tgmgmt.services.audit import AuditLog

_log = get_logger("messages")


async def safe_reply(
    *,
    guard: LoopGuard,
    in_reply_to: Message,
    text: str,
) -> Message | None:
    """Reply to ``in_reply_to`` only if the loop guard permits it."""
    target_user = in_reply_to.from_user.id if in_reply_to.from_user else None
    decision: Decision = await guard.gate_outbound(
        chat_id=in_reply_to.chat.id,
        target_user_id=target_user,
        in_reply_to=in_reply_to,
    )
    if not decision.allowed:
        _log.info(
            "drop_outbound",
            verdict=decision.verdict.value,
            reason=decision.reason,
            chat_id=in_reply_to.chat.id,
            retry_after_ms=decision.retry_after_ms,
        )
        return None
    sent = await in_reply_to.reply_text(text)
    await guard.record_outbound(
        chat_id=sent.chat.id,
        sent_message_id=sent.message_id,
        in_reply_to_id=in_reply_to.message_id,
    )
    return sent


def install_messages(app: Application, guard: LoopGuard, audit: AuditLog) -> None:
    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None:
            return
        # Minimal default behaviour: log only. Real features go in their own
        # handlers and call ``safe_reply`` when they need to talk back.
        await audit.emit(
            "msg.observed",
            chat_id=msg.chat.id if msg.chat else None,
            sender_id=msg.from_user.id if msg.from_user else None,
            is_bot=bool(msg.from_user and msg.from_user.is_bot),
            message_id=msg.message_id,
            has_text=bool(msg.text),
        )

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))
