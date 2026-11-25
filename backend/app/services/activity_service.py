"""Readable activity history, and undo for the actions where undoing is safe and unambiguous."""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import record_service, sheet_service
from app.services.sheet_service import err, jload, log_activity
from app.utils.validators import is_empty

UNDOABLE = {"record.update", "record.create", "record.trash", "sheet.trash"}

LABELS = {
    "sheet.create": "Created sheet", "sheet.update": "Updated sheet", "sheet.trash": "Moved sheet to Trash", "sheet.restore": "Restored sheet",
    "sheet.duplicate": "Duplicated sheet", "sheet.purge": "Permanently deleted a sheet", "sheet.from_extraction": "Created sheet from AI extraction",
    "sheet.from_template": "Created sheet from a template", "sheet.import": "Imported a file into", "sheet.merge": "Merged another sheet into",
    "column.add": "Added a column to", "column.update": "Edited a column in", "column.delete": "Removed a column from",
    "record.create": "Added a row to", "record.update": "Edited a row in", "record.trash": "Moved rows to Trash", "record.restore": "Restored rows",
    "record.purge": "Permanently deleted rows", "record.move": "Moved rows into", "records.bulk_add": "Added extracted rows to",
    "export.sheet": "Exported", "export.workspace": "Exported all sheets", "assistant.create_sheet": "Assistant created sheet (confirmed)",
    "assistant.add_records": "Assistant added rows (confirmed) to", "activity.undo": "Undid an action",
}


def _fmt(v: Any) -> str:
    if is_empty(v):
        return "(empty)"
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)[:120]


def describe(action: str, details: dict, sheet_name: str | None, names: dict[str, str]) -> tuple[str, list[dict]]:
    label = LABELS.get(action, action.replace(".", " ").replace("_", " ").capitalize())
    where = f" “{sheet_name}”" if sheet_name else ""
    changes: list[dict] = []
    extra = ""
    if action == "record.update":
        before, after = details.get("before") or {}, details.get("after") or {}
        for cid in after:
            changes.append({"column": names.get(cid, cid), "before": _fmt(before.get(cid)), "after": _fmt(after.get(cid))})
    elif action in ("records.bulk_add", "sheet.from_extraction", "sheet.import", "assistant.add_records"):
        n = details.get("added", details.get("records", details.get("rows")))
        extra = f" ({n} row{'s' if n != 1 else ''})" if isinstance(n, int) else ""
    elif action in ("record.trash", "record.restore", "record.purge", "record.move"):
        n = details.get("count")
        extra = f" ({n})" if isinstance(n, int) else ""
    elif action == "export.sheet":
        extra = f" as {details.get('format', 'file').upper()}"
    return f"{label}{where}{extra}", changes


async def list_activity(db: AsyncSession, uid: str, sheet_id: Any | None, limit: int, offset: int) -> dict:
    params: dict[str, Any] = {"u": uid}
    cond = "a.user_id = :u"
    if sheet_id:
        cond += " and a.sheet_id = :s"
        params["s"] = str(sheet_id)
    total = (await db.execute(text(f"select count(*) from public.activity_logs a where {cond}"), params)).scalar_one()
    rows = (
        await db.execute(
            text(
                f"select a.id, a.action, a.sheet_id, a.details_json, a.created_at, s.name as sheet_name, s.schema_json, s.deleted_at as sheet_deleted "
                f"from public.activity_logs a left join public.sheets s on s.id = a.sheet_id where {cond} order by a.created_at desc, a.id limit :lim offset :off"
            ),
            {**params, "lim": limit, "off": offset},
        )
    ).all()
    undone = {
        r.of for r in (
            await db.execute(text("select details_json ->> 'of' as of from public.activity_logs where user_id = :u and action = 'activity.undo'"), {"u": uid})
        ).all() if r.of
    }
    items = []
    for r in rows:
        d = jload(r.details_json) or {}
        names = {c["id"]: c["name"] for c in (jload(r.schema_json).get("columns", []) if r.schema_json else [])}
        summary, changes = describe(r.action, d, r.sheet_name, names)
        was_undone = str(r.id) in undone
        can = r.action in UNDOABLE and not was_undone
        if r.action == "record.trash" and (not d.get("ids") or d.get("count") != len(d.get("ids", []))):
            can = False  # too many rows were logged to restore them all reliably
        if r.action == "sheet.trash" and r.sheet_name is None:
            can = False
        items.append({
            "id": str(r.id), "action": r.action, "summary": summary, "changes": changes, "sheet_id": str(r.sheet_id) if r.sheet_id else None,
            "sheet_name": r.sheet_name, "created_at": r.created_at.isoformat(), "undoable": can, "undone": was_undone,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def undo(db: AsyncSession, uid: str, log_id: Any) -> dict:
    row = (
        await db.execute(
            text("select id, action, sheet_id, details_json from public.activity_logs where id = :id and user_id = :u"), {"id": str(log_id), "u": uid}
        )
    ).first()
    if row is None:
        raise err(404, "activity_not_found", "That activity entry doesn't exist.")
    if row.action not in UNDOABLE:
        raise err(422, "not_undoable", "This kind of action can't be undone automatically.")
    already = (
        await db.execute(
            text("select 1 from public.activity_logs where user_id = :u and action = 'activity.undo' and details_json ->> 'of' = :id limit 1"), {"u": uid, "id": str(log_id)}
        )
    ).first()
    if already:
        raise err(409, "already_undone", "That action has already been undone.")
    d = jload(row.details_json) or {}

    if row.action == "record.update":
        rid, before, after = d.get("record_id"), d.get("before") or {}, d.get("after") or {}
        cur = (await db.execute(text("select data_json from public.records r where r.id = :id and r.user_id = :u and r.deleted_at is null"), {"id": rid, "u": uid})).first()
        if cur is None:
            raise err(409, "record_gone", "That row no longer exists, so the edit can't be undone.")
        now = jload(cur.data_json)
        if any(now.get(k) != v for k, v in after.items() if not (v is None and k not in now)):
            raise err(409, "changed_since", "This row was edited again after that change, so undoing it would overwrite newer edits. Edit it directly instead.")
        await record_service.update_record(db, uid, rid, {k: before.get(k) for k in after})
        msg = "Edit undone."
    elif row.action == "record.create":
        n = await record_service.trash_records(db, uid, [d.get("record_id")])
        if n == 0:
            raise err(409, "record_gone", "That row was already removed.")
        msg = "The added row was moved to Trash."
    elif row.action == "record.trash":
        ids = d.get("ids") or []
        if not ids or d.get("count") != len(ids):
            raise err(422, "not_undoable", "Too many rows were deleted at once to restore them automatically. Use Trash instead.")
        n = await record_service.restore_records(db, uid, ids)
        if n == 0:
            raise err(409, "nothing_to_restore", "Those rows aren't in Trash any more.")
        msg = f"Restored {n} row{'s' if n != 1 else ''}."
    else:  # sheet.trash
        await sheet_service.restore_sheet(db, uid, row.sheet_id)
        msg = "Sheet restored."
    await log_activity(db, uid, "activity.undo", row.sheet_id, {"of": str(log_id), "action": row.action})
    return {"message": msg}
