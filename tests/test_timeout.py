import asyncio

from tgmgmt.loop_guard.timeout import TimeoutTracker


async def test_conversation_active_after_touch(redis, settings):
    t = TimeoutTracker(redis, settings)
    await t.touch_conversation(1, 100)
    assert await t.conversation_active(1, 100) is True


async def test_pair_can_be_ended(redis, settings):
    t = TimeoutTracker(redis, settings)
    await t.touch_pair(1, 7777)
    assert await t.pair_active(1, 7777) is True
    await t.end_pair(1, 7777)
    assert await t.pair_active(1, 7777) is False


async def test_short_ttl_expires(redis, settings):
    # Override TTL to 1 second for this test
    settings.convo_timeout_seconds = 1
    t = TimeoutTracker(redis, settings)
    await t.touch_conversation(1, 200)
    await asyncio.sleep(1.2)
    assert await t.conversation_active(1, 200) is False
