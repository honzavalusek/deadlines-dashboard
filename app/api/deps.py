"""FastAPI dependencies.

Where the engine is chosen. Everything downstream depends on the
``CommitmentEngine`` protocol, so flipping ``ENGINE=stub`` to ``ENGINE=claude``
swaps the implementation without another line changing — which is the same seam
that would carry a Bedrock client or a real Slack ingestion.
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


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in session_scope():
        yield session


def get_config() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_config)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_engine(settings: SettingsDep) -> CommitmentEngine:
    """Pick the engine from configuration.

    The Claude adapter is imported lazily so that running with ``ENGINE=stub``
    never touches the SDK — the offline path stays genuinely offline.
    """
    if settings.engine == "claude":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ENGINE=claude but ANTHROPIC_API_KEY is unset. "
                "Set the key, or use ENGINE=stub to run offline."
            )
        from app.adapters.cached_engine import build_claude_engine

        return build_claude_engine(settings)

    from app.adapters.stub_engine import StubCommitmentEngine

    return StubCommitmentEngine()


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
