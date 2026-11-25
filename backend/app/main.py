import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import ai, auth, dashboard, exports, imports, insights, records, sheets
from app.config import get_settings, production_problems
from app.database.connection import dispose_engine
from app.rate_limit import limiter
from app.middleware.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
if settings.env == "production":
    _errors, _warnings = production_problems(settings)
    for _w in _warnings:
        logging.getLogger("datanest").warning("production config: %s", _w)
    if _errors:
        raise RuntimeError("Refusing to start with unsafe production settings:\n - " + "\n - ".join(_errors))
if settings.auth_disabled:
    logging.getLogger("datanest").warning("AUTH IS DISABLED (dev mode): every request acts as the local dev user")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await dispose_engine()  # release database connections cleanly on shutdown


app = FastAPI(
    lifespan=lifespan,
    title="DataNest API",
    version="0.1.0",
    docs_url=None if settings.env == "production" else "/docs",
    openapi_url=None if settings.env == "production" else "/openapi.json",
    redoc_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)  # JSON lists/tables compress ~5-10x; tiny responses skip it
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # bearer tokens, no cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
install_error_handlers(app)

app.include_router(auth.router, prefix="/api")
app.include_router(sheets.router, prefix="/api")
app.include_router(records.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(insights.router, prefix="/api")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
