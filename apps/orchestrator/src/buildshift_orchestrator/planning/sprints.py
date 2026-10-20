from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import (
    BacklogItem,
    Epic,
    HumanItem,
    PrdProduct,
    PrdRequirement,
    Project,
    Sprint,
    Task,
    TaskState,
)
from buildshift_orchestrator.prd.indexer import index_prd_markdown
from buildshift_orchestrator.router_config import role_tier, router_limits
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.runner.locks import owned_paths_overlap

# Rough hours per ticket — capacity is a ceiling, not a pad target
HOURS_PER_TICKET = Decimal("1.0")


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or f"project-{uuid.uuid4().hex[:8]}"


def create_project(db: Session, title: str, slug: str | None = None) -> Project:
    slug = slug or _slugify(title)
    existing = db.scalar(select(Project).where(Project.slug == slug))
    if existing:
        raise ValueError(f"project slug already exists: {slug}")
    project = Project(id=uuid.uuid4(), slug=slug, title=title, status="active")
    db.add(project)
    emit(db, kind="project.created", summary=f"Created project {title}", payload={"project_id": str(project.id)})
    db.commit()
    db.refresh(project)
    return project


def project_mirror_path(settings: Settings, project: Project) -> Path:
    return settings.data_dir / "repos" / project.slug


def connect_project_repo(
    db: Session,
    project_id: uuid.UUID,
    *,
    repo_url: str,
    repo_branch: str = "main",
    sync: bool = True,
    settings: Settings | None = None,
) -> Project:
    """Bind a Project to a git remote (HTTPS/SSH) or local path; optionally clone/fetch now."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    url = (repo_url or "").strip()
    if not url:
        raise ValueError("repo_url is required")
    branch = (repo_branch or "main").strip() or "main"
    project.repo_url = url
    project.repo_branch = branch
    project.updated_at = datetime.now(timezone.utc)

    if sync:
        if settings is None:
            raise ValueError("settings required to sync repo")
        mirror = project_mirror_path(settings, project)
        try:
            gitops.ensure_repo(url, mirror, branch, token=settings.github_token or "")
        except gitops.GitError as exc:
            raise ValueError(f"failed to clone/sync repo: {exc}") from exc
        project.repo_path = str(mirror)
        project.repo_synced_at = datetime.now(timezone.utc)

    emit(
        db,
        kind="project.repo_connected",
        summary=f"Connected repo for {project.title}",
        payload={
            "project_id": str(project.id),
            "repo_url": project.repo_url,
            "repo_branch": project.repo_branch,
            "repo_path": project.repo_path,
            "synced": sync,
        },
    )
    db.commit()
    db.refresh(project)
    return project


def sync_project_repo(db: Session, project_id: uuid.UUID, settings: Settings) -> Project:
    """Fetch/reset the project's local mirror from its configured remote."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    if not (project.repo_url or "").strip():
        raise ValueError("project has no repo_url — connect a repository first")
    mirror = project_mirror_path(settings, project)
    try:
        gitops.ensure_repo(
            project.repo_url.strip(),
            mirror,
            project.repo_branch or "main",
            token=settings.github_token or "",
        )
    except gitops.GitError as exc:
        raise ValueError(f"failed to sync repo: {exc}") from exc
    project.repo_path = str(mirror)
    project.repo_synced_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="project.repo_synced",
        summary=f"Synced repo for {project.title}",
        payload={"project_id": str(project.id), "repo_path": project.repo_path},
    )
    db.commit()
    db.refresh(project)
    return project


def upload_prd(
    db: Session,
    project_id: uuid.UUID,
    markdown: str,
    *,
    docs_root=None,
    source_name: str = "uploaded.md",
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    project.prd_markdown = markdown
    project.updated_at = datetime.now(timezone.utc)
    db.flush()
    modules = index_prd_markdown(
        db,
        markdown,
        project_id=project.id,
        docs_root=docs_root,
        source_name=source_name,
    )
    if docs_root is not None:
        path = docs_root / f"{project.slug}.prd.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown)
        project.prd_path = str(path)
        db.commit()
    return {
        "project_id": str(project.id),
        "modules": len(modules),
        "module_ids": [str(m.id) for m in modules],
    }


def reindex_prd(db: Session, project_id: uuid.UUID, *, docs_root=None) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    if not (project.prd_markdown or "").strip():
        raise ValueError("project has no stored PRD; upload first")
    return upload_prd(
        db,
        project_id,
        project.prd_markdown,
        docs_root=docs_root,
        source_name=project.prd_path or "reindex.md",
    )


def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


def project_detail(db: Session, project_id: uuid.UUID) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    modules = list(
        db.scalars(
            select(PrdProduct)
            .where(PrdProduct.project_id == project_id)
            .order_by(PrdProduct.build_order)
        )
    )
    sprint_count = (
        db.scalar(select(func.count()).select_from(Sprint).where(Sprint.project_id == project_id))
        or 0
    )
    open_hitl = (
        db.scalar(
            select(func.count())
            .select_from(HumanItem)
            .where(HumanItem.project_id == project_id, HumanItem.status == "open")
        )
        or 0
    )
    return {
        "project": project,
        "modules": modules,
        "sprint_count": int(sprint_count),
        "open_hitl": int(open_hitl),
    }


def _collect_candidates(db: Session, project_id: uuid.UUID, settings: Settings) -> list[dict]:
    """Backlog + untraced requirements across modules, ordered by build_order."""
    modules = list(
        db.scalars(
            select(PrdProduct)
            .where(PrdProduct.project_id == project_id)
            .order_by(PrdProduct.build_order)
        )
    )
    candidates: list[dict] = []
    for product in modules:
        open_backlog = list(
            db.scalars(
                select(BacklogItem)
                .where(
                    BacklogItem.product_id == product.id,
                    BacklogItem.status == "open",
                )
                .order_by(BacklogItem.sort_order)
            )
        )
        for item in open_backlog:
            candidates.append(
                {
                    "product_id": product.id,
                    "product_title": product.title,
                    "title": item.title,
                    "acceptance_criteria": item.acceptance_criteria,
                    "owned_paths": item.owned_paths,
                    "difficulty": item.difficulty,
                    "estimated_spend_usd": float(item.estimated_spend_usd),
                    "estimated_hours": float(HOURS_PER_TICKET),
                    "req_ids": item.req_ids,
                    "backlog_id": str(item.id),
                }
            )
        reqs = list(
            db.scalars(
                select(PrdRequirement)
                .where(PrdRequirement.product_id == product.id, PrdRequirement.traced.is_(False))
                .order_by(PrdRequirement.sort_order)
            )
        )
        for req in reqs:
            slug = product.slug.replace("-", "_")
            path = f"src/{slug}/{req.req_key.lower()}.md"
            candidates.append(
                {
                    "product_id": product.id,
                    "product_title": product.title,
                    "title": f"{product.title}: {req.req_key}",
                    "acceptance_criteria": req.text,
                    "owned_paths": [path],
                    "difficulty": "normal",
                    "estimated_spend_usd": float(settings.task_budget_usd) / 2,
                    "estimated_hours": float(HOURS_PER_TICKET),
                    "req_ids": [str(req.id)],
                    "backlog_id": None,
                }
            )
    return candidates


def propose_sprint(
    db: Session,
    settings: Settings,
    project_id: uuid.UUID,
    *,
    capacity_hours: float = 6.0,
    mode: str = "hours",
) -> Sprint:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    try:
        hours_req = float(capacity_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("capacity_hours must be a number") from exc
    if hours_req < 1 or hours_req > 40:
        raise ValueError("capacity_hours must be between 1 and 40")

    cap = Decimal(str(hours_req))
    candidates = _collect_candidates(db, project_id, settings)
    selected: list[dict] = []
    hours = Decimal("0")
    spend = Decimal("0")
    for c in candidates:
        h = Decimal(str(c["estimated_hours"]))
        # Ceiling: stop once we would exceed capacity (unless nothing selected yet — take at least one if any work)
        if selected and hours + h > cap:
            break
        selected.append(c)
        hours += h
        spend += Decimal(str(c["estimated_spend_usd"]))
        if hours >= cap:
            break

    sprint = Sprint(
        id=uuid.uuid4(),
        project_id=project.id,
        mode=mode or "hours",
        status="planned",
        capacity_hours=cap,
        goals=[
            f"Sprint for {project.title}",
            f"Plan ceiling ≤ {cap}h (not padded if less work remains)",
            f"{len(selected)} tasks from remaining backlog",
        ],
        estimated_spend_usd=spend,
        estimated_hours=hours,
    )
    db.add(sprint)
    db.flush()

    # Group into epics by module
    by_product: dict[uuid.UUID, list[dict]] = {}
    for c in selected:
        by_product.setdefault(c["product_id"], []).append(c)

    limits = router_limits()
    max_attempts = max(
        int(limits.get("max_attempts_per_tier") or settings.max_attempts_per_tier),
        4,
    )
    budget = Decimal(str(limits.get("task_budget_usd") or settings.task_budget_usd))

    sort_i = 0
    created_tasks: list[Task] = []
    for product_id, tickets in by_product.items():
        title = tickets[0]["product_title"]
        product = db.get(PrdProduct, product_id)
        epic = Epic(
            id=uuid.uuid4(),
            sprint_id=sprint.id,
            project_id=project.id,
            product_id=product_id,
            title=title,
            summary=(product.summary if product else "") or "",
            status="planned",
            sort_order=sort_i,
        )
        sort_i += 1
        db.add(epic)
        db.flush()

        for ticket in tickets:
            backlog_id = ticket.get("backlog_id")
            if backlog_id:
                item = db.get(BacklogItem, uuid.UUID(backlog_id))
                if item:
                    item.status = "scheduled"
            else:
                item = BacklogItem(
                    id=uuid.uuid4(),
                    product_id=product_id,
                    title=ticket["title"],
                    acceptance_criteria=ticket.get("acceptance_criteria") or "",
                    owned_paths=ticket.get("owned_paths") or [],
                    difficulty=ticket.get("difficulty") or "normal",
                    estimated_spend_usd=Decimal(str(ticket.get("estimated_spend_usd") or 1)),
                    req_ids=ticket.get("req_ids") or [],
                    status="scheduled",
                )
                db.add(item)

            for req_id in ticket.get("req_ids") or []:
                try:
                    req = db.get(PrdRequirement, uuid.UUID(str(req_id)))
                    if req:
                        req.traced = True
                except ValueError:
                    pass

            task = Task(
                id=uuid.uuid4(),
                title=ticket["title"],
                # Stay planned until sprint kickoff
                state=TaskState.planned.value,
                role="test_author",
                stage="test_author",
                tier=role_tier("test_author"),
                difficulty=ticket.get("difficulty") or "normal",
                acceptance_criteria=ticket.get("acceptance_criteria") or "",
                owned_paths=ticket.get("owned_paths") or [],
                budget_usd=budget,
                max_attempts=max_attempts,
                product_id=product_id,
                project_id=project.id,
                sprint_id=sprint.id,
                epic_id=epic.id,
                parent_epic=title,
                req_ids=ticket.get("req_ids") or [],
                deps=[],
            )
            db.add(task)
            created_tasks.append(task)

    db.flush()
    for i, task in enumerate(created_tasks):
        deps: list[str] = []
        for prev in created_tasks[:i]:
            if owned_paths_overlap(task.owned_paths or [], prev.owned_paths or []):
                deps.append(str(prev.id))
        task.deps = deps

    emit(
        db,
        kind="sprint.proposed",
        summary=f"Sprint {sprint.id}: {len(created_tasks)} tasks, ~{hours}h (cap {cap}h)",
        payload={
            "sprint_id": str(sprint.id),
            "project_id": str(project.id),
            "task_count": len(created_tasks),
            "estimated_hours": float(hours),
            "capacity_hours": float(cap),
            "mode": mode,
        },
        role="planner",
    )
    db.commit()
    db.refresh(sprint)
    return sprint


def kickoff_sprint(db: Session, sprint_id: uuid.UUID) -> dict:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None:
        raise ValueError("sprint not found")
    if sprint.status == "active":
        raise ValueError("sprint already active")
    if sprint.status not in ("planned", "draft"):
        raise ValueError(f"cannot kickoff sprint in status {sprint.status}")

    tasks = list(db.scalars(select(Task).where(Task.sprint_id == sprint.id)))
    for task in tasks:
        if task.state == TaskState.planned.value:
            task.state = TaskState.ready.value

    epics = list(db.scalars(select(Epic).where(Epic.sprint_id == sprint.id)))
    for epic in epics:
        epic.status = "active"

    sprint.status = "active"
    sprint.started_at = datetime.now(timezone.utc)

    # Attach open HITL without sprint to this sprint when same project
    for item in db.scalars(
        select(HumanItem).where(
            HumanItem.project_id == sprint.project_id,
            HumanItem.sprint_id.is_(None),
            HumanItem.status == "open",
        )
    ):
        item.sprint_id = sprint.id

    emit(
        db,
        kind="sprint.kicked_off",
        summary=f"Sprint {sprint.id} active with {len(tasks)} tasks",
        payload={"sprint_id": str(sprint.id), "task_ids": [str(t.id) for t in tasks]},
        role="planner",
    )
    db.commit()
    return {
        "sprint_id": str(sprint.id),
        "status": sprint.status,
        "task_ids": [str(t.id) for t in tasks],
        "task_count": len(tasks),
    }


INFLIGHT_STATES = (
    TaskState.test_authoring.value,
    TaskState.coding.value,
    TaskState.testing.value,
    TaskState.reviewing.value,
    TaskState.integrating.value,
)


def pause_sprint(db: Session, sprint_id: uuid.UUID) -> dict:
    """Request graceful pause: no new claims; in-flight stages finish then park with notes."""
    sprint = db.get(Sprint, sprint_id)
    if sprint is None:
        raise ValueError("sprint not found")
    if sprint.status == "paused":
        return {
            "sprint_id": str(sprint.id),
            "status": "paused",
            "inflight": 0,
            "message": "Sprint already paused",
        }
    if sprint.status == "pausing":
        inflight = (
            db.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.sprint_id == sprint.id, Task.state.in_(INFLIGHT_STATES))
            )
            or 0
        )
        return {
            "sprint_id": str(sprint.id),
            "status": "pausing",
            "inflight": int(inflight),
            "message": "Pause already in progress; agents finishing current stages",
        }
    if sprint.status != "active":
        raise ValueError(f"can only pause an active sprint (now {sprint.status})")

    sprint.status = "pausing"
    # Ready/planned tasks wait without being claimed
    waiting = list(
        db.scalars(
            select(Task).where(
                Task.sprint_id == sprint.id,
                Task.state.in_([TaskState.ready.value, TaskState.planned.value]),
            )
        )
    )
    for task in waiting:
        task.state = TaskState.paused.value
        note = (
            f"Sprint pause requested. Holding before stage {task.stage or task.role}. "
            "Resume will continue from this stage."
        )
        task.pause_notes = ((task.pause_notes or "") + "\n" + note).strip()

    inflight = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.sprint_id == sprint.id, Task.state.in_(INFLIGHT_STATES))
        )
        or 0
    )
    if inflight == 0:
        sprint.status = "paused"

    emit(
        db,
        kind="sprint.pause_requested",
        summary=f"Sprint {sprint.id} → {sprint.status} ({inflight} still in flight)",
        payload={"sprint_id": str(sprint.id), "inflight": int(inflight)},
        role="planner",
    )
    db.commit()
    return {
        "sprint_id": str(sprint.id),
        "status": sprint.status,
        "inflight": int(inflight),
        "message": (
            "Pause complete"
            if sprint.status == "paused"
            else "Agents asked to finish current work and leave pause notes; no new work will start"
        ),
    }


def resume_sprint(db: Session, sprint_id: uuid.UUID) -> dict:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None:
        raise ValueError("sprint not found")
    if sprint.status not in ("paused", "pausing"):
        raise ValueError(f"can only resume a paused/pausing sprint (now {sprint.status})")

    tasks = list(db.scalars(select(Task).where(Task.sprint_id == sprint.id)))
    resumed = 0
    for task in tasks:
        if task.state == TaskState.paused.value:
            task.state = TaskState.ready.value
            note = "Sprint resumed — continue from pause notes."
            task.pause_notes = ((task.pause_notes or "") + "\n" + note).strip()
            resumed += 1

    sprint.status = "active"
    if sprint.started_at is None:
        sprint.started_at = datetime.now(timezone.utc)

    emit(
        db,
        kind="sprint.resumed",
        summary=f"Sprint {sprint.id} resumed ({resumed} tasks ready)",
        payload={"sprint_id": str(sprint.id), "resumed": resumed},
        role="planner",
    )
    db.commit()
    return {
        "sprint_id": str(sprint.id),
        "status": sprint.status,
        "task_ids": [str(t.id) for t in tasks if t.state == TaskState.ready.value],
        "task_count": resumed,
    }


def finalize_pausing_sprints(db: Session) -> int:
    """If a pausing sprint has no inflight tasks, mark it paused."""
    pausing = list(db.scalars(select(Sprint).where(Sprint.status == "pausing")))
    done = 0
    for sprint in pausing:
        inflight = (
            db.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.sprint_id == sprint.id, Task.state.in_(INFLIGHT_STATES))
            )
            or 0
        )
        if inflight == 0:
            sprint.status = "paused"
            emit(
                db,
                kind="sprint.paused",
                summary=f"Sprint {sprint.id} fully paused",
                payload={"sprint_id": str(sprint.id)},
            )
            done += 1
    if done:
        db.commit()
    return done


def sprint_is_pausing_or_paused(db: Session, sprint_id: uuid.UUID | None) -> bool:
    if not sprint_id:
        return False
    sprint = db.get(Sprint, sprint_id)
    return sprint is not None and sprint.status in ("pausing", "paused")


def park_task_for_sprint_pause(db: Session, task: Task, completed_stage: str) -> bool:
    """After a stage finishes cleanly: if sprint is pausing, park with notes. Returns True if parked."""
    if not task.sprint_id:
        return False
    sprint = db.get(Sprint, task.sprint_id)
    if sprint is None or sprint.status not in ("pausing", "paused"):
        return False
    note = (
        f"Graceful pause after completing stage '{completed_stage}'. "
        f"Next stage was '{task.stage}'. Branch={task.branch or 'n/a'}. "
        "Resume from this stage with full context above."
    )
    task.pause_notes = ((task.pause_notes or "") + "\n" + note).strip()
    task.state = TaskState.paused.value
    from buildshift_orchestrator.runner.locks import release_locks

    release_locks(db, task.id)
    emit(
        db,
        kind="task.paused",
        task_id=task.id,
        role=completed_stage,
        status="paused",
        summary=note[:500],
        payload={"sprint_id": str(task.sprint_id)},
    )
    return True


def sprint_hierarchy(db: Session, sprint_id: uuid.UUID) -> dict:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None:
        raise ValueError("sprint not found")
    epics = list(
        db.scalars(select(Epic).where(Epic.sprint_id == sprint_id).order_by(Epic.sort_order))
    )
    tasks = list(db.scalars(select(Task).where(Task.sprint_id == sprint_id)))
    by_epic: dict[str, list[Task]] = {}
    for t in tasks:
        key = str(t.epic_id) if t.epic_id else "none"
        by_epic.setdefault(key, []).append(t)
    return {
        "sprint": sprint,
        "epics": [
            {
                "epic": e,
                "tasks": by_epic.get(str(e.id), []),
            }
            for e in epics
        ],
        "ungrouped_tasks": by_epic.get("none", []),
    }


def list_sprints(db: Session, project_id: uuid.UUID) -> list[Sprint]:
    return list(
        db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project_id)
            .order_by(Sprint.created_at.desc())
        )
    )
