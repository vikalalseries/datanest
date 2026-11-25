"""Global search across the user's sheets and records, with category / status / date filters."""
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.record_service import _like
from app.services.sheet_service import err, jload
from app.utils.validators import is_empty

MAX_Q = 200


def _iso(v: str | None, label: str) -> str | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise err(422, "bad_date", f"“{label}” must be a date like 2026-11-30.")


async def search(
    db: AsyncSession, uid: str, *, q: str | None, category: str | None, status: str | None,
    date_from: str | None, date_to: str | None, limit: int, offset: int,
) -> dict:
    q = (q or "").strip()[:MAX_Q]
    category = (category or "").strip() or None
    status = (status or "").strip() or None
    d_from, d_to = _iso(date_from, "From"), _iso(date_to, "To")
    if d_from and d_to and d_from > d_to:
        raise err(422, "bad_date", "The “From” date must be before the “To” date.")
    if not (q or category or status or d_from or d_to):
        raise err(422, "empty_search", "Type something to search for, or choose a filter.")

    params: dict[str, Any] = {"u": uid}
    # ---- sheets (name match only makes sense for text queries; status/date filters apply to rows)
    sheets: list[dict] = []
    if q and not status and not d_from and not d_to:
        sp: dict[str, Any] = {"u": uid, "q": _like(q)}
        cat_sql = ""
        if category:
            cat_sql, sp["cat"] = " and s.category = :cat", category
        rows = (
            await db.execute(
                text(
                    "select s.id, s.name, s.category, s.description, "
                    "(select count(*) from public.records r where r.sheet_id = s.id and r.deleted_at is null) as rc "
                    "from public.sheets s where s.user_id = :u and s.deleted_at is null and "
                    f"(s.name ilike :q escape '\\' or coalesce(s.description, '') ilike :q escape '\\'){cat_sql} order by s.updated_at desc limit 10"
                ),
                sp,
            )
        ).all()
        sheets = [{"id": str(r.id), "name": r.name, "category": r.category, "description": r.description, "record_count": r.rc} for r in rows]

    # ---- records
    where = ["r.user_id = :u", "r.deleted_at is null", "s.deleted_at is null"]
    if q:
        where.append("lower(r.data_json::text) like lower(:rq) escape '\\'")
        params["rq"] = _like(q)
    if category:
        where.append("s.category = :cat")
        params["cat"] = category
    if status:
        where.append(
            "exists (select 1 from jsonb_array_elements(s.schema_json -> 'columns') c "
            "where c ->> 'type' = 'status' and lower(r.data_json ->> (c ->> 'id')) = lower(:st))"
        )
        params["st"] = status
    if d_from or d_to:
        cond = []
        if d_from:
            cond.append("(r.data_json ->> (c ->> 'id')) >= :df")
            params["df"] = d_from
        if d_to:
            cond.append("(r.data_json ->> (c ->> 'id')) <= :dt")
            params["dt"] = d_to
        where.append(
            "exists (select 1 from jsonb_array_elements(s.schema_json -> 'columns') c "
            "where c ->> 'type' = 'date' and (r.data_json ->> (c ->> 'id')) ~ '^\\d{4}-\\d{2}-\\d{2}$' and " + " and ".join(cond) + ")"
        )
    base = "from public.records r join public.sheets s on s.id = r.sheet_id where " + " and ".join(where)
    total = (await db.execute(text(f"select count(*) {base}"), params)).scalar_one()
    rows = (
        await db.execute(
            text(f"select r.id, r.sheet_id, r.data_json, r.updated_at, s.name as sheet_name, s.category, s.schema_json {base} order by r.updated_at desc, r.id limit :lim offset :off"),
            {**params, "lim": limit, "off": offset},
        )
    ).all()
    records = []
    for r in rows:
        names = {c["id"]: c["name"] for c in jload(r.schema_json).get("columns", [])}
        data = {names.get(k, k): v for k, v in jload(r.data_json).items() if not is_empty(v)}
        records.append({"id": str(r.id), "sheet_id": str(r.sheet_id), "sheet_name": r.sheet_name, "category": r.category, "data": data, "updated_at": r.updated_at.isoformat()})
    return {"query": q, "sheets": sheets, "records": records, "total": total, "limit": limit, "offset": offset}


async def facets(db: AsyncSession, uid: str) -> dict:
    cats = (await db.execute(text("select category, count(*) as n from public.sheets where user_id = :u and deleted_at is null group by category order by n desc"), {"u": uid})).all()
    sts = (
        await db.execute(
            text(
                "select lower(v) as v, count(*) as n from ("
                " select r.data_json ->> (c ->> 'id') as v from public.records r join public.sheets s on s.id = r.sheet_id "
                " cross join lateral jsonb_array_elements(s.schema_json -> 'columns') c "
                " where r.user_id = :u and r.deleted_at is null and s.deleted_at is null and c ->> 'type' = 'status') t "
                "where v is not null and v <> '' group by lower(v) order by n desc limit 40"
            ),
            {"u": uid},
        )
    ).all()
    return {"categories": [{"value": c.category, "count": c.n} for c in cats], "statuses": [{"value": s.v, "count": s.n} for s in sts]}
