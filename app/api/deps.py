"""FastAPI dependencies.

Where the engine is built. Everything downstream depends on the
``CommitmentEngine`` protocol rather than ``ClaudeCommitmentEngine`` directly,
which is the same seam that would carry a Bedrock client or a real Slack
ingestion, and the one tests use to inject a fake engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import session_user_id
from app.config import Settings, get_settings
from app.db.session import session_scope
from app.db.tables import User
from app.domain.ports import CommitmentEngine


class NeedsLogin(Exception):
    """Raised by the HTML dependency so a browser gets a redirect, not JSON."""


class MissingApiKeyError(RuntimeError):
    """Raised when the engine is requested but ANTHROPIC_API_KEY is unset."""


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in session_scope():
        yield session


def get_config() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_config)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_engine(settings: SettingsDep) -> CommitmentEngine:
    """Build the Claude-backed engine.

    Imported lazily so that a missing key raises the friendly error below
    before anything tries to import or construct the Anthropic SDK client.
    """
    if not settings.anthropic_api_key:
        raise MissingApiKeyError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file to run "
            "the analysis pipeline."
        )
    from app.adapters.claude_engine import ClaudeCommitmentEngine

    return ClaudeCommitmentEngine(settings)


EngineDep = Annotated[CommitmentEngine, Depends(get_engine)]


async def _load_session_user(request: Request, db: AsyncSession) -> User | None:
    user_id = session_user_id(request)
    if user_id is None:
        return None
    return await db.get(User, user_id)


async def current_user_or_redirect(request: Request, db: DbDep) -> User:
    """For HTML routes: an unauthenticated browser is sent to the login form."""
    user = await _load_session_user(request, db)
    if user is None:
        raise NeedsLogin
    return user


async def current_user_or_401(request: Request, db: DbDep) -> User:
    """For JSON routes: no cookie means 401, never an HTML redirect."""
    user = await _load_session_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


UserDep = Annotated[User, Depends(current_user_or_redirect)]
ApiUserDep = Annotated[User, Depends(current_user_or_401)]


def redirect_to_login() -> RedirectResponse:
    # Relative path: there is no TLS here, so nothing may hardcode a scheme.
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
