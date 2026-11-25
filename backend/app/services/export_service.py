"""Build real XLSX / CSV files (actual cell values, not images) from sheets."""
import csv
import io
import re
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MAX_ROWS_PER_SHEET = 50_000
HEADER_FILL = PatternFill("solid", fgColor="E8EAF6")
DATE_FMT = "yyyy-mm-dd"
CURRENCY_FMT = '#,##0.00'
NUMBER_FMT = "General"
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def safe_filename(name: str, ext: str) -> str:
    base = re.sub(r"[^\w\-. ]+", "_", name, flags=re.U).strip(" ._") or "datanest"
    return f"{base[:80]}.{ext}"


def worksheet_title(name: str, used: set[str]) -> str:
    """Excel limits: <=31 chars, no []:*?/\\, not blank, unique (case-insensitive)."""
    t = BAD_SHEET_CHARS.sub(" ", name).strip().strip("'") or "Sheet"
    t = t[:31]
    base, n = t, 2
    while t.lower() in used:
        suffix = f" ({n})"
        t = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(t.lower())
    return t


def _text_cell_value(v: str) -> str:
    return v if len(v) <= 32_000 else v[:32_000]  # Excel cell limit is 32,767


def _excel_value(col_type: str, v: Any) -> tuple[Any, str | None]:
    """Return (python value, number_format). Strings are always stored as text, never evaluated as formulas."""
    if v is None or v == "" or v == []:
        return None, None
    if col_type == "date":
        try:
            return date.fromisoformat(str(v)[:10]), DATE_FMT
        except ValueError:
            return str(v), None
    if col_type in ("number", "currency"):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v, CURRENCY_FMT if col_type == "currency" else NUMBER_FMT
        return str(v), None
    if col_type == "boolean":
        return bool(v), None
    if col_type == "tags":
        return _text_cell_value(", ".join(map(str, v)) if isinstance(v, list) else str(v)), None
    return _text_cell_value(str(v)), None


def _write_sheet(ws, columns: list[dict], rows: list[dict]) -> None:
    for ci, col in enumerate(columns, start=1):
        c = ws.cell(row=1, column=ci, value=col["name"][:255])
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
        c.data_type = "s"
    widths = [min(max(len(col["name"]) + 4, 12), 60) for col in columns]
    for ri, rec in enumerate(rows[:MAX_ROWS_PER_SHEET], start=2):
        for ci, col in enumerate(columns, start=1):
            value, fmt = _excel_value(col["type"], rec.get(col["id"]))
            if value is None:
                continue
            cell = ws.cell(row=ri, column=ci, value=value)
            if isinstance(value, str):
                cell.data_type = "s"  # force literal text: "=HYPERLINK(...)" must never run as a formula
                widths[ci - 1] = min(max(widths[ci - 1], min(len(value), 60) + 2), 60)
            if fmt:
                cell.number_format = fmt
            if col["type"] in ("date", "number", "currency"):
                widths[ci - 1] = max(widths[ci - 1], 14)
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"
    if columns:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(2, min(len(rows), MAX_ROWS_PER_SHEET) + 1)}"


def build_workbook(sheets: list[dict]) -> bytes:
    """sheets: [{name, columns:[{id,name,type}], rows:[{col_id: value}]}] -> .xlsx bytes (one worksheet per sheet)."""
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for s in sheets or [{"name": "DataNest", "columns": [], "rows": []}]:
        ws = wb.create_sheet(worksheet_title(s["name"], used))
        _write_sheet(ws, s["columns"], s["rows"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _csv_text(v: str) -> str:
    # neutralise spreadsheet formula injection for people who open the CSV in Excel/Sheets
    return "'" + v if v and v.startswith(FORMULA_START) else v


def build_csv(columns: list[dict], rows: list[dict]) -> bytes:
    """UTF-8 with BOM so Excel detects the encoding."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([_csv_text(c["name"]) for c in columns])
    for rec in rows[:MAX_ROWS_PER_SHEET]:
        line = []
        for col in columns:
            v = rec.get(col["id"])
            if v is None or v == "" or v == []:
                line.append("")
            elif col["type"] == "boolean":
                line.append("TRUE" if v else "FALSE")
            elif col["type"] == "tags":
                line.append(_csv_text(", ".join(map(str, v)) if isinstance(v, list) else str(v)))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                line.append(repr(v) if isinstance(v, float) else str(v))
            else:
                line.append(_csv_text(str(v)))
        w.writerow(line)
    return ("﻿" + buf.getvalue()).encode("utf-8")
