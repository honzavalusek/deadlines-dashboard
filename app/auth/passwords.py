"""Password hashing.

argon2 via ``argon2-cffi`` directly rather than through passlib: a three-call
surface, actively maintained, and one fewer dependency layer to reason about.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify, returning False rather than raising on any failure.

    The caller must not be able to distinguish "no such user" from "wrong
    password" — see ``app.auth.session.authenticate``.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash predates the current parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return False
