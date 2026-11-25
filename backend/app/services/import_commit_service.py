"""Turn a previewed + user-edited import into a real sheet with rows."""
import json
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.schemas import ColumnIn, ColumnType, SheetCreate
from app.services import import_service as imp
from app.services import sheet_service
from app.services.sheet_service import err, log_activity
from app.utils.validators import ValueError_


class ImportColumn(BaseModel):
    index: int = Field(ge=0, le=imp.MAX_COLS)
    name: str = Field(min_length=1, max_length=80)
    type: ColumnType = "text"
    include: bool = True


class ImportOptions(BaseModel):
    worksheet: str | None = None
    sheet_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    columns: list[ImportColumn] = Field(min_length=1, max_length=imp.MAX_COLS)


def pick_table(tables: list[imp.ParsedTable], worksheet: str | None) -> imp.ParsedTable:
    if worksheet is None:
        return tables[0]
    for t in tables:
        if t.name == worksheet:
            return t
    raise err(422, "worksheet_not_found", "That worksheet isn't in the file.")


async def commit_new_sheet(db: AsyncSession, uid: str, table: imp.ParsedTable, opts: ImportOptions, filename: str):
    chosen = [c for c in opts.columns if c.include]
    if not chosen:
        raise err(422, "no_columns", "Select at least one column to import.")
    names = [c.name.strip().lower() for c in chosen]
    if len(set(names)) != len(names):
        raise err(422, "duplicate_column", "Every imported column needs a unique name.")
    if any(c.index >= len(table.headers) for c in chosen):
        raise err(422, "bad_columns", "The column selection doesn't match the file.")

    # convert everything first; abort the whole import (nothing saved) if anything is unreadable
    slash = {}
    for c in chosen:
        if c.type == "date":
            slash[c.index] = imp._slash_order([str(r[c.index]) for r in table.rows if r[c.index] is not None and isinstance(r[c.index], str)])
    data_rows: list[dict[int, Any]] = []
    problems: list[str] = []
    for ri, row in enumerate(table.rows, start=2):  # row 1 is the header in the source file
        out: dict[int, Any] = {}
        for pos, c in enumerate(chosen):
            try:
                v = imp.convert_cell(c.type, row[c.index], slash.get(c.index))
            except ValueError_ as e:
                problems.append(f"Row {ri}, “{c.name}”: {e}")
                continue
            if v is not None:
                out[pos] = v
        data_rows.append(out)
    if problems:
        extra = f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""
        raise err(
            422, "import_invalid",
            "Some values don't fit their column type: " + "; ".join(problems[:8]) + extra + ". Change those columns to Text in the preview, or fix the file.",
            problem_count=len(problems),
        )

    sheet = await sheet_service.create_sheet(
        db, uid,
        SheetCreate(name=opts.sheet_name, description=opts.description, category="imported",
                    columns=[ColumnIn(name=c.name.strip(), type=c.type) for c in chosen]),
    )
    ids = [c.id for c in sheet.columns]
    batch: list[dict] = []
    total = 0
    for out in data_rows:
        data = {ids[pos]: v for pos, v in out.items()}
        if not data:
            continue
        batch.append({"s": str(sheet.id), "u": uid, "d": json.dumps(data), "p": float(total + len(batch))})
        if len(batch) >= 1000:
            await _insert(db, batch)
            total += len(batch)
            batch = []
    if batch:
        await _insert(db, batch)
        total += len(batch)
    await log_activity(db, uid, "sheet.import", sheet.id, {"file": filename[:120], "rows": total})
    return await sheet_service.get_sheet(db, uid, sheet.id)


async def _insert(db: AsyncSession, rows: list[dict]) -> None:
    await db.execute(
        text("insert into public.records (sheet_id, user_id, data_json, source_type, position) values (:s, :u, CAST(:d AS jsonb), 'import', :p)"), rows
    )


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
