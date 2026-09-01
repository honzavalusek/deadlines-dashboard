#!/usr/bin/env python
"""Seed the database: two demo users and their fake Slack/email history.

The JSON files under ``data/`` are *seed* data, not the runtime source. The app
reads messages from the database, scoped per user, exactly as it would with a
real Slack or Graph API ingestion behind the same repository.

    python scripts/seed.py            # idempotent: skips users that exist
    python scripts/seed.py --reset    # drop every table first
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.passwords import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import session as dbs  # noqa: E402
from app.db.repositories import MessageRepository, UserRepository  # noqa: E402
from app.db.tables import Base  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Demo passwords. Fine for a PoC with disposable data; printed on seed so the
# demo is self-documenting. A real deployment would invite users instead.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "deadlines-demo")

USERS = [
    {
        "email": "jan@example.com",
        "display_name": "Jan Valušek",
        # Czech vocative and dative forms are how people are actually addressed
        # in these threads, and the model needs them to resolve "Honzo, ..."
        # to this user.
        "aliases": ["Honza", "Honzo", "Honzovi", "Jane", "JV"],
        "alt_emails": ["j.valusek@example.com"],
        # What makes an `audience: my_team` judgment possible: without this,
        # "the pricing page still has no copy" is undecidable.
        "projects": ["pricing page", "product launch", "MSA with Acme"],
    },
    {
        "email": "petra@example.com",
        "display_name": "Petra Nováková",
        "aliases": ["Peťa", "Petro"],
        "alt_emails": [],
        "projects": ["legal operations", "data processing agreements"],
    },
]


def load_fixture(filename: str, source: str) -> list[dict]:
    payload = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
    messages = []
    for raw in payload["messages"]:
        messages.append(
            {
                "owner_email": raw["owner_email"],
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
    return messages


async def seed(reset: bool) -> None:
    settings = get_settings()
    engine = dbs.init_engine(settings.database_url)

    if reset:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        print("dropped all tables")

    await dbs.create_schema()

    fixtures = load_fixture("seed_slack.json", "slack") + load_fixture("seed_emails.json", "email")
    by_owner: dict[str, list[dict]] = {}
    for m in fixtures:
        by_owner.setdefault(m.pop("owner_email"), []).append(m)

    unknown = set(by_owner) - {u["email"] for u in USERS}
    if unknown:
        raise SystemExit(f"fixture references unknown owner_email: {sorted(unknown)}")

    async with dbs.get_sessionmaker()() as db:
        users_repo = UserRepository(db)
        messages_repo = MessageRepository(db)

        for spec in USERS:
            existing = await users_repo.get_by_email(spec["email"])
            if existing is not None:
                print(f"  {spec['email']:22} exists, skipped")
                continue

            user = await users_repo.create(
                email=spec["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                display_name=spec["display_name"],
                aliases=spec["aliases"],
                alt_emails=spec["alt_emails"],
                projects=spec["projects"],
                timezone_name=settings.user_timezone,
            )
            count = await messages_repo.add_many(user.id, by_owner.get(spec["email"], []))
            threads = len({m["thread_key"] for m in by_owner.get(spec["email"], [])})
            print(f"  {spec['email']:22} created — {count} messages across {threads} threads")

        await db.commit()

    await dbs.dispose_engine()

    print(f"\nDemo login password for both users: {DEMO_PASSWORD}")
    print(f"Relative dates resolve against NOW_OVERRIDE = {settings.now().isoformat()}"
          f" ({settings.now():%A})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop all tables before seeding")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
