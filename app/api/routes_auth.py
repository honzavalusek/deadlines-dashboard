"""Login and logout."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import DbDep
from app.auth.session import authenticate, log_in, log_out, session_user_id
from app.db.repositories import UserRepository

router = APIRouter()
templates: Jinja2Templates | None = None  # injected by the app factory


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if session_user_id(request) is not None:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    db: DbDep,
    email: str = Form(...),
    password: str = Form(...),
):
    user, error = await authenticate(UserRepository(db), email, password)
    if user is None:
        # 200, not 401: this is a form being re-rendered, not an API rejection.
        return templates.TemplateResponse(request, "login.html", {"error": error})

    log_in(request, user)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    log_out(request)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
