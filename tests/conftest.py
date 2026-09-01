"""Test fixtures.

Every test runs against the stub engine on an in-memory database: no API key,
no network, no cost, and no dependence on whatever is in ``.env``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.passwords import hash_password
from app.config import Settings
from app.db.tables import Base
from app.domain.models import Identity

TEST_PASSWORD = "test-password"

# Same anchor the fixture is authored against, so relative dates resolve the way
# the expectations assume.
PINNED_NOW = "2026-09-02T09:00:00+02:00"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        now_override=PINNED_NOW,
        secret_key="test-secret-key",
        cookie_secure=False,
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture
def identity() -> Identity:
    return Identity(
        display_name="Jan Valušek",
        aliases=["Honza", "Honzo", "Honzovi", "Jane"],
        emails=["jan@example.com"],
        projects=["pricing page", "product launch"],
    )


@pytest_asyncio.fixture
async def session_factory():
    """A fresh in-memory database per test.

    StaticPool keeps every connection on the same in-memory database; without it
    each connection would get its own empty one.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_user(session_factory):
    """One user with the full adversarial fixture loaded."""
    import json
    from datetime import datetime
    from pathlib import Path

    from app.db.repositories import MessageRepository, UserRepository

    data_dir = Path(__file__).resolve().parent.parent / "data"
    rows = []
    for filename, source in (("seed_slack.json", "slack"), ("seed_emails.json", "email")):
        payload = json.loads((data_dir / filename).read_text(encoding="utf-8"))
        for raw in payload["messages"]:
            if raw["owner_email"] != "jan@example.com":
                continue
            rows.append(
                {
                    "source": source,
                    "external_id": raw["external_id"],
                    "thread_key": raw["thread_key"],
                    "author": raw["author"],
                    "sent_at": datetime.fromisoformat(raw["sent_at"]),
                    "body": raw["body"],
                    "channel": raw.get("channel"),
                    "subject": raw.get("subject"),
                }
            )

    async with session_factory() as db:
        user = await UserRepository(db).create(
            email="jan@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            display_name="Jan Valušek",
            aliases=["Honza", "Honzo", "Jane"],
            alt_emails=[],
            projects=["pricing page", "product launch"],
        )
        await MessageRepository(db).add_many(user.id, rows)
        await db.commit()
        return user.id
