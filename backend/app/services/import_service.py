"""Safe parsing of user-uploaded XLSX / CSV files into a typed table (preview first, commit second)."""
import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook

from app.utils.validators import ValueError_, coerce_value, is_empty

MAX_ROWS = 5000
MAX_COLS = 100
MAX_UNZIPPED = 60 * 1024 * 1024  # zip-bomb guard
MAX_CELL_CHARS = 10_000
PREVIEW_ROWS = 20


class ImportError_(ValueError):
    """User-safe message."""


class ParsedTable:
    def __init__(self, name: str, headers: list[str], rows: list[list[Any]], warnings: list[str]):
        self.name, self.headers, self.rows, self.warnings = name, headers, rows, warnings


# ---------- file sniffing ----------
def detect_kind(data: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not data:
        raise ImportError_("The file is empty.")
    if ext == "xlsx":
        if data[:4] != b"PK\x03\x04":
            raise ImportError_("That file isn't a valid Excel (.xlsx) workbook.")
        return "xlsx"
    if ext == "csv":
        if b"\x00" in data[:4096]:
            raise ImportError_("That file doesn't look like a CSV text file.")
        return "csv"
    if ext in ("xls", "xlsm", "xlsb"):
        raise ImportError_("Only .xlsx and .csv files are supported. Open the file in Excel and save it as .xlsx first.")
    raise ImportError_("Unsupported file type. Please upload an .xlsx or .csv file.")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


# ---------- parsing ----------
def _cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, str):
        v = v.strip()
        return v[:MAX_CELL_CHARS] if v else None
    return v


def _shape(name: str, grid: list[list[Any]]) -> ParsedTable:
    warnings: list[str] = []
    grid = [r for r in (list(map(_cell, row)) for row in grid)]
    while grid and all(c is None for c in grid[-1]):
        grid.pop()
    first = next((i for i, r in enumerate(grid) if any(c is not None for c in r)), None)
    if first is None:
        raise ImportError_(f"“{name}” has no data.")
    header_row, body = grid[first], grid[first + 1:]
    width = max([len(header_row)] + [len(r) for r in body] or [0])
    # drop columns that are completely empty (header and all values)
    keep = [i for i in range(width) if (i < len(header_row) and header_row[i] is not None) or any(i < len(r) and r[i] is not None for r in body)]
    if not keep:
        raise ImportError_(f"“{name}” has no data.")
    if len(keep) > MAX_COLS:
        raise ImportError_(f"“{name}” has {len(keep)} columns. The limit is {MAX_COLS}.")
    body = [r for r in body if any(c is not None for c in r)]
    if len(body) > MAX_ROWS:
        raise ImportError_(f"“{name}” has {len(body)} rows. The limit is {MAX_ROWS} per import. Split the file and import it in parts.")
    headers: list[str] = []
    seen: dict[str, int] = {}
    for n, i in enumerate(keep, start=1):
        h = str(header_row[i]).strip() if i < len(header_row) and header_row[i] is not None else f"Column {n}"
        h = re.sub(r"\s+", " ", h)[:80] or f"Column {n}"
        k = h.lower()
        if k in seen:
            seen[k] += 1
            warnings.append(f"Duplicate column name “{h}” was renamed.")
            h = f"{h} ({seen[k]})"[:80]
        seen.setdefault(h.lower(), 1)
        headers.append(h)
    rows = [[(r[i] if i < len(r) else None) for i in keep] for r in body]
    return ParsedTable(name, headers, rows, warnings)


def parse_csv(data: bytes) -> list[ParsedTable]:
    text = _decode(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    grid: list[list[Any]] = []
    try:
        for i, row in enumerate(reader):
            grid.append(row)
            if i > MAX_ROWS + 50:
                break
    except csv.Error:
        raise ImportError_("That CSV file is malformed and couldn't be read.")
    return [_shape("Imported data", grid)]


def parse_xlsx(data: bytes) -> list[ParsedTable]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise ImportError_("That workbook is too large when unpacked.")
            if "[Content_Types].xml" not in z.namelist():
                raise ImportError_("That file isn't a valid Excel (.xlsx) workbook.")
            if any(n.lower().endswith("vbaproject.bin") for n in z.namelist()):
                raise ImportError_("Workbooks with macros aren't supported.")
        # data_only: use stored results of formulas; formulas are never evaluated or executed
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ImportError_:
        raise
    except Exception:
        raise ImportError_("We couldn't read that Excel file. It may be corrupted or password-protected.")
    out: list[ParsedTable] = []
    problems: list[str] = []
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            try:
                grid = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    grid.append(list(row))
                    if i > MAX_ROWS + 5000:  # stop reading absurdly long sheets (blank styled rows etc.)
                        break
                out.append(_shape(ws.title, grid))
            except ImportError_ as e:
                problems.append(str(e))
    finally:
        wb.close()
    if not out:
        raise ImportError_(problems[0] if problems else "The workbook has no data.")
    return out


def parse_file(data: bytes, filename: str) -> list[ParsedTable]:
    kind = detect_kind(data, filename)
    tables = parse_xlsx(data) if kind == "xlsx" else parse_csv(data)
    base = filename.rsplit(".", 1)[0][:80] or "Imported data"
    if kind == "csv":
        tables[0].name = base
    return tables


# ---------- type inference ----------
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y")
_CURRENCY_HINT = re.compile(r"amount|price|cost|salary|fee|total|revenue|budget|paid|spent|stipend|ctc|rate", re.I)
_SLASH = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


def _slash_order(values: list[str]) -> str | None:
    """'dmy' / 'mdy' when the data makes it unambiguous, else None."""
    dmy = mdy = False
    for v in values:
        m = _SLASH.match(v)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12:
            dmy = True
        if b > 12:
            mdy = True
    if dmy and not mdy:
        return "dmy"
    if mdy and not dmy:
        return "mdy"
    return None


def to_iso_date(v: Any, slash_order: str | None = None) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    m = _SLASH.match(s)
    if m and slash_order:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d, mo = (a, b) if slash_order == "dmy" else (b, a)
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def infer_types(table: ParsedTable) -> list[dict]:
    """Pick the narrowest type that EVERY non-empty value fits; otherwise text. Returns [{name, type, note?}]."""
    cols = []
    for ci, name in enumerate(table.headers):
        vals = [r[ci] for r in table.rows if not is_empty(r[ci])]
        t, note = "text", None
        if vals:
            if all(isinstance(v, bool) for v in vals):
                t = "boolean"
            elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
                t = "currency" if _CURRENCY_HINT.search(name) else "number"
            elif all(isinstance(v, (date, datetime)) for v in vals):
                t = "date"
            else:
                strs = [str(v) for v in vals]
                if all(to_iso_date(s) for s in strs):
                    t = "date"
                elif any(_SLASH.match(s) for s in strs) and all(to_iso_date(s, _slash_order(strs)) for s in strs):
                    t = "date"
                elif any(_SLASH.match(s) for s in strs) and all(_SLASH.match(s) or to_iso_date(s) for s in strs):
                    note = "These dates are ambiguous (day/month order), so they are kept as text."
                elif all(_try(coerce_value, "number", s) for s in strs):
                    t = "currency" if _CURRENCY_HINT.search(name) else "number"
                elif all(_try(coerce_value, "email", s) for s in strs):
                    t = "email"
                elif all(_try(coerce_value, "url", s) for s in strs):
                    t = "url"
                elif all(s.strip().lower() in ("true", "false", "yes", "no") for s in strs):
                    t = "boolean"
        cols.append({"name": name, "type": t, **({"note": note} if note else {})})
    return cols


def _try(fn, *a) -> bool:
    try:
        return fn(*a) is not None
    except ValueError_:
        return False


def convert_cell(col_type: str, v: Any, slash_order: str | None = None) -> Any:
    """Convert a parsed cell for storage (raises ValueError_ with a readable reason)."""
    if is_empty(v):
        return None
    if col_type == "date":
        iso = to_iso_date(v, slash_order)
        if iso is None:
            raise ValueError_("Not a date this app can read.")
        return iso
    if isinstance(v, (date, datetime)):
        v = v.isoformat()
    return coerce_value(col_type, v)


def preview(table: ParsedTable) -> dict:
    types = infer_types(table)
    sample = [[_json(c) for c in r] for r in table.rows[:PREVIEW_ROWS]]
    return {"name": table.name, "columns": types, "row_count": len(table.rows), "sample_rows": sample, "warnings": table.warnings}


def _json(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
