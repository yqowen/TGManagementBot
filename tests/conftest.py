from __future__ import annotations

import os

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis

# Provide a token so Settings() validation passes
os.environ.setdefault("TGMGMT_BOT_TOKEN", "1234567890:TEST_TOKEN_FOR_UNIT_TESTS")

from tgmgmt.config import Settings  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="1234567890:TEST",
        redis_url="redis://localhost:6379/0",
        redis_key_prefix="tgmgmt-test",
        dedup_ttl_seconds=2,
        rl_per_sender_rps=2.0,
        rl_per_sender_burst=3,
        rl_outbound_rps=2.0,
        rl_outbound_burst=3,
        rl_global_rps=10.0,
        rl_global_burst=10,
        max_reply_depth=3,
        convo_timeout_seconds=10,
        pair_timeout_seconds=10,
        cb_threshold=5,
        cb_window_seconds=2,
        cb_cooldown_seconds=5,
    )


@pytest_asyncio.fixture
async def redis():
    r = fake_aioredis.FakeRedis(decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()
