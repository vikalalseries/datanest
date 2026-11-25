import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings

log = logging.getLogger("datanest")


def _body(code: str, message: str, request: Request, extra: dict | None = None) -> dict:
    # `extra` carries structured, user-safe hints (e.g. which columns are missing) alongside the message
    return {"error": {**(extra or {}), "code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}}


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")  # personal data must not sit in shared caches
        if get_settings().env == "production":
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        extra = None
        if isinstance(detail, dict) and "code" in detail:
            code, message = detail["code"], detail.get("message", "Request failed.")
            extra = {k: v for k, v in detail.items() if k not in ("code", "message")}
        else:
            code, message = "http_error", str(detail)
        return JSONResponse(_body(code, message, request, extra), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        return JSONResponse(_body("validation_error", "Some of the data you sent is invalid.", request), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Log type only + request id: never echo exception text (may contain credentials/SQL).
        orig = getattr(exc, "orig", None)  # driver-level cause for DB errors
        # Server-side log only (never sent to the client). First line of the driver's own message, e.g. "too many connections";
        # SQLAlchemy's str(exc) (which includes SQL and parameters) is deliberately NOT logged.
        cause = f" (caused by {type(orig).__name__}: {str(orig).splitlines()[0][:160]})" if orig is not None and str(orig) else ""
        log.error("unhandled %s%s request_id=%s path=%s", type(exc).__name__, cause, request.state.request_id, request.url.path)
        return JSONResponse(
            _body("internal_error", "Something went wrong on our side. Please try again.", request), status_code=500
        )
