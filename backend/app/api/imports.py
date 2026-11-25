import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.database.schemas import SheetOut
from app.rate_limit import limiter
from app.services import import_commit_service as commit
from app.services import import_service as imp
from app.services.sheet_service import err

router = APIRouter(prefix="/import", tags=["import"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024
IMPORT_LIMIT = "20/minute"


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_IMPORT_BYTES + 1)  # never buffer more than the limit
    if len(data) > MAX_IMPORT_BYTES:
        raise err(422, "file_too_large", f"That file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB.")
    return data


def _parse(data: bytes, filename: str) -> list[imp.ParsedTable]:
    try:
        return imp.parse_file(data, filename or "")
    except imp.ImportError_ as e:
        raise err(422, "invalid_file", str(e))


@router.post("/preview")
@limiter.limit(IMPORT_LIMIT)
async def preview(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Parse the file and show what would be imported. Nothing is saved."""
    data = await _read(file)
    tables = _parse(data, file.filename)
    return {"filename": (file.filename or "")[:200], "worksheets": [imp.preview(t) for t in tables]}


@router.post("/commit", response_model=SheetOut, status_code=201)
@limiter.limit(IMPORT_LIMIT)
async def commit_import(request: Request, file: UploadFile = File(...), options: str = Form(...), db: AsyncSession = Depends(get_db)):
    """Re-reads the same file and creates a sheet using the (edited) column choices from the preview."""
    try:
        opts = commit.ImportOptions.model_validate(json.loads(options))
    except (ValueError, ValidationError):
        raise err(422, "bad_options", "The import settings are invalid. Please redo the preview.")
    data = await _read(file)
    table = commit.pick_table(_parse(data, file.filename), opts.worksheet)
    return await commit.commit_new_sheet(db, db.info["user_id"], table, opts, file.filename or "import")
