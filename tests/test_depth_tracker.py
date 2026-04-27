from tgmgmt.loop_guard.depth_tracker import DepthTracker


async def test_depth_increments_along_chain(redis, settings):
    d = DepthTracker(redis, settings)
    info0 = await d.record(chat_id=1, message_id=100, reply_to_message_id=None)
    assert info0.depth == 0
    assert info0.root_message_id == 100

    info1 = await d.record(chat_id=1, message_id=101, reply_to_message_id=100)
    assert info1.depth == 1
    assert info1.root_message_id == 100

    info2 = await d.record(chat_id=1, message_id=102, reply_to_message_id=101)
    assert info2.depth == 2
    assert info2.root_message_id == 100


async def test_too_deep(redis, settings):
    d = DepthTracker(redis, settings)
    # settings.max_reply_depth = 3 in fixture
    info = await d.record(chat_id=1, message_id=1, reply_to_message_id=None)
    parent_id = 1
    for mid in range(2, 6):
        info = await d.record(chat_id=1, message_id=mid, reply_to_message_id=parent_id)
        parent_id = mid
    assert d.is_too_deep(info) is True


async def test_unknown_parent_is_depth_one(redis, settings):
    d = DepthTracker(redis, settings)
    info = await d.record(chat_id=1, message_id=999, reply_to_message_id=42)
    assert info.depth == 1
    assert info.root_message_id == 42
