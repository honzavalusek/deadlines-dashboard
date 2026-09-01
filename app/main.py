"""Application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from app.api import deps, routes_api, routes_auth, routes_dashboard
from app.config import get_settings
from app.db.session import create_schema, dispose_engine, init_engine
from app.api.rendering import day, highlight, money, stamp
from app.domain.dates import describe_relative

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_engine(settings.database_url)
        await create_schema()
        yield
        await dispose_engine()

    app = FastAPI(title="Deadlines Dashboard", lifespan=lifespan, docs_url="/api/docs")

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="deadlines_session",
        same_site="lax",
        # Must stay False on plain HTTP. A Secure cookie is not sent over
        # http://, so enabling it locally makes login appear to succeed and then
        # bounce straight back to /login with nothing in any log.
        https_only=settings.cookie_secure,
    )

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["relative_day"] = describe_relative
    templates.env.filters["highlight"] = highlight
    templates.env.filters["day"] = day
    templates.env.filters["stamp"] = stamp
    templates.env.filters["money"] = money

    # Routers hold a module-level template handle so the factory owns the
    # directory rather than each route module guessing at it.
    routes_auth.templates = templates
    routes_dashboard.templates = templates

    app.include_router(routes_auth.router)
    app.include_router(routes_dashboard.router)
    app.include_router(routes_api.router)

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.exception_handler(deps.NeedsLogin)
    async def needs_login(request: Request, exc: deps.NeedsLogin) -> RedirectResponse:
        """An unauthenticated browser gets the login form, not a JSON error."""
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

    @app.exception_handler(deps.MissingApiKeyError)
    async def missing_api_key(request: Request, exc: deps.MissingApiKeyError):
        """A misconfigured server gets a clear message, not a raw 500."""
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": str(exc)}, status_code=503)
        return templates.TemplateResponse(
            request, "config_error.html", {"message": str(exc)}, status_code=503
        )

    return app


app = create_app()
