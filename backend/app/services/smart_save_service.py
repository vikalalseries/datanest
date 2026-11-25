"""Phase 4: decide where extracted data goes, and save it into an existing sheet without silent data loss."""
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.schemas import (
    BulkAddRequest, ColumnIn, DuplicateCheckRequest, ExtractionIn, MatchRequest, MergeRequest, MoveRecords,
)
from app.services import matching_service as m
from app.services import record_service, sheet_service
from app.services.sheet_service import _make_column, _save_schema, columns_of, err, get_sheet_row, jload, log_activity
from app.utils.validators import ValueError_, is_empty, validate_record_data

log = logging.getLogger("datanest.smartsave")


def _ecols(ex: ExtractionIn) -> list[dict]:
    return [c.model_dump() for c in ex.columns]


def _erecs(ex: ExtractionIn) -> list[dict]:
    return [r.model_dump() for r in ex.records]


async def rank_sheets(db: AsyncSession, uid: str, ex: ExtractionIn) -> list[dict]:
    """Rank the user's sheets by how well the extraction fits them (deterministic, no AI call)."""
    ecols, recs = _ecols(ex), _erecs(ex)
    with_data = m.columns_with_data(ecols, recs)
    out = []
    for s in await sheet_service.list_sheets(db, uid, None):
        scols = [c.model_dump() for c in s.columns]
        maps = m.deterministic_match(ecols, scols)
        sm = m.summarize(ecols, recs, s.name, s.category, ex.category, maps, scols)
        score_ = sm["match_ratio"] + (0.15 if sm["category_match"] else 0)
        out.append({
            "sheet_id": str(s.id), "name": s.name, "category": s.category, "record_count": s.record_count,
            "column_names": [c["name"] for c in scols][:12], "match_ratio": sm["match_ratio"], "matched": sm["matched"],
            "total": len(with_data), "category_match": sm["category_match"], "score": round(score_, 3),
        })
    out.sort(key=lambda x: (-x["score"], -x["record_count"]))
    return out[:30]


async def match_sheet(db: AsyncSession, uid: str, req: MatchRequest) -> dict:
    from app.services.sheet_service import get_sheet_row as _get

    row = await _get(db, uid, req.sheet_id)
    scols = columns_of(row)
    ecols, recs = _ecols(req.extraction), _erecs(req.extraction)
    mappings = m.deterministic_match(ecols, scols)
    notes: list[str] = []

    if req.use_ai:
        with_data = m.columns_with_data(ecols, recs)
        left_e = [c for c in ecols if c["name"] in with_data and not next(x for x in mappings if x.extracted == c["name"]).sheet_column_id]
        used = {x.sheet_column_id for x in mappings if x.sheet_column_id}
        left_s = [c for c in scols if c["id"] not in used]
        if left_e and left_s:
            try:
                samples = (
                    await db.execute(
                        text("select data_json from public.records where sheet_id = :s and deleted_at is null order by created_at desc limit 3"),
                        {"s": str(req.sheet_id)},
                    )
                ).all()
                for c in left_s:
                    c["_examples"] = [jload(r.data_json).get(c["id"]) for r in samples if not is_empty(jload(r.data_json).get(c["id"]))]
                ai = await m.ai_match_leftovers(left_e, recs, left_s, [])
                by_id = {c["id"]: c for c in scols}
                for mp in mappings:
                    if mp.extracted in ai:
                        cid, conf = ai[mp.extracted]
                        mp.sheet_column_id, mp.sheet_column_name, mp.confidence, mp.method = cid, by_id[cid]["name"], conf, "ai"
            except Exception as e:  # AI problems must never block saving: fall back to the deterministic result
                log.warning("ai column matching unavailable: %s", type(e).__name__)
                notes.append("AI matching was unavailable, so only simple name matching was used. Please check the mapping.")

    summary = m.summarize(ecols, recs, row.name, row.category, ex_cat(req), mappings, scols)
    return {
        "sheet": {"id": str(row.id), "name": row.name, "category": row.category, "columns": scols},
        "mappings": [x.model_dump() for x in mappings], "notes": notes, **summary,
    }


def ex_cat(req: MatchRequest) -> str:
    return req.extraction.category


async def suggest_sheet(db: AsyncSession, uid: str, ex: ExtractionIn) -> dict:
    existing = await sheet_service.list_sheets(db, uid, None)
    names = {s.name.strip().lower() for s in existing}
    ecols, recs = _ecols(ex), _erecs(ex)
    base = (ex.category.replace("_", " ").title() if ex.category and ex.category != "general" else "New sheet")
    name, n = base, 2
    while name.lower() in names:
        name, n = f"{base} {n}", n + 1
    cols = []
    for c in ecols:
        spec: dict[str, Any] = {"name": c["name"], "type": c["type"]}
        if c["type"] == "status":
            vals = list(dict.fromkeys(str(r["values"][c["name"]]).strip() for r in recs if not is_empty(r["values"].get(c["name"]))))
            if vals:
                spec["options"] = vals[:8]
        cols.append(spec)
    similar = [r for r in await rank_sheets(db, uid, ex) if r["match_ratio"] >= 0.5][:3]
    return {"name": name, "category": ex.category or "general", "columns": cols, "similar_sheets": similar}


# ---------- applying a mapping ----------
def _validate_mapping(body_columns: list, mapping: dict, records: list, sheet_cols: list[dict]) -> None:
    names = {c.name for c in body_columns}
    unknown = [k for k in mapping if k not in names]
    if unknown:
        raise err(422, "bad_mapping", "The mapping refers to fields that don't exist: " + ", ".join(unknown[:5]))
    with_data = m.columns_with_data([c.model_dump() for c in body_columns], [r.model_dump() for r in records])
    missing = sorted(n for n in with_data if n not in mapping)
    if missing:
        raise err(422, "mapping_incomplete", "Choose what to do with: " + ", ".join(missing) + ". Nothing is skipped unless you say so.", missing=missing)
    ids = {c["id"] for c in sheet_cols}
    targets: list[str] = []
    for name, act in mapping.items():
        if act.action == "map":
            if act.column_id not in ids:
                raise err(422, "bad_mapping", f"“{name}” is mapped to a column that doesn't exist.")
            targets.append(act.column_id)
    if len(targets) != len(set(targets)):
        raise err(409, "duplicate_mapping", "Two fields are mapped to the same column. Map each field to a different column.")


async def bulk_add(db: AsyncSession, uid: str, sheet_id: Any, body: BulkAddRequest) -> dict:
    row = await get_sheet_row(db, uid, sheet_id, lock=True)
    columns = columns_of(row)
    _validate_mapping(body.columns, body.mapping, body.records, columns)

    etypes = {c.name: c.type for c in body.columns}
    created: dict[str, str] = {}
    new_cols = []
    low = {c["name"].strip().lower() for c in columns}
    for name, act in body.mapping.items():
        if act.action != "create":
            continue
        if name.strip().lower() in low:
            raise err(409, "duplicate_column", f"A column named “{name}” already exists. Map the field to it instead of creating a new one.")
        new_cols.append(_make_column(ColumnIn(name=name, type=act.type or etypes.get(name, "text"))))
        low.add(name.strip().lower())
        created[name] = new_cols[-1]["id"]
    if len(columns) + len(new_cols) > 100:
        raise err(422, "too_many_columns", "A sheet can have at most 100 columns.")
    if new_cols:
        columns = columns + new_cols
        await _save_schema(db, sheet_id, columns)

    col_dicts = columns
    rows, problems = [], []
    for i, r in enumerate(body.records, start=1):
        data: dict[str, Any] = {}
        for name, val in r.values.items():
            if is_empty(val):
                continue
            act = body.mapping[name]
            if act.action == "map":
                data[act.column_id] = val
            elif act.action == "create":
                data[created[name]] = val
        try:
            clean = {k: v for k, v in validate_record_data(col_dicts, data).items() if v is not None}
        except ValueError_ as e:
            problems.append(f"Row {i}: {e}")
            continue
        rows.append({"s": str(sheet_id), "u": uid, "d": json.dumps(clean), "st": body.source_type, "su": body.source_url, "p": float(len(rows)),
                     "f": str(body.source_file_id) if body.source_file_id else None})
    if problems:  # raising rolls back the whole request, including any new columns
        raise err(422, "invalid_value", " ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
    await db.execute(
        text(
            "insert into public.records (sheet_id, user_id, data_json, source_type, source_url, source_file_id, position) "
            "values (:s, :u, CAST(:d AS jsonb), :st, :su, CAST(:f AS uuid), :p)"
        ),
        rows,
    )
    await db.execute(text("update public.sheets set updated_at = now() where id = :s"), {"s": str(sheet_id)})
    skipped = sorted(n for n, a in body.mapping.items() if a.action == "skip")
    await log_activity(db, uid, "records.bulk_add", sheet_id, {"added": len(rows), "created_columns": list(created), "skipped_fields": skipped, "source": body.source_type})
    return {"added": len(rows), "sheet": (await sheet_service.get_sheet(db, uid, sheet_id)).model_dump(mode="json")}


async def check_duplicates(db: AsyncSession, uid: str, sheet_id: Any, body: DuplicateCheckRequest) -> dict:
    row = await get_sheet_row(db, uid, sheet_id)
    columns = columns_of(row)
    by_id = {c["id"]: c for c in columns}
    incoming: list[dict] = []
    for r in body.records:
        data: dict[str, Any] = {}
        for name, val in r.values.items():
            act = body.mapping.get(name)
            if act and act.action == "map" and act.column_id in by_id and not is_empty(val):
                data[act.column_id] = val
        incoming.append(data)
    existing = (
        await db.execute(
            text("select id, data_json from public.records where sheet_id = :s and user_id = :u and deleted_at is null order by created_at desc limit 5000"),
            {"s": str(sheet_id), "u": uid},
        )
    ).all()
    existing_data = [(str(e.id), jload(e.data_json)) for e in existing]
    names = {c["id"]: c["name"] for c in columns}
    vs_existing, within = [], []
    for i, data in enumerate(incoming):
        if not data:
            continue
        best = []
        for rid, edata in existing_data:
            sim, matched = m.compare_rows(by_id, data, edata)
            if sim:
                best.append((sim, rid, matched, edata))
        best.sort(key=lambda x: -x[0])
        if best:
            sim, rid, matched, edata = best[0]
            vs_existing.append({
                "row": i, "existing_record_id": rid, "similarity": sim, "matched_columns": matched,
                "existing": {names[k]: v for k, v in edata.items() if k in names and not is_empty(v)},
            })
    if len(incoming) <= 300:
        for i in range(len(incoming)):
            for j in range(i):
                if incoming[i] and incoming[j]:
                    sim, matched = m.compare_rows(by_id, incoming[i], incoming[j])
                    if sim:
                        within.append({"row": i, "duplicate_of_row": j, "similarity": sim})
                        break
    return {"duplicates": vs_existing, "within_batch": within}


async def merge_sheets(db: AsyncSession, uid: str, target_id: Any, body: MergeRequest) -> dict:
    if str(body.source_sheet_id) == str(target_id):
        raise err(422, "same_sheet", "Choose a different sheet to merge in.")
    target = await get_sheet_row(db, uid, target_id, lock=True)
    source = await get_sheet_row(db, uid, body.source_sheet_id)
    t_cols, s_cols = columns_of(target), columns_of(source)
    have = {c["name"].strip().lower() for c in t_cols}
    missing = [c for c in s_cols if c["name"].strip().lower() not in have]
    if missing and not body.add_missing_columns:
        raise err(
            409, "columns_missing",
            "These sheets aren't fully compatible. The target has no column for: " + ", ".join(c["name"] for c in missing) + ".",
            missing=[c["name"] for c in missing],
        )
    if len(t_cols) + len(missing) > 100:
        raise err(422, "too_many_columns", "The merged sheet would have more than 100 columns.")
    if missing:
        for c in missing:
            t_cols.append(_make_column(ColumnIn(name=c["name"], type=c["type"], options=c.get("options"))))
        await _save_schema(db, target_id, t_cols)
    ids = [
        str(r.id) for r in (
            await db.execute(
                text("select id from public.records where sheet_id = :s and user_id = :u and deleted_at is null order by created_at, position nulls last, id"),
                {"s": str(body.source_sheet_id), "u": uid},
            )
        ).all()
    ]
    moved = 0
    for i in range(0, len(ids), 500):
        moved += await record_service.move_records(db, uid, MoveRecords(ids=ids[i:i + 500], target_sheet_id=target_id, add_missing_columns=True))
    if body.trash_source:
        await sheet_service.trash_sheet(db, uid, body.source_sheet_id)
    await log_activity(db, uid, "sheet.merge", target_id, {"source": str(body.source_sheet_id), "moved": moved, "trashed_source": body.trash_source})
    return {"moved": moved, "sheet": (await sheet_service.get_sheet(db, uid, target_id)).model_dump(mode="json")}
