"""AI endpoint tests. Gemini is faked (deterministic); DB, validation, upload handling and saving are real.
Skipped unless RLS_TEST=1 (needs the real database)."""
import io
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app
from app.middleware.authentication import AuthUser, get_current_user
from app.services import extraction_service as ex

pytestmark = pytest.mark.skipif(
    os.environ.get("RLS_TEST") != "1" or not get_settings().database_url,
    reason="set RLS_TEST=1 and DATABASE_URL to run against a real database",
)

UID = f"it-ai-{uuid.uuid4().hex[:8]}"


def F(c, v, origin="extracted", unc=False):
    return ex.GField(column=c, value=v, origin=origin, uncertain=unc)


CANNED = ex.GResult(
    category="internship_application", suggested_sheet_name="Internship Applications", description="Applications",
    columns=[ex.GColumn(name="Company", type="text"), ex.GColumn(name="Position", type="text"), ex.GColumn(name="Applied Date", type="date"), ex.GColumn(name="Status", type="status")],
    records=[ex.GRecord(fields=[F("Company", "Dobbe AI"), F("Position", "AI Intern"), F("Applied Date", "2026-11-23"), F("Status", "Applied", "inferred")])],
    missing_fields=["Deadline"], confidence=0.93, warnings=[],
)


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(uid=UID, email=f"{UID}@it.invalid")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    import asyncio

    async def cleanup():
        eng = create_async_engine(get_settings().async_database_url, connect_args={"statement_cache_size": 0})
        async with eng.begin() as conn:
            await conn.execute(text("delete from public.users where firebase_uid = :u"), {"u": UID})
        await eng.dispose()

    asyncio.run(cleanup())


@pytest.fixture
def fake_gemini(monkeypatch):
    seen = {}

    async def fake(parts):
        seen["parts"] = parts
        return CANNED

    monkeypatch.setattr(ex, "run_gemini", fake)
    return seen


def png(size=(40, 30)):
    b = io.BytesIO()
    Image.new("RGB", size, "white").save(b, "PNG")
    return b.getvalue()


def test_extract_text_returns_editable_preview(client, fake_gemini):
    r = client.post("/api/ai/extract/text", json={"text": "I applied for an AI internship at Dobbe AI on 23 Nov 2026 via LinkedIn"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["category"] == "internship_application"
    assert d["records"][0]["values"]["Company"] == "Dobbe AI"
    assert d["records"][0]["meta"]["Status"] == {"origin": "inferred", "uncertain": True, "raw": None}
    assert d["missing_fields"] == ["Deadline"] and d["source"]["type"] == "text"
    # the user text reached the model wrapped as data, with today's date for relative-date resolution
    assert any("<content>" in str(p) for p in fake_gemini["parts"])


def test_extract_text_empty_rejected(client, fake_gemini):
    assert client.post("/api/ai/extract/text", json={"text": "   "}).json()["error"]["code"] == "empty_input"
    assert client.post("/api/ai/extract/text", json={"text": "x" * 20_001}).status_code == 422


def test_extract_url_blocks_ssrf_targets(client, fake_gemini):
    for url in ["http://127.0.0.1/", "http://localhost:8000/api/auth/me", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "http://10.0.0.1/"]:
        r = client.post("/api/ai/extract/url", json={"url": url})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_url", (url, r.text)
    assert "parts" not in fake_gemini  # nothing was fetched/sent to the AI


def test_extract_image_valid_and_invalid(client, fake_gemini):
    r = client.post("/api/ai/extract/image", files={"file": ("shot.png", png(), "image/png")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"]["type"] == "image" and d["records"][0]["values"]["Company"] == "Dobbe AI"
    for name, data in [("a.txt", b"hello"), ("evil.png", b"<?php system($_GET[0]);"), ("a.gif", png()), ("empty.png", b"")]:
        r = client.post("/api/ai/extract/image", files={"file": (name, data, "image/png")})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_image", (name, r.text)
    big = client.post("/api/ai/extract/image", files={"file": ("big.png", b"\x89PNG" + b"0" * (6 * 1024 * 1024), "image/png")})
    assert big.status_code == 422


def test_gemini_failures_become_friendly_errors(client, monkeypatch):
    from fastapi import HTTPException

    async def boom(parts):
        raise HTTPException(status_code=429, detail={"code": "ai_rate_limited", "message": "busy"})

    monkeypatch.setattr(ex, "run_gemini", boom)
    r = client.post("/api/ai/extract/text", json={"text": "something to extract"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_rate_limited"


def test_save_extraction_as_new_sheet(client, fake_gemini):
    d = client.post("/api/ai/extract/text", json={"text": "anything long enough"}).json()
    # user edits a value in the preview before saving
    d["records"][0]["values"]["Position"] = "Generative AI Intern"
    body = {
        "name": d["suggested_sheet_name"], "description": d["description"], "category": d["category"],
        "columns": d["columns"], "records": [{"values": r["values"]} for r in d["records"]],
        "source_type": "text",
    }
    r = client.post("/api/sheets/from-extraction", json=body)
    assert r.status_code == 201, r.text
    sheet = r.json()
    assert sheet["record_count"] == 1 and [c["name"] for c in sheet["columns"]] == ["Company", "Position", "Applied Date", "Status"]
    recs = client.get(f"/api/sheets/{sheet['id']}/records").json()["items"]
    by_name = {c["name"]: c["id"] for c in sheet["columns"]}
    assert recs[0]["data"][by_name["Position"]] == "Generative AI Intern" and recs[0]["source_type"] == "text"


def test_save_extraction_is_atomic_on_invalid_row(client):
    before = len(client.get("/api/sheets").json())
    body = {
        "name": "Should not exist", "columns": [{"name": "Amount", "type": "number"}],
        "records": [{"values": {"Amount": "12"}}, {"values": {"Amount": "lots"}}], "source_type": "text",
    }
    r = client.post("/api/sheets/from-extraction", json=body)
    assert r.status_code == 422 and "Row 2" in r.json()["error"]["message"]
    assert len(client.get("/api/sheets").json()) == before  # nothing half-saved
