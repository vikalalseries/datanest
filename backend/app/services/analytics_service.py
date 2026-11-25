"""Category-aware analytics. Only sheets whose category makes a metric meaningful get it (no irrelevant numbers)."""
import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sheet_service
from app.services.sheet_service import jload
from app.utils.validators import is_empty

MAX_ROWS = 20_000

_REJECT = ("reject", "declin", "not selected", "unsuccessful", "turned down", "denied", "no longer")
_OFFER = ("offer", "accepted", "hired", "selected", "joined")
_INTERVIEW = ("interview", "screening", "assessment", "shortlist", "technical", "hr round", "test round", "call scheduled")
_WITHDRAWN = ("withdr", "cancel")
_PENDING = ("appli", "pending", "waiting", "submitted", "sent", "in review", "under review", "awaiting", "no response", "wishlist", "saved")


def classify_status(value: Any) -> str:
    """-> interview | rejected | offer | pending | withdrawn | other. Empty means no response yet (pending)."""
    if is_empty(value):
        return "pending"
    v = str(value).strip().lower()
    for key, words in (("rejected", _REJECT), ("offer", _OFFER), ("interview", _INTERVIEW), ("withdrawn", _WITHDRAWN), ("pending", _PENDING)):
        if any(w in v for w in words):
            return key
    return "other"


def is_job_category(category: str) -> bool:
    c = (category or "").lower()
    return c in ("job_application", "internship_application") or "internship" in c or "job_app" in c or c == "application"


def is_expense_category(category: str) -> bool:
    return "expense" in (category or "").lower() or (category or "").lower() in ("spending", "budget")


def _name_match(col: dict, pattern: str) -> bool:
    return re.search(pattern, col["name"], re.I) is not None


def find_status_column(columns: list[dict]) -> dict | None:
    return next((c for c in columns if c["type"] == "status" and _name_match(c, r"status|stage|state|progress")), None) \
        or next((c for c in columns if c["type"] == "status"), None) \
        or next((c for c in columns if _name_match(c, r"^(application )?(status|stage)$")), None)


def find_amount_column(columns: list[dict]) -> dict | None:
    return next((c for c in columns if c["type"] == "currency"), None) \
        or next((c for c in columns if c["type"] == "number" and _name_match(c, r"amount|cost|price|spent|total|paid")), None)


def find_date_column(columns: list[dict], pattern: str = r"date|day|when") -> dict | None:
    dates = [c for c in columns if c["type"] == "date"]
    return next((c for c in dates if _name_match(c, pattern)), None) or (dates[0] if dates else None)


def find_category_column(columns: list[dict]) -> dict | None:
    return next((c for c in columns if _name_match(c, r"category|type|kind") and c["type"] in ("status", "text", "tags")), None) \
        or next((c for c in columns if c["type"] == "status" and not _name_match(c, r"status|stage|payment|method")), None)


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def compute_job(columns: list[dict], rows: list[dict], today: date) -> dict:
    total = len(rows)
    status_col = find_status_column(columns)
    notes: list[str] = []
    metrics = [{"key": "applications", "label": "Applications sent", "value": total}]
    breakdown: list[dict] = []
    if status_col is None:
        notes.append("Add a Status column (for example Applied, Interview, Offer, Rejected) to see interviews, offers and your response rate.")
        return {"metrics": metrics, "breakdown": breakdown, "notes": notes}
    counts = Counter(classify_status(r.get(status_col["id"])) for r in rows)
    responded = counts["interview"] + counts["rejected"] + counts["offer"]
    pending = counts["pending"]
    rate = round(responded / total * 100, 1) if total else 0.0
    metrics += [
        {"key": "interviews", "label": "Interviews", "value": counts["interview"]},
        {"key": "rejections", "label": "Rejections", "value": counts["rejected"]},
        {"key": "offers", "label": "Offers", "value": counts["offer"]},
        {"key": "pending", "label": "Pending", "value": pending},
        {"key": "response_rate", "label": "Response rate", "value": rate, "unit": "%", "hint": "Interviews, offers and rejections as a share of all applications"},
    ]
    labels = Counter(str(r.get(status_col["id"])).strip() if not is_empty(r.get(status_col["id"])) else "(no status)" for r in rows)
    breakdown = [{"label": k, "value": v} for k, v in labels.most_common(8)]
    if counts["other"]:
        notes.append(f"{counts['other']} application(s) have a status that isn't counted as pending, interview, offer or rejected.")
    date_col = find_date_column(columns, r"appl|sent|date")
    if date_col:
        month = sum(1 for r in rows if isinstance(r.get(date_col["id"]), str) and r[date_col["id"]][:7] == today.isoformat()[:7])
        metrics.append({"key": "this_month", "label": "Applied this month", "value": month})
    return {"metrics": metrics, "breakdown": breakdown, "notes": notes}


def compute_expense(columns: list[dict], rows: list[dict], today: date) -> dict:
    amt = find_amount_column(columns)
    if amt is None:
        return {"metrics": [{"key": "rows", "label": "Entries", "value": len(rows)}], "breakdown": [],
                "notes": ["Add an Amount column (currency or number) to see totals."]}
    vals = [(r, _num(r.get(amt["id"]))) for r in rows]
    nums = [v for _, v in vals if v is not None]
    total = round(sum(nums), 2)
    date_col = find_date_column(columns)
    month_total = 0.0
    if date_col:
        month_total = round(sum(v for r, v in vals if v is not None and isinstance(r.get(date_col["id"]), str) and r[date_col["id"]][:7] == today.isoformat()[:7]), 2)
    metrics = [
        {"key": "total_spent", "label": "Total spent", "value": total},
        {"key": "entries", "label": "Entries", "value": len(nums)},
        {"key": "average", "label": "Average per entry", "value": round(total / len(nums), 2) if nums else 0},
        {"key": "largest", "label": "Largest entry", "value": max(nums) if nums else 0},
    ]
    if date_col:
        metrics.append({"key": "this_month", "label": "Spent this month", "value": month_total})
    breakdown: list[dict] = []
    cat = find_category_column(columns)
    if cat:
        sums: dict[str, float] = defaultdict(float)
        for r, v in vals:
            if v is None:
                continue
            c = r.get(cat["id"])
            label = ", ".join(c) if isinstance(c, list) else (str(c).strip() if not is_empty(c) else "(uncategorised)")
            sums[label] += v
        breakdown = [{"label": k, "value": round(v, 2)} for k, v in sorted(sums.items(), key=lambda x: -x[1])[:8]]
    return {"metrics": metrics, "breakdown": breakdown, "notes": []}


async def _rows(db: AsyncSession, uid: str, sheet_id: Any) -> tuple[list[dict], bool]:
    res = await db.execute(
        text("select data_json from public.records where sheet_id = :s and user_id = :u and deleted_at is null limit :lim"),
        {"s": str(sheet_id), "u": uid, "lim": MAX_ROWS + 1},
    )
    rows = [jload(r.data_json) for r in res.all()]
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


async def sheet_analytics(db: AsyncSession, uid: str, sheet_id: Any, today: date | None = None) -> dict:
    today = today or date.today()
    sheet = await sheet_service.get_sheet_row(db, uid, sheet_id)
    cols = sheet_service.columns_of(sheet)
    cat = sheet.category
    if is_job_category(cat):
        kind, fn = "job", compute_job
    elif is_expense_category(cat):
        kind, fn = "expense", compute_expense
    else:
        return {"applicable": False, "kind": None, "category": cat, "metrics": [], "breakdown": [], "notes": [],
                "reason": "Insights appear for job, internship and expense sheets. Set this sheet's category to enable them."}
    rows, truncated = await _rows(db, uid, sheet_id)
    out = fn(cols, rows, today)
    if truncated:
        out["notes"].append(f"Only the first {MAX_ROWS:,} rows were analysed.")
    return {"applicable": True, "kind": kind, "category": cat, **out}


async def overview(db: AsyncSession, uid: str, today: date | None = None) -> dict:
    """Dashboard roll-up: combined job/internship funnel across all such sheets. Absent entirely if there are none."""
    today = today or date.today()
    job_sheets = [s for s in await sheet_service.list_sheets(db, uid, None) if is_job_category(s.category)]
    if not job_sheets:
        return {"job": None}
    all_rows: list[dict] = []
    per_sheet = []
    totals = Counter()
    for s in job_sheets:
        cols = [c.model_dump() for c in s.columns]
        rows, _ = await _rows(db, uid, s.id)
        m = {x["key"]: x["value"] for x in compute_job(cols, rows, today)["metrics"]}
        per_sheet.append({"sheet_id": str(s.id), "name": s.name, "applications": m.get("applications", 0), "interviews": m.get("interviews"), "offers": m.get("offers"), "response_rate": m.get("response_rate")})
        for k in ("applications", "interviews", "rejections", "offers", "pending"):
            totals[k] += m.get(k) or 0
        all_rows.extend(rows)
    apps = totals["applications"]
    responded = totals["interviews"] + totals["rejections"] + totals["offers"]
    return {"job": {"sheets": per_sheet, "applications": apps, "interviews": totals["interviews"], "rejections": totals["rejections"],
                    "offers": totals["offers"], "pending": totals["pending"], "response_rate": round(responded / apps * 100, 1) if apps else 0.0}}
