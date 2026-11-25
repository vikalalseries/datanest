"""In-app notifications, computed on demand from the user's own data (no extra tables, nothing to get stale)."""
import hashlib
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import analytics_service as an
from app.services import sheet_service
from app.services.sheet_service import jload
from app.utils.validators import is_empty

SOON_DAYS = 7
OVERDUE_DAYS = 30
STALE_AFTER_DAYS = 14
STALE_UNTIL_DAYS = 120
MAX_ITEMS = 50
ROWS_PER_SHEET = 5000
_DEADLINE = re.compile(r"deadline|due|closing|last date|submission|expires?|follow-?up", re.I)
_DONE = ("done", "complete", "submitted", "graded", "closed", "accepted", "offer", "reject", "withdr", "cancel", "paid", "customer", "lost", "finished")


def _title(columns: list[dict], row: dict) -> str:
    for pat in (r"company|employer|organi[sz]ation", r"^(task|title|name|item|assignment|subject)$", r"name|title|task|item"):
        for c in columns:
            if c["type"] in ("text", "status") and re.search(pat, c["name"], re.I) and not is_empty(row.get(c["id"])):
                return str(row[c["id"]])[:60]
    for c in columns:
        if c["type"] == "text" and not is_empty(row.get(c["id"])):
            return str(row[c["id"]])[:60]
    return "A row"


def _parse(v: Any) -> date | None:
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _nid(kind: str, rid: str, col: str = "") -> str:
    return hashlib.sha1(f"{kind}:{rid}:{col}".encode()).hexdigest()[:16]


def compute_for_sheet(sheet_id: str, sheet_name: str, category: str, columns: list[dict], rows: list[tuple[str, dict]], today: date) -> list[dict]:
    out: list[dict] = []
    deadline_cols = [c for c in columns if c["type"] == "date" and _DEADLINE.search(c["name"])]
    status_col = an.find_status_column(columns)
    for rid, row in rows:
        status_val = row.get(status_col["id"]) if status_col else None
        done = not is_empty(status_val) and any(w in str(status_val).lower() for w in _DONE)
        title = _title(columns, row)
        for c in deadline_cols:
            d = _parse(row.get(c["id"]))
            if d is None or done:
                continue
            days = (d - today).days
            if 0 <= days <= SOON_DAYS:
                when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
                out.append({"id": _nid("due", rid, c["id"]), "kind": "due_soon", "severity": "warning", "title": f"{title}: {c['name'].lower()} {when}",
                            "detail": f"{sheet_name} · {d.isoformat()}", "sheet_id": sheet_id, "sheet_name": sheet_name, "date": d.isoformat(), "days": days})
            elif -OVERDUE_DAYS <= days < 0:
                out.append({"id": _nid("overdue", rid, c["id"]), "kind": "overdue", "severity": "danger", "title": f"{title}: {c['name'].lower()} passed {-days} day{'s' if days != -1 else ''} ago",
                            "detail": f"{sheet_name} · {d.isoformat()}", "sheet_id": sheet_id, "sheet_name": sheet_name, "date": d.isoformat(), "days": days})
        if an.is_job_category(category) and status_col is not None and an.classify_status(status_val) == "pending":
            applied_col = an.find_date_column(columns, r"appl|sent|date")
            if applied_col is not None and (applied_col not in deadline_cols):
                d = _parse(row.get(applied_col["id"]))
                if d is not None:
                    age = (today - d).days
                    if STALE_AFTER_DAYS <= age <= STALE_UNTIL_DAYS:
                        out.append({"id": _nid("stale", rid), "kind": "no_response", "severity": "info", "title": f"No response from {title} after {age} days",
                                    "detail": f"{sheet_name} · applied {d.isoformat()}", "sheet_id": sheet_id, "sheet_name": sheet_name, "date": d.isoformat(), "days": -age})
    return out


_ORDER = {"danger": 0, "warning": 1, "info": 2}


async def compute(db: AsyncSession, uid: str, today: date | None = None) -> dict:
    today = today or date.today()
    items: list[dict] = []
    for s in await sheet_service.list_sheets(db, uid, None):
        cols = [c.model_dump() for c in s.columns]
        relevant = any(c["type"] == "date" and _DEADLINE.search(c["name"]) for c in cols) or (an.is_job_category(s.category) and an.find_status_column(cols))
        if not relevant:
            continue
        res = await db.execute(
            text("select id, data_json from public.records where sheet_id = :s and user_id = :u and deleted_at is null limit :lim"),
            {"s": str(s.id), "u": uid, "lim": ROWS_PER_SHEET},
        )
        rows = [(str(r.id), jload(r.data_json)) for r in res.all()]
        items.extend(compute_for_sheet(str(s.id), s.name, s.category, cols, rows, today))
    items.sort(key=lambda i: (_ORDER[i["severity"]], abs(i["days"])))
    return {"items": items[:MAX_ITEMS], "count": min(len(items), MAX_ITEMS), "total": len(items)}
