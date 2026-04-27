import asyncio

from tgmgmt.loop_guard.rate_limiter import TokenBucketLimiter


async def test_burst_then_throttle(redis, settings):
    lim = TokenBucketLimiter(redis, settings)
    bucket = settings.k("test", "rl", "user", 1)
    # capacity=3, rate=2/s
    results = []
    for _ in range(3):
        results.append(await lim.acquire(bucket, capacity=3, rate_per_sec=2.0))
    assert all(r.allowed for r in results)

    # 4th immediately should fail
    denied = await lim.acquire(bucket, capacity=3, rate_per_sec=2.0)
    assert denied.allowed is False
    assert denied.retry_after_ms > 0


async def test_refills_over_time(redis, settings):
    lim = TokenBucketLimiter(redis, settings)
    bucket = settings.k("test", "rl", "refill")
    # Drain
    for _ in range(3):
        await lim.acquire(bucket, capacity=3, rate_per_sec=10.0)
    # Wait long enough to refill ~1 token (rate=10/s → 100ms / token)
    await asyncio.sleep(0.25)
    again = await lim.acquire(bucket, capacity=3, rate_per_sec=10.0)
    assert again.allowed is True
