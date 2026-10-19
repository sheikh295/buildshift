from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from buildshift_orchestrator import __version__
from buildshift_orchestrator.api import router
from buildshift_orchestrator.db import apply_migrations
from buildshift_orchestrator.worker_loop import WorkerLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("buildshift")

worker_loop = WorkerLoop()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    apply_migrations()
    worker_loop.start()
    log.info("buildshift orchestrator %s ready", __version__)
    yield
    worker_loop.stop()


app = FastAPI(
    title="Buildshift Orchestrator",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(router)
