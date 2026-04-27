"""Integration tests for LoopGuard that fake telegram.Message via SimpleNamespace."""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio

from tgmgmt.loop_guard import LoopGuard, Verdict
from tgmgmt.services.audit import AuditLog


def _fake_message(
    *,
    chat_id: int,
    message_id: int,
    sender_id: int,
    is_bot: bool,
    text: str | None = "hello",
    reply_to_id: int | None = None,
) -> SimpleNamespace:
    reply_to = None
    if reply_to_id is not None:
        reply_to = SimpleNamespace(message_id=reply_to_id)
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=sender_id, is_bot=is_bot),
        message_id=message_id,
        text=text,
        caption=None,
        reply_to_message=reply_to,
        photo=None,
        video=None,
        audio=None,
        document=None,
        sticker=None,
        voice=None,
        animation=None,
    )


@pytest_asyncio.fixture
async def guard(redis, settings, tmp_path):
    audit = AuditLog(str(tmp_path / "audit.log"))
    return LoopGuard(redis=redis, settings=settings, audit=audit)


async def test_inbound_dedup_blocks_repeat(guard):
    m = _fake_message(chat_id=10, message_id=1, sender_id=200, is_bot=True, text="dup")
    d1 = await guard.evaluate_inbound(m)
    assert d1.allowed is True

    m2 = _fake_message(chat_id=10, message_id=2, sender_id=200, is_bot=True, text="dup")
    d2 = await guard.evaluate_inbound(m2)
    assert d2.verdict is Verdict.DROP_DEDUP


async def test_inbound_blocked_bot_dropped(guard):
    await guard.allowlist.block(10, 500)
    m = _fake_message(chat_id=10, message_id=1, sender_id=500, is_bot=True)
    d = await guard.evaluate_inbound(m)
    assert d.verdict is Verdict.DROP_BLOCKED


async def test_inbound_rate_limit_eventually_trips(guard, settings):
    # rl_per_sender_burst=3 → 4th distinct message in burst is denied
    for i in range(settings.rl_per_sender_burst):
        m = _fake_message(chat_id=10, message_id=100 + i, sender_id=600, is_bot=True, text=f"t{i}")
        d = await guard.evaluate_inbound(m)
        assert d.allowed, f"iteration {i} unexpectedly denied: {d}"
    m = _fake_message(chat_id=10, message_id=999, sender_id=600, is_bot=True, text="trigger")
    d = await guard.evaluate_inbound(m)
    assert d.verdict is Verdict.DROP_RATE_LIMIT


async def test_outbound_blocked_when_too_deep(guard, settings):
    # Build a chain at the depth limit
    chat = 11
    parent_id = 1
    await guard.depth.record(chat_id=chat, message_id=parent_id, reply_to_message_id=None)
    for mid in range(2, settings.max_reply_depth + 2):
        await guard.depth.record(chat_id=chat, message_id=mid, reply_to_message_id=parent_id)
        parent_id = mid
    # The deepest message is now >= max depth; refusing to extend it
    last = _fake_message(chat_id=chat, message_id=parent_id, sender_id=42, is_bot=True)
    decision = await guard.gate_outbound(chat_id=chat, target_user_id=42, in_reply_to=last)
    assert decision.verdict is Verdict.DROP_DEPTH


async def test_outbound_allowed_for_top_level(guard):
    decision = await guard.gate_outbound(chat_id=12, target_user_id=None, in_reply_to=None)
    assert decision.allowed is True
