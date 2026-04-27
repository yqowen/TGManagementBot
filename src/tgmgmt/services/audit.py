"""Audit log writer.

Writes one JSON line per security-relevant event, both to the structured
logger and to a dedicated append-only file. The file is rotated by an
external mechanism (logrotate, k8s, etc.) — we keep the writer dumb.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import orjson

from tgmgmt.logging_setup import get_logger

_log = get_logger("audit")


class AuditLog:
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def emit(self, event: str, **fields: Any) -> None:
        record = {"event": event, **fields}
        # Structured stdout (picked up by container log collectors)
        _log.info(event, **fields)
        line = orjson.dumps(record) + b"\n"
        # Async-safe append; serialize with a lock since we share an FD
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: bytes) -> None:
        with self._path.open("ab") as fh:
            fh.write(line)
