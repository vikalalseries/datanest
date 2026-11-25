"""Phase 7 endpoints: templates, analytics, global search, activity history, notifications."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.rate_limit import limiter
from app.services import activity_service, analytics_service, notification_service, search_service, templates_service

router = APIRouter(tags=["insights"])


def uid(db: AsyncSession) -> str:
    return db.info["user_id"]


# ---------- templates ----------
class InstantiateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class GenerateTemplateIn(BaseModel):
    description: str = Field(min_length=3, max_length=500)


@router.get("/templates")
async def list_templates():
    return templates_service.list_templates()


@router.post("/templates/{key}/instantiate", status_code=201)
async def instantiate_template(key: str, body: InstantiateIn, db: AsyncSession = Depends(get_db)):
    return await templates_service.instantiate(db, uid(db), key, body.name)


@router.post("/ai/generate-template")
@limiter.limit("10/minute")
async def generate_template(request: Request, body: GenerateTemplateIn, db: AsyncSession = Depends(get_db)):
    """AI designs a sheet from a description. Returns a preview only; create it with POST /sheets after the user reviews it."""
    return await templates_service.generate(body.description)


# ---------- analytics ----------
@router.get("/analytics/sheet/{sheet_id}")
async def sheet_analytics(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    return await analytics_service.sheet_analytics(db, uid(db), sheet_id)


@router.get("/analytics/overview")
async def analytics_overview(db: AsyncSession = Depends(get_db)):
    return await analytics_service.overview(db, uid(db))


# ---------- search ----------
@router.get("/search")
async def search(
    q: str | None = Query(None, max_length=200), category: str | None = Query(None, max_length=60), status: str | None = Query(None, max_length=60),
    date_from: str | None = Query(None, max_length=10), date_to: str | None = Query(None, max_length=10),
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db),
):
    return await search_service.search(db, uid(db), q=q, category=category, status=status, date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/search/facets")
async def search_facets(db: AsyncSession = Depends(get_db)):
    return await search_service.facets(db, uid(db))


# ---------- activity ----------
@router.get("/activity")
async def activity(sheet_id: UUID | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    return await activity_service.list_activity(db, uid(db), sheet_id, limit, offset)


@router.post("/activity/{log_id}/undo")
async def undo_activity(log_id: UUID, db: AsyncSession = Depends(get_db)):
    return await activity_service.undo(db, uid(db), log_id)


# ---------- notifications ----------
@router.get("/notifications")
async def notifications(db: AsyncSession = Depends(get_db)):
    return await notification_service.compute(db, uid(db))
