"""Application factory and lifecycle wiring."""
from __future__ import annotations

import contextlib

from telegram.ext import AIORateLimiter, Application, ApplicationBuilder

from tgmgmt.config import Settings, get_settings
from tgmgmt.handlers.admin import install_admin
from tgmgmt.handlers.chat_member import install_chat_member
from tgmgmt.handlers.errors import install_errors
from tgmgmt.handlers.guard import install_guard
from tgmgmt.handlers.messages import install_messages
from tgmgmt.logging_setup import configure_logging, get_logger
from tgmgmt.loop_guard import LoopGuard
from tgmgmt.services.audit import AuditLog
from tgmgmt.services.redis_client import create_redis

_log = get_logger("app")


async def _post_init(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    redis = create_redis(settings.redis_url)
    audit = AuditLog(settings.audit_log_file)
    guard = LoopGuard(redis=redis, settings=settings, audit=audit)

    app.bot_data["redis"] = redis
    app.bot_data["audit"] = audit
    app.bot_data["guard"] = guard

    install_errors(app)
    install_guard(app, guard)
    install_admin(app, guard, audit)
    install_chat_member(app, guard, audit)
    install_messages(app, guard, audit)

    _log.info("app.ready", trusted_bots=settings.trusted_bot_ids,
              allowed_chats=settings.allowed_chat_ids)


async def _post_shutdown(app: Application) -> None:
    redis = app.bot_data.get("redis")
    if redis is not None:
        with contextlib.suppress(Exception):
            await redis.aclose()


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    builder = (
        ApplicationBuilder()
        .token(settings.bot_token)
        # PTB built-in client-side rate limiter — Telegram-API friendliness.
        # Our LoopGuard limiter is a separate, semantic-aware layer on top.
        .rate_limiter(AIORateLimiter(overall_max_rate=30, max_retries=3))
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .concurrent_updates(True)
    )
    app = builder.build()
    app.bot_data["settings"] = settings
    return app
