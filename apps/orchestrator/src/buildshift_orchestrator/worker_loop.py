from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings, get_settings
from buildshift_orchestrator.control import is_kill_switch_on, under_daily_budget
from buildshift_orchestrator.db import SessionLocal
from buildshift_orchestrator.models import Task, TaskState
from buildshift_orchestrator.runner.locks import recover_orphaned_inflight
from buildshift_orchestrator.runner.pipeline import STAGE_STATE, run_task

log = logging.getLogger(__name__)

INFLIGHT = (
    TaskState.test_authoring.value,
    TaskState.coding.value,
    TaskState.testing.value,
    TaskState.reviewing.value,
    TaskState.integrating.value,
)


def count_inflight(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Task).where(Task.state.in_(INFLIGHT))) or 0


def claim_next_task(db: Session) -> Task | None:
    row = db.execute(
        text(
            """
            SELECT id FROM tasks
            WHERE state = :state
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"state": TaskState.ready.value},
    ).first()
    if not row:
        return None
    task = db.get(Task, row[0])
    if task is None:
        return None
    stage = task.stage or task.role or "implementer"
    task.state = STAGE_STATE.get(stage, TaskState.coding.value)
    db.commit()
    db.refresh(task)
    return task


def _execute_task(settings: Settings, task_id) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        if task.spent_usd >= Decimal(str(task.budget_usd)):
            task.state = TaskState.parked.value
            task.error = "task budget exceeded before start"
            db.commit()
            return
        run_task(db, settings, task)
    except Exception:
        log.exception("background task %s crashed", task_id)
    finally:
        db.close()


class WorkerLoop:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        db = SessionLocal()
        try:
            n = recover_orphaned_inflight(db, force=True)
            if n:
                log.warning("recovered %s orphaned inflight task(s) on startup", n)
        finally:
            db.close()
        self._pool = ThreadPoolExecutor(
            max_workers=self.settings.max_parallel_workers,
            thread_name_prefix="buildshift-task",
        )
        self._thread = threading.Thread(target=self._run, name="buildshift-worker-loop", daemon=True)
        self._thread.start()
        log.info("worker loop started (max_parallel=%s)", self.settings.max_parallel_workers)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=False)

    def _run(self) -> None:
        assert self._pool is not None
        while not self._stop.is_set():
            try:
                db = SessionLocal()
                try:
                    recover_orphaned_inflight(db)
                    if is_kill_switch_on(db):
                        time.sleep(self.settings.poll_interval_sec)
                        continue
                    if not under_daily_budget(db, self.settings):
                        log.warning("daily budget exhausted; not claiming work")
                        time.sleep(self.settings.poll_interval_sec)
                        continue
                    if count_inflight(db) >= self.settings.max_parallel_workers:
                        time.sleep(self.settings.poll_interval_sec)
                        continue
                    task = claim_next_task(db)
                    if task is None:
                        time.sleep(self.settings.poll_interval_sec)
                        continue
                    task_id = task.id
                finally:
                    db.close()

                self._pool.submit(_execute_task, self.settings, task_id)
                time.sleep(0.2)
            except Exception:
                log.exception("worker loop iteration failed")
                time.sleep(self.settings.poll_interval_sec)
