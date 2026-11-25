from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.database.schemas import ColumnIn, ColumnOrder, ColumnUpdate, MergeRequest, SheetCreate, SheetFromExtraction, SheetOut, SheetUpdate
from app.services import record_service, smart_save_service
from app.services import sheet_service as svc

router = APIRouter(prefix="/sheets", tags=["sheets"])


def uid(db: AsyncSession) -> str:
    return db.info["user_id"]


@router.get("", response_model=list[SheetOut])
async def list_sheets(q: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_db)):
    return await svc.list_sheets(db, uid(db), q)


@router.post("", response_model=SheetOut, status_code=201)
async def create_sheet(body: SheetCreate, db: AsyncSession = Depends(get_db)):
    return await svc.create_sheet(db, uid(db), body)


@router.post("/from-extraction", response_model=SheetOut, status_code=201)
async def create_from_extraction(body: SheetFromExtraction, db: AsyncSession = Depends(get_db)):
    """Create a sheet and its rows from a confirmed AI extraction, atomically."""
    return await record_service.create_sheet_from_extraction(db, uid(db), body)


@router.get("/{sheet_id}", response_model=SheetOut)
async def get_sheet(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    return await svc.get_sheet(db, uid(db), sheet_id)


@router.put("/{sheet_id}", response_model=SheetOut)
async def update_sheet(sheet_id: UUID, body: SheetUpdate, db: AsyncSession = Depends(get_db)):
    return await svc.update_sheet(db, uid(db), sheet_id, body)


@router.delete("/{sheet_id}", status_code=204)
async def delete_sheet(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    """Moves the sheet to Trash (recoverable)."""
    await svc.trash_sheet(db, uid(db), sheet_id)
    return Response(status_code=204)


@router.post("/{sheet_id}/restore", response_model=SheetOut)
async def restore_sheet(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    return await svc.restore_sheet(db, uid(db), sheet_id)


@router.delete("/{sheet_id}/permanent", status_code=204)
async def purge_sheet(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    await svc.purge_sheet(db, uid(db), sheet_id)
    return Response(status_code=204)


@router.post("/{sheet_id}/duplicate", response_model=SheetOut, status_code=201)
async def duplicate_sheet(sheet_id: UUID, db: AsyncSession = Depends(get_db)):
    return await svc.duplicate_sheet(db, uid(db), sheet_id)


@router.post("/{sheet_id}/merge")
async def merge_sheet(sheet_id: UUID, body: MergeRequest, db: AsyncSession = Depends(get_db)):
    """Merge another sheet's rows into this one (columns matched by name; missing ones added only if allowed)."""
    return await smart_save_service.merge_sheets(db, uid(db), sheet_id, body)


@router.post("/{sheet_id}/columns", response_model=SheetOut, status_code=201)
async def add_column(sheet_id: UUID, body: ColumnIn, db: AsyncSession = Depends(get_db)):
    return await svc.add_column(db, uid(db), sheet_id, body)


@router.put("/{sheet_id}/columns-order", response_model=SheetOut)
async def reorder_columns(sheet_id: UUID, body: ColumnOrder, db: AsyncSession = Depends(get_db)):
    return await svc.reorder_columns(db, uid(db), sheet_id, body.ids)


@router.patch("/{sheet_id}/columns/{col_id}", response_model=SheetOut)
async def update_column(sheet_id: UUID, col_id: str, body: ColumnUpdate, db: AsyncSession = Depends(get_db)):
    return await svc.update_column(db, uid(db), sheet_id, col_id, body)


@router.delete("/{sheet_id}/columns/{col_id}", response_model=SheetOut)
async def delete_column(sheet_id: UUID, col_id: str, db: AsyncSession = Depends(get_db)):
    return await svc.delete_column(db, uid(db), sheet_id, col_id)
