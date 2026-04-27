"""Admin commands: /ban /mute /kick /allow /block /status.

All commands require the issuer to be a chat administrator. Targets are
resolved either from a reply-to message or from the first command
argument (a user_id or @username).
"""
from __future__ import annotations

from datetime import timedelta

from telegram import ChatPermissions, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes

from tgmgmt.loop_guard import LoopGuard
from tgmgmt.services.audit import AuditLog


async def _is_admin(update: Update) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


def _resolve_target(update: Update) -> int | None:
    msg = update.effective_message
    if msg is None:
        return None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    if context_args := (msg.text or "").split()[1:]:
        token = context_args[0]
        if token.lstrip("-").isdigit():
            return int(token)
    return None


def install_admin(app: Application, guard: LoopGuard, audit: AuditLog) -> None:
    async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _is_admin(update):
            return
        target = _resolve_target(update)
        chat = update.effective_chat
        if target is None or chat is None:
            return
        await chat.ban_member(target)
        await guard.allowlist.block(chat.id, target)
        await audit.emit("admin.ban", chat_id=chat.id, target=target,
                         by=update.effective_user.id if update.effective_user else None)
        await update.effective_message.reply_text(f"Banned {target}.")

    async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _is_admin(update):
            return
        target = _resolve_target(update)
        chat = update.effective_chat
        if target is None or chat is None:
            return
        await chat.ban_member(target)
        await chat.unban_member(target)  # kick = ban + unban
        await audit.emit("admin.kick", chat_id=chat.id, target=target,
                         by=update.effective_user.id if update.effective_user else None)
        await update.effective_message.reply_text(f"Kicked {target}.")

    async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _is_admin(update):
            return
        target = _resolve_target(update)
        chat = update.effective_chat
        if target is None or chat is None:
            return
        until = update.effective_message.date + timedelta(hours=1)
        await chat.restrict_member(
            target,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await audit.emit("admin.mute", chat_id=chat.id, target=target,
                         by=update.effective_user.id if update.effective_user else None,
                         until=until.isoformat())
        await update.effective_message.reply_text(f"Muted {target} for 1h.")

    async def cmd_allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _is_admin(update):
            return
        target = _resolve_target(update)
        chat = update.effective_chat
        if target is None or chat is None:
            return
        await guard.allowlist.add_allowed(chat.id, target)
        await guard.allowlist.unblock(chat.id, target)
        await audit.emit("admin.allow", chat_id=chat.id, target=target)
        await update.effective_message.reply_text(f"Allowed {target}.")

    async def cmd_block(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _is_admin(update):
            return
        target = _resolve_target(update)
        chat = update.effective_chat
        if target is None or chat is None:
            return
        await guard.allowlist.block(chat.id, target)
        await audit.emit("admin.block", chat_id=chat.id, target=target)
        await update.effective_message.reply_text(f"Blocked {target}.")

    async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Loop guard active.")

    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("status", cmd_status))
