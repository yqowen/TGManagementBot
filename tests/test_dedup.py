from tgmgmt.loop_guard.dedup import Deduplicator


async def test_dedup_first_pass_then_blocks(redis, settings):
    d = Deduplicator(redis, settings)
    fp = d.fingerprint(chat_id=1, sender_id=2, text="hello", reply_to=None)
    assert await d.seen(fp) is False
    assert await d.seen(fp) is True


async def test_dedup_distinct_messages_pass(redis, settings):
    d = Deduplicator(redis, settings)
    fp1 = d.fingerprint(chat_id=1, sender_id=2, text="a", reply_to=None)
    fp2 = d.fingerprint(chat_id=1, sender_id=2, text="b", reply_to=None)
    assert await d.seen(fp1) is False
    assert await d.seen(fp2) is False
