"""JSON view of the same data the dashboard renders.

Exists to show the template is a client of the service rather than the service
itself — and to make the pipeline's output inspectable without reading HTML.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ApiUserDep, DbDep, EngineFactoryDep, SettingsDep
from app.services.dashboard import build_view, to_json

router = APIRouter(prefix="/api")


@router.get("/commitments")
async def commitments(
    db: DbDep,
    user: ApiUserDep,
    engine: EngineFactoryDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    return to_json(await build_view(db, user, engine, settings))
