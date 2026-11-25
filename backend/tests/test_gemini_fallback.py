"""The model-fallback logic, with a scripted fake Gemini client (no network, no waiting)."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.config import get_settings
from app.services import gemini_service as g


class Out(BaseModel):
    answer: str


def api_error(code: int, status: str):
    return genai_errors.APIError(code, {"error": {"code": code, "message": "x", "status": status}})


class FakeModels:
    """script: {model: [outcome, ...]} where outcome is 'ok', an APIError, 'timeout', or 'bad_thinking' (400 only when thinking is set)."""

    def __init__(self, script):
        self.script, self.calls = {k: list(v) for k, v in script.items()}, []

    async def generate_content(self, *, model, contents, config):
        thinking = getattr(config, "thinking_config", None) is not None
        self.calls.append((model, thinking))
        queue = self.script.get(model, [])
        outcome = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else "ok")
        if outcome == "timeout":
            await asyncio.sleep(10)  # longer than any per-attempt timeout used in these tests
        if outcome == "bad_thinking":
            if thinking:
                raise api_error(400, "INVALID_ARGUMENT")
            outcome = "ok"
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(parsed=Out(answer=f"from {model}"), text='{"answer": "x"}', candidates=[])


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "second, third")
    get_settings.cache_clear()
    g.reset_health()
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(g.asyncio, "sleep", fake_sleep) if False else None

    def install(script):
        fm = FakeModels(script)
        monkeypatch.setattr(g, "get_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=fm)))
        return fm

    yield install
    get_settings.cache_clear()
    g.reset_health()


def run(**kw):
    return asyncio.run(g.generate_structured(Out, system="s", parts=["p"], **kw))


def test_chain_order_and_dedupe(setup):
    assert g.model_chain() == ["primary", "second", "third"]
    assert g.model_chain(prefer="third") == ["third", "primary", "second"]
    assert g.normalize_model("Gemini 3.5 Flash Lite") == "gemini-3.5-flash-lite"


def test_healthy_primary_is_used_with_one_call(setup):
    fm = setup({"primary": ["ok"]})
    assert run().answer == "from primary" and [c[0] for c in fm.calls] == ["primary"]


def test_overloaded_primary_falls_through_immediately(setup):
    fm = setup({"primary": [api_error(503, "UNAVAILABLE")], "second": ["ok"]})
    t = time.monotonic()
    assert run().answer == "from second"
    assert [c[0] for c in fm.calls] == ["primary", "second"]
    assert time.monotonic() - t < 1.0  # no waiting on a model that is down


def test_quota_exhausted_model_falls_through_too(setup):
    fm = setup({"primary": [api_error(429, "RESOURCE_EXHAUSTED")], "second": [api_error(503, "UNAVAILABLE")], "third": ["ok"]})
    assert run().answer == "from third"


def test_slow_primary_times_out_and_the_next_model_answers(setup):
    fm = setup({"primary": ["timeout"], "second": ["ok"]})
    t = time.monotonic()
    assert run(timeout=0.3).answer == "from second"
    assert time.monotonic() - t < 2.0


def test_missing_model_is_skipped(setup):
    fm = setup({"primary": [api_error(404, "NOT_FOUND")], "second": ["ok"]})
    assert run().answer == "from second"


def test_thinking_setting_rejected_by_a_model_is_retried_without_it(setup):
    fm = setup({"primary": ["bad_thinking"]})
    assert run().answer == "from primary"
    assert fm.calls == [("primary", True), ("primary", False)]  # same model, no thinking, no fallback needed


def test_everything_overloaded_gives_a_friendly_bounded_error(setup, monkeypatch):
    fm = setup({m: [api_error(503, "UNAVAILABLE")] for m in ("primary", "second", "third")})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    t = time.monotonic()
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.status_code == 502 and e.value.detail["code"] == "ai_unavailable" and "very busy" in e.value.detail["message"]
    assert len(fm.calls) == 6 and time.monotonic() - t < 3  # two passes over three models, no long waits


def test_all_quota_errors_report_rate_limit(setup, monkeypatch):
    setup({m: [api_error(429, "RESOURCE_EXHAUSTED")] for m in ("primary", "second", "third")})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.status_code == 429 and e.value.detail["code"] == "ai_rate_limited"


def test_bad_key_fails_fast_without_trying_other_models(setup):
    fm = setup({"primary": [api_error(403, "PERMISSION_DENIED")]})
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.detail["code"] == "ai_rejected" and len(fm.calls) == 1


def test_total_time_budget_is_respected(setup):
    fm = setup({m: ["timeout"] for m in ("primary", "second", "third")})
    t = time.monotonic()
    with pytest.raises(HTTPException) as e:
        run(timeout=10, budget=3.4)  # budget leaves room for exactly one attempt
    assert e.value.detail["code"] == "ai_timeout" and time.monotonic() - t < 4.5 and len(fm.calls) == 1


def test_last_model_is_recorded_so_chats_can_stay_on_one_model(setup):
    setup({"primary": [api_error(503, "UNAVAILABLE")], "second": ["ok"]})

    async def flow():  # same task, as in a real request: step 1 records the model, step 2 is pinned to it
        await g.generate_structured(Out, system="s", parts=["p"])
        return g.last_model.get()

    assert asyncio.run(flow()) == "second"
    fm = setup({"primary": ["ok"], "second": ["ok"]})
    asyncio.run(g.generate_raw(system="s", contents=["c"], prefer_model="second"))
    assert fm.calls[0][0] == "second"  # a conversation stays on the model that started it


# ---------------- slow models, memory of failures, quota messages ----------------
def quota_error(retry_s=None, daily=False):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if daily else "RequestsPerMinute", "quotaValue": "20"}]}]
    if retry_s:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{retry_s}s"})
    return genai_errors.APIError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED", "details": details}})


def test_a_slow_model_gets_a_parallel_backup_and_the_first_answer_wins(setup, monkeypatch):
    monkeypatch.setattr(g, "HEDGE_AFTER", 0.2)
    fm = setup({"primary": ["timeout"], "second": ["ok"]})  # primary would take 10 s
    t = time.monotonic()
    assert run(timeout=15, budget=30).answer == "from second"
    assert time.monotonic() - t < 2.0  # didn't wait for the slow one
    assert [c[0] for c in fm.calls] == ["primary", "second"]  # both were started: the backup ran alongside


def test_a_fast_primary_is_never_hedged(setup, monkeypatch):
    monkeypatch.setattr(g, "HEDGE_AFTER", 0.2)
    fm = setup({"primary": ["ok"]})
    assert run().answer == "from primary" and len(fm.calls) == 1  # no extra quota spent when the first model answers promptly


def test_models_that_just_failed_are_tried_last_next_time(setup):
    fm = setup({"primary": [api_error(503, "UNAVAILABLE")], "second": ["ok"]})
    run()
    assert [c[0] for c in fm.calls] == ["primary", "second"]
    fm.calls.clear()
    assert run().answer == "from second" and [c[0] for c in fm.calls] == ["second"]  # goes straight to the healthy model
    assert g._ordered_chain(None)[0] == "second"


def test_a_model_that_recovers_goes_back_to_the_front(setup, monkeypatch):
    fm = setup({"primary": [api_error(503, "UNAVAILABLE"), "ok"], "second": ["ok"]})
    run()  # primary fails, second answers
    monkeypatch.setattr(g, "BUSY_COOLDOWN", 0)
    g._health["primary"]["until"] = 0  # cooldown over
    assert run().answer == "from primary"  # primary is tried first again and has recovered
    assert "primary" not in g._health


def test_daily_quota_message_gives_the_real_reset_time_and_options(setup, monkeypatch):
    setup({m: [quota_error(45066, daily=True)] for m in ("primary", "second", "third")})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    with pytest.raises(HTTPException) as e:
        run()
    d = e.value.detail
    assert e.value.status_code == 429 and d["code"] == "ai_rate_limited" and d["retry_after_seconds"] == 45066
    assert "Today's free AI quota is used up" in d["message"] and "about 13 hours" in d["message"] and "billing" in d["message"]


def test_per_minute_limit_message_is_short(setup, monkeypatch):
    setup({m: [quota_error(30, daily=False)] for m in ("primary", "second", "third")})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    with pytest.raises(HTTPException) as e:
        run()
    assert "a minute" in e.value.detail["message"] and "billing" not in e.value.detail["message"]


def test_mixed_quota_and_overload_says_so(setup, monkeypatch):
    setup({"primary": [api_error(503, "UNAVAILABLE")], "second": [quota_error(100, True)], "third": [quota_error(100, True)]})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.detail["code"] == "ai_unavailable" and "out of free quota" in e.value.detail["message"]


def test_status_reports_each_models_state_without_calling_the_api(setup):
    fm = setup({"primary": [api_error(503, "UNAVAILABLE")], "second": [quota_error(7200, True)], "third": ["ok"]})
    run()
    calls_before = len(fm.calls)
    st = g.status()
    by = {m["name"]: m for m in st["models"]}
    assert by["primary"]["state"] == "busy" and by["second"]["state"] == "quota" and by["second"]["daily"] is True
    assert 7000 < by["second"]["resets_in_seconds"] <= 7200 and by["third"]["state"] == "ok"
    assert st["any_available"] is True and len(fm.calls) == calls_before  # asking for status costs nothing


def test_status_when_nothing_is_available(setup, monkeypatch):
    setup({m: [quota_error(7200, True)] for m in ("primary", "second", "third")})
    monkeypatch.setattr(g, "PASS_PAUSE", 0.01)
    with pytest.raises(HTTPException):
        run()
    assert g.status()["any_available"] is False


def test_a_model_that_keeps_failing_is_avoided_for_longer_each_time(setup):
    o = g.Outcome("transient")
    cools = []
    for _ in range(5):
        g._mark_bad("primary", o)
        cools.append(round(g._health["primary"]["until"] - __import__("time").monotonic()))
    assert cools[0] == 20 and cools[1] == 60 and cools[2] == 180 and cools[3] == 300 and cools[4] == 300  # backs off, capped at 5 minutes
    g._mark_ok("primary")
    g._mark_bad("primary", o)
    assert round(g._health["primary"]["until"] - __import__("time").monotonic()) == 20  # one success resets it


def test_quota_cooldown_does_not_back_off_exponentially(setup):
    for _ in range(3):
        g._mark_bad("primary", g.Outcome("quota", 45066, True))
    assert g._health["primary"]["until"] - __import__("time").monotonic() <= g.QUOTA_RECHECK + 1  # re-checked every 10 minutes at most
