import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.database.schemas import BulkAddRequest, DuplicateCheckRequest, IdList, MoveRecords, RecordCreate, RecordOut, RecordPage, RecordUpdate
from app.services import record_service as svc
from app.services import smart_save_service
from app.services.sheet_service import err

router = APIRouter(tags=["records"])


def uid(db: AsyncSession) -> str:
    return db.info["user_id"]


def parse_filters(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) > 20 or not all(isinstance(f, dict) for f in data):
            raise ValueError
        return data
    except ValueError:
        raise err(422, "bad_filter", "The filter is malformed.")


@router.get("/sheets/{sheet_id}/records", response_model=RecordPage)
async def list_records(
    sheet_id: UUID,
    q: str | None = Query(None, max_length=200),
    sort: str | None = Query(None, max_length=40),
    dir: str = Query("asc", pattern="^(asc|desc)$"),
    filters: str | None = Query(None, max_length=4000, description="JSON list of {column, op, value}"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_records(
        db, uid(db), sheet_id, q=q, sort=sort, direction=dir, filters=parse_filters(filters), limit=limit, offset=offset
    )


@router.post("/sheets/{sheet_id}/records", response_model=RecordOut, status_code=201)
async def create_record(sheet_id: UUID, body: RecordCreate, db: AsyncSession = Depends(get_db)):
    return await svc.create_record(db, uid(db), sheet_id, body.data)


@router.post("/sheets/{sheet_id}/records/bulk", status_code=201)
async def bulk_add(sheet_id: UUID, body: BulkAddRequest, db: AsyncSession = Depends(get_db)):
    """Add extracted records to an existing sheet using an explicit field->column mapping (nothing dropped silently)."""
    return await smart_save_service.bulk_add(db, uid(db), sheet_id, body)


@router.post("/sheets/{sheet_id}/records/check-duplicates")
async def check_duplicates(sheet_id: UUID, body: DuplicateCheckRequest, db: AsyncSession = Depends(get_db)):
    return await smart_save_service.check_duplicates(db, uid(db), sheet_id, body)


@router.get("/records", response_model=RecordPage)
async def all_records(
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await svc.all_records(db, uid(db), q, limit, offset)


@router.put("/records/{record_id}", response_model=RecordOut)
async def update_record(record_id: UUID, body: RecordUpdate, db: AsyncSession = Depends(get_db)):
    return await svc.update_record(db, uid(db), record_id, body.data)


@router.delete("/records/{record_id}", status_code=204)
async def delete_record(record_id: UUID, db: AsyncSession = Depends(get_db)):
    if await svc.trash_records(db, uid(db), [record_id]) == 0:
        raise err(404, "record_not_found", "That record doesn't exist or you don't have access to it.")
    return Response(status_code=204)


@router.post("/records/bulk-delete")
async def bulk_delete(body: IdList, db: AsyncSession = Depends(get_db)):
    return {"deleted": await svc.trash_records(db, uid(db), body.ids)}


@router.post("/records/restore")
async def restore(body: IdList, db: AsyncSession = Depends(get_db)):
    return {"restored": await svc.restore_records(db, uid(db), body.ids)}


@router.post("/records/purge")
async def purge(body: IdList, db: AsyncSession = Depends(get_db)):
    return {"purged": await svc.purge_records(db, uid(db), body.ids)}


@router.post("/records/move")
async def move(body: MoveRecords, db: AsyncSession = Depends(get_db)):
    return {"moved": await svc.move_records(db, uid(db), body)}
