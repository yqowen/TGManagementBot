"""High-priority Loop Guard handler.

Registered with ``group=-100`` so it runs before any feature handler.
If the guard returns a non-allow decision we raise
``ApplicationHandlerStop`` to halt propagation entirely.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes, MessageHandler, filters

from tgmgmt.logging_setup import get_logger
from tgmgmt.loop_guard import LoopGuard

_log = get_logger("guard_handler")
GUARD_GROUP = -100


def install_guard(app: Application, guard: LoopGuard) -> None:
    async def _gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None:
            return
        decision = await guard.evaluate_inbound(msg)
        if not decision.allowed:
            _log.info(
                "drop_inbound",
                verdict=decision.verdict.value,
                reason=decision.reason,
                chat_id=msg.chat.id if msg.chat else None,
                sender_id=msg.from_user.id if msg.from_user else None,
                message_id=msg.message_id,
            )
            raise ApplicationHandlerStop
        # Stash the depth info for downstream handlers / outbound checks
        if decision.depth is not None:
            context.chat_data["last_depth"] = decision.depth  # type: ignore[index]

    app.add_handler(MessageHandler(filters.ALL, _gate), group=GUARD_GROUP)
