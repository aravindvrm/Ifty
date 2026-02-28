from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import logging
import time

from app.api.routes import router
from app.db import ensure_schema_and_seed, get_engine
from app.config import get_settings

@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Avoid heavyweight schema sync at API startup on Postgres.
    # Postgres schema/migrations should run via explicit ops/CLI jobs.
    settings = get_settings()
    if settings.api_db_url.startswith("sqlite:///"):
        ensure_schema_and_seed(get_engine())
    yield


app = FastAPI(title="Institutional Flow Tracker API", version="0.1.0", lifespan=_lifespan)
app.include_router(router)
_log = logging.getLogger("flow.api")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    settings = get_settings()
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        ms = (time.perf_counter() - t0) * 1000.0
        _log.exception("request_failed method=%s path=%s duration_ms=%.1f", request.method, request.url.path, ms)
        raise
    ms = (time.perf_counter() - t0) * 1000.0
    if settings.api_verbose_logs or ms >= float(settings.api_slow_request_ms):
        _log.info(
            "request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            ms,
        )
    return response
