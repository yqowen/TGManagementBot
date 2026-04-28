"""Application configuration loaded from environment variables.

All knobs that affect Loop Prevention live here so they can be tuned
without code changes. Values are validated on startup.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field, NonNegativeFloat, PositiveFloat, PositiveInt, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TGMGMT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram --------------------------------------------------------
    bot_token: str = Field(..., min_length=10)

    # --- Redis -----------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "tgmgmt"

    # --- Loop prevention -------------------------------------------------
    dedup_ttl_seconds: PositiveInt = 5

    rl_per_sender_rps: PositiveFloat = 1.0
    rl_per_sender_burst: PositiveInt = 3

    rl_outbound_rps: PositiveFloat = 1.0
    rl_outbound_burst: PositiveInt = 3

    rl_global_rps: PositiveFloat = 20.0
    rl_global_burst: PositiveInt = 40

    max_reply_depth: PositiveInt = 5
    convo_timeout_seconds: PositiveInt = 60
    pair_timeout_seconds: PositiveInt = 30

    cb_threshold: PositiveInt = 15
    cb_window_seconds: PositiveInt = 10
    cb_cooldown_seconds: PositiveInt = 120

    # --- Misc ------------------------------------------------------------
    log_level: str = "INFO"
    audit_log_file: str = "/var/log/tgmgmt/audit.log"

    trusted_bot_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # Hard ceiling we never let go above to protect ourselves regardless of config
    abs_max_outbound_rps: NonNegativeFloat = 30.0

    @field_validator("trusted_bot_ids", "allowed_chat_ids", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    def k(self, *parts: str | int) -> str:
        """Build a namespaced Redis key."""
        return ":".join((self.redis_key_prefix, *(str(p) for p in parts)))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
