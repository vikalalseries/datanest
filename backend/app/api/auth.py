from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.database.schemas import UserOut, WorkspaceOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserOut)
async def me(db: AsyncSession = Depends(get_db)) -> UserOut:
    """Return the caller's profile. The profile/workspace rows are created on first authenticated request."""
    uid = db.info["user_id"]
    row = (
        await db.execute(
            text("select id, email, full_name, avatar_url, created_at from public.users where id = :u"), {"u": uid}
        )
    ).first()
    ws = (
        await db.execute(text("select id, name from public.workspaces where user_id = :u order by created_at limit 1"), {"u": uid})
    ).first()
    if row is None or ws is None:
        raise HTTPException(status_code=500, detail={"code": "profile_error", "message": "Could not load your profile."})
    return UserOut(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        avatar_url=row.avatar_url,
        created_at=row.created_at,
        workspace=WorkspaceOut(id=ws.id, name=ws.name),
    )
