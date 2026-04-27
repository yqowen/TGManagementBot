from tgmgmt.loop_guard.circuit_breaker import BreakerState, CircuitBreaker


async def test_breaker_trips_after_threshold(redis, settings):
    # threshold=5 in fixture
    cb = CircuitBreaker(redis, settings)
    last = None
    for _ in range(settings.cb_threshold + 1):
        last = await cb.observe(chat_id=1, bot_id=42)
    assert last is not None
    assert last.state is BreakerState.OPEN
    assert last.just_tripped is True
    assert await cb.is_open(1, 42) is True


async def test_breaker_starts_closed(redis, settings):
    cb = CircuitBreaker(redis, settings)
    res = await cb.observe(chat_id=2, bot_id=99)
    assert res.state is BreakerState.CLOSED
    assert res.just_tripped is False
    assert await cb.is_open(2, 99) is False
