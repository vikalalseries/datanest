import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.schemas import MoveRecords, RecordOut, RecordPage
from app.services.sheet_service import (
    _make_column, _save_schema, columns_of, err, get_sheet_row, jload, log_activity,
)
from app.database.schemas import ColumnIn
from app.utils.validators import ValueError_, coerce_value, is_empty, validate_record_data

REC_COLS = "r.id, r.sheet_id, r.data_json, r.source_type, r.source_url, r.source_file_id, r.created_at, r.updated_at, r.deleted_at"
OPS = {"contains", "eq", "neq", "gt", "gte", "lt", "lte", "empty", "notempty"}
SORT_META = {"created_at", "updated_at"}


def record_out(row: Any, sheet_name: str | None = None, data: dict | None = None) -> RecordOut:
    return RecordOut(
        id=row.id, sheet_id=row.sheet_id, data=data if data is not None else jload(row.data_json),
        source_type=row.source_type, source_url=row.source_url, source_file_id=getattr(row, 'source_file_id', None), created_at=row.created_at,
        updated_at=row.updated_at, deleted_at=row.deleted_at, sheet_name=sheet_name,
    )


def _like(v: str) -> str:
    return "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _col_expr(col: dict, key: str) -> str:
    base = f"(r.data_json ->> :{key})"
    if col["type"] in ("number", "currency"):
        return f"CAST({base} AS numeric)"
    if col["type"] == "boolean":
        return f"CAST({base} AS boolean)"
    return base


def _build_where(columns: list[dict], q: str | None, filters: list[dict]) -> tuple[str, dict]:
    by_id = {c["id"]: c for c in columns}
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if q and q.strip():
        clauses.append("lower(r.data_json::text) like lower(:q) escape '\\'")
        params["q"] = _like(q.strip())
    for i, f in enumerate(filters):
        col = by_id.get(f.get("column"))
        op = f.get("op")
        if col is None or op not in OPS:
            raise err(422, "bad_filter", "One of the filters refers to a column or operator that doesn't exist.")
        k, v = f"fk{i}", f"fv{i}"
        params[k] = col["id"]
        raw = f"(r.data_json ->> :{k})"
        if op == "empty":
            clauses.append(f"({raw} is null or {raw} = '' or {raw} = '[]')")
            continue
        if op == "notempty":
            clauses.append(f"({raw} is not null and {raw} <> '' and {raw} <> '[]')")
            continue
        try:
            value = coerce_value(col["type"] if op not in ("contains",) else "text", f.get("value"))
        except ValueError_ as e:
            raise err(422, "bad_filter", f"Filter on “{col['name']}”: {e}")
        if value is None:
            raise err(422, "bad_filter", f"Enter a value to filter “{col['name']}” by.")
        expr = _col_expr(col, k)
        if op == "contains":
            clauses.append(f"{raw} ilike :{v} escape '\\'")
            params[v] = _like(str(value))
            continue
        if col["type"] == "tags":
            value = json.dumps(value)
            expr = raw
        if col["type"] in ("number", "currency"):
            ph = f"CAST(:{v} AS numeric)"
        elif col["type"] == "boolean":
            ph = f":{v}"
        else:
            ph = f":{v}"
            if op in ("eq", "neq") and col["type"] in ("text", "status", "email", "url"):
                expr, ph = f"lower({raw})", f"lower(:{v})"
        sql_op = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        clauses.append(f"{expr} {sql_op} {ph}")
        params[v] = value if not isinstance(value, (int, float)) or isinstance(value, bool) else value
    return (" and " + " and ".join(clauses)) if clauses else "", params


async def list_records(
    db: AsyncSession, uid: str, sheet_id: Any, *, q: str | None, sort: str | None, direction: str,
    filters: list[dict], limit: int, offset: int,
) -> RecordPage:
    sheet = await get_sheet_row(db, uid, sheet_id)
    columns = columns_of(sheet)
    where, params = _build_where(columns, q, filters)
    params.update({"s": str(sheet_id), "u": uid})
    base = f"from public.records r where r.sheet_id = :s and r.user_id = :u and r.deleted_at is null{where}"
    order = "r.created_at asc, r.position asc nulls last, r.id"
    if sort:
        d = "desc" if direction == "desc" else "asc"
        if sort in SORT_META:
            order = f"r.{sort} {d}, r.position nulls last, r.id"
        else:
            col = next((c for c in columns if c["id"] == sort), None)
            if col is None:
                raise err(422, "bad_sort", "You can't sort by that column.")
            params["sortk"] = sort
            order = f"{_col_expr(col, 'sortk')} {d} nulls last, r.created_at, r.position nulls last, r.id"
    total = (await db.execute(text(f"select count(*) {base}"), params)).scalar_one()
    rows = (await db.execute(text(f"select {REC_COLS} {base} order by {order} limit :lim offset :off"), {**params, "lim": limit, "off": offset})).all()
    return RecordPage(items=[record_out(r) for r in rows], total=total, limit=limit, offset=offset)


async def all_records(db: AsyncSession, uid: str, q: str | None, limit: int, offset: int) -> RecordPage:
    """Cross-sheet listing. `data` is keyed by column NAME so it is readable without the sheet schema."""
    params: dict[str, Any] = {"u": uid}
    where = ""
    if q and q.strip():
        where = " and lower(r.data_json::text) like lower(:q) escape '\\'"
        params["q"] = _like(q.strip())
    base = f"from public.records r join public.sheets s on s.id = r.sheet_id where r.user_id = :u and r.deleted_at is null and s.deleted_at is null{where}"
    total = (await db.execute(text(f"select count(*) {base}"), params)).scalar_one()
    rows = (
        await db.execute(
            text(f"select {REC_COLS}, s.name as sheet_name, s.schema_json {base} order by r.updated_at desc, r.id limit :lim offset :off"),
            {**params, "lim": limit, "off": offset},
        )
    ).all()
    items = []
    for r in rows:
        names = {c["id"]: c["name"] for c in jload(r.schema_json).get("columns", [])}
        data = {names.get(k, k): v for k, v in jload(r.data_json).items() if not is_empty(v)}
        items.append(record_out(r, r.sheet_name, data))
    return RecordPage(items=items, total=total, limit=limit, offset=offset)


async def _get_record(db: AsyncSession, uid: str, record_id: Any, *, lock: bool = False):
    row = (
        await db.execute(
            text(
                f"select {REC_COLS}, s.schema_json from public.records r join public.sheets s on s.id = r.sheet_id "
                f"where r.id = :id and r.user_id = :u and r.deleted_at is null and s.deleted_at is null" + (" for update of r" if lock else "")
            ),
            {"id": str(record_id), "u": uid},
        )
    ).first()
    if row is None:
        raise err(404, "record_not_found", "That record doesn't exist or you don't have access to it.")
    return row


def _validated(columns: list[dict], data: dict) -> dict:
    try:
        return validate_record_data(columns, data)
    except ValueError_ as e:
        raise err(422, "invalid_value", str(e))


async def create_record(db: AsyncSession, uid: str, sheet_id: Any, data: dict, source_type: str = "manual", source_url: str | None = None) -> RecordOut:
    sheet = await get_sheet_row(db, uid, sheet_id)
    clean = {k: v for k, v in _validated(columns_of(sheet), data).items() if v is not None}
    row = (
        await db.execute(
            text(
                "insert into public.records (sheet_id, user_id, data_json, source_type, source_url) "
                "values (:s, :u, CAST(:d AS jsonb), :st, :su) returning " + REC_COLS.replace("r.", "")
            ),
            {"s": str(sheet_id), "u": uid, "d": json.dumps(clean), "st": source_type, "su": source_url},
        )
    ).one()
    await db.execute(text("update public.sheets set updated_at = now() where id = :s"), {"s": str(sheet_id)})
    await log_activity(db, uid, "record.create", sheet_id, {"record_id": str(row.id), "data": clean})
    return record_out(row)


async def update_record(db: AsyncSession, uid: str, record_id: Any, data: dict) -> RecordOut:
    rec = await _get_record(db, uid, record_id, lock=True)
    clean = _validated(jload(rec.schema_json).get("columns", []), data)
    before_all = jload(rec.data_json)
    setv = {k: v for k, v in clean.items() if v is not None}
    rem = [k for k, v in clean.items() if v is None]
    row = (
        await db.execute(
            text(
                "update public.records set data_json = (data_json || CAST(:s AS jsonb)) - CAST(:r AS text[]) "
                "where id = :id returning " + REC_COLS.replace("r.", "")
            ),
            {"s": json.dumps(setv), "r": rem, "id": str(record_id)},
        )
    ).one()
    await db.execute(text("update public.sheets set updated_at = now() where id = :s"), {"s": str(rec.sheet_id)})
    await log_activity(
        db, uid, "record.update", rec.sheet_id,
        {"record_id": str(record_id), "before": {k: before_all.get(k) for k in clean}, "after": clean},
    )
    return record_out(row)


async def _bulk(db: AsyncSession, uid: str, ids: list[Any], sql: str, action: str) -> int:
    str_ids = [str(i) for i in ids]
    # attribute the action to its sheet when all affected rows live in one sheet (so per-sheet history shows it)
    sheets = (await db.execute(
        text("select distinct sheet_id from public.records where id = ANY(CAST(:ids AS uuid[])) and user_id = :u"), {"ids": str_ids, "u": uid}
    )).all()
    sheet_id = sheets[0].sheet_id if len(sheets) == 1 else None
    res = await db.execute(text(sql), {"ids": str_ids, "u": uid})
    n = res.rowcount
    await log_activity(db, uid, action, sheet_id, {"count": n, "ids": str_ids[:50]})
    return n


async def trash_records(db: AsyncSession, uid: str, ids: list[Any]) -> int:
    return await _bulk(
        db, uid, ids,
        "update public.records set deleted_at = now() where id = ANY(CAST(:ids AS uuid[])) and user_id = :u and deleted_at is null",
        "record.trash",
    )


async def restore_records(db: AsyncSession, uid: str, ids: list[Any]) -> int:
    # records whose sheet is in the trash stay hidden until the sheet is restored
    return await _bulk(
        db, uid, ids,
        "update public.records r set deleted_at = null where r.id = ANY(CAST(:ids AS uuid[])) and r.user_id = :u and r.deleted_at is not null",
        "record.restore",
    )


async def purge_records(db: AsyncSession, uid: str, ids: list[Any]) -> int:
    return await _bulk(
        db, uid, ids,
        "delete from public.records where id = ANY(CAST(:ids AS uuid[])) and user_id = :u and deleted_at is not null",
        "record.purge",
    )


async def move_records(db: AsyncSession, uid: str, body: MoveRecords) -> int:
    target = await get_sheet_row(db, uid, body.target_sheet_id, lock=True)
    t_cols = columns_of(target)
    rows = (
        await db.execute(
            text(
                "select r.id, r.sheet_id, r.data_json, s.schema_json from public.records r join public.sheets s on s.id = r.sheet_id "
                "where r.id = ANY(CAST(:ids AS uuid[])) and r.user_id = :u and r.deleted_at is null and s.deleted_at is null"
            ),
            {"ids": [str(i) for i in body.ids], "u": uid},
        )
    ).all()
    if len(rows) != len(set(body.ids)):
        raise err(404, "record_not_found", "Some of the selected records no longer exist.")
    rows = [r for r in rows if str(r.sheet_id) != str(body.target_sheet_id)]
    if not rows:
        return 0

    # Plan: map each source column that holds data to a target column (by name), never dropping data silently.
    t_by_name = {c["name"].strip().lower(): c for c in t_cols}
    missing: dict[str, dict] = {}
    plans: dict[str, dict[str, dict]] = {}
    for r in rows:
        sid = str(r.sheet_id)
        if sid in plans:
            continue
        mapping: dict[str, dict] = {}
        s_cols = jload(r.schema_json).get("columns", [])
        for sc in s_cols:
            if not any(not is_empty(jload(x.data_json).get(sc["id"])) for x in rows if str(x.sheet_id) == sid):
                continue
            tc = t_by_name.get(sc["name"].strip().lower())
            if tc is None:
                missing[sc["name"].strip().lower()] = sc
            else:
                mapping[sc["id"]] = tc
        plans[sid] = mapping
    if missing and not body.add_missing_columns:
        raise err(
            409, "columns_missing",
            "The target sheet is missing columns that hold data: " + ", ".join(c["name"] for c in missing.values()) + ".",
            missing=[c["name"] for c in missing.values()],
        )
    for sc in missing.values():
        new = _make_column(ColumnIn(name=sc["name"], type=sc["type"], options=sc.get("options")))
        t_cols.append(new)
        t_by_name[new["name"].strip().lower()] = new
    if missing:
        await _save_schema(db, body.target_sheet_id, t_cols)

    updates = []
    for r in rows:
        s_cols = jload(r.schema_json).get("columns", [])
        out: dict[str, Any] = {}
        for sc in s_cols:
            v = jload(r.data_json).get(sc["id"])
            if is_empty(v):
                continue
            tc = t_by_name[sc["name"].strip().lower()]
            try:
                out[tc["id"]] = coerce_value(tc["type"], ", ".join(v) if isinstance(v, list) and tc["type"] != "tags" else v)
            except ValueError_:
                raise err(409, "type_mismatch", f"“{sc['name']}” has values that don't fit the target column type ({tc['type']}).")
        updates.append({"id": str(r.id), "t": str(body.target_sheet_id), "d": json.dumps(out)})
    await db.execute(text("update public.records set sheet_id = :t, data_json = CAST(:d AS jsonb) where id = :id"), updates)
    await db.execute(text("update public.sheets set updated_at = now() where id = :s"), {"s": str(body.target_sheet_id)})
    await log_activity(db, uid, "record.move", body.target_sheet_id, {"count": len(updates)})
    return len(updates)


async def create_sheet_from_extraction(db: AsyncSession, uid: str, body) -> "SheetOut":
    """Create a sheet from a confirmed extraction and insert all rows atomically (same request transaction)."""
    from app.database.schemas import SheetCreate
    from app.services import sheet_service

    sheet = await sheet_service.create_sheet(
        db, uid, SheetCreate(name=body.name, description=body.description, category=body.category, columns=body.columns)
    )
    by_name = {c.name.strip().lower(): c.id for c in sheet.columns}
    rows: list[dict] = []
    problems: list[str] = []
    for i, r in enumerate(body.records, start=1):
        data: dict[str, Any] = {}
        for name, val in r.values.items():
            cid = by_name.get(name.strip().lower())
            if cid is None:
                problems.append(f"Row {i}: unknown column “{name[:40]}”.")
                continue
            data[cid] = val
        try:
            clean = {k: v for k, v in validate_record_data([c.model_dump() for c in sheet.columns], data).items() if v is not None}
        except ValueError_ as e:
            problems.append(f"Row {i}: {e}")
            continue
        rows.append({"s": str(sheet.id), "u": uid, "d": json.dumps(clean), "st": body.source_type, "su": body.source_url, "p": float(len(rows)),
                     "f": str(body.source_file_id) if body.source_file_id else None})
    if problems:
        # roll the whole request back (sheet included) so nothing half-saved remains
        raise err(422, "invalid_value", " ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
    if rows:
        await db.execute(
            text(
                "insert into public.records (sheet_id, user_id, data_json, source_type, source_url, source_file_id, position) "
                "values (:s, :u, CAST(:d AS jsonb), :st, :su, CAST(:f AS uuid), :p)"
            ),
            rows,
        )
    await log_activity(db, uid, "sheet.from_extraction", sheet.id, {"records": len(rows), "source": body.source_type})
    return await sheet_service.get_sheet(db, uid, sheet.id)
