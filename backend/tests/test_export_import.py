import io
import zipfile
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook

from app.services import export_service as ex
from app.services import import_service as imp

COLS = [
    {"id": "c1", "name": "Company", "type": "text"},
    {"id": "c2", "name": "Salary", "type": "currency"},
    {"id": "c3", "name": "Applied", "type": "date"},
    {"id": "c4", "name": "Remote", "type": "boolean"},
    {"id": "c5", "name": "Tags", "type": "tags"},
    {"id": "c6", "name": "Qty", "type": "number"},
]
ROWS = [
    {"c1": "Dobbe AI", "c2": 1500.5, "c3": "2026-11-23", "c4": True, "c5": ["ai", "remote"], "c6": 3},
    {"c1": "=HYPERLINK(\"http://evil\",\"x\")", "c2": None, "c3": "2026-01-02", "c4": False},
    {"c1": "-2+3", "c3": "not a date"},
]


# ---------------- export ----------------
def wb_of(sheets):
    return load_workbook(io.BytesIO(ex.build_workbook(sheets)))


def test_xlsx_has_real_typed_values_and_formatting():
    wb = wb_of([{"name": "Jobs", "columns": COLS, "rows": ROWS}])
    ws = wb["Jobs"]
    assert [c.value for c in ws[1]] == [c["name"] for c in COLS]
    assert all(c.font.bold for c in ws[1])
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:F4"
    r2 = [c.value for c in ws[2]]
    assert r2[0] == "Dobbe AI" and r2[1] == 1500.5 and isinstance(r2[2], datetime) and r2[2].date() == date(2026, 11, 23) and r2[3] is True
    assert r2[4] == "ai, remote" and r2[5] == 3
    assert ws["B2"].number_format == "#,##0.00" and ws["C2"].number_format == "yyyy-mm-dd"
    assert ws["C4"].value == "not a date"  # unparseable values are kept, not lost
    assert ws.column_dimensions["A"].width >= 12 and ws.column_dimensions["C"].width >= 14


def test_formulas_in_user_data_are_stored_as_literal_text():
    ws = wb_of([{"name": "Jobs", "columns": COLS, "rows": ROWS}])["Jobs"]
    cell = ws["A3"]
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")  # not a formula
    raw = zipfile.ZipFile(io.BytesIO(ex.build_workbook([{"name": "Jobs", "columns": COLS, "rows": ROWS}])))
    sheet_xml = raw.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml  # no formula element anywhere in the file


def test_multi_sheet_workbook_with_safe_unique_titles():
    sheets = [{"name": n, "columns": COLS[:1], "rows": [{"c1": n}]} for n in ["Jobs", "jobs", "A/B:C*?[x]", "x" * 50, "", "x" * 50]]
    wb = wb_of(sheets)
    titles = wb.sheetnames
    assert len(titles) == 6 and len({t.lower() for t in titles}) == 6
    assert all(len(t) <= 31 and not set(t) & set("[]:*?/\\") and t for t in titles)


def test_empty_sheet_still_exports():
    wb = wb_of([{"name": "Empty", "columns": [], "rows": []}])
    assert wb["Empty"].max_row == 1


def test_csv_bom_quoting_and_injection_guard():
    data = ex.build_csv(COLS, ROWS)
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    lines = text.split("\r\n")
    assert lines[0] == "Company,Salary,Applied,Remote,Tags,Qty"
    assert lines[1] == 'Dobbe AI,1500.5,2026-11-23,TRUE,"ai, remote",3'
    assert lines[2].startswith("\"'=HYPERLINK") or lines[2].startswith("'=HYPERLINK")  # formula neutralised
    assert "'-2+3" in lines[3]


def test_filenames_are_safe():
    assert ex.safe_filename("../../etc/passwd", "csv") == "etc_passwd.csv"
    assert ex.safe_filename("Résumé tracker", "xlsx").endswith(".xlsx")
    assert "/" not in ex.safe_filename("a/b\\c", "csv")


# ---------------- import ----------------
def xlsx_bytes(build):
    wb = Workbook()
    build(wb)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_csv_with_bom_semicolons_and_duplicates():
    data = "﻿Name;Amount;Name\nAnn;10;x\nBob;20;y\n".encode("utf-8")
    t = imp.parse_file(data, "people.csv")[0]
    assert t.headers == ["Name", "Amount", "Name (2)"] and len(t.rows) == 2
    assert any("Duplicate column" in w for w in t.warnings)


def test_csv_cp1252_fallback():
    t = imp.parse_file("Name,City\nJosé,Zürich\n".encode("cp1252"), "a.csv")[0]
    assert t.rows[0] == ["José", "Zürich"]


def test_xlsx_parse_dates_numbers_bools_and_formulas_use_cached_values():
    def build(wb):
        ws = wb.active
        ws.title = "Data"
        ws.append(["Company", "Applied", "Salary", "Remote", "Note"])
        ws.append(["A", datetime(2026, 11, 23), 100, True, "=1+1"])
        ws.append(["B", datetime(2026, 12, 1), 250.5, False, None])
        ws.append([None, None, None, None, None])  # blank row ignored
        ws["F1"] = None

    tables = imp.parse_file(xlsx_bytes(build), "jobs.xlsx")
    t = tables[0]
    assert t.name == "Data" and t.headers == ["Company", "Applied", "Salary", "Remote", "Note"] and len(t.rows) == 2
    types = {c["name"]: c["type"] for c in imp.infer_types(t)}
    assert types == {"Company": "text", "Applied": "date", "Salary": "currency", "Remote": "boolean", "Note": "text"}
    assert t.rows[0][4] == "=1+1" or t.rows[0][4] is None  # a formula is never evaluated (openpyxl has no cached value here)


def test_multi_sheet_workbook_hidden_sheets_skipped():
    def build(wb):
        a = wb.active
        a.title = "One"
        a.append(["x"]); a.append([1])
        b = wb.create_sheet("Two")
        b.append(["y"]); b.append([2])
        h = wb.create_sheet("Hidden")
        h.append(["z"]); h.append([3])
        h.sheet_state = "hidden"

    assert [t.name for t in imp.parse_file(xlsx_bytes(build), "w.xlsx")] == ["One", "Two"]


def test_type_inference_all_or_nothing():
    t = imp.ParsedTable("t", ["A", "B", "C", "D", "E", "Price"], [
        ["1", "2026-01-05", "a@b.co", "https://x.io", "yes", "10"],
        ["2.5", "5 Jan 2026", "c@d.org", "http://y.io", "no", "20"],
        ["x", "2026-02-01", "e@f.net", "https://z.io", "yes", "30"],
    ], [])
    ty = {c["name"]: c["type"] for c in imp.infer_types(t)}
    assert ty["A"] == "text"  # one bad value keeps the whole column text instead of losing data
    assert ty["B"] == "date" and ty["C"] == "email" and ty["D"] == "url" and ty["E"] == "boolean" and ty["Price"] == "currency"


def test_slash_dates_only_converted_when_unambiguous():
    amb = imp.ParsedTable("t", ["D"], [["03/04/2026"], ["05/06/2026"]], [])
    c = imp.infer_types(amb)[0]
    assert c["type"] == "text" and "ambiguous" in c["note"]
    dmy = imp.ParsedTable("t", ["D"], [["25/04/2026"], ["05/06/2026"]], [])
    assert imp.infer_types(dmy)[0]["type"] == "date"
    assert imp.convert_cell("date", "05/06/2026", "dmy") == "2026-06-05"
    assert imp.convert_cell("date", "05/06/2026", "mdy") == "2026-05-06"


def test_convert_cell_errors_are_readable():
    from app.utils.validators import ValueError_

    with pytest.raises(ValueError_):
        imp.convert_cell("number", "abc")
    with pytest.raises(ValueError_):
        imp.convert_cell("date", "someday")
    assert imp.convert_cell("number", "₹1,200") == 1200
    assert imp.convert_cell("text", None) is None


@pytest.mark.parametrize(
    "data,name,fragment",
    [
        (b"", "a.csv", "empty"),
        (b"a,b\n1,2\n", "a.txt", "Unsupported"),
        (b"a,b\n1,2\n", "a.xls", "Only .xlsx"),
        (b"a,b\n1,2\n", "a.xlsm", "Only .xlsx"),
        (b"not a zip", "a.xlsx", "valid Excel"),
        (b"\x00\x01\x02binary", "a.csv", "CSV"),
        (b"\n\n\n", "a.csv", "no data"),
    ],
)
def test_bad_files_rejected_with_clear_messages(data, name, fragment):
    with pytest.raises(imp.ImportError_) as e:
        imp.parse_file(data, name)
    assert fragment.lower() in str(e.value).lower()


def test_fake_xlsx_zip_without_content_types_rejected():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(imp.ImportError_):
        imp.parse_file(b.getvalue(), "evil.xlsx")


def test_zip_bomb_rejected(monkeypatch):
    monkeypatch.setattr(imp, "MAX_UNZIPPED", 1000)
    data = xlsx_bytes(lambda wb: wb.active.append(["x" * 5000]))
    with pytest.raises(imp.ImportError_) as e:
        imp.parse_file(data, "bomb.xlsx")
    assert "too large" in str(e.value)


def test_row_and_column_limits(monkeypatch):
    monkeypatch.setattr(imp, "MAX_ROWS", 3)
    csv_rows = "h\n" + "\n".join(str(i) for i in range(10)) + "\n"
    with pytest.raises(imp.ImportError_) as e:
        imp.parse_file(csv_rows.encode(), "big.csv")
    assert "rows" in str(e.value)
    monkeypatch.setattr(imp, "MAX_COLS", 2)
    with pytest.raises(imp.ImportError_):
        imp.parse_file(b"a,b,c\n1,2,3\n", "wide.csv")


def test_export_then_import_roundtrip_preserves_data():
    sheet = {"name": "Round", "columns": COLS[:4], "rows": [{"c1": "Dobbe AI", "c2": 1500.5, "c3": "2026-11-23", "c4": True}, {"c1": "Acme", "c2": 20, "c3": "2026-01-02", "c4": False}]}
    t = imp.parse_file(ex.build_workbook([sheet]), "r.xlsx")[0]
    types = {c["name"]: c["type"] for c in imp.infer_types(t)}
    assert types == {"Company": "text", "Salary": "currency", "Applied": "date", "Remote": "boolean"}
    assert imp.convert_cell("date", t.rows[0][2]) == "2026-11-23" and t.rows[0][1] == 1500.5 and t.rows[0][3] is True
    csvt = imp.parse_file(ex.build_csv(COLS[:4], sheet["rows"]), "r.csv")[0]
    assert csvt.headers == ["Company", "Salary", "Applied", "Remote"] and csvt.rows[0][0] == "Dobbe AI"
