"""Session-cookie authentication.

Cookie-based rather than JWT because the app is server-rendered: a signed
session cookie is what a Jinja dashboard actually wants, and it avoids
hand-rolling token storage in the browser.
"""

from __future__ import annotations

from typing import Final

from starlette.requests import Request

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.db.repositories import UserRepository
from app.db.tables import User

SESSION_USER_ID: Final = "uid"

_GENERIC_LOGIN_ERROR: Final = "Incorrect email or password."
"""One message for both failure modes. Saying "no such user" would turn the
login form into an account-enumeration oracle."""


async def authenticate(users: UserRepository, email: str, password: str) -> tuple[User | None, str | None]:
    """Return ``(user, None)`` on success or ``(None, message)`` on failure.

    A dummy verification runs when the email is unknown so that the response
    time does not reveal whether the account exists.
    """
    user = await users.get_by_email(email)
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None, _GENERIC_LOGIN_ERROR

    if not verify_password(user.password_hash, password):
        return None, _GENERIC_LOGIN_ERROR

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    return user, None


def log_in(request: Request, user: User) -> None:
    """Start a session.

    ``clear()`` first so a pre-existing session identifier is never reused
    across a login — that would be session fixation.
    """
    request.session.clear()
    request.session[SESSION_USER_ID] = user.id


def log_out(request: Request) -> None:
    request.session.clear()


def session_user_id(request: Request) -> int | None:
    value = request.session.get(SESSION_USER_ID)
    return value if isinstance(value, int) else None


# Precomputed so an unknown email costs the same as a known one.
_DUMMY_HASH: Final = hash_password("dummy-password-for-constant-time-comparison")
