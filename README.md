# TGManagementBot

Telegram management bot with built-in **bot-to-bot loop prevention** —
deduplication, multi-tier rate limiting, reply-chain depth limits,
conversation/pair timeouts, and a per-bot circuit breaker. Also ships
admin commands (`/ban` `/kick` `/mute` `/allow` `/block`), bot
member screening, and JSON audit logging.

Built on `python-telegram-bot 21.x` (asyncio) with Redis as the
distributed state store.

## Loop prevention

Implements every requirement from Telegram's
[bot-to-bot communication guidelines](https://core.telegram.org/bots/features#bot-to-bot-communication):

| Requirement | Where |
|---|---|
| Deduplicate identical incoming messages | [`loop_guard/dedup.py`](src/tgmgmt/loop_guard/dedup.py) |
| Rate-limit replies (per-sender / per-target / global) | [`loop_guard/rate_limiter.py`](src/tgmgmt/loop_guard/rate_limiter.py) |
| Bound reply-chain depth | [`loop_guard/depth_tracker.py`](src/tgmgmt/loop_guard/depth_tracker.py) |
| Conversation- and pair-level timeouts | [`loop_guard/timeout.py`](src/tgmgmt/loop_guard/timeout.py) |
| Survive a hostile peer flooding us | [`loop_guard/circuit_breaker.py`](src/tgmgmt/loop_guard/circuit_breaker.py) |

The guard is wired in as a high-priority `MessageHandler` (group=-100)
and as an explicit `gate_outbound` check before every send.

## Quick start (local)

```bash
cp .env.example .env          # then fill in TGMGMT_BOT_TOKEN
docker compose up --build
```

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Deployment

Three Azure paths under [`deploy/azure/`](deploy/azure):

- **VM + rsync** (no registry): [`deploy-rsync.sh`](deploy/azure/vm/deploy-rsync.sh)
- **VM + GHCR image**: [`deploy-image.sh`](deploy/azure/vm/deploy-image.sh)
- **Container Apps + managed Redis**: [`container-apps/`](deploy/azure/container-apps)

See [`deploy/azure/README.md`](deploy/azure/README.md) for the full
comparison.

## Configuration

All knobs are environment variables prefixed with `TGMGMT_`.
See [`.env.example`](.env.example) for the full list.

## License

MIT
