from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.rate_limit import limiter
from app.services import export_service as ex
from app.services import sheet_service, storage_service
from app.services.import_commit_service import content_disposition
from app.services.sheet_service import err, jload, log_activity

router = APIRouter(tags=["export"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_LIMIT = "20/minute"


async def _rows(db: AsyncSession, uid: str, sheet_id) -> list[dict]:
    res = await db.execute(
        text(
            "select data_json from public.records where sheet_id = :s and user_id = :u and deleted_at is null "
            "order by created_at, position nulls last, id limit :lim"
        ),
        {"s": str(sheet_id), "u": uid, "lim": ex.MAX_ROWS_PER_SHEET + 1},
    )
    return [jload(r.data_json) for r in res.all()]


@router.get("/export/sheet/{sheet_id}")
@limiter.limit(EXPORT_LIMIT)
async def export_sheet(request: Request, sheet_id: UUID, format: str = Query("xlsx", pattern="^(xlsx|csv)$"), db: AsyncSession = Depends(get_db)):
    uid = db.info["user_id"]
    sheet = await sheet_service.get_sheet_row(db, uid, sheet_id)
    columns = sheet_service.columns_of(sheet)
    rows = await _rows(db, uid, sheet_id)
    try:
        if format == "csv":
            body, media = ex.build_csv(columns, rows), "text/csv; charset=utf-8"
        else:
            body, media = ex.build_workbook([{"name": sheet.name, "columns": columns, "rows": rows}]), XLSX
    except Exception:
        raise err(500, "export_failed", "We couldn't create the file. Please try again.")
    await log_activity(db, uid, "export.sheet", sheet_id, {"format": format, "rows": min(len(rows), ex.MAX_ROWS_PER_SHEET)})
    headers = {"Content-Disposition": content_disposition(ex.safe_filename(sheet.name, format)), "Cache-Control": "no-store"}
    if len(rows) > ex.MAX_ROWS_PER_SHEET:
        headers["X-Export-Truncated"] = "true"
    return Response(content=body, media_type=media, headers=headers)


@router.get("/export/workspace")
@limiter.limit(EXPORT_LIMIT)
async def export_workspace(request: Request, db: AsyncSession = Depends(get_db)):
    """All active sheets in one workbook, one worksheet per sheet."""
    uid = db.info["user_id"]
    sheets = await sheet_service.list_sheets(db, uid, None)
    if not sheets:
        raise err(404, "nothing_to_export", "You don't have any sheets to export yet.")
    payload = []
    for s in reversed(sheets):  # oldest-updated first so the workbook reads in a stable order
        payload.append({"name": s.name, "columns": [c.model_dump() for c in s.columns], "rows": await _rows(db, uid, s.id)})
    try:
        body = ex.build_workbook(payload)
    except Exception:
        raise err(500, "export_failed", "We couldn't create the workbook. Please try again.")
    await log_activity(db, uid, "export.workspace", None, {"sheets": len(payload)})
    return Response(content=body, media_type=XLSX, headers={"Content-Disposition": content_disposition("datanest-all-sheets.xlsx"), "Cache-Control": "no-store"})


@router.get("/files/{file_id}/download")
async def download_original(file_id: UUID, db: AsyncSession = Depends(get_db)):
    """Short-lived link to an original upload. Only the owner can request it."""
    uid = db.info["user_id"]
    row = (
        await db.execute(text("select file_name, file_path from public.files where id = :id and user_id = :u"), {"id": str(file_id), "u": uid})
    ).first()
    if row is None:
        raise err(404, "file_not_found", "That file doesn't exist or you don't have access to it.")
    url = await storage_service.signed_url(row.file_path)
    if url is None:
        raise err(503, "storage_unavailable", "The original file isn't available right now.")
    return {"url": url, "file_name": row.file_name, "expires_in": 300}
