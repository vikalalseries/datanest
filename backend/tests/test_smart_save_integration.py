"""Phase 4 API tests against the REAL database (skipped unless RLS_TEST=1). Gemini is faked."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app
from app.middleware.authentication import AuthUser, get_current_user
from app.services import gemini_service
from app.services import matching_service as m

pytestmark = pytest.mark.skipif(
    os.environ.get("RLS_TEST") != "1" or not get_settings().database_url,
    reason="set RLS_TEST=1 and DATABASE_URL to run against a real database",
)

TAG = uuid.uuid4().hex[:8]
current = {"uid": f"it-p4-{TAG}-a"}


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
            await conn.execute(text("delete from public.users where firebase_uid like :p"), {"p": f"it-p4-{TAG}-%"})
        await eng.dispose()

    asyncio.run(cleanup())


def as_user(w):
    current["uid"] = f"it-p4-{TAG}-{w}"


def mk(client, name, category, cols):
    r = client.post("/api/sheets", json={"name": name, "category": category, "columns": cols})
    assert r.status_code == 201, r.text
    return r.json()


def cid(sheet, name):
    return next(c["id"] for c in sheet["columns"] if c["name"] == name)


JOB_COLS = [{"name": "Employer", "type": "text"}, {"name": "Role", "type": "text"}, {"name": "Applied Date", "type": "date"}, {"name": "Status", "type": "status"}]
JOB_EX = {
    "category": "job_application",
    "columns": [{"name": "Company", "type": "text"}, {"name": "Position", "type": "text"}, {"name": "Date Applied", "type": "date"}, {"name": "Source", "type": "text"}],
    "records": [{"values": {"Company": "Dobbe AI", "Position": "AI Intern", "Date Applied": "2026-11-23", "Source": "LinkedIn"}}],
}
EXPENSE_EX = {
    "category": "expense",
    "columns": [{"name": "Merchant", "type": "text"}, {"name": "Amount", "type": "currency"}, {"name": "Date", "type": "date"}],
    "records": [{"values": {"Merchant": "Uber", "Amount": 230, "Date": "2026-11-19"}}],
}


def test_rank_sheets_puts_best_fit_first(client):
    as_user("a")
    jobs = mk(client, "My Jobs", "job_application", JOB_COLS)
    mk(client, "Spending", "expense", [{"name": "Merchant", "type": "text"}, {"name": "Amount", "type": "currency"}, {"name": "Date", "type": "date"}])
    ranked = client.post("/api/ai/rank-sheets", json=JOB_EX).json()
    assert ranked[0]["sheet_id"] == jobs["id"] and ranked[0]["category_match"]
    assert ranked[0]["score"] > ranked[1]["score"]
    ranked2 = client.post("/api/ai/rank-sheets", json=EXPENSE_EX).json()
    assert ranked2[0]["name"] == "Spending"


def test_match_columns_and_mismatch_explanation(client):
    as_user("a")
    sheets = {s["name"]: s for s in client.get("/api/sheets").json()}
    jobs = sheets["My Jobs"]
    r = client.post("/api/ai/match-columns", json={"sheet_id": jobs["id"], "extraction": JOB_EX, "use_ai": False}).json()
    mp = {x["extracted"]: x for x in r["mappings"]}
    assert mp["Company"]["sheet_column_name"] == "Employer" and mp["Position"]["sheet_column_name"] == "Role"
    assert mp["Date Applied"]["sheet_column_name"] == "Applied Date"
    assert r["unmapped_extracted"] == ["Source"] and r["unfilled_sheet_columns"] == ["Status"]  # reported, not hidden
    bad = client.post("/api/ai/match-columns", json={"sheet_id": jobs["id"], "extraction": EXPENSE_EX, "use_ai": False}).json()
    assert bad["suggestion"] == "create_new_sheet" and "expense" in bad["explanation"]


def test_ai_resolves_leftovers_and_failure_falls_back(client, monkeypatch):
    as_user("a")
    odd = mk(client, "Odd", "general", [{"name": "Employer", "type": "text"}, {"name": "Platform", "type": "text"}])
    ex = {"category": "general", "columns": [{"name": "Org", "type": "text"}, {"name": "Where I found it", "type": "text"}],
          "records": [{"values": {"Org": "X Corp", "Where I found it": "LinkedIn"}}]}

    async def fake_ai(schema, **kw):
        return m.GMatches(matches=[m.GMatch(extracted="Org", sheet_column="Employer", confidence=0.9),
                                   m.GMatch(extracted="Where I found it", sheet_column="Employer", confidence=0.9),  # duplicate target: ignored
                                   m.GMatch(extracted="Where I found it", sheet_column="Nonexistent", confidence=0.9)])

    monkeypatch.setattr(gemini_service, "generate_structured", fake_ai)
    r = client.post("/api/ai/match-columns", json={"sheet_id": odd["id"], "extraction": ex, "use_ai": True}).json()
    mp = {x["extracted"]: x for x in r["mappings"]}
    assert mp["Org"]["sheet_column_name"] == "Employer" and mp["Org"]["method"] == "ai"
    assert mp["Where I found it"]["sheet_column_id"] is None  # invalid / conflicting AI answers are rejected

    async def boom(schema, **kw):
        raise RuntimeError("AI down")

    monkeypatch.setattr(gemini_service, "generate_structured", boom)
    r = client.post("/api/ai/match-columns", json={"sheet_id": odd["id"], "extraction": ex, "use_ai": True})
    assert r.status_code == 200 and any("unavailable" in n for n in r.json()["notes"])


def bulk_body(extra=None, mapping=None, records=None):
    body = {
        "columns": JOB_EX["columns"],
        "mapping": mapping,
        "records": records or JOB_EX["records"],
        "source_type": "text",
    }
    body.update(extra or {})
    return body


def test_bulk_add_with_map_create_and_skip(client):
    as_user("a")
    jobs = {s["name"]: s for s in client.get("/api/sheets").json()}["My Jobs"]
    mapping = {
        "Company": {"action": "map", "column_id": cid(jobs, "Employer")},
        "Position": {"action": "map", "column_id": cid(jobs, "Role")},
        "Date Applied": {"action": "map", "column_id": cid(jobs, "Applied Date")},
        "Source": {"action": "create", "type": "text"},
    }
    r = client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=mapping))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["added"] == 1 and [c["name"] for c in out["sheet"]["columns"]][-1] == "Source"
    new_src = cid(out["sheet"], "Source")
    rec = client.get(f"/api/sheets/{jobs['id']}/records").json()["items"][0]["data"]
    assert rec[cid(jobs, "Employer")] == "Dobbe AI" and rec[new_src] == "LinkedIn" and rec[cid(jobs, "Applied Date")] == "2026-11-23"
    # explicit skip is allowed and recorded
    mapping2 = {**mapping, "Source": {"action": "skip"}}
    assert client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=mapping2)).status_code == 201
    log = client.get("/api/dashboard/stats").json()["recent_activity"]
    assert any(a["action"] == "records.bulk_add" for a in log)


def test_bulk_add_never_drops_data_silently_and_is_atomic(client):
    as_user("a")
    jobs = {s["name"]: s for s in client.get("/api/sheets").json()}["My Jobs"]
    base = {"Company": {"action": "map", "column_id": cid(jobs, "Employer")}, "Position": {"action": "map", "column_id": cid(jobs, "Role")},
            "Date Applied": {"action": "map", "column_id": cid(jobs, "Applied Date")}}
    r = client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=base))  # 'Source' has data but no decision
    assert r.status_code == 422 and r.json()["error"]["code"] == "mapping_incomplete" and r.json()["error"]["missing"] == ["Source"]
    dup = {**base, "Source": {"action": "map", "column_id": cid(jobs, "Employer")}}
    assert client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=dup)).status_code == 409
    unknown = {**base, "Source": {"action": "map", "column_id": "c_nope"}}
    assert client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=unknown)).status_code == 422
    existing_name = {**base, "Source": {"action": "create"}, "Company": {"action": "create"}}  # would clash with nothing; Employer still unmapped is fine
    # invalid value in one row: new column must NOT remain
    before = client.get(f"/api/sheets/{jobs['id']}").json()
    ex = {"columns": [{"name": "Company", "type": "text"}, {"name": "Date Applied", "type": "date"}, {"name": "Extra", "type": "text"}],
          "mapping": {"Company": {"action": "map", "column_id": cid(jobs, "Employer")},
                      "Date Applied": {"action": "map", "column_id": cid(jobs, "Applied Date")}, "Extra": {"action": "create"}},
          "records": [{"values": {"Company": "Ok", "Date Applied": "2026-01-01", "Extra": "x"}}, {"values": {"Company": "Bad", "Date Applied": "next spring", "Extra": "y"}}]}
    r = client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=ex)
    assert r.status_code == 422 and "Row 2" in r.json()["error"]["message"]
    after = client.get(f"/api/sheets/{jobs['id']}").json()
    assert after["columns"] == before["columns"] and after["record_count"] == before["record_count"]
    # creating a column whose name already exists is refused with guidance
    clash = {"columns": [{"name": "Role", "type": "text"}], "mapping": {"Role": {"action": "create"}}, "records": [{"values": {"Role": "x"}}]}
    r = client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=clash)
    assert r.status_code == 409 and "instead" in r.json()["error"]["message"]


def test_check_duplicates(client):
    as_user("a")
    jobs = {s["name"]: s for s in client.get("/api/sheets").json()}["My Jobs"]
    mapping = {"Company": {"action": "map", "column_id": cid(jobs, "Employer")}, "Position": {"action": "map", "column_id": cid(jobs, "Role")},
               "Date Applied": {"action": "map", "column_id": cid(jobs, "Applied Date")}, "Source": {"action": "skip"}}
    rows = [
        {"values": {"Company": "dobbe ai", "Position": "AI intern", "Date Applied": "2026-11-23"}},  # same as saved
        {"values": {"Company": "Dobbe AI", "Position": "Data Analyst", "Date Applied": "2026-12-01"}},  # new role
        {"values": {"Company": "Acme", "Position": "Dev", "Date Applied": "2026-12-02"}},
        {"values": {"Company": "Acme", "Position": "Dev", "Date Applied": "2026-12-02"}},  # repeated inside the batch
    ]
    r = client.post(f"/api/sheets/{jobs['id']}/records/check-duplicates", json={"columns": JOB_EX["columns"], "mapping": mapping, "records": rows}).json()
    assert [d["row"] for d in r["duplicates"]] == [0] and r["duplicates"][0]["similarity"] == 1.0
    assert r["duplicates"][0]["existing"]["Employer"] == "Dobbe AI"
    assert r["within_batch"] == [{"row": 3, "duplicate_of_row": 2, "similarity": 1.0}]


def test_suggest_sheet_gives_unique_name_and_status_options(client):
    as_user("a")
    ex = {"category": "job_application", "columns": [{"name": "Company", "type": "text"}, {"name": "Stage", "type": "status"}],
          "records": [{"values": {"Company": "A", "Stage": "Applied"}}, {"values": {"Company": "B", "Stage": "Interview"}}, {"values": {"Company": "C", "Stage": "Applied"}}]}
    s = client.post("/api/ai/suggest-sheet", json=ex).json()
    assert s["name"] == "Job Application"
    mk(client, "Job Application", "job_application", [{"name": "Company", "type": "text"}])
    s2 = client.post("/api/ai/suggest-sheet", json=ex).json()
    assert s2["name"] == "Job Application 2"
    assert next(c for c in s2["columns"] if c["name"] == "Stage")["options"] == ["Applied", "Interview"]
    assert "Job Application" in [x["name"] for x in s2["similar_sheets"]]


def test_merge_sheets(client):
    as_user("a")
    a = mk(client, "Merge A", "general", [{"name": "Name", "type": "text"}])
    b = mk(client, "Merge B", "general", [{"name": "name", "type": "text"}, {"name": "Phone", "type": "text"}])
    client.post(f"/api/sheets/{a['id']}/records", json={"data": {cid(a, "Name"): "Ann"}})
    client.post(f"/api/sheets/{b['id']}/records", json={"data": {cid(b, "name"): "Bob", cid(b, "Phone"): "123"}})
    assert client.post(f"/api/sheets/{a['id']}/merge", json={"source_sheet_id": a["id"]}).status_code == 422
    r = client.post(f"/api/sheets/{a['id']}/merge", json={"source_sheet_id": b["id"]})
    assert r.status_code == 409 and r.json()["error"]["missing"] == ["Phone"]  # incompatible unless the user allows adding columns
    assert client.get(f"/api/sheets/{b['id']}").json()["record_count"] == 1  # nothing moved
    r = client.post(f"/api/sheets/{a['id']}/merge", json={"source_sheet_id": b["id"], "add_missing_columns": True, "trash_source": True})
    assert r.status_code == 200 and r.json()["moved"] == 1
    merged = r.json()["sheet"]
    assert [c["name"] for c in merged["columns"]] == ["Name", "Phone"] and merged["record_count"] == 2
    assert b["id"] not in [s["id"] for s in client.get("/api/sheets").json()]  # source went to Trash
    assert any(s["id"] == b["id"] for s in client.get("/api/trash").json()["sheets"])


def test_other_users_cannot_use_my_sheets(client):
    as_user("a")
    jobs = {s["name"]: s for s in client.get("/api/sheets").json()}["My Jobs"]
    mine = mk(client, "Scratch", "general", [{"name": "X", "type": "text"}])
    as_user("b")
    assert client.get("/api/auth/me").status_code == 200
    mapping = {"Company": {"action": "create"}, "Position": {"action": "create"}, "Date Applied": {"action": "create"}, "Source": {"action": "create"}}
    assert client.post(f"/api/sheets/{jobs['id']}/records/bulk", json=bulk_body(mapping=mapping)).status_code == 404
    assert client.post(f"/api/sheets/{jobs['id']}/records/check-duplicates", json={"columns": JOB_EX["columns"], "mapping": mapping, "records": JOB_EX["records"]}).status_code == 404
    assert client.post("/api/ai/match-columns", json={"sheet_id": jobs["id"], "extraction": JOB_EX, "use_ai": False}).status_code == 404
    assert client.post(f"/api/sheets/{jobs['id']}/merge", json={"source_sheet_id": mine["id"]}).status_code == 404
    assert client.post("/api/ai/rank-sheets", json=JOB_EX).json() == []  # B has no sheets: A's are invisible
