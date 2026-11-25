import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.schemas import ColumnIn, SheetCreate, SheetOut, SheetUpdate, ColumnUpdate
from app.utils.validators import ValueError_, coerce_value, is_empty, new_column_id


def err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def jload(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


async def log_activity(db: AsyncSession, uid: str, action: str, sheet_id: Any = None, details: dict | None = None) -> None:
    await db.execute(
        text("insert into public.activity_logs (user_id, sheet_id, action, details_json) values (:u, :s, :a, CAST(:d AS jsonb))"),
        {"u": uid, "s": str(sheet_id) if sheet_id else None, "a": action, "d": json.dumps(details or {}, default=str)},
    )


SHEET_COLS = "id, workspace_id, name, description, category, schema_json, deleted_at, created_at, updated_at"


async def get_sheet_row(db: AsyncSession, uid: str, sheet_id: Any, *, state: str = "active", lock: bool = False):
    cond = {"active": " and deleted_at is null", "deleted": " and deleted_at is not null", "any": ""}[state]
    row = (
        await db.execute(
            text(f"select {SHEET_COLS} from public.sheets where id = :id and user_id = :u{cond}" + (" for update" if lock else "")),
            {"id": str(sheet_id), "u": uid},
        )
    ).first()
    if row is None:
        raise err(404, "sheet_not_found", "That sheet doesn't exist or you don't have access to it.")
    return row


def columns_of(row: Any) -> list[dict]:
    return jload(row.schema_json).get("columns", [])


def sheet_out(row: Any, record_count: int = 0) -> SheetOut:
    return SheetOut(
        id=row.id, name=row.name, description=row.description, category=row.category,
        columns=columns_of(row), record_count=record_count,
        deleted_at=row.deleted_at, created_at=row.created_at, updated_at=row.updated_at,
    )


def _check_unique_name(columns: list[dict], name: str, ignore_id: str | None = None) -> None:
    low = name.strip().lower()
    if any(c["name"].strip().lower() == low and c["id"] != ignore_id for c in columns):
        raise err(409, "duplicate_column", f"A column named “{name.strip()}” already exists.")


def _make_column(c: ColumnIn) -> dict:
    col: dict[str, Any] = {"id": new_column_id(), "name": c.name.strip(), "type": c.type}
    if c.type == "status" and c.options:
        col["options"] = [o.strip() for o in c.options if o.strip()]
    return col


async def _save_schema(db: AsyncSession, sheet_id: Any, columns: list[dict]) -> None:
    await db.execute(
        text("update public.sheets set schema_json = CAST(:s AS jsonb) where id = :id"),
        {"s": json.dumps({"columns": columns}), "id": str(sheet_id)},
    )


async def count_records(db: AsyncSession, sheet_id: Any) -> int:
    return (
        await db.execute(text("select count(*) from public.records where sheet_id = :s and deleted_at is null"), {"s": str(sheet_id)})
    ).scalar_one()


async def list_sheets(db: AsyncSession, uid: str, q: str | None, state: str = "active") -> list[SheetOut]:
    cond = "s.deleted_at is null" if state == "active" else "s.deleted_at is not null"
    params: dict[str, Any] = {"u": uid}
    if q:
        cond += " and s.name ilike :q escape '\\'"
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        await db.execute(
            text(
                f"select s.*, (select count(*) from public.records r where r.sheet_id = s.id and r.deleted_at is null) as rc "
                f"from public.sheets s where s.user_id = :u and {cond} order by s.updated_at desc"
            ),
            params,
        )
    ).all()
    return [sheet_out(r, r.rc) for r in rows]


async def create_sheet(db: AsyncSession, uid: str, body: SheetCreate) -> SheetOut:
    ws = (await db.execute(text("select id from public.workspaces where user_id = :u order by created_at limit 1"), {"u": uid})).first()
    if ws is None:
        raise err(500, "no_workspace", "Your workspace could not be found.")
    columns: list[dict] = []
    for c in body.columns:
        _check_unique_name(columns, c.name)
        columns.append(_make_column(c))
    row = (
        await db.execute(
            text(
                "insert into public.sheets (workspace_id, user_id, name, description, category, schema_json) "
                "values (:w, :u, :n, :d, :c, CAST(:s AS jsonb)) returning " + SHEET_COLS
            ),
            {"w": ws.id, "u": uid, "n": body.name.strip(), "d": body.description, "c": body.category.strip() or "general",
             "s": json.dumps({"columns": columns})},
        )
    ).one()
    await log_activity(db, uid, "sheet.create", row.id, {"name": row.name})
    return sheet_out(row, 0)


async def get_sheet(db: AsyncSession, uid: str, sheet_id: Any) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id)
    return sheet_out(row, await count_records(db, sheet_id))


async def update_sheet(db: AsyncSession, uid: str, sheet_id: Any, body: SheetUpdate) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    fields = body.model_dump(exclude_unset=True)
    name = (fields.get("name") or row.name).strip()
    row = (
        await db.execute(
            text("update public.sheets set name = :n, description = :d, category = :c where id = :id returning " + SHEET_COLS),
            {"n": name, "d": fields.get("description", row.description), "c": (fields.get("category") or row.category), "id": str(sheet_id)},
        )
    ).one()
    await log_activity(db, uid, "sheet.update", sheet_id, {"fields": list(fields)})
    return sheet_out(row, await count_records(db, sheet_id))


async def trash_sheet(db: AsyncSession, uid: str, sheet_id: Any) -> None:
    await get_sheet_row(db, uid, sheet_id)
    await db.execute(text("update public.sheets set deleted_at = now() where id = :id"), {"id": str(sheet_id)})
    await log_activity(db, uid, "sheet.trash", sheet_id)


async def restore_sheet(db: AsyncSession, uid: str, sheet_id: Any) -> SheetOut:
    await get_sheet_row(db, uid, sheet_id, state="deleted")
    await db.execute(text("update public.sheets set deleted_at = null where id = :id"), {"id": str(sheet_id)})
    await log_activity(db, uid, "sheet.restore", sheet_id)
    return await get_sheet(db, uid, sheet_id)


async def purge_sheet(db: AsyncSession, uid: str, sheet_id: Any) -> None:
    await get_sheet_row(db, uid, sheet_id, state="deleted")
    await db.execute(text("delete from public.sheets where id = :id and user_id = :u"), {"id": str(sheet_id), "u": uid})
    await log_activity(db, uid, "sheet.purge", None, {"sheet_id": str(sheet_id)})


async def duplicate_sheet(db: AsyncSession, uid: str, sheet_id: Any) -> SheetOut:
    src = await get_sheet_row(db, uid, sheet_id)
    new = (
        await db.execute(
            text(
                "insert into public.sheets (workspace_id, user_id, name, description, category, schema_json, template_key) "
                "select workspace_id, user_id, left(name, 105) || ' (copy)', description, category, schema_json, template_key "
                "from public.sheets where id = :id returning " + SHEET_COLS
            ),
            {"id": str(sheet_id)},
        )
    ).one()
    await db.execute(
        text(
            "insert into public.records (sheet_id, user_id, data_json, source_type, source_url, position, ai_meta) "
            "select :n, user_id, data_json, source_type, source_url, position, ai_meta "
            "from public.records where sheet_id = :o and deleted_at is null order by created_at, position nulls last, id"
        ),
        {"n": str(new.id), "o": str(src.id)},
    )
    await log_activity(db, uid, "sheet.duplicate", new.id, {"from": str(src.id)})
    return sheet_out(new, await count_records(db, new.id))


# ---------- columns ----------
async def add_column(db: AsyncSession, uid: str, sheet_id: Any, body: ColumnIn) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    columns = columns_of(row)
    if len(columns) >= 100:
        raise err(422, "too_many_columns", "A sheet can have at most 100 columns.")
    _check_unique_name(columns, body.name)
    columns.append(_make_column(body))
    await _save_schema(db, sheet_id, columns)
    await log_activity(db, uid, "column.add", sheet_id, {"name": body.name, "type": body.type})
    return await get_sheet(db, uid, sheet_id)


async def update_column(db: AsyncSession, uid: str, sheet_id: Any, col_id: str, body: ColumnUpdate) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    columns = columns_of(row)
    col = next((c for c in columns if c["id"] == col_id), None)
    if col is None:
        raise err(404, "column_not_found", "That column doesn't exist.")
    fields = body.model_dump(exclude_unset=True)
    if body.name is not None:
        _check_unique_name(columns, body.name, ignore_id=col_id)
        col["name"] = body.name.strip()
    if "options" in fields:
        opts = [o.strip() for o in (body.options or []) if o.strip()]
        col["options"] = opts or None
        if not opts:
            col.pop("options", None)
    if body.type is not None and body.type != col["type"]:
        await _convert_column_data(db, sheet_id, col_id, body.type, body.force)
        col["type"] = body.type
        if body.type != "status":
            col.pop("options", None)
    await _save_schema(db, sheet_id, columns)
    await log_activity(db, uid, "column.update", sheet_id, {"column": col_id, "fields": [k for k in fields if k != "force"]})
    return await get_sheet(db, uid, sheet_id)


async def _convert_column_data(db: AsyncSession, sheet_id: Any, col_id: str, new_type: str, force: bool) -> None:
    rows = (
        await db.execute(
            text("select id, CAST(data_json -> :k AS text) as v from public.records where sheet_id = :s and jsonb_exists(data_json, :k)"),
            {"k": col_id, "s": str(sheet_id)},
        )
    ).all()
    converted: list[tuple[Any, Any]] = []
    failed = 0
    for r in rows:
        v = jload(r.v)
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        try:
            converted.append((r.id, coerce_value(new_type, v)))
        except ValueError_:
            failed += 1
            converted.append((r.id, None))
    if failed and not force:
        raise err(409, "conversion_loses_data", f"{failed} value(s) can't be converted to {new_type} and would be cleared.", failed=failed)
    sets = [{"id": str(i), "k": col_id, "v": json.dumps(v)} for i, v in converted if v is not None]
    clears = [{"id": str(i), "k": col_id} for i, v in converted if v is None]
    if sets:
        await db.execute(
            text("update public.records set data_json = jsonb_set(data_json, ARRAY[CAST(:k AS text)], CAST(:v AS jsonb)) where id = :id"), sets
        )
    if clears:
        await db.execute(text("update public.records set data_json = data_json - CAST(:k AS text) where id = :id"), clears)


async def delete_column(db: AsyncSession, uid: str, sheet_id: Any, col_id: str) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    columns = columns_of(row)
    if not any(c["id"] == col_id for c in columns):
        raise err(404, "column_not_found", "That column doesn't exist.")
    await _save_schema(db, sheet_id, [c for c in columns if c["id"] != col_id])
    await db.execute(
        text("update public.records set data_json = data_json - CAST(:k AS text) where sheet_id = :s"), {"k": col_id, "s": str(sheet_id)}
    )
    await log_activity(db, uid, "column.delete", sheet_id, {"column": col_id})
    return await get_sheet(db, uid, sheet_id)


async def reorder_columns(db: AsyncSession, uid: str, sheet_id: Any, ids: list[str]) -> SheetOut:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    columns = columns_of(row)
    if sorted(ids) != sorted(c["id"] for c in columns):
        raise err(422, "bad_order", "The column order must list every column exactly once.")
    by_id = {c["id"]: c for c in columns}
    await _save_schema(db, sheet_id, [by_id[i] for i in ids])
    return await get_sheet(db, uid, sheet_id)


def has_value(v: Any) -> bool:
    return not is_empty(v)
