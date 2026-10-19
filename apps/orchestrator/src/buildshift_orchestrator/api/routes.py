from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator import __version__
from buildshift_orchestrator.config import Settings, get_settings
from buildshift_orchestrator.control import is_kill_switch_on, set_kill_switch
from buildshift_orchestrator.db import get_db
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import Task, TaskState
from buildshift_orchestrator.schemas import (
    HealthOut,
    KillSwitchIn,
    KillSwitchOut,
    TaskCreate,
    TaskOut,
)

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    return HealthOut(
        status="ok",
        kill_switch=is_kill_switch_on(db),
        version=__version__,
    )


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Task:
    budget = (
        Decimal(str(body.budget_usd))
        if body.budget_usd is not None
        else Decimal(str(settings.task_budget_usd))
    )
    task = Task(
        id=uuid.uuid4(),
        title=body.title,
        state=TaskState.ready.value,
        tier=body.tier,
        difficulty=body.difficulty,
        acceptance_criteria=body.acceptance_criteria,
        owned_paths=body.owned_paths,
        deps=body.deps,
        budget_usd=budget,
        max_attempts=settings.max_attempts_per_tier,
    )
    db.add(task)
    db.flush()  # ensure task row exists before event FK
    emit(
        db,
        kind="task.created",
        task_id=task.id,
        role="implementer",
        tier=task.tier,
        status=task.state,
        summary=task.title,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), limit: int = 50) -> list[Task]:
    return list(db.scalars(select(Task).order_by(Task.created_at.desc()).limit(limit)))


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/control/kill", response_model=KillSwitchOut)
def get_kill(db: Session = Depends(get_db)) -> KillSwitchOut:
    return KillSwitchOut(enabled=is_kill_switch_on(db))


@router.post("/control/kill", response_model=KillSwitchOut)
def post_kill(body: KillSwitchIn, db: Session = Depends(get_db)) -> KillSwitchOut:
    enabled = set_kill_switch(db, body.enabled)
    emit(
        db,
        kind="control.kill_switch",
        status="enabled" if enabled else "disabled",
        summary=f"kill switch set to {enabled}",
        payload={"enabled": enabled},
    )
    db.commit()
    return KillSwitchOut(enabled=enabled)
