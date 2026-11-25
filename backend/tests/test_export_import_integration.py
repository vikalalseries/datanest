"""Phase 5 API tests against the REAL database (skipped unless RLS_TEST=1)."""
import io
import json
import os
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app
from app.middleware.authentication import AuthUser, get_current_user

pytestmark = pytest.mark.skipif(
    os.environ.get("RLS_TEST") != "1" or not get_settings().database_url,
    reason="set RLS_TEST=1 and DATABASE_URL to run against a real database",
)

TAG = uuid.uuid4().hex[:8]
current = {"uid": f"it-p5-{TAG}-a"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(uid=current["uid"], email=f"{current['uid']}@it.invalid")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    import asyncio

    async def cleanup():
        eng = create_async_engine(get_settings().async_database_url, connect_args={"statement_cache_size": 0})
        async with eng.begin() as conn:
            await conn.execute(text("delete from public.users where firebase_uid like :p"), {"p": f"it-p5-{TAG}-%"})
        await eng.dispose()

    asyncio.run(cleanup())


def as_user(w):
    current["uid"] = f"it-p5-{TAG}-{w}"


def mk(client, name, cols, rows=()):
    s = client.post("/api/sheets", json={"name": name, "category": "general", "columns": cols}).json()
    ids = {c["name"]: c["id"] for c in s["columns"]}
    for r in rows:
        assert client.post(f"/api/sheets/{s['id']}/records", json={"data": {ids[k]: v for k, v in r.items()}}).status_code == 201
    return s, ids


COLS = [{"name": "Company", "type": "text"}, {"name": "Salary", "type": "currency"}, {"name": "Applied", "type": "date"}, {"name": "Remote", "type": "boolean"}, {"name": "Tags", "type": "tags"}]
ROWS = [
    {"Company": "Dobbe AI", "Salary": 1500.5, "Applied": "2026-11-23", "Remote": True, "Tags": "ai, remote"},
    {"Company": '=HYPERLINK("http://evil","x")', "Salary": 20, "Applied": "2026-01-02", "Remote": False},
]


def test_export_xlsx_and_csv(client):
    as_user("a")
    s, ids = mk(client, "Jobs / 2026: Export?", COLS, ROWS)
    r = client.get(f"/api/export/sheet/{s['id']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    assert "attachment" in r.headers["content-disposition"] and ".xlsx" in r.headers["content-disposition"] and "/" not in r.headers["content-disposition"].split("filename=")[1].split(";")[0]
    ws = load_workbook(io.BytesIO(r.content)).active
    assert [c.value for c in ws[1]] == ["Company", "Salary", "Applied", "Remote", "Tags"] and ws.freeze_panes == "A2"
    row2 = [c.value for c in ws[2]]
    assert row2[0] == "Dobbe AI" and row2[1] == 1500.5 and isinstance(row2[2], datetime) and row2[3] is True and row2[4] == "ai, remote"
    assert ws["A3"].data_type == "s"  # the formula-looking text is literal
    c = client.get(f"/api/export/sheet/{s['id']}", params={"format": "csv"})
    assert c.status_code == 200 and c.headers["content-type"].startswith("text/csv") and c.content.startswith(b"\xef\xbb\xbf")
    assert "'=HYPERLINK" in c.content.decode("utf-8-sig")
    assert client.get(f"/api/export/sheet/{s['id']}", params={"format": "pdf"}).status_code == 422
    assert any(a["action"] == "export.sheet" for a in client.get("/api/dashboard/stats").json()["recent_activity"])


def test_export_workspace_one_worksheet_per_sheet(client):
    as_user("a")
    s2, _ = mk(client, "Second", [{"name": "X", "type": "text"}], [{"X": "hello"}])
    gone, _ = mk(client, "Trashed one", [{"name": "Y", "type": "text"}])
    client.delete(f"/api/sheets/{gone['id']}")
    r = client.get("/api/export/workspace")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert "Second" in wb.sheetnames and "Trashed one" not in wb.sheetnames and len(wb.sheetnames) >= 2
    assert wb["Second"]["A2"].value == "hello"


def test_empty_workspace_export_is_a_friendly_404(client):
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    r = client.get("/api/export/workspace")
    assert r.status_code == 404 and r.json()["error"]["code"] == "nothing_to_export"


def sample_xlsx():
    wb = Workbook()
    a = wb.active
    a.title = "Applications"
    a.append(["Company", "Applied", "Salary", "Remote", "Notes"])
    a.append(["Acme", datetime(2026, 11, 23), 100, True, "first"])
    a.append(["Globex", datetime(2026, 12, 1), 250.5, False, None])
    b = wb.create_sheet("Other")
    b.append(["Name"])
    b.append(["Zed"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def preview(client, data, name):
    return client.post("/api/import/preview", files={"file": (name, data, "application/octet-stream")})


def test_import_preview_then_commit_with_edits(client):
    as_user("a")
    r = preview(client, sample_xlsx(), "jobs.xlsx")
    assert r.status_code == 200, r.text
    pv = r.json()
    assert [w["name"] for w in pv["worksheets"]] == ["Applications", "Other"]
    app_ws = pv["worksheets"][0]
    assert app_ws["row_count"] == 2 and {c["name"]: c["type"] for c in app_ws["columns"]} == {"Company": "text", "Applied": "date", "Salary": "currency", "Remote": "boolean", "Notes": "text"}
    # preview saves nothing
    assert "Imported Jobs" not in [s["name"] for s in client.get("/api/sheets").json()]
    opts = {"worksheet": "Applications", "sheet_name": "Imported Jobs",
            "columns": [{"index": 0, "name": "Employer", "type": "text"}, {"index": 1, "name": "Applied", "type": "date"},
                        {"index": 2, "name": "Pay", "type": "number"}, {"index": 3, "name": "Remote", "type": "boolean", "include": False},
                        {"index": 4, "name": "Notes", "type": "text"}]}
    r = client.post("/api/import/commit", files={"file": ("jobs.xlsx", sample_xlsx(), "application/octet-stream")}, data={"options": json.dumps(opts)})
    assert r.status_code == 201, r.text
    sheet = r.json()
    assert sheet["name"] == "Imported Jobs" and sheet["record_count"] == 2 and [c["name"] for c in sheet["columns"]] == ["Employer", "Applied", "Pay", "Notes"]
    ids = {c["name"]: c["id"] for c in sheet["columns"]}
    recs = client.get(f"/api/sheets/{sheet['id']}/records").json()["items"]
    assert recs[0]["data"][ids["Employer"]] == "Acme" and recs[0]["data"][ids["Applied"]] == "2026-11-23" and recs[1]["data"][ids["Pay"]] == 250.5
    assert ids["Notes"] not in recs[1]["data"] and recs[0]["source_type"] == "import"


def test_import_bad_values_abort_everything(client):
    as_user("a")
    before = len(client.get("/api/sheets").json())
    csv = b"Name,Amount\nAnn,10\nBob,lots\nCy,x\n"
    opts = {"sheet_name": "Should not exist", "columns": [{"index": 0, "name": "Name", "type": "text"}, {"index": 1, "name": "Amount", "type": "number"}]}
    r = client.post("/api/import/commit", files={"file": ("a.csv", csv, "text/csv")}, data={"options": json.dumps(opts)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "import_invalid" and "Row 3" in r.json()["error"]["message"] and r.json()["error"]["problem_count"] == 2
    assert len(client.get("/api/sheets").json()) == before  # nothing half-imported
    opts["columns"][1]["type"] = "text"  # the suggested fix works
    assert client.post("/api/import/commit", files={"file": ("a.csv", csv, "text/csv")}, data={"options": json.dumps(opts)}).status_code == 201


def test_import_rejects_bad_input(client):
    as_user("a")
    for name, data in [("a.exe", b"MZ"), ("a.xls", b"x"), ("fake.xlsx", b"hello"), ("empty.csv", b""), ("bin.csv", b"\x00\x01\x02")]:
        r = preview(client, data, name)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_file", (name, r.text)
    big = preview(client, b"a,b\n" + b"1,2\n" * (3 * 1024 * 1024), "big.csv")
    assert big.status_code == 422 and big.json()["error"]["code"] == "file_too_large"
    assert client.post("/api/import/commit", files={"file": ("a.csv", b"a\n1\n", "text/csv")}, data={"options": "{not json"}).status_code == 422
    dup = {"sheet_name": "x", "columns": [{"index": 0, "name": "A", "type": "text"}, {"index": 0, "name": "a", "type": "text"}]}
    assert client.post("/api/import/commit", files={"file": ("a.csv", b"a\n1\n", "text/csv")}, data={"options": json.dumps(dup)}).status_code == 422
    nows = {"worksheet": "Nope", "sheet_name": "x", "columns": [{"index": 0, "name": "A", "type": "text"}]}
    assert client.post("/api/import/commit", files={"file": ("a.xlsx", sample_xlsx(), "application/octet-stream")}, data={"options": json.dumps(nows)}).status_code == 422


def test_export_import_roundtrip(client):
    as_user("a")
    s, ids = mk(client, "Roundtrip", COLS[:4], [{k: v for k, v in ROWS[0].items() if k != "Tags"}, {"Company": "Acme", "Salary": 20, "Applied": "2026-01-02", "Remote": False}])
    exported = client.get(f"/api/export/sheet/{s['id']}").content
    pv = preview(client, exported, "roundtrip.xlsx").json()["worksheets"][0]
    assert [c["type"] for c in pv["columns"]] == ["text", "currency", "date", "boolean"]
    opts = {"sheet_name": "Roundtrip copy", "columns": [{"index": i, "name": c["name"], "type": c["type"]} for i, c in enumerate(pv["columns"])]}
    r = client.post("/api/import/commit", files={"file": ("roundtrip.xlsx", exported, "application/octet-stream")}, data={"options": json.dumps(opts)})
    assert r.status_code == 201
    copy = r.json()
    cids = {c["name"]: c["id"] for c in copy["columns"]}
    got = [{k: x["data"].get(cids[k]) for k in cids} for x in client.get(f"/api/sheets/{copy['id']}/records").json()["items"]]
    assert got == [{"Company": "Dobbe AI", "Salary": 1500.5, "Applied": "2026-11-23", "Remote": True}, {"Company": "Acme", "Salary": 20, "Applied": "2026-01-02", "Remote": False}]


def test_other_users_cannot_export_or_download(client):
    as_user("a")
    s, _ = mk(client, "Private export", [{"name": "X", "type": "text"}], [{"X": "secret"}])
    as_user("b")
    assert client.get(f"/api/export/sheet/{s['id']}").status_code == 404
    assert client.get(f"/api/export/sheet/{s['id']}", params={"format": "csv"}).status_code == 404
    assert client.get(f"/api/files/{uuid.uuid4()}/download").status_code == 404
    ws = load_workbook(io.BytesIO(client.get("/api/export/workspace").content)) if client.get("/api/export/workspace").status_code == 200 else None
    assert ws is None or "Private export" not in ws.sheetnames
