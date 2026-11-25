"""Column-type aware validation/normalisation of cell values."""
import re
import secrets
from datetime import date, datetime
from typing import Any

COLUMN_TYPES = ("text", "number", "currency", "date", "boolean", "email", "url", "status", "tags")
MAX_TEXT = 10_000
MAX_TAGS = 50
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TRUE = {"true", "yes", "y", "1"}
FALSE = {"false", "no", "n", "0"}


class ValueError_(ValueError):
    """Raised when a value cannot be coerced to a column type."""


def new_column_id() -> str:
    return "c_" + secrets.token_hex(4)


def is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, list) and len(v) == 0)


def coerce_value(col_type: str, value: Any) -> Any:
    """Return a normalised value (or None when empty). Raises ValueError_ when impossible."""
    if is_empty(value):
        return None
    if col_type in ("text", "status"):
        s = str(value).strip()
        if len(s) > MAX_TEXT:
            raise ValueError_("Text is too long.")
        return s
    if col_type in ("number", "currency"):
        if isinstance(value, bool):
            raise ValueError_("Not a number.")
        if isinstance(value, (int, float)):
            num = float(value)
        else:
            cleaned = re.sub(r"[,\s₹$€£]", "", str(value))
            try:
                num = float(cleaned)
            except ValueError:
                raise ValueError_("Not a number.")
        if num != num or num in (float("inf"), float("-inf")):
            raise ValueError_("Not a number.")
        return int(num) if num.is_integer() and abs(num) < 1e15 else num
    if col_type == "date":
        if isinstance(value, (date, datetime)):
            return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
        s = str(value).strip()
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            raise ValueError_("Dates must look like YYYY-MM-DD.")
    if col_type == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in TRUE:
            return True
        if s in FALSE:
            return False
        raise ValueError_("Must be true or false.")
    if col_type == "email":
        s = str(value).strip()
        if len(s) > 320 or not EMAIL_RE.match(s):
            raise ValueError_("Not a valid email address.")
        return s
    if col_type == "url":
        s = str(value).strip()
        if len(s) > 2048 or not re.match(r"^https?://[^\s]+$", s, re.I):
            raise ValueError_("Links must start with http:// or https://")
        return s
    if col_type == "tags":
        items = value if isinstance(value, list) else str(value).split(",")
        tags: list[str] = []
        for t in items:
            t = str(t).strip()
            if t and t not in tags:
                tags.append(t[:60])
        if len(tags) > MAX_TAGS:
            raise ValueError_("Too many tags.")
        return tags or None
    raise ValueError_("Unknown column type.")


def validate_record_data(columns: list[dict], data: dict, partial: bool = False) -> dict:
    """Validate a {column_id: value} dict against the sheet schema. Unknown columns are rejected, never dropped."""
    by_id = {c["id"]: c for c in columns}
    unknown = [k for k in data if k not in by_id]
    if unknown:
        raise ValueError_("Unknown columns: " + ", ".join(unknown[:5]))
    out: dict[str, Any] = {}
    errors: list[str] = []
    for key, val in data.items():
        try:
            out[key] = coerce_value(by_id[key]["type"], val)
        except ValueError_ as e:
            errors.append(f"{by_id[key]['name']}: {e}")
    if errors:
        raise ValueError_("; ".join(errors))
    return out
