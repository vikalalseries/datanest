"""Reusable Gemini client: structured JSON in, validated Pydantic model out.

Reliability model. The free tier is often "high demand" (503), slow (a trivial call can take 30 s) or out of daily
quota (429, ~20 requests/day/model), so a single model is not dependable:
  * a CHAIN of models is used: GEMINI_MODEL first, then GEMINI_FALLBACK_MODELS;
  * an overloaded / over-quota / failing model hands over to the next one IMMEDIATELY;
  * if a model is merely SLOW, the next one is started in parallel after HEDGE_AFTER seconds and the first answer wins;
  * the app remembers which models just failed and tries them last, instead of re-discovering it on every request;
  * a hard time budget bounds each call, and quota errors are reported with the real reset time.
"""
import asyncio
import contextvars
import json
import logging
import re
import time
from typing import TypeVar

from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger("datanest.gemini")
T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None
last_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("gemini_last_model", default=None)

TRANSIENT = {500, 502, 503, 504}
PASS_PAUSE = 1.5        # seconds between whole passes over the chain
MIN_ATTEMPT_TIME = 3.0  # don't start an attempt with less than this left in the budget
HEDGE_AFTER = 7.0       # a model that hasn't answered in this long gets a parallel backup
QUOTA_RECHECK = 600     # re-test a quota-exhausted model at least this often (limits can change, e.g. billing enabled)
BUSY_COOLDOWN = 20      # try an overloaded / slow model last for this many seconds (grows if it keeps failing)
BUSY_COOLDOWN_MAX = 300


def _ai_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def normalize_model(name: str) -> str:
    """Accept 'Gemini 3.5 Flash Lite', 'models/gemini-3.5-flash-lite' etc. -> 'gemini-3.5-flash-lite'."""
    n = name.strip().lower().replace("models/", "").replace("_", "-")
    return "-".join(n.split())


def model_chain(prefer: str | None = None) -> list[str]:
    """Primary model first (or `prefer` when a conversation is pinned to the model that started it), then fallbacks."""
    s = get_settings()
    names = [normalize_model(m) for m in [s.gemini_model, *s.gemini_fallback_model_list] if m and m.strip()]
    if prefer:
        names.insert(0, normalize_model(prefer))
    return list(dict.fromkeys(names))


def get_client() -> genai.Client:
    global _client
    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_model:
        raise _ai_error(503, "ai_not_configured", "AI features aren't configured on the server yet.")
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


class Outcome:
    __slots__ = ("kind", "retry_s", "daily")

    def __init__(self, kind: str, retry_s: float | None = None, daily: bool = False):
        self.kind, self.retry_s, self.daily = kind, retry_s, daily


# ---- model health memory (process-wide) ----
_health: dict[str, dict] = {}


def reset_health() -> None:
    _health.clear()


def _mark_bad(model: str, o: Outcome) -> None:
    now = time.monotonic()
    fails = _health.get(model, {}).get("fails", 0) + 1  # consecutive failures since the last success
    if o.kind == "quota":
        cool = min(o.retry_s or 60, QUOTA_RECHECK)
    elif o.kind == "missing":
        cool = 3600
    elif o.kind == "bad_request":
        cool = 120
    else:  # overloaded / slow: back off more each time it keeps failing (20 s, 60 s, 180 s, then 300 s)
        cool = min(BUSY_COOLDOWN * 3 ** (fails - 1), BUSY_COOLDOWN_MAX)
    _health[model] = {
        "until": now + cool, "kind": o.kind, "daily": o.daily, "fails": fails,
        "resets_at": (now + (o.retry_s or 0)) if o.kind == "quota" else None,
    }


def _mark_ok(model: str) -> None:
    _health.pop(model, None)


def _ordered_chain(prefer: str | None) -> list[str]:
    """Healthy models first (configured order), then recently-failed ones, soonest-to-recover first (a last resort)."""
    now = time.monotonic()
    chain = model_chain(prefer)
    ok = [m for m in chain if _health.get(m, {}).get("until", 0) <= now]
    bad = sorted((m for m in chain if m not in ok), key=lambda m: _health[m]["until"])
    return ok + bad


def status() -> dict:
    """What the app currently knows about AI availability (no API call, no quota used)."""
    now = time.monotonic()
    models = []
    for m in model_chain():
        h = _health.get(m)
        if not h or h["until"] <= now:
            models.append({"name": m, "state": "ok"})
        elif h["kind"] == "quota":
            models.append({"name": m, "state": "quota", "resets_in_seconds": int(max(0, (h["resets_at"] or now) - now)), "daily": h["daily"]})
        else:
            state = "busy" if h["kind"] in ("transient", "timeout", "network") else "unavailable"
            models.append({"name": m, "state": state, "retry_in_seconds": int(h["until"] - now)})
    return {"configured": bool(get_settings().gemini_api_key and get_settings().gemini_model), "models": models,
            "any_available": any(m["state"] == "ok" for m in models)}


def _retry_info(e: BaseException) -> tuple[float | None, bool]:
    """(seconds until the quota resets, is-it-a-daily-quota), read from a 429's structured details."""
    try:
        blob = json.dumps(getattr(e, "details", None) or {}, default=str)
    except Exception:  # noqa: BLE001
        return None, False
    m = re.search(r'retryDelay"?\s*:\s*"?([0-9.]+)s', blob)
    return (float(m.group(1)) if m else None), ("PerDay" in blob)


def _classify(e: BaseException) -> Outcome:
    if isinstance(e, asyncio.TimeoutError):
        return Outcome("timeout")
    if isinstance(e, genai_errors.APIError):
        code = getattr(e, "code", None)
        status_ = str(getattr(e, "status", "")).upper()
        if code in TRANSIENT or status_ in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
            return Outcome("transient")
        if code == 429 or status_ == "RESOURCE_EXHAUSTED":
            retry_s, daily = _retry_info(e)
            return Outcome("quota", retry_s, daily)
        if code == 404 or status_ == "NOT_FOUND":
            return Outcome("missing")
        if code in (401, 403) or status_ in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
            return Outcome("auth")
        return Outcome("bad_request")
    return Outcome("network")


async def _attempt(client, model: str, contents: list, make_config, thinking: str | None, timeout: float):
    """One model, one logical try (a model that rejects the thinking setting is retried once without it)."""
    cfg_thinking = types.ThinkingConfig(thinking_level=thinking) if thinking else None
    for use_thinking in ([True, False] if cfg_thinking else [False]):
        try:
            cfg = make_config(cfg_thinking if use_thinking else None)
            return await asyncio.wait_for(client.aio.models.generate_content(model=model, contents=contents, config=cfg), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            if use_thinking and _classify(e).kind == "bad_request":
                continue
            raise


async def _generate(contents: list, make_config, *, prefer: str | None, thinking: str | None, timeout: float, budget: float):
    """Run one logical call through the model chain (see module docstring)."""
    client = get_client()
    chain = _ordered_chain(prefer)
    started = time.monotonic()
    deadline = started + budget
    outcomes: list[Outcome] = []
    queue = list(chain)
    running: dict[asyncio.Future, str] = {}
    pass_no = 0

    def launch() -> None:
        model = queue.pop(0)
        t = max(1.0, min(timeout, deadline - time.monotonic()))
        running[asyncio.ensure_future(_attempt(client, model, contents, make_config, thinking, t))] = model

    try:
        launch()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.2:
                break
            hedging = bool(queue) and len(running) < 2
            done, _ = await asyncio.wait(list(running), timeout=min(HEDGE_AFTER, remaining) if hedging else remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                if hedging and deadline - time.monotonic() > MIN_ATTEMPT_TIME:
                    log.info("gemini slow, starting backup model %s", queue[0])
                    launch()
                    continue
                break  # out of time
            for task in done:
                model = running.pop(task)
                try:
                    resp = task.result()
                except Exception as e:  # noqa: BLE001
                    o = _classify(e)
                    log.warning("gemini model=%s failed kind=%s retry_s=%s", model, o.kind, o.retry_s)  # never log request content or keys
                    outcomes.append(o)
                    if o.kind == "auth":
                        raise _ai_error(502, "ai_rejected", "The AI service rejected the server's key. Check GEMINI_API_KEY.")
                    _mark_bad(model, o)
                    continue
                _mark_ok(model)
                last_model.set(model)
                log.info("gemini ok model=%s elapsed=%.1fs fallbacks_used=%s", model, time.monotonic() - started, bool(outcomes))
                return resp
            if not running:
                if not queue and pass_no == 0 and deadline - time.monotonic() > MIN_ATTEMPT_TIME + PASS_PAUSE:
                    pass_no = 1
                    await asyncio.sleep(PASS_PAUSE)  # one short breather, then a second pass over the chain
                    queue = list(chain)
                if queue and deadline - time.monotonic() > MIN_ATTEMPT_TIME:
                    launch()
                else:
                    break
        for model in running.values():  # budget ran out with attempts still in flight
            outcomes.append(Outcome("timeout"))
            _mark_bad(model, Outcome("timeout"))
    finally:
        for t in running:
            t.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
    raise _failure(outcomes)


def _fmt_wait(seconds: float) -> str:
    if seconds >= 5400:
        return f"about {round(seconds / 3600)} hours"
    if seconds >= 90:
        return f"about {round(seconds / 60)} minutes"
    return "a minute"


def _failure(outcomes: list[Outcome]) -> HTTPException:
    kinds = [o.kind for o in outcomes]
    quotas = [o for o in outcomes if o.kind == "quota"]
    if kinds and all(k == "quota" for k in kinds):
        soonest = min((o.retry_s for o in quotas if o.retry_s), default=None)
        daily = any(o.daily for o in quotas)
        when = f" It resets in {_fmt_wait(soonest)}." if soonest else " Please wait a minute and try again."
        msg = ("Today's free AI quota is used up on every configured model." if daily else "The AI service's request limit was reached.") + when
        if daily:
            msg += " You can keep adding records by hand, or enable billing on the Gemini API key to lift the daily limit."
        detail = {"code": "ai_rate_limited", "message": msg}
        if soonest:
            detail["retry_after_seconds"] = int(soonest)
        return HTTPException(status_code=429, detail=detail)
    if kinds and all(k == "missing" for k in kinds):
        return _ai_error(502, "ai_model_unavailable", "The configured AI models aren't available. Check GEMINI_MODEL and GEMINI_FALLBACK_MODELS in the server settings.")
    if kinds and all(k in ("bad_request", "missing") for k in kinds):
        return _ai_error(502, "ai_rejected", "The AI service rejected the request. Check the server's Gemini key and model settings.")
    if "timeout" in kinds and all(k in ("timeout", "network") for k in kinds):
        return _ai_error(504, "ai_timeout", "The AI took too long to respond. Please try again.")
    extra = " Some models are also out of free quota today." if quotas else ""
    return _ai_error(502, "ai_unavailable", "The AI service is very busy right now (the models are overloaded)." + extra + " Please try again in a moment.")


async def generate_structured(
    schema: type[T],
    *,
    system: str,
    parts: list,
    temperature: float = 0.1,
    max_output_tokens: int = 8192,
    thinking: str | None = "minimal",
    timeout: float = 20,
    budget: float = 55,
) -> T:
    """Call Gemini with a JSON schema; validate with Pydantic; retry once on invalid output."""
    def make_config(thinking_cfg):
        return types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_schema=schema,
            temperature=temperature, max_output_tokens=max_output_tokens, thinking_config=thinking_cfg,
        )

    last_problem = "invalid"
    for attempt in range(2):
        resp = await _generate(parts, make_config, prefer=None, thinking=thinking, timeout=timeout, budget=budget)
        if resp.parsed is not None and isinstance(resp.parsed, schema):
            return resp.parsed
        try:
            return schema.model_validate_json(resp.text or "")
        except (ValidationError, ValueError):
            last_problem = "block" if getattr(resp, "prompt_feedback", None) and getattr(resp.prompt_feedback, "block_reason", None) else "invalid"
            log.warning("gemini returned invalid structured output (attempt %s, %s)", attempt + 1, last_problem)
            if last_problem == "block":
                break
    if last_problem == "block":
        raise _ai_error(422, "ai_blocked", "The AI couldn't process that content. Try different input.")
    raise _ai_error(502, "ai_bad_response", "The AI returned an unreadable answer. Please try again.")


async def generate_raw(
    *, system: str, contents: list, tools: list | None = None, temperature: float = 0.2, max_output_tokens: int = 4096,
    prefer_model: str | None = None, thinking: str | None = "low", timeout: float = 30, budget: float = 60,
):
    """One Gemini call (optionally with function-calling tools), with model fallback and friendly errors.

    Automatic function calling is disabled: the caller executes (and validates) every tool itself.
    `prefer_model` pins a multi-step conversation to the model that served its first step (tool-call turns carry
    model-specific data), falling back to others only if that model fails.
    """
    def make_config(thinking_cfg):
        return types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_output_tokens,
            tools=tools or None, thinking_config=thinking_cfg,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if tools else None,
        )

    return await _generate(contents, make_config, prefer=prefer_model, thinking=thinking, timeout=timeout, budget=budget)
