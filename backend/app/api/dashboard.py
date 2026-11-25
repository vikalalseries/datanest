from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.services import record_service, sheet_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    uid = db.info["user_id"]
    sheets = await sheet_service.list_sheets(db, uid, None)
    recent_records = await record_service.all_records(db, uid, None, 5, 0)
    activity = (
        await db.execute(
            text(
                "select a.id, a.action, a.sheet_id, a.created_at, s.name as sheet_name from public.activity_logs a "
                "left join public.sheets s on s.id = a.sheet_id where a.user_id = :u order by a.created_at desc limit 8"
            ),
            {"u": uid},
        )
    ).all()
    return {
        "total_sheets": len(sheets),
        "total_records": sum(s.record_count for s in sheets),
        "recent_sheets": [s.model_dump(mode="json") for s in sheets[:5]],
        "recent_records": [r.model_dump(mode="json") for r in recent_records.items],
        "recent_activity": [
            {
                "id": str(a.id), "action": a.action, "sheet_id": str(a.sheet_id) if a.sheet_id else None,
                "sheet_name": a.sheet_name, "created_at": a.created_at.isoformat(),
            }
            for a in activity
        ],
    }


@router.get("/trash")
async def trash(db: AsyncSession = Depends(get_db)):
    uid = db.info["user_id"]
    sheets = await sheet_service.list_sheets(db, uid, None, state="deleted")
    rows = (
        await db.execute(
            text(
                "select r.id, r.sheet_id, r.data_json, r.deleted_at, s.name as sheet_name, s.schema_json "
                "from public.records r join public.sheets s on s.id = r.sheet_id "
                "where r.user_id = :u and r.deleted_at is not null and s.deleted_at is null "
                "order by r.deleted_at desc limit 200"
            ),
            {"u": uid},
        )
    ).all()
    records = []
    for r in rows:
        names = {c["id"]: c["name"] for c in sheet_service.jload(r.schema_json).get("columns", [])}
        data = {names.get(k, k): v for k, v in sheet_service.jload(r.data_json).items() if v not in (None, "", [])}
        records.append(
            {"id": str(r.id), "sheet_id": str(r.sheet_id), "sheet_name": r.sheet_name, "data": data, "deleted_at": r.deleted_at.isoformat()}
        )
    return {"sheets": [s.model_dump(mode="json") for s in sheets], "records": records}
