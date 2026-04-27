"""Global error handler — never let an exception kill the bot."""
from __future__ import annotations

import traceback

from telegram.ext import Application, ContextTypes

from tgmgmt.logging_setup import get_logger

_log = get_logger("errors")


def install_errors(app: Application) -> None:
    async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        _log.error(
            "handler_error",
            error=str(ctx.error),
            update=str(update)[:500],
            tb="".join(traceback.format_exception(ctx.error)) if ctx.error else "",
        )

    app.add_error_handler(on_error)
