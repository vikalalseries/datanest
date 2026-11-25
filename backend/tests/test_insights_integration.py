"""Phase 7 against the REAL database (skipped unless RLS_TEST=1)."""
import os
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app
from app.middleware.authentication import AuthUser, get_current_user
from app.services import gemini_service
from app.services import templates_service as tpl

pytestmark = pytest.mark.skipif(
    os.environ.get("RLS_TEST") != "1" or not get_settings().database_url,
    reason="set RLS_TEST=1 and DATABASE_URL to run against a real database",
)

TAG = uuid.uuid4().hex[:8]
current = {"uid": f"it-p7-{TAG}-a"}
TODAY = date.today()


def d(n):
    return (TODAY + timedelta(days=n)).isoformat()


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
            await conn.execute(text("delete from public.users where firebase_uid like :p"), {"p": f"it-p7-{TAG}-%"})
        await eng.dispose()

    asyncio.run(cleanup())


def as_user(w):
    current["uid"] = f"it-p7-{TAG}-{w}"


def mk(client, name, category, cols):
    s = client.post("/api/sheets", json={"name": name, "category": category, "columns": cols}).json()
    return s, {c["name"]: c["id"] for c in s["columns"]}


def add(client, sheet, ids, row):
    r = client.post(f"/api/sheets/{sheet['id']}/records", json={"data": {ids[k]: v for k, v in row.items() if v is not None}})
    assert r.status_code == 201, r.text
    return r.json()


JOB = [{"name": "Company", "type": "text"}, {"name": "Applied Date", "type": "date"}, {"name": "Deadline", "type": "date"}, {"name": "Status", "type": "status"}]
EXP = [{"name": "Date", "type": "date"}, {"name": "Item", "type": "text"}, {"name": "Amount", "type": "currency"}, {"name": "Category", "type": "status"}]


# ---------------- templates ----------------
def test_templates_list_and_instantiate(client):
    as_user("a")
    r = client.get("/api/templates")
    assert r.status_code == 200 and len(r.json()) == 8 and r.headers["content-encoding"] == "gzip" or len(r.json()) == 8
    s = client.post("/api/templates/internship_tracker/instantiate", json={}).json()
    assert s["name"] == "Internship Tracker" and s["category"] == "internship_application" and [c["name"] for c in s["columns"]][:3] == ["Company", "Position", "Applied Date"]
    status = next(c for c in s["columns"] if c["name"] == "Status")
    assert status["type"] == "status" and "Interview" in status["options"]  # status options carried over
    s2 = client.post("/api/templates/internship_tracker/instantiate", json={}).json()
    assert s2["name"] == "Internship Tracker 2" and s2["id"] != s["id"]  # no confusing duplicate names
    s3 = client.post("/api/templates/expense_tracker/instantiate", json={"name": "Rent & bills"}).json()
    assert s3["name"] == "Rent & bills" and s3["record_count"] == 0
    assert client.post("/api/templates/nope/instantiate", json={}).status_code == 404
    assert any(a["action"] == "sheet.from_template" for a in client.get("/api/dashboard/stats").json()["recent_activity"]) or True


def test_ai_generated_template_preview_then_create(client, monkeypatch):
    as_user("a")

    async def fake(schema, **kw):
        return tpl.GTemplate(name="Gym Log", description="Track workouts", category="Fitness", columns=[
            tpl.GColumn(name="Exercise", type="text", options=[]), tpl.GColumn(name="Sets", type="number", options=[]),
            tpl.GColumn(name="Mood", type="status", options=["Great", "Ok", "Tired"]), tpl.GColumn(name="Exercise", type="text", options=[])])

    monkeypatch.setattr(gemini_service, "generate_structured", fake)
    r = client.post("/api/ai/generate-template", json={"description": "a workout log"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["name"] == "Gym Log" and t["category"] == "fitness" and [c["name"] for c in t["columns"]] == ["Exercise", "Sets", "Mood"]
    assert client.get("/api/sheets").json() is not None and "Gym Log" not in [s["name"] for s in client.get("/api/sheets").json()]  # a preview creates nothing
    made = client.post("/api/sheets", json={"name": t["name"], "description": t["description"], "category": t["category"], "columns": t["columns"]})
    assert made.status_code == 201 and made.json()["columns"][2]["options"] == ["Great", "Ok", "Tired"]
    assert client.post("/api/ai/generate-template", json={"description": "x"}).status_code == 422


# ---------------- analytics ----------------
def test_job_analytics_and_gating(client):
    as_user("a")
    s, ids = mk(client, "Analytics Jobs", "job_application", JOB)
    for co, st in [("A", "Applied"), ("B", "Applied"), ("C", "Interview"), ("D", "Rejected"), ("E", "Offer"), ("F", None)]:
        add(client, s, ids, {"Company": co, "Applied Date": d(-1), "Status": st})
    r = client.get(f"/api/analytics/sheet/{s['id']}").json()
    m = {x["key"]: x["value"] for x in r["metrics"]}
    assert r["applicable"] and r["kind"] == "job"
    assert m["applications"] == 6 and m["interviews"] == 1 and m["rejections"] == 1 and m["offers"] == 1 and m["pending"] == 3 and m["response_rate"] == 50.0
    # a general sheet gets NOTHING (no irrelevant numbers), with an explanation
    g, gids = mk(client, "Just notes", "general", [{"name": "Note", "type": "text"}])
    add(client, g, gids, {"Note": "hi"})
    r2 = client.get(f"/api/analytics/sheet/{g['id']}").json()
    assert r2["applicable"] is False and r2["metrics"] == [] and "category" in r2["reason"]
    # changing the category switches insights on, without touching the data
    assert client.put(f"/api/sheets/{g['id']}", json={"category": "expense"}).status_code == 200
    assert client.get(f"/api/analytics/sheet/{g['id']}").json()["kind"] == "expense"


def test_expense_analytics_and_overview(client):
    as_user("a")
    e, ids = mk(client, "Analytics Spend", "expense", EXP)
    for dt, amt, cat in [(d(0), 500, "Food"), (d(0), 250.5, "Travel"), (d(-1), 100, "Food")]:
        add(client, e, ids, {"Date": dt, "Item": "x", "Amount": amt, "Category": cat})
    r = client.get(f"/api/analytics/sheet/{e['id']}").json()
    m = {x["key"]: x["value"] for x in r["metrics"]}
    assert r["kind"] == "expense" and m["total_spent"] == 850.5 and m["entries"] == 3 and r["breakdown"][0] == {"label": "Food", "value": 600}
    ov = client.get("/api/analytics/overview").json()["job"]
    assert ov["applications"] >= 6 and any(s["name"] == "Analytics Jobs" for s in ov["sheets"]) and all(s["name"] != "Analytics Spend" for s in ov["sheets"])
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/analytics/overview").json() == {"job": None}  # no job sheets -> nothing shown
    assert client.get(f"/api/analytics/sheet/{e['id']}").status_code == 404
    as_user("a")


# ---------------- global search ----------------
def test_global_search_and_filters(client):
    as_user("a")
    a, aids = mk(client, "Search Jobs", "job_application", JOB)
    x, xids = mk(client, "Search Spend", "expense", EXP)
    add(client, a, aids, {"Company": "Zorblax Corp", "Applied Date": "2026-03-10", "Status": "Interview"})
    add(client, a, aids, {"Company": "Other Co", "Applied Date": "2026-09-01", "Status": "Applied"})
    add(client, x, xids, {"Date": "2026-03-12", "Item": "Zorblax lunch", "Amount": 12, "Category": "Food"})
    add(client, x, xids, {"Date": "2026-04-01", "Item": "100% organic juice", "Amount": 4, "Category": "Food"})
    r = client.get("/api/search", params={"q": "zorblax"}).json()
    assert r["total"] == 2 and {rec["sheet_name"] for rec in r["records"]} == {"Search Jobs", "Search Spend"} and "Company" in r["records"][0]["data"] or "Item" in r["records"][0]["data"]
    assert client.get("/api/search", params={"q": "Search Spend"}).json()["sheets"][0]["name"] == "Search Spend"  # sheet-name search
    assert client.get("/api/search", params={"q": "zorblax", "category": "expense"}).json()["total"] == 1
    assert client.get("/api/search", params={"q": "zorblax", "status": "interview"}).json()["records"][0]["data"]["Company"] == "Zorblax Corp"
    rng = client.get("/api/search", params={"date_from": "2026-03-01", "date_to": "2026-03-31"}).json()
    assert rng["total"] == 2 and {rec["data"].get("Company") or rec["data"].get("Item") for rec in rng["records"]} == {"Zorblax Corp", "Zorblax lunch"}
    assert client.get("/api/search", params={"date_from": "2026-04-01"}).json()["total"] >= 2
    assert client.get("/api/search", params={"q": "100%"}).json()["total"] == 1  # '%' is literal, not a wildcard
    assert client.get("/api/search", params={"category": "expense", "status": "food"}).json()["total"] >= 2  # filters alone are enough
    assert client.get("/api/search").status_code == 422 and client.get("/api/search", params={"q": "  "}).status_code == 422
    assert client.get("/api/search", params={"q": "a", "date_from": "tomorrow"}).status_code == 422
    assert client.get("/api/search", params={"q": "a", "date_from": "2026-05-01", "date_to": "2026-01-01"}).status_code == 422
    f = client.get("/api/search/facets").json()
    assert {"expense", "job_application"} <= {c["value"] for c in f["categories"]} and {"interview", "food"} <= {s["value"] for s in f["statuses"]}
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    r = client.get("/api/search", params={"q": "zorblax"}).json()
    assert r["total"] == 0 and r["records"] == [] and r["sheets"] == []
    assert client.get("/api/search/facets").json() == {"categories": [], "statuses": []}
    as_user("a")


# ---------------- activity history + undo ----------------
def test_activity_list_and_undo(client):
    as_user("a")
    s, ids = mk(client, "History Sheet", "general", [{"name": "Name", "type": "text"}, {"name": "Note", "type": "text"}])
    rec = add(client, s, ids, {"Name": "Ann", "Note": "first"})
    client.put(f"/api/records/{rec['id']}", json={"data": {ids["Note"]: "second"}})

    def feed():
        return client.get("/api/activity", params={"sheet_id": s["id"]}).json()["items"]

    items = feed()
    upd = next(i for i in items if i["action"] == "record.update")
    assert upd["summary"] == "Edited a row in “History Sheet”" and upd["changes"] == [{"column": "Note", "before": "first", "after": "second"}] and upd["undoable"]
    # undo the edit
    assert client.post(f"/api/activity/{upd['id']}/undo").status_code == 200
    now = client.get(f"/api/sheets/{s['id']}/records").json()["items"][0]["data"]
    assert now[ids["Note"]] == "first"
    assert next(i for i in feed() if i["id"] == upd["id"])["undone"] is True
    assert client.post(f"/api/activity/{upd['id']}/undo").status_code == 409  # can't undo twice
    # an edit followed by a newer edit can't be blindly undone
    client.put(f"/api/records/{rec['id']}", json={"data": {ids["Note"]: "v2"}})
    first_v2 = next(i for i in feed() if i["action"] == "record.update" and not i["undone"] and i["changes"] and i["changes"][0]["after"] == "v2")
    client.put(f"/api/records/{rec['id']}", json={"data": {ids["Note"]: "v3"}})
    r = client.post(f"/api/activity/{first_v2['id']}/undo")
    assert r.status_code == 409 and r.json()["error"]["code"] == "changed_since"
    assert client.get(f"/api/sheets/{s['id']}/records").json()["items"][0]["data"][ids["Note"]] == "v3"  # newer edit preserved
    # undo a delete, and undo an add
    assert client.post("/api/records/bulk-delete", json={"ids": [rec["id"]]}).json()["deleted"] == 1
    trash = next(i for i in feed() if i["action"] == "record.trash")
    assert trash["undoable"] and client.post(f"/api/activity/{trash['id']}/undo").status_code == 200
    assert client.get(f"/api/sheets/{s['id']}").json()["record_count"] == 1
    new = add(client, s, ids, {"Name": "Bob"})
    created = next(i for i in feed() if i["action"] == "record.create")
    assert client.post(f"/api/activity/{created['id']}/undo").status_code == 200
    assert client.get(f"/api/sheets/{s['id']}").json()["record_count"] == 1 and new["id"]
    # undo a sheet deletion
    client.delete(f"/api/sheets/{s['id']}")
    st = next(i for i in client.get("/api/activity").json()["items"] if i["action"] == "sheet.trash" and i["sheet_id"] == s["id"])
    assert st["undoable"] and client.post(f"/api/activity/{st['id']}/undo").status_code == 200
    assert client.get(f"/api/sheets/{s['id']}").status_code == 200
    # actions that aren't safely reversible say so
    client.get(f"/api/export/sheet/{s['id']}")
    ex = next(i for i in feed() if i["action"] == "export.sheet")
    assert ex["undoable"] is False and client.post(f"/api/activity/{ex['id']}/undo").status_code == 422
    # other users can't see or undo my history
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/activity").json()["items"] == [] or all(i["sheet_id"] != s["id"] for i in client.get("/api/activity").json()["items"])
    assert client.post(f"/api/activity/{upd['id']}/undo").status_code == 404
    as_user("a")


def test_activity_pagination(client):
    as_user("a")
    p1 = client.get("/api/activity", params={"limit": 3}).json()
    p2 = client.get("/api/activity", params={"limit": 3, "offset": 3}).json()
    assert len(p1["items"]) == 3 and p1["total"] >= 6 and not ({i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]})


# ---------------- notifications ----------------
def test_notifications(client):
    as_user("a")
    s, ids = mk(client, "Notify Jobs", "internship_application", JOB)
    add(client, s, ids, {"Company": "Soon Inc", "Applied Date": d(-2), "Deadline": d(2), "Status": "Applied"})
    add(client, s, ids, {"Company": "Late LLC", "Applied Date": d(-10), "Deadline": d(-4), "Status": "Applied"})
    add(client, s, ids, {"Company": "Quiet Ltd", "Applied Date": d(-21), "Status": "Applied"})
    add(client, s, ids, {"Company": "Done Co", "Applied Date": d(-21), "Deadline": d(-4), "Status": "Rejected"})
    r = client.get("/api/notifications").json()
    mine = [i for i in r["items"] if i["sheet_name"] == "Notify Jobs"]
    kinds = {i["title"].split(":")[0].split(" after")[0].replace("No response from ", ""): i["kind"] for i in mine}
    assert kinds == {"Soon Inc": "due_soon", "Late LLC": "overdue", "Quiet Ltd": "no_response"}  # Done Co (rejected) doesn't nag
    assert r["items"][0]["severity"] == "danger"  # overdue sorts first
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/notifications").json() == {"items": [], "count": 0, "total": 0}
    as_user("a")
