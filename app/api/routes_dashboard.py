"""The dashboard, and the two state-changing actions on it."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import DbDep, EngineDep, EngineFactoryDep, SettingsDep, UserDep
from app.db.repositories import CompletionRepository
from app.services.dashboard import analyse_and_store, build_view

router = APIRouter()
templates: Jinja2Templates | None = None  # injected by the app factory


@router.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: DbDep,
    user: UserDep,
    engine: EngineFactoryDep,
    settings: SettingsDep,
) -> HTMLResponse:
    view = await build_view(db, user, engine, settings)
    return templates.TemplateResponse(request, "dashboard.html", view.context())


@router.post("/analyze")
async def analyze(
    db: DbDep,
    user: UserDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> RedirectResponse:
    await analyse_and_store(db, user, engine, settings)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/commitments/{commitment_key}/complete")
async def complete(commitment_key: str, thread_key: str, db: DbDep, user: UserDep) -> RedirectResponse:
    """Mark done.

    Scoped to the session user: the key in the URL identifies *which* commitment,
    never *whose*. A key belonging to someone else simply creates a mark under
    this user that matches nothing.
    """
    await CompletionRepository(db).mark(user.id, commitment_key, thread_key)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/commitments/{commitment_key}/uncomplete")
async def uncomplete(commitment_key: str, db: DbDep, user: UserDep) -> RedirectResponse:
    await CompletionRepository(db).unmark(user.id, commitment_key)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
