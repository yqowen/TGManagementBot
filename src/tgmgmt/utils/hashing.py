"""Hashing helpers for content-based deduplication."""
from __future__ import annotations

import hashlib


def content_fingerprint(*parts: object) -> str:
    """Deterministic short hash for variable-length parts.

    None-valued parts are normalised so that ``(1, None)`` and ``(1, "")``
    do not collide.
    """
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(b"\x00")
        if p is None:
            h.update(b"\x01N")
        else:
            h.update(b"\x02")
            h.update(str(p).encode("utf-8"))
    return h.hexdigest()
