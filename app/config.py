"""Settings, loaded from the environment and ``.env``.

Secrets never appear here as literals — only as names to be read from the
environment. ``.env`` is git-ignored; ``.env.example`` carries placeholders.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # Two stages, one model, different effort. The split runs the opposite way
    # to intuition: extraction is the subtler reasoning (resolving "do patku"
    # against a timestamp, spotting that a later message supersedes an earlier
    # one), while prioritisation ranks an already-clean table.
    extract_model: str = Field(default="claude-sonnet-5", alias="EXTRACT_MODEL")
    extract_effort: Effort = Field(default="medium", alias="EXTRACT_EFFORT")
    prioritize_model: str = Field(default="claude-sonnet-5", alias="PRIORITIZE_MODEL")
    prioritize_effort: Effort = Field(default="high", alias="PRIORITIZE_EFFORT")
    max_concurrent_extractions: int = Field(default=4, alias="MAX_CONCURRENT_EXTRACTIONS")

    # --- Sessions ---
    secret_key: str = Field(default="dev-only-insecure-key", alias="SECRET_KEY")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    """Must stay False on plain HTTP. A Secure cookie is not sent over http://,
    so setting this locally makes login appear to succeed and then bounce
    straight back to /login with nothing in any log."""

    # --- Demo determinism ---
    now_override: datetime | None = Field(default=None, alias="NOW_OVERRIDE")
    """Anchors relative-date resolution to the fixture window. Without it the
    adversarial fixture rots: "do patku" silently means a different day next
    week, and the demo breaks in front of an audience."""

    user_timezone: str = Field(default="Europe/Prague", alias="USER_TIMEZONE")

    # --- Storage ---
    database_url: str = Field(default="sqlite+aiosqlite:///./deadlines.db", alias="DATABASE_URL")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.user_timezone)

    def now(self) -> datetime:
        """The single source of "now" for the whole app.

        Everything that resolves or buckets a date goes through this, so tests
        and the demo share one clock.
        """
        if self.now_override is not None:
            value = self.now_override
            return value if value.tzinfo else value.replace(tzinfo=self.tz)
        return datetime.now(self.tz)


@lru_cache
def get_settings() -> Settings:
    return Settings()
