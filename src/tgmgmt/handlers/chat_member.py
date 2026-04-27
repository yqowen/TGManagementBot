"""New chat-member screening.

When a *bot* joins, we check the per-chat allow-list. Unknown bots are
auto-banned and an audit event is emitted; trusted bots are welcomed.
Human members are unaffected by this handler.
"""
from __future__ import annotations

from telegram import ChatMemberUpdated, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, ChatMemberHandler, ContextTypes

from tgmgmt.loop_guard import LoopGuard
from tgmgmt.services.audit import AuditLog


def install_chat_member(app: Application, guard: LoopGuard, audit: AuditLog) -> None:
    async def on_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cmu: ChatMemberUpdated | None = update.chat_member or update.my_chat_member
        if cmu is None:
            return
        new = cmu.new_chat_member
        user = new.user
        chat = cmu.chat
        if new.status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
            return
        if not user.is_bot:
            return

        if user.id in guard.settings.trusted_bot_ids or await guard.allowlist.is_allowed(
            chat.id, user.id
        ):
            await audit.emit("member.bot_admitted", chat_id=chat.id, bot_id=user.id)
            return

        # Unknown bot: auto-ban as a safety default.
        try:
            await chat.ban_member(user.id)
        except Exception as exc:  # pragma: no cover - depends on chat perms
            await audit.emit(
                "member.bot_ban_failed", chat_id=chat.id, bot_id=user.id, error=str(exc)
            )
            return
        await guard.allowlist.block(chat.id, user.id)
        await audit.emit("member.bot_auto_banned", chat_id=chat.id, bot_id=user.id)

    app.add_handler(
        ChatMemberHandler(on_member, ChatMemberHandler.ANY_CHAT_MEMBER)
    )
