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
from buildshift_orchestrator.models import (
    DailyPlan,
    Epic,
    Event,
    HumanItem,
    Project,
    Run,
    RuntimeSettings,
    Sprint,
    Task,
    TaskState,
)
from buildshift_orchestrator.planning.planner import approve_plan, kickoff_product, propose_plan
from buildshift_orchestrator.planning import cto_chat as cto_chat_svc
from buildshift_orchestrator.planning import sprints as sprint_svc
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
    EodSessionOut,
    EpicOut,
    EventOut,
    HealthOut,
    HitlProjectNode,
    HitlSprintNode,
    HitlTreeItem,
    HitlTreeOut,
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
    CtoChatIn,
    CtoChatMessageOut,
    CtoChatOut,
    ProjectCreate,
    ProjectDetailOut,
    ProjectOut,
    ProjectPrdIn,
    ProjectPrdOut,
    ProjectRepoIn,
    RuntimeSettingsIn,
    RuntimeSettingsOut,
    SprintDetailOut,
    SprintKickoffOut,
    SprintOut,
    SprintPauseOut,
    SprintProposeIn,
    TaskCreate,
    TaskOut,
    UsageBucket,
    UsageOut,
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
def list_tasks(
    db: Session = Depends(get_db),
    limit: int = 50,
    project_id: uuid.UUID | None = None,
    sprint_id: uuid.UUID | None = None,
) -> list[Task]:
    q = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if project_id:
        q = q.where(Task.project_id == project_id)
    if sprint_id:
        q = q.where(Task.sprint_id == sprint_id)
    return list(db.scalars(q))


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        slug=p.slug,
        title=p.title,
        status=p.status,
        prd_path=p.prd_path,
        has_prd=bool((p.prd_markdown or "").strip() or p.prd_path),
        context_markdown=p.context_markdown or "",
        index_status=p.index_status or "none",
        index_error=p.index_error,
        indexed_at=p.indexed_at,
        repo_url=p.repo_url,
        repo_branch=p.repo_branch or "main",
        repo_path=p.repo_path,
        repo_synced_at=p.repo_synced_at,
        has_repo=bool((p.repo_url or "").strip()),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.post("/projects", response_model=ProjectOut, status_code=201)
def projects_create(body: ProjectCreate, db: Session = Depends(get_db)) -> ProjectOut:
    try:
        p = sprint_svc.create_project(db, body.title, body.slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _project_out(p)


@router.get("/projects", response_model=list[ProjectOut])
def projects_list(db: Session = Depends(get_db)) -> list[ProjectOut]:
    return [_project_out(p) for p in sprint_svc.list_projects(db)]


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def projects_get(project_id: uuid.UUID, db: Session = Depends(get_db)) -> ProjectDetailOut:
    try:
        detail = sprint_svc.project_detail(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectDetailOut(
        project=_project_out(detail["project"]),
        modules=[PrdProductOut.model_validate(m) for m in detail["modules"]],
        sprint_count=detail["sprint_count"],
        open_hitl=detail["open_hitl"],
        open_backlog=detail.get("open_backlog") or 0,
    )


@router.put("/projects/{project_id}/repo", response_model=ProjectOut)
def projects_connect_repo(
    project_id: uuid.UUID,
    body: ProjectRepoIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    """Connect (and optionally clone/sync) the git repo this project works in."""
    try:
        p = sprint_svc.connect_project_repo(
            db,
            project_id,
            repo_url=body.repo_url,
            repo_branch=body.repo_branch,
            sync=body.sync,
            settings=effective_settings(settings),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _project_out(p)


@router.post("/projects/{project_id}/repo/sync", response_model=ProjectOut)
def projects_sync_repo(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    """Fetch/reset the project's local mirror from its configured remote."""
    try:
        p = sprint_svc.sync_project_repo(db, project_id, effective_settings(settings))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _project_out(p)


@router.post("/projects/{project_id}/prd", response_model=ProjectPrdOut)
def projects_upload_prd(
    project_id: uuid.UUID,
    body: ProjectPrdIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectPrdOut:
    try:
        docs = _prd_docs_root(settings, project_id=project_id, db=db)
        result = sprint_svc.upload_prd(
            db,
            project_id,
            body.markdown,
            docs_root=docs,
            source_name=body.source_name,
            settings=effective_settings(settings),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProjectPrdOut(
        project_id=result["project_id"],
        modules=result["modules"],
        module_ids=result["module_ids"],
        index_status=result.get("index_status") or "ready",
        cost_usd=float(result.get("cost_usd") or 0),
    )


@router.post("/projects/{project_id}/reindex", response_model=ProjectPrdOut)
def projects_reindex(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectPrdOut:
    try:
        docs = _prd_docs_root(settings, project_id=project_id, db=db)
        result = sprint_svc.reindex_prd(
            db,
            project_id,
            docs_root=docs,
            settings=effective_settings(settings),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProjectPrdOut(
        project_id=result["project_id"],
        modules=result["modules"],
        module_ids=result["module_ids"],
        index_status=result.get("index_status") or "ready",
        cost_usd=float(result.get("cost_usd") or 0),
    )


@router.get("/projects/{project_id}/cto/chat", response_model=list[CtoChatMessageOut])
def cto_chat_history(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[CtoChatMessageOut]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return [
        CtoChatMessageOut.model_validate(m)
        for m in cto_chat_svc.list_messages(db, project_id)
    ]


@router.post("/projects/{project_id}/cto/chat", response_model=CtoChatOut)
def cto_chat_send(
    project_id: uuid.UUID,
    body: CtoChatIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CtoChatOut:
    try:
        result = cto_chat_svc.chat(db, settings, project_id, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return CtoChatOut(
        reply=CtoChatMessageOut.model_validate(result["reply"]),
        history=[CtoChatMessageOut.model_validate(m) for m in result["history"]],
        applied_actions=result.get("applied_actions") or [],
    )


@router.delete("/projects/{project_id}/cto/chat", status_code=204)
def cto_chat_clear(project_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    cto_chat_svc.clear_messages(db, project_id)


@router.get("/projects/{project_id}/sprints", response_model=list[SprintOut])
def projects_sprints(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Sprint]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return sprint_svc.list_sprints(db, project_id)


@router.post("/projects/{project_id}/sprints/propose", response_model=SprintOut)
def projects_propose_sprint(
    project_id: uuid.UUID,
    body: SprintProposeIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Sprint:
    try:
        return sprint_svc.propose_sprint(
            db,
            effective_settings(settings),
            project_id,
            capacity_hours=body.capacity_hours,
            mode=body.mode or "hours",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sprints/{sprint_id}", response_model=SprintDetailOut)
def sprint_get(sprint_id: uuid.UUID, db: Session = Depends(get_db)) -> SprintDetailOut:
    try:
        hier = sprint_svc.sprint_hierarchy(db, sprint_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    epics_out = []
    for block in hier["epics"]:
        epics_out.append(
            {
                "epic": EpicOut.model_validate(block["epic"]).model_dump(mode="json"),
                "tasks": [TaskOut.model_validate(t).model_dump(mode="json") for t in block["tasks"]],
            }
        )
    return SprintDetailOut(
        sprint=SprintOut.model_validate(hier["sprint"]),
        epics=epics_out,
        ungrouped_tasks=[TaskOut.model_validate(t) for t in hier["ungrouped_tasks"]],
    )


@router.post("/sprints/{sprint_id}/kickoff", response_model=SprintKickoffOut)
def sprint_kickoff(sprint_id: uuid.UUID, db: Session = Depends(get_db)) -> SprintKickoffOut:
    try:
        result = sprint_svc.kickoff_sprint(db, sprint_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SprintKickoffOut(**result)


@router.post("/sprints/{sprint_id}/pause", response_model=SprintPauseOut)
def sprint_pause(sprint_id: uuid.UUID, db: Session = Depends(get_db)) -> SprintPauseOut:
    try:
        result = sprint_svc.pause_sprint(db, sprint_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SprintPauseOut(**result)


@router.post("/sprints/{sprint_id}/resume", response_model=SprintKickoffOut)
def sprint_resume(sprint_id: uuid.UUID, db: Session = Depends(get_db)) -> SprintKickoffOut:
    try:
        result = sprint_svc.resume_sprint(db, sprint_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SprintKickoffOut(**result)


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


def _prd_docs_root(
    settings: Settings,
    *,
    project_id: uuid.UUID | None = None,
    db: Session | None = None,
) -> Path:
    """Write indexed PRD markdown under the project's (or global proving) clone docs/prd."""
    eff = effective_settings(settings)
    project: Project | None = None
    if project_id is not None and db is not None:
        project = db.get(Project, project_id)
    if project is not None and (project.repo_url or "").strip():
        mirror = (
            Path(project.repo_path)
            if project.repo_path
            else sprint_svc.project_mirror_path(eff, project)
        )
        gitops.ensure_repo(
            project.repo_url.strip(),
            mirror,
            project.repo_branch or "main",
            token=eff.github_token or "",
        )
        return mirror / "docs" / "prd"

    clone_url = resolve_clone_url(eff)
    repos_dir = eff.data_dir / "repos"
    repo_name = "proving" if eff.proving_repo_url else "demo-app"
    repo_path = repos_dir / repo_name
    gitops.ensure_repo(
        clone_url, repo_path, eff.proving_repo_branch, token=eff.github_token or ""
    )
    return repo_path / "docs" / "prd"


@router.post("/prd/index", response_model=PrdIndexOut)
def prd_index(
    body: PrdIndexIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    project_id: uuid.UUID | None = Query(None),
) -> PrdIndexOut:
    """Legacy global index; prefer POST /projects/{id}/prd. Requires project_id for CTO LLM index."""
    if project_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id is required; use POST /projects/{id}/prd for CTO indexing",
        )
    try:
        docs = _prd_docs_root(settings, project_id=project_id, db=db)
        sprint_svc.upload_prd(
            db,
            project_id,
            body.markdown,
            docs_root=docs,
            source_name=body.source_name,
            settings=effective_settings(settings),
        )
        products = list_products(db, project_id=project_id)
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


def _ensure_blocked_hitl(db: Session) -> None:
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
                project_id=task.project_id,
                sprint_id=task.sprint_id,
                kind="blocked_task",
                summary=task.error or task.title,
                status="open",
            )
        )
        created = True
    if created:
        db.commit()


@router.get("/hitl")
def list_hitl(
    db: Session = Depends(get_db),
    status: str | None = Query("open"),
    group: str | None = Query(None, description="Set to 'tree' for project→sprint nesting"),
):
    _ensure_blocked_hitl(db)
    q = select(HumanItem).order_by(HumanItem.created_at.desc())
    if status:
        q = q.where(HumanItem.status == status)
    items = list(db.scalars(q.limit(200)))

    if group != "tree":
        return [HumanItemOut.model_validate(i) for i in items]

    # Tree: project → sprint → items
    projects = {p.id: p for p in db.scalars(select(Project)).all()}
    sprints = {s.id: s for s in db.scalars(select(Sprint)).all()}
    tree: dict[str, dict] = {}
    for item in items:
        pid = str(item.project_id) if item.project_id else "none"
        if pid not in tree:
            proj = projects.get(item.project_id) if item.project_id else None
            tree[pid] = {
                "project_id": item.project_id,
                "project_title": proj.title if proj else "Unscoped",
                "sprints": {},
            }
        sid = str(item.sprint_id) if item.sprint_id else "none"
        snode = tree[pid]["sprints"]
        if sid not in snode:
            sp = sprints.get(item.sprint_id) if item.sprint_id else None
            label = (
                f"{sp.mode} · {sp.status}"
                if sp
                else "No sprint"
            )
            snode[sid] = {
                "sprint_id": item.sprint_id,
                "sprint_label": label,
                "items": [],
            }
        snode[sid]["items"].append(item)

    out_projects: list[HitlProjectNode] = []
    for node in tree.values():
        sprint_nodes = []
        total = 0
        for sn in node["sprints"].values():
            total += len(sn["items"])
            sprint_nodes.append(
                HitlSprintNode(
                    sprint_id=sn["sprint_id"],
                    sprint_label=sn["sprint_label"],
                    count=len(sn["items"]),
                    items=[
                        HitlTreeItem(
                            id=i.id,
                            kind=i.kind,
                            summary=i.summary,
                            status=i.status,
                            task_id=i.task_id,
                            needed_by=i.needed_by,
                            created_at=i.created_at,
                        )
                        for i in sn["items"]
                    ],
                )
            )
        out_projects.append(
            HitlProjectNode(
                project_id=node["project_id"],
                project_title=node["project_title"],
                count=total,
                sprints=sprint_nodes,
            )
        )
    return HitlTreeOut(projects=out_projects)


@router.post("/hitl", response_model=HumanItemOut, status_code=201)
def create_hitl(body: HumanItemCreate, db: Session = Depends(get_db)) -> HumanItem:
    item = HumanItem(
        id=uuid.uuid4(),
        product_id=body.product_id,
        project_id=body.project_id,
        sprint_id=body.sprint_id,
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
    project_id: uuid.UUID | None = Query(None),
) -> EodDigestOut:
    target = day or date.today().isoformat()
    try:
        day_date = date.fromisoformat(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid day") from exc

    start = datetime(day_date.year, day_date.month, day_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    task_q = select(Task.state, func.count()).group_by(Task.state)
    if project_id:
        task_q = select(Task.state, func.count()).where(Task.project_id == project_id).group_by(Task.state)
    rows = db.execute(task_q).all()
    counts = {str(state): int(n) for state, n in rows}

    spend = float(daily_spend_usd(db))
    event_spend_q = select(func.coalesce(func.sum(Event.cost_usd), 0)).where(
        Event.ts >= start, Event.ts < end
    )
    event_spend = db.scalar(event_spend_q)
    if event_spend is not None and float(event_spend) > 0:
        spend = float(event_spend)

    hitl_q = select(func.count()).select_from(HumanItem).where(HumanItem.status == "open")
    if project_id:
        hitl_q = hitl_q.where(HumanItem.project_id == project_id)
    open_hitl = db.scalar(hitl_q) or 0

    recent = list(
        db.scalars(
            select(Event)
            .where(Event.ts >= start, Event.ts < end)
            .order_by(Event.id.desc())
            .limit(40)
        )
    )

    # Sessions (runs) for the day, optionally scoped via task.project_id
    runs_q = (
        select(Run, Task)
        .join(Task, Run.task_id == Task.id)
        .where(Run.started_at >= start, Run.started_at < end)
        .order_by(Run.started_at.desc())
        .limit(100)
    )
    if project_id:
        runs_q = runs_q.where(Task.project_id == project_id)
    run_rows = db.execute(runs_q).all()
    sessions: list[EodSessionOut] = []
    agent_acc: dict[str, dict] = {}
    for run, task in run_rows:
        dur = None
        if run.ended_at and run.started_at:
            dur = (run.ended_at - run.started_at).total_seconds()
        sessions.append(
            EodSessionOut(
                run_id=run.id,
                task_id=task.id,
                task_title=task.title,
                role=run.role,
                model=run.model,
                status=run.status,
                cost_usd=float(run.cost_usd or 0),
                tokens_in=int(run.tokens_in or 0),
                tokens_out=int(run.tokens_out or 0),
                started_at=run.started_at,
                ended_at=run.ended_at,
                duration_sec=dur,
            )
        )
        key = run.role
        acc = agent_acc.setdefault(key, {"role": key, "runs": 0, "cost_usd": 0.0, "duration_sec": 0.0})
        acc["runs"] += 1
        acc["cost_usd"] += float(run.cost_usd or 0)
        acc["duration_sec"] += dur or 0

    # Hierarchy for project that day: sprints with tasks touched
    hierarchy: list[dict] = []
    if project_id:
        sprints = sprint_svc.list_sprints(db, project_id)
        for sp in sprints:
            hier = sprint_svc.sprint_hierarchy(db, sp.id)
            hierarchy.append(
                {
                    "sprint": SprintOut.model_validate(hier["sprint"]).model_dump(mode="json"),
                    "epics": [
                        {
                            "epic": EpicOut.model_validate(b["epic"]).model_dump(mode="json"),
                            "tasks": [
                                TaskOut.model_validate(t).model_dump(mode="json") for t in b["tasks"]
                            ],
                        }
                        for b in hier["epics"]
                    ],
                }
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
        project_id=project_id,
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
        sessions=sessions,
        agents=list(agent_acc.values()),
        hierarchy=hierarchy,
    )


@router.get("/usage", response_model=UsageOut)
def usage_report(
    db: Session = Depends(get_db),
    from_day: str | None = Query(None, alias="from"),
    to_day: str | None = Query(None, alias="to"),
    project_id: uuid.UUID | None = None,
    sprint_id: uuid.UUID | None = None,
    epic_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    group_by: str = Query("day", description="day|project|sprint|epic|task|run|role|model"),
) -> UsageOut:
    q = select(Run, Task).join(Task, Run.task_id == Task.id)
    if from_day:
        try:
            start = datetime.fromisoformat(from_day).replace(tzinfo=timezone.utc)
        except ValueError:
            start = datetime.fromisoformat(from_day + "T00:00:00").replace(tzinfo=timezone.utc)
        q = q.where(Run.started_at >= start)
    if to_day:
        try:
            end = datetime.fromisoformat(to_day).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            end = datetime.fromisoformat(to_day + "T00:00:00").replace(tzinfo=timezone.utc) + timedelta(
                days=1
            )
        q = q.where(Run.started_at < end)
    if project_id:
        q = q.where(Task.project_id == project_id)
    if sprint_id:
        q = q.where(Task.sprint_id == sprint_id)
    if epic_id:
        q = q.where(Task.epic_id == epic_id)
    if task_id:
        q = q.where(Task.id == task_id)

    rows = db.execute(q.order_by(Run.started_at.desc()).limit(2000)).all()
    buckets: dict[str, UsageBucket] = {}
    model_totals: dict[str, float] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for run, task in rows:
        cost = float(run.cost_usd or 0)
        tin = int(run.tokens_in or 0)
        tout = int(run.tokens_out or 0)
        total_cost += cost
        total_in += tin
        total_out += tout
        model = run.model or "unknown"
        model_totals[model] = model_totals.get(model, 0.0) + cost

        if group_by == "project":
            key = str(task.project_id or "none")
            label = key
        elif group_by == "sprint":
            key = str(task.sprint_id or "none")
            label = key
        elif group_by == "epic":
            key = str(task.epic_id or "none")
            label = task.parent_epic or key
        elif group_by == "task":
            key = str(task.id)
            label = task.title
        elif group_by == "run":
            key = str(run.id)
            label = f"{task.title} · {run.role}"
        elif group_by == "role" or group_by == "agent":
            key = run.role
            label = run.role
        elif group_by == "model":
            key = model
            label = model
        else:  # day
            key = (run.started_at or datetime.now(timezone.utc)).date().isoformat()
            label = key

        b = buckets.get(key)
        if not b:
            b = UsageBucket(key=key, label=label, cost_usd=0, tokens_in=0, tokens_out=0, run_count=0, models={})
            buckets[key] = b
        b.cost_usd += cost
        b.tokens_in += tin
        b.tokens_out += tout
        b.run_count += 1
        b.models[model] = b.models.get(model, 0.0) + cost

    return UsageOut(
        from_day=from_day,
        to_day=to_day,
        group_by=group_by,
        total_cost_usd=total_cost,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        buckets=list(buckets.values()),
        model_totals=model_totals,
    )
