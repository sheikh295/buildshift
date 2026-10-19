from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from buildshift_orchestrator import __version__
from buildshift_orchestrator.config import Settings, get_settings
from buildshift_orchestrator.control import (
    daily_spend_usd,
    is_kill_switch_on,
    set_kill_switch,
)
from buildshift_orchestrator.db import SessionLocal, get_db
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import DailyPlan, Event, HumanItem, RuntimeSettings, Task, TaskState
from buildshift_orchestrator.planning.planner import approve_plan, kickoff_product, propose_plan
from buildshift_orchestrator.prd.indexer import index_prd_markdown, list_products
from buildshift_orchestrator.runner.pipeline import resolve_clone_url
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.runtime_settings import (
    effective_settings,
    get_runtime_settings,
    put_runtime_settings,
)
from buildshift_orchestrator.schemas import (
    EodDigestOut,
    EventOut,
    HealthOut,
    HumanItemCreate,
    HumanItemOut,
    HumanItemReplyIn,
    KickoffOut,
    KillSwitchIn,
    KillSwitchOut,
    PlanApproveOut,
    PlanOut,
    PlanProposeIn,
    PrdIndexIn,
    PrdIndexOut,
    PrdProductOut,
    RuntimeSettingsIn,
    RuntimeSettingsOut,
    TaskCreate,
    TaskOut,
)

router = APIRouter()


def _settings_out(db: Session, blob: dict) -> RuntimeSettingsOut:
    row = db.get(RuntimeSettings, "default")
    return RuntimeSettingsOut(
        version=int(blob.get("version") or 1),
        roles=blob.get("roles") or {},
        limits=blob.get("limits") or {},
        harness=str(blob.get("harness") or "mock"),
        multi_role_pipeline=bool(blob.get("multi_role_pipeline", True)),
        poll_interval_sec=float(blob.get("poll_interval_sec") or 2.0),
        proving_repo_url=str(blob.get("proving_repo_url") or ""),
        proving_repo_branch=str(blob.get("proving_repo_branch") or "main"),
        kill_switch=is_kill_switch_on(db),
        ui=blob.get("ui") or {},
        updated_at=row.updated_at if row else None,
    )


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
    eff = effective_settings(settings)
    budget = (
        Decimal(str(body.budget_usd))
        if body.budget_usd is not None
        else Decimal(str(eff.task_budget_usd))
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
        max_attempts=eff.max_attempts_per_tier,
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


@router.get("/control/settings", response_model=RuntimeSettingsOut)
def get_settings_api(db: Session = Depends(get_db)) -> RuntimeSettingsOut:
    blob = get_runtime_settings(db)
    return _settings_out(db, blob)


@router.put("/control/settings", response_model=RuntimeSettingsOut)
def put_settings_api(body: RuntimeSettingsIn, db: Session = Depends(get_db)) -> RuntimeSettingsOut:
    patch = body.model_dump(exclude_none=True)
    kill = patch.pop("kill_switch", None)
    blob = put_runtime_settings(db, patch)
    if kill is not None:
        set_kill_switch(db, bool(kill))
        emit(
            db,
            kind="control.kill_switch",
            status="enabled" if kill else "disabled",
            summary=f"kill switch set to {kill}",
            payload={"enabled": bool(kill)},
        )
    emit(
        db,
        kind="control.settings_updated",
        summary="runtime settings updated",
        payload={"keys": list(patch.keys())},
    )
    db.commit()
    return _settings_out(db, blob)


def _prd_docs_root(settings: Settings) -> Path:
    """Write indexed PRD markdown under the proving clone's docs/prd."""
    eff = effective_settings(settings)
    clone_url = resolve_clone_url(eff)
    repos_dir = eff.data_dir / "repos"
    repo_name = "proving" if eff.proving_repo_url else "demo-app"
    repo_path = repos_dir / repo_name
    gitops.ensure_repo(clone_url, repo_path, eff.proving_repo_branch)
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
        return propose_plan(db, effective_settings(settings), body.product_id, max_tickets=body.max_tickets)
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
        result = approve_plan(db, effective_settings(settings), plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlanApproveOut(**result)


@router.get("/events", response_model=list[EventOut])
def list_events(
    db: Session = Depends(get_db),
    since: int = Query(0, ge=0, description="Return events with id > since"),
    limit: int = Query(100, ge=1, le=500),
) -> list[Event]:
    q = select(Event).where(Event.id > since).order_by(Event.id.asc()).limit(limit)
    return list(db.scalars(q))


@router.get("/events/stream")
async def events_stream(
    request: Request,
    since: int = Query(0, ge=0),
) -> StreamingResponse:
    """SSE stream of events (polls Postgres). Cursor = last event id."""

    async def gen():
        cursor = since
        while True:
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                rows = list(
                    db.scalars(
                        select(Event)
                        .where(Event.id > cursor)
                        .order_by(Event.id.asc())
                        .limit(50)
                    )
                )
                for ev in rows:
                    cursor = ev.id
                    payload = EventOut.model_validate(ev).model_dump(mode="json")
                    yield f"id: {ev.id}\ndata: {json.dumps(payload)}\n\n"
            finally:
                db.close()
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/hitl", response_model=list[HumanItemOut])
def list_hitl(
    db: Session = Depends(get_db),
    status: str | None = Query("open"),
) -> list[HumanItem]:
    # Ensure blocked_human tasks have an open HITL row so reply can unblock them
    blocked = list(
        db.scalars(select(Task).where(Task.state == TaskState.blocked_human.value).limit(50))
    )
    open_for_tasks = set(
        db.scalars(
            select(HumanItem.task_id).where(
                HumanItem.status == "open",
                HumanItem.task_id.isnot(None),
            )
        ).all()
    )
    created = False
    for task in blocked:
        if task.id in open_for_tasks:
            continue
        db.add(
            HumanItem(
                id=uuid.uuid4(),
                task_id=task.id,
                product_id=task.product_id,
                kind="blocked_task",
                summary=task.error or task.title,
                status="open",
            )
        )
        created = True
    if created:
        db.commit()

    q = select(HumanItem).order_by(HumanItem.created_at.desc())
    if status:
        q = q.where(HumanItem.status == status)
    return list(db.scalars(q.limit(100)))


@router.post("/hitl", response_model=HumanItemOut, status_code=201)
def create_hitl(body: HumanItemCreate, db: Session = Depends(get_db)) -> HumanItem:
    item = HumanItem(
        id=uuid.uuid4(),
        product_id=body.product_id,
        task_id=body.task_id,
        kind=body.kind,
        summary=body.summary,
        needed_by=body.needed_by,
        status="open",
    )
    db.add(item)
    if body.task_id:
        task = db.get(Task, body.task_id)
        if task is not None:
            task.state = TaskState.blocked_human.value
    emit(
        db,
        kind="hitl.created",
        task_id=body.task_id,
        summary=body.summary,
        payload={"kind": body.kind},
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/hitl/{item_id}/reply", response_model=HumanItemOut)
def reply_hitl(
    item_id: uuid.UUID,
    body: HumanItemReplyIn,
    db: Session = Depends(get_db),
) -> HumanItem:
    item = db.get(HumanItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="hitl item not found")
    item.reply = body.reply
    item.status = "resolved"
    item.updated_at = datetime.now(timezone.utc)
    if item.task_id:
        task = db.get(Task, item.task_id)
        if task is not None and task.state == TaskState.blocked_human.value:
            task.state = TaskState.ready.value
            task.error = None
    emit(
        db,
        kind="hitl.replied",
        task_id=item.task_id,
        summary=body.reply[:200],
        payload={"item_id": str(item.id)},
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/digest/eod", response_model=EodDigestOut)
def eod_digest(
    db: Session = Depends(get_db),
    day: str | None = Query(None, description="ISO date YYYY-MM-DD; default today"),
) -> EodDigestOut:
    target = day or date.today().isoformat()
    try:
        day_date = date.fromisoformat(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid day") from exc

    start = datetime(day_date.year, day_date.month, day_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows = db.execute(
        select(Task.state, func.count()).group_by(Task.state)
    ).all()
    counts = {str(state): int(n) for state, n in rows}

    spend = float(daily_spend_usd(db))
    # Prefer event cost sum for the day when available
    event_spend = db.scalar(
        select(func.coalesce(func.sum(Event.cost_usd), 0)).where(
            Event.ts >= start, Event.ts < end
        )
    )
    if event_spend is not None and float(event_spend) > 0:
        spend = float(event_spend)

    open_hitl = (
        db.scalar(select(func.count()).select_from(HumanItem).where(HumanItem.status == "open"))
        or 0
    )
    recent = list(
        db.scalars(
            select(Event)
            .where(Event.ts >= start, Event.ts < end)
            .order_by(Event.id.desc())
            .limit(40)
        )
    )
    risks: list[str] = []
    if counts.get(TaskState.blocked_human.value, 0) or open_hitl:
        risks.append(f"{counts.get(TaskState.blocked_human.value, 0)} blocked + {open_hitl} open HITL")
    if counts.get(TaskState.failed.value, 0):
        risks.append(f"{counts[TaskState.failed.value]} failed tasks")
    if counts.get(TaskState.parked.value, 0):
        risks.append(f"{counts[TaskState.parked.value]} parked (budget/attempts)")
    if is_kill_switch_on(db):
        risks.append("kill switch is ON")

    return EodDigestOut(
        day=target,
        counts_by_state=counts,
        merged=counts.get(TaskState.merged.value, 0),
        reviewing=counts.get(TaskState.reviewing.value, 0),
        blocked_human=counts.get(TaskState.blocked_human.value, 0),
        parked=counts.get(TaskState.parked.value, 0),
        failed=counts.get(TaskState.failed.value, 0),
        spend_usd=spend,
        open_hitl=int(open_hitl),
        recent_events=[EventOut.model_validate(e) for e in recent],
        risks=risks,
    )
