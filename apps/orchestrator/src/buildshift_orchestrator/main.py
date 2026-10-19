from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from buildshift_orchestrator import __version__
from buildshift_orchestrator.api import router
from buildshift_orchestrator.config import get_settings
from buildshift_orchestrator.db import SessionLocal, apply_migrations
from buildshift_orchestrator.runtime_settings import ensure_runtime_settings
from buildshift_orchestrator.worker_loop import WorkerLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("buildshift")

worker_loop = WorkerLoop()


class OperatorAuthMiddleware(BaseHTTPMiddleware):
    """If OPERATOR_TOKEN is set, require Bearer / X-Operator-Token (except /health)."""

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        token = (settings.operator_token or "").strip()
        if not token or request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        auth = request.headers.get("authorization") or ""
        header_tok = request.headers.get("x-operator-token") or ""
        provided = header_tok
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        if provided != token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    apply_migrations()
    db = SessionLocal()
    try:
        ensure_runtime_settings(db)
        log.info("runtime_settings seeded/loaded")
    finally:
        db.close()
    worker_loop.start()
    log.info("buildshift orchestrator %s ready", __version__)
    yield
    worker_loop.stop()


app = FastAPI(
    title="Buildshift Orchestrator",
    version=__version__,
    lifespan=lifespan,
)

_settings = get_settings()
_origins = [o.strip() for o in (_settings.cors_origins or "").split(",") if o.strip()]
if not _origins:
    _origins = ["http://127.0.0.1:3000", "http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(OperatorAuthMiddleware)
app.include_router(router)
