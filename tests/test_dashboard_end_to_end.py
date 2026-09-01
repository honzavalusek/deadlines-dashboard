"""Login through to a rendered board, against a fake engine.

Worth more than any single unit test here: it exercises auth, the session
cookie, DI, the pipeline, persistence and the templates in one pass, and it
asserts the adversarial fixture lands in the right places.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD


@pytest.fixture
def client(monkeypatch, tmp_path):
    """App on a throwaway file database, forced onto a fake engine."""
    from app.config import Settings, get_settings

    db_path = tmp_path / "test.db"
    overrides = Settings(
        now_override="2026-09-02T09:00:00+02:00",
        secret_key="test-secret-key",
        cookie_secure=False,
        database_url=f"sqlite+aiosqlite:///{db_path}",
    )
    get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", lambda: overrides)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: overrides, raising=False)

    import app.main as main
    from app.api import deps
    from tests.fakes import StubCommitmentEngine

    monkeypatch.setattr(main, "get_settings", lambda: overrides)
    app = main.create_app()
    app.dependency_overrides[deps.get_engine] = lambda: StubCommitmentEngine()

    with TestClient(app, follow_redirects=False) as c:
        _seed(overrides)
        yield c

    get_settings.cache_clear()


def _seed(settings) -> None:
    import asyncio
    import json
    from datetime import datetime
    from pathlib import Path

    from app.auth.passwords import hash_password
    from app.db import session as dbs
    from app.db.repositories import MessageRepository, UserRepository

    async def go() -> None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
        rows = []
        for filename, source in (("seed_slack.json", "slack"), ("seed_emails.json", "email")):
            for raw in json.loads((data_dir / filename).read_text(encoding="utf-8"))["messages"]:
                if raw["owner_email"] != "jan@example.com":
                    continue
                rows.append({
                    "source": source, "external_id": raw["external_id"],
                    "thread_key": raw["thread_key"], "author": raw["author"],
                    "sent_at": datetime.fromisoformat(raw["sent_at"]), "body": raw["body"],
                    "channel": raw.get("channel"), "subject": raw.get("subject"),
                })
        async with dbs.get_sessionmaker()() as db:
            users = UserRepository(db)
            if await users.get_by_email("jan@example.com"):
                return
            user = await users.create(
                email="jan@example.com", password_hash=hash_password(TEST_PASSWORD),
                display_name="Jan Valušek", aliases=["Honza", "Honzo", "Jane"],
                alt_emails=[], projects=["pricing page", "product launch"],
            )
            await MessageRepository(db).add_many(user.id, rows)
            await db.commit()

    asyncio.new_event_loop().run_until_complete(go())


def _login(client) -> None:
    r = client.post("/login", data={"email": "jan@example.com", "password": TEST_PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_dashboard_requires_a_session(client):
    r = client.get("/dashboard")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_json_endpoint_returns_401_not_a_redirect(client):
    """An API client must get a status code, not an HTML login page."""
    assert client.get("/api/commitments").status_code == 401


def test_login_failures_are_indistinguishable(client):
    wrong = client.post("/login", data={"email": "jan@example.com", "password": "nope"})
    unknown = client.post("/login", data={"email": "ghost@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 200
    assert "Incorrect email or password" in wrong.text
    assert "Incorrect email or password" in unknown.text


def test_session_cookie_is_safe_for_plain_http(client):
    r = client.post("/login", data={"email": "jan@example.com", "password": TEST_PASSWORD})
    cookie = r.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    # A Secure cookie is never sent over http://, which would break login here.
    assert "secure" not in cookie


def test_board_renders_the_adversarial_fixture(client):
    _login(client)
    html = client.get("/dashboard").text

    for bucket in ("Overdue", "Today", "This week", "Later", "No date"):
        assert bucket in html, f"bucket {bucket!r} missing — every bucket should be populated"

    assert "Send the MSA redlines back to our counsel" in html
    assert "moved from" in html, "the superseded deadline lost its history"
    assert "your project" in html, "the my_team item is not tagged"
    assert "Not yours" in html, "someone else's work is not shown as filtered"
    assert "Considered and dismissed" in html, "the noise thread was silently dropped"
    assert "How this was produced" in html, "no audit trail"


def test_json_view_matches_the_expected_shape(client):
    _login(client)
    body = client.get("/api/commitments").json()

    assert len(body["board"]) == 8
    assert body["off_board"]["cancelled"] and body["off_board"]["not_yours"]
    assert body["dismissed_threads"], "the noise thread should be reported, not discarded"
    assert body["daily_briefing"]
    assert not body["warnings"], f"validation warnings on a clean fixture: {body['warnings']}"

    tasks = [i["task"] for i in body["board"]]
    uohs = next(i for i, t in enumerate(tasks) if "ÚOHS" in t)
    alt = next(i for i, t in enumerate(tasks) if "alt text" in t)
    assert uohs < alt, "a statutory deadline must outrank sooner-but-trivial work"


def test_marking_done_moves_it_off_the_board(client):
    _login(client)
    board = client.get("/api/commitments").json()["board"]
    target = next(i for i in board if "MSA redlines" in i["task"])

    r = client.post(
        f"/commitments/{target['key']}/complete",
        params={"thread_key": "slack:legal-oops:wrong"},  # value comes from the form, not trusted
    )
    assert r.status_code == 303

    after = client.get("/api/commitments").json()
    assert not any(i["key"] == target["key"] for i in after["board"])
    assert any(i["key"] == target["key"] for i in after["off_board"]["completed"])


def test_reanalysis_does_not_resurrect_completed_work(client):
    _login(client)
    board = client.get("/api/commitments").json()["board"]
    target = next(i for i in board if "MSA redlines" in i["task"])
    client.post(f"/commitments/{target['key']}/complete",
                params={"thread_key": "slack:legal-ops:msa-redlines"})

    assert client.post("/analyze").status_code == 303

    after = client.get("/api/commitments").json()
    assert not any(i["key"] == target["key"] for i in after["board"]), \
        "completed work came back after re-analysis"
