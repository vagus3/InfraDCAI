import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.database import engine, init_db
from app.logging_config import log_event, request_id_ctx, setup_logging
from app.redis_client import get_redis
from app.routers import auth, chat

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log_event(logger, logging.INFO, "startup_complete", environment=settings.environment)
    yield


app = FastAPI(title="Mini ChatGPT Infra", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Tags every request with an id and logs how long it took.

    The id is echoed back in X-Request-ID, so a user reporting a failure can
    hand over one string that points straight at the matching log lines.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_ctx.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log_event(
            logger,
            logging.ERROR,
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=elapsed_ms,
        )
        logger.exception("unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if request.url.path not in ("/health", "/ready"):
        log_event(
            logger,
            logging.INFO,
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness: is the process up? Deliberately checks nothing else -- if this
    depended on Postgres, a database blip would make the orchestrator kill a
    perfectly healthy app and turn a small outage into a restart loop."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    """Readiness: can this instance actually serve traffic right now?
    This one does check dependencies, because an app that cannot reach
    Postgres should be pulled out of the load balancer, not restarted."""
    checks = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unreachable"

    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unreachable"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if all_ok else 503, content={"ready": all_ok, "checks": checks})


static_dir = Path(__file__).parent.parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
