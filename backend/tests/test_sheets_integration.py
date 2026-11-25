"""End-to-end API tests for Phase 2 against the REAL database (skipped unless RLS_TEST=1).

Auth is bypassed with a dependency override, but everything else (service layer, SQL, RLS) is real.
Two throwaway users are created and removed afterwards.
"""
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
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
current = {"uid": f"it-{TAG}-a"}


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
            await conn.execute(text("delete from public.users where firebase_uid like :p"), {"p": f"it-{TAG}-%"})
        await eng.dispose()

    asyncio.run(cleanup())


def as_user(who: str):
    current["uid"] = f"it-{TAG}-{who}"


def mk_sheet(client, name="Jobs", cols=None):
    cols = cols or [
        {"name": "Company", "type": "text"},
        {"name": "Salary", "type": "currency"},
        {"name": "Applied", "type": "date"},
        {"name": "Status", "type": "status"},
    ]
    r = client.post("/api/sheets", json={"name": name, "category": "job_application", "columns": cols})
    assert r.status_code == 201, r.text
    return r.json()


def col(sheet, name):
    return next(c["id"] for c in sheet["columns"] if c["name"] == name)


def test_me_creates_profile(client):
    as_user("a")
    r = client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["workspace"]["name"]


def test_sheet_and_record_lifecycle(client):
    as_user("a")
    s = mk_sheet(client)
    sid = s["id"]
    c, sal, ap = col(s, "Company"), col(s, "Salary"), col(s, "Applied")
    r = client.post(f"/api/sheets/{sid}/records", json={"data": {c: "Acme", sal: "₹1,500", ap: "2026-11-23"}})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["data"][sal] == 1500
    # partial update + clear
    r = client.put(f"/api/records/{rec['id']}", json={"data": {c: "Acme Corp", ap: None}})
    assert r.status_code == 200
    assert r.json()["data"][c] == "Acme Corp" and ap not in r.json()["data"] and r.json()["data"][sal] == 1500
    # invalid values are rejected, not stored
    bad = client.put(f"/api/records/{rec['id']}", json={"data": {sal: "lots", ap: "yesterday"}})
    assert bad.status_code == 422
    assert client.post(f"/api/sheets/{sid}/records", json={"data": {"c_nope": "x"}}).status_code == 422
    # trash + restore
    assert client.delete(f"/api/records/{rec['id']}").status_code == 204
    assert client.get(f"/api/sheets/{sid}/records").json()["total"] == 0
    assert client.get("/api/trash").json()["records"][0]["data"]["Company"] == "Acme Corp"
    assert client.post("/api/records/restore", json={"ids": [rec["id"]]}).json()["restored"] == 1
    assert client.get(f"/api/sheets/{sid}/records").json()["total"] == 1


def test_sort_filter_search(client):
    as_user("a")
    s = mk_sheet(client, "Expenses", [{"name": "Item", "type": "text"}, {"name": "Amount", "type": "number"}, {"name": "Paid", "type": "boolean"}])
    sid, item, amt, paid = s["id"], col(s, "Item"), col(s, "Amount"), col(s, "Paid")
    for name, a, p in [("Internet", 500, True), ("Rent", 12000, False), ("Coffee", 90, True), ("Blank", None, None)]:
        assert client.post(f"/api/sheets/{sid}/records", json={"data": {item: name, amt: a, paid: p}}).status_code == 201
    names = lambda r: [x["data"].get(item) for x in r.json()["items"]]
    assert names(client.get(f"/api/sheets/{sid}/records", params={"sort": amt, "dir": "desc"})) == ["Rent", "Internet", "Coffee", "Blank"]
    assert names(client.get(f"/api/sheets/{sid}/records", params={"sort": amt, "dir": "asc"})) == ["Coffee", "Internet", "Rent", "Blank"]
    f = json.dumps([{"column": amt, "op": "gt", "value": 100}])
    assert sorted(names(client.get(f"/api/sheets/{sid}/records", params={"filters": f}))) == ["Internet", "Rent"]
    f = json.dumps([{"column": paid, "op": "eq", "value": True}, {"column": item, "op": "contains", "value": "INTER"}])
    assert names(client.get(f"/api/sheets/{sid}/records", params={"filters": f})) == ["Internet"]
    f = json.dumps([{"column": amt, "op": "empty"}])
    assert names(client.get(f"/api/sheets/{sid}/records", params={"filters": f})) == ["Blank"]
    assert names(client.get(f"/api/sheets/{sid}/records", params={"q": "rent"})) == ["Rent"]
    assert names(client.get(f"/api/sheets/{sid}/records", params={"q": "100%"})) == []  # wildcard chars are literal
    assert client.get(f"/api/sheets/{sid}/records", params={"sort": "c_bogus"}).status_code == 422
    inj = json.dumps([{"column": "x'; drop table records;--", "op": "eq", "value": 1}])
    assert client.get(f"/api/sheets/{sid}/records", params={"filters": inj}).status_code == 422
    page = client.get(f"/api/sheets/{sid}/records", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2


def test_columns_add_rename_retype_delete(client):
    as_user("a")
    s = mk_sheet(client, "Cols", [{"name": "Name", "type": "text"}, {"name": "Qty", "type": "text"}])
    sid, name, qty = s["id"], col(s, "Name"), col(s, "Qty")
    client.post(f"/api/sheets/{sid}/records", json={"data": {name: "a", qty: "5"}})
    client.post(f"/api/sheets/{sid}/records", json={"data": {name: "b", qty: "five"}})
    assert client.post(f"/api/sheets/{sid}/columns", json={"name": "name", "type": "text"}).status_code == 409  # duplicate (case-insens.)
    r = client.patch(f"/api/sheets/{sid}/columns/{qty}", json={"type": "number"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conversion_loses_data"  # no silent data loss
    r = client.patch(f"/api/sheets/{sid}/columns/{qty}", json={"type": "number", "force": True, "name": "Quantity"})
    assert r.status_code == 200
    vals = {x["data"][name]: x["data"].get(qty) for x in client.get(f"/api/sheets/{sid}/records").json()["items"]}
    assert vals == {"a": 5, "b": None}
    r = client.post(f"/api/sheets/{sid}/columns", json={"name": "Tags", "type": "tags"})
    new_id = r.json()["columns"][-1]["id"]
    assert client.put(f"/api/sheets/{sid}/columns-order", json={"ids": [new_id, name, qty]}).json()["columns"][0]["id"] == new_id
    assert client.put(f"/api/sheets/{sid}/columns-order", json={"ids": [name]}).status_code == 422
    assert [c["name"] for c in client.delete(f"/api/sheets/{sid}/columns/{qty}").json()["columns"]] == ["Tags", "Name"]


def test_duplicate_trash_restore_sheet(client):
    as_user("a")
    s = mk_sheet(client, "Orig")
    sid = s["id"]
    client.post(f"/api/sheets/{sid}/records", json={"data": {col(s, "Company"): "X"}})
    d = client.post(f"/api/sheets/{sid}/duplicate").json()
    assert d["name"] == "Orig (copy)" and d["record_count"] == 1 and d["id"] != sid
    assert client.delete(f"/api/sheets/{sid}").status_code == 204
    assert sid not in [x["id"] for x in client.get("/api/sheets").json()]
    assert client.get(f"/api/sheets/{sid}").status_code == 404
    assert client.post(f"/api/sheets/{sid}/restore").json()["record_count"] == 1
    client.delete(f"/api/sheets/{sid}")
    assert client.delete(f"/api/sheets/{sid}/permanent").status_code == 204
    assert client.post(f"/api/sheets/{sid}/restore").status_code == 404


def test_move_records_between_sheets(client):
    as_user("a")
    src = mk_sheet(client, "Src", [{"name": "Company", "type": "text"}, {"name": "Notes", "type": "text"}])
    dst = mk_sheet(client, "Dst", [{"name": "company", "type": "text"}])
    rec = client.post(f"/api/sheets/{src['id']}/records", json={"data": {col(src, "Company"): "Z", col(src, "Notes"): "keep me"}}).json()
    body = {"ids": [rec["id"]], "target_sheet_id": dst["id"]}
    r = client.post("/api/records/move", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "columns_missing"  # never drops data silently
    assert r.json()["error"]["missing"] == ["Notes"]  # the UI shows exactly which columns are missing
    assert client.get(f"/api/sheets/{src['id']}/records").json()["total"] == 1
    r = client.post("/api/records/move", json={**body, "add_missing_columns": True})
    assert r.json()["moved"] == 1
    dst2 = client.get(f"/api/sheets/{dst['id']}").json()
    assert [c["name"] for c in dst2["columns"]] == ["company", "Notes"]
    moved = client.get(f"/api/sheets/{dst['id']}/records").json()["items"][0]["data"]
    assert sorted(moved.values()) == ["Z", "keep me"]
    assert client.get(f"/api/sheets/{src['id']}/records").json()["total"] == 0


def test_dashboard_and_all_records(client):
    as_user("a")
    st = client.get("/api/dashboard/stats").json()
    assert st["total_sheets"] >= 1 and st["total_records"] >= 1 and st["recent_activity"]
    r = client.get("/api/records", params={"q": "keep me"}).json()
    assert r["total"] >= 1 and "Notes" in r["items"][0]["data"]  # keyed by column name


def test_user_isolation_via_api(client):
    as_user("a")
    s = mk_sheet(client, "Private")
    rec = client.post(f"/api/sheets/{s['id']}/records", json={"data": {col(s, "Company"): "Secret"}}).json()
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/sheets").json() == []
    assert client.get(f"/api/sheets/{s['id']}").status_code == 404
    assert client.get(f"/api/sheets/{s['id']}/records").status_code == 404
    assert client.put(f"/api/sheets/{s['id']}", json={"name": "pwned"}).status_code == 404
    assert client.delete(f"/api/sheets/{s['id']}").status_code == 404
    assert client.post(f"/api/sheets/{s['id']}/records", json={"data": {}}).status_code == 404
    assert client.put(f"/api/records/{rec['id']}", json={"data": {col(s, "Company"): "pwned"}}).status_code == 404
    assert client.delete(f"/api/records/{rec['id']}").status_code == 404
    assert client.post("/api/records/bulk-delete", json={"ids": [rec["id"]]}).json()["deleted"] == 0
    mine = mk_sheet(client, "Mine")
    assert client.post("/api/records/move", json={"ids": [rec["id"]], "target_sheet_id": mine["id"]}).status_code == 404
    assert client.get("/api/records", params={"q": "Secret"}).json()["total"] == 0
    as_user("a")
    assert client.get(f"/api/sheets/{s['id']}/records").json()["items"][0]["data"][col(s, "Company")] == "Secret"
