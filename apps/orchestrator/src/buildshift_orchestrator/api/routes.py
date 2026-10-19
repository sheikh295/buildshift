from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator import __version__
from buildshift_orchestrator.config import Settings, get_settings
from buildshift_orchestrator.control import is_kill_switch_on, set_kill_switch
from buildshift_orchestrator.db import get_db
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import DailyPlan, Task, TaskState
from buildshift_orchestrator.planning.planner import approve_plan, kickoff_product, propose_plan
from buildshift_orchestrator.prd.indexer import index_prd_markdown, list_products
from buildshift_orchestrator.runner.pipeline import resolve_clone_url
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.schemas import (
    HealthOut,
    KickoffOut,
    KillSwitchIn,
    KillSwitchOut,
    PlanApproveOut,
    PlanOut,
    PlanProposeIn,
    PrdIndexIn,
    PrdIndexOut,
    PrdProductOut,
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
        role="implementer",
        stage="implementer",
        acceptance_criteria=body.acceptance_criteria,
        owned_paths=body.owned_paths,
        deps=body.deps,
        budget_usd=budget,
        max_attempts=settings.max_attempts_per_tier,
    )
    db.add(task)
    db.flush()
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


def _prd_docs_root(settings: Settings) -> Path:
    """Write indexed PRD markdown under the proving clone's docs/prd."""
    clone_url = resolve_clone_url(settings)
    repos_dir = settings.data_dir / "repos"
    repo_name = "proving" if settings.proving_repo_url else "demo-app"
    repo_path = repos_dir / repo_name
    gitops.ensure_repo(clone_url, repo_path, settings.proving_repo_branch)
    return repo_path / "docs" / "prd"


@router.post("/prd/index", response_model=PrdIndexOut)
def prd_index(
    body: PrdIndexIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PrdIndexOut:
    try:
        docs = _prd_docs_root(settings)
        products = index_prd_markdown(
            db, body.markdown, docs_root=docs, source_name=body.source_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PrdIndexOut(products=products)


@router.get("/prd/products", response_model=list[PrdProductOut])
def prd_products(db: Session = Depends(get_db)) -> list:
    return list_products(db)


@router.post("/products/{product_id}/kickoff", response_model=KickoffOut)
def product_kickoff(product_id: uuid.UUID, db: Session = Depends(get_db)) -> KickoffOut:
    try:
        result = kickoff_product(db, product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return KickoffOut(**result)


@router.post("/plans/propose", response_model=PlanOut)
def plans_propose(
    body: PlanProposeIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DailyPlan:
    try:
        return propose_plan(db, settings, body.product_id, max_tickets=body.max_tickets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/plans/{plan_id}", response_model=PlanOut)
def plans_get(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> DailyPlan:
    plan = db.get(DailyPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@router.post("/plans/{plan_id}/approve", response_model=PlanApproveOut)
def plans_approve(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlanApproveOut:
    try:
        result = approve_plan(db, settings, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlanApproveOut(**result)
