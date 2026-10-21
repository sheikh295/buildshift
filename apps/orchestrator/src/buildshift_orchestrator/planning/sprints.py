from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.control import add_daily_spend, is_kill_switch_on, under_daily_budget
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import (
    BacklogItem,
    CtoChatMessage,
    DailyPlan,
    Decision,
    Epic,
    HumanItem,
    PrdProduct,
    PrdRequirement,
    Project,
    Sprint,
    Task,
    TaskState,
)

log = logging.getLogger(__name__)
from buildshift_orchestrator.planning.cto_index import index_prd_with_cto
from buildshift_orchestrator.planning.llm import call_role_llm
from buildshift_orchestrator.router_config import role_tier, router_limits
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.runner.locks import owned_paths_overlap
from buildshift_orchestrator.runtime_settings import effective_settings


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


def delete_project(
    db: Session,
    project_id: uuid.UUID,
    *,
    settings: Settings | None = None,
) -> dict:
    """Delete a project and related planning/execution rows; best-effort cleanup of local git mirrors."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")

    title = project.title
    slug = project.slug
    mirror_hint = project.repo_path
    modules = list(
        db.scalars(select(PrdProduct).where(PrdProduct.project_id == project.id))
    )
    module_ids = [m.id for m in modules]
    sprints = list(db.scalars(select(Sprint).where(Sprint.project_id == project.id)))
    sprint_ids = [s.id for s in sprints]

    tasks = list(db.scalars(select(Task).where(Task.project_id == project.id)))
    if sprint_ids:
        extra = list(db.scalars(select(Task).where(Task.sprint_id.in_(sprint_ids))))
        seen = {t.id for t in tasks}
        for t in extra:
            if t.id not in seen:
                tasks.append(t)
                seen.add(t.id)
    task_ids = [t.id for t in tasks]
    worktree_paths = [t.worktree_path for t in tasks if t.worktree_path]

    # Explicit deletes where FKs are SET NULL (would otherwise leave orphans)
    if task_ids:
        for item in db.scalars(select(HumanItem).where(HumanItem.task_id.in_(task_ids))):
            db.delete(item)
    for item in db.scalars(select(HumanItem).where(HumanItem.project_id == project.id)):
        db.delete(item)
    for plan in db.scalars(select(DailyPlan).where(DailyPlan.project_id == project.id)):
        db.delete(plan)
    if module_ids:
        for item in db.scalars(select(BacklogItem).where(BacklogItem.product_id.in_(module_ids))):
            db.delete(item)
        for dec in db.scalars(select(Decision).where(Decision.product_id.in_(module_ids))):
            db.delete(dec)

    for task in tasks:
        db.delete(task)
    db.flush()

    # CASCADE: sprints/epics/cto_chat/prd_products (+ requirements)
    for msg in db.scalars(
        select(CtoChatMessage).where(CtoChatMessage.project_id == project.id)
    ):
        db.delete(msg)

    emit(
        db,
        kind="project.deleted",
        summary=f"Deleted project {title}",
        payload={
            "project_id": str(project.id),
            "slug": slug,
            "tasks_deleted": len(task_ids),
            "modules_deleted": len(module_ids),
            "sprints_deleted": len(sprint_ids),
        },
    )
    db.delete(project)
    db.commit()

    cleaned: list[str] = []
    if settings is not None:
        candidates: list[Path] = []
        if mirror_hint:
            candidates.append(Path(mirror_hint))
        candidates.append(settings.data_dir / "repos" / slug)
        for path in candidates:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                    cleaned.append(str(path))
            except OSError as exc:
                log.warning("failed to remove project mirror %s: %s", path, exc)
        for wt in worktree_paths:
            try:
                p = Path(wt)
                if p.is_dir():
                    shutil.rmtree(p)
                    cleaned.append(str(p))
            except OSError as exc:
                log.warning("failed to remove worktree %s: %s", wt, exc)
        # Common worktree layout: data/worktrees/{task-id}
        for tid in task_ids:
            p = settings.data_dir / "worktrees" / str(tid)
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                    cleaned.append(str(p))
            except OSError as exc:
                log.warning("failed to remove worktree %s: %s", p, exc)

    return {
        "project_id": str(project_id),
        "slug": slug,
        "title": title,
        "tasks_deleted": len(task_ids),
        "modules_deleted": len(module_ids),
        "sprints_deleted": len(sprint_ids),
        "paths_removed": cleaned,
    }


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
    settings: Settings | None = None,
) -> dict:
    """Store PRD and run CTO LLM indexing (no regex scrape)."""
    if settings is None:
        raise ValueError("settings required for CTO PRD indexing")
    return index_prd_with_cto(
        db,
        settings,
        project_id,
        markdown,
        docs_root=docs_root,
        source_name=source_name,
    )


def reindex_prd(
    db: Session,
    project_id: uuid.UUID,
    *,
    docs_root=None,
    settings: Settings | None = None,
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    if not (project.prd_markdown or "").strip():
        raise ValueError("project has no stored PRD; upload first")
    if settings is None:
        raise ValueError("settings required for CTO reindex")
    return index_prd_with_cto(
        db,
        settings,
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
    module_ids = [m.id for m in modules]
    open_backlog = 0
    if module_ids:
        open_backlog = (
            db.scalar(
                select(func.count())
                .select_from(BacklogItem)
                .where(
                    BacklogItem.product_id.in_(module_ids),
                    BacklogItem.status == "open",
                )
            )
            or 0
        )
    return {
        "project": project,
        "modules": modules,
        "sprint_count": int(sprint_count),
        "open_hitl": int(open_hitl),
        "open_backlog": int(open_backlog),
    }


PM_SPRINT_SYSTEM = """You are the Product Manager of an AI software house (Buildshift).
The Boss asked you to propose a time-boxed sprint from the CTO's project index and open backlog.

Return ONLY JSON:
{
  "goals": ["sprint goal bullets"],
  "epics": [
    {
      "title": "Epic title",
      "summary": "What this epic delivers",
      "product_id": "<optional uuid of a module from context>",
      "tasks": [
        {
          "title": "Concrete developer task",
          "acceptance_criteria": "Testable done-when statement",
          "owned_paths": ["real/repo/paths/..."],
          "difficulty": "easy|normal|hard",
          "estimated_hours": 1.5,
          "backlog_id": "<optional uuid from open_backlog>",
          "req_ids": ["optional requirement uuids"]
        }
      ]
    }
  ]
}

Rules:
- capacity_hours is the TARGET fill, not a soft suggestion: sum(estimated_hours) should be
  between 70% and 100% of capacity_hours. Prefer more small tasks over one tiny sprint.
- Never exceed capacity_hours.
- Prefer open_backlog items before inventing new PRD-derived work (QA fixes first).
- Tasks must be implementable by coding agents: real acceptance criteria and owned_paths.
- owned_paths should fit a typical Next.js/TS repo when unknown (e.g. app/, packages/, lib/).
- Group related tasks under epics. 1–4 epics typical for short sprints.
- Slice modules into concrete 0.5–2h tasks until the hour budget is mostly used.
"""


def _pm_project_snapshot(db: Session, project: Project) -> dict:
    modules = list(
        db.scalars(
            select(PrdProduct)
            .where(PrdProduct.project_id == project.id)
            .order_by(PrdProduct.build_order)
        )
    )
    module_payload = []
    backlog_payload = []
    for m in modules:
        reqs = list(
            db.scalars(
                select(PrdRequirement)
                .where(PrdRequirement.product_id == m.id)
                .order_by(PrdRequirement.sort_order)
            )
        )
        module_payload.append(
            {
                "id": str(m.id),
                "title": m.title,
                "slug": m.slug,
                "summary": m.summary,
                "build_order": m.build_order,
                "requirements": [
                    {
                        "id": str(r.id),
                        "req_key": r.req_key,
                        "text": r.text,
                        "traced": r.traced,
                    }
                    for r in reqs
                ],
            }
        )
        for item in db.scalars(
            select(BacklogItem)
            .where(BacklogItem.product_id == m.id, BacklogItem.status == "open")
            .order_by(BacklogItem.sort_order)
        ):
            backlog_payload.append(
                {
                    "id": str(item.id),
                    "product_id": str(m.id),
                    "title": item.title,
                    "acceptance_criteria": item.acceptance_criteria,
                    "owned_paths": item.owned_paths or [],
                    "difficulty": item.difficulty,
                }
            )

    recent_tasks = list(
        db.scalars(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.updated_at.desc())
            .limit(40)
        )
    )
    return {
        "project": {
            "id": str(project.id),
            "title": project.title,
            "slug": project.slug,
            "repo_url": project.repo_url,
            "repo_branch": project.repo_branch,
            "context_markdown": project.context_markdown or "",
            "index_status": project.index_status,
        },
        "modules": module_payload,
        "open_backlog": backlog_payload,
        "recent_tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "state": t.state,
                "error": t.error,
                "acceptance_criteria": (t.acceptance_criteria or "")[:400],
            }
            for t in recent_tasks
        ],
    }


def propose_sprint(
    db: Session,
    settings: Settings,
    project_id: uuid.UUID,
    *,
    capacity_hours: float = 6.0,
    mode: str = "hours",
) -> Sprint:
    """PM LLM proposes sprint/epics/tasks from CTO index + open backlog."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    if (project.index_status or "") != "ready":
        raise ValueError(
            "CTO has not indexed this PRD yet — upload/reindex the PRD first "
            f"(index_status={project.index_status or 'none'})"
        )
    try:
        hours_req = float(capacity_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("capacity_hours must be a number") from exc
    if hours_req < 1 or hours_req > 40:
        raise ValueError("capacity_hours must be between 1 and 40")

    if is_kill_switch_on(db):
        raise ValueError("kill switch is on — PM planning paused")
    eff = effective_settings(settings)
    if not under_daily_budget(db, eff):
        raise ValueError("daily budget exhausted — PM planning paused")

    cap = Decimal(str(hours_req))
    snapshot = _pm_project_snapshot(db, project)
    import json as _json

    emit(
        db,
        kind="pm.propose_started",
        summary=f"PM proposing ≤{float(cap)}h sprint for {project.title}",
        role="pm",
        status="working",
        payload={
            "project_id": str(project.id),
            "capacity_hours": float(cap),
        },
    )
    db.commit()

    user_content = (
        f"Propose a sprint with capacity_hours={float(cap)}. "
        f"Fill at least {float(cap) * 0.7:.1f}h and at most {float(cap)}h of estimated work.\n\n"
        f"## Project snapshot\n```json\n{_json.dumps(snapshot, indent=2, default=str)[:100_000]}\n```"
    )

    try:
        parsed, cost = call_role_llm(
            eff,
            "pm",
            [
                {"role": "system", "content": PM_SPRINT_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=8192,
            timeout=240.0,
        )
    except Exception as exc:
        emit(
            db,
            kind="pm.propose_failed",
            summary=f"PM propose failed for {project.title}: {exc}"[:500],
            role="pm",
            status="failed",
            payload={"project_id": str(project.id)},
        )
        db.commit()
        raise

    epics_data = parsed.get("epics") or []
    if not isinstance(epics_data, list) or not epics_data:
        # One repair attempt if empty
        parsed, cost2 = call_role_llm(
            eff,
            "pm",
            [
                {"role": "system", "content": PM_SPRINT_SYSTEM},
                {"role": "user", "content": user_content},
                {
                    "role": "user",
                    "content": "Your previous response had no epics. Return a valid plan with at least one epic and tasks within capacity.",
                },
            ],
            temperature=0.2,
        )
        cost += cost2
        epics_data = parsed.get("epics") or []
    if not isinstance(epics_data, list) or not epics_data:
        raise ValueError("PM returned no epics/tasks")

    # Validate / trim hours
    total_h = Decimal("0")
    for epic in epics_data:
        for t in epic.get("tasks") or []:
            try:
                total_h += Decimal(str(t.get("estimated_hours") or 1))
            except Exception:
                total_h += Decimal("1")
    if total_h > cap * Decimal("1.15") or total_h < cap * Decimal("0.7"):
        # Soft overage or underfill: ask repair once
        if total_h > cap * Decimal("1.15"):
            repair_msg = (
                f"Total estimated_hours={float(total_h)} exceeds capacity {float(cap)}. "
                "Return a revised JSON plan that fits ≤ capacity."
            )
        else:
            repair_msg = (
                f"Total estimated_hours={float(total_h)} is too small for capacity {float(cap)}. "
                "Return a revised JSON plan that fills at least 70% of capacity with concrete "
                "additional tasks from modules/backlog (still ≤ capacity)."
            )
        parsed, cost2 = call_role_llm(
            eff,
            "pm",
            [
                {"role": "system", "content": PM_SPRINT_SYSTEM},
                {"role": "user", "content": user_content},
                {
                    "role": "assistant",
                    "content": _json.dumps(parsed),
                },
                {
                    "role": "user",
                    "content": repair_msg,
                },
            ],
            temperature=0.2,
        )
        cost += cost2
        epics_data = parsed.get("epics") or epics_data

    goals = parsed.get("goals") or [
        f"Sprint for {project.title}",
        f"Capacity ≤ {cap}h",
    ]
    if not isinstance(goals, list):
        goals = [str(goals)]

    limits = router_limits()
    max_attempts = max(
        int(limits.get("max_attempts_per_tier") or settings.max_attempts_per_tier),
        4,
    )
    budget = Decimal(str(limits.get("task_budget_usd") or settings.task_budget_usd))

    hours = Decimal("0")
    spend = Decimal("0")
    created_tasks: list[Task] = []

    sprint = Sprint(
        id=uuid.uuid4(),
        project_id=project.id,
        mode=mode or "hours",
        status="planned",
        capacity_hours=cap,
        goals=[str(g) for g in goals][:20],
        estimated_spend_usd=Decimal("0"),
        estimated_hours=Decimal("0"),
    )
    db.add(sprint)
    db.flush()

    default_product = db.scalar(
        select(PrdProduct)
        .where(PrdProduct.project_id == project.id)
        .order_by(PrdProduct.build_order)
    )

    for sort_i, epic_raw in enumerate(epics_data):
        title = str(epic_raw.get("title") or f"Epic {sort_i + 1}").strip()
        summary = str(epic_raw.get("summary") or "")
        product_id = None
        if epic_raw.get("product_id"):
            try:
                product_id = uuid.UUID(str(epic_raw["product_id"]))
            except ValueError:
                product_id = None
        if product_id is None and default_product:
            product_id = default_product.id

        epic = Epic(
            id=uuid.uuid4(),
            sprint_id=sprint.id,
            project_id=project.id,
            product_id=product_id,
            title=title,
            summary=summary,
            status="planned",
            sort_order=sort_i,
        )
        db.add(epic)
        db.flush()

        for ticket in epic_raw.get("tasks") or []:
            t_title = str(ticket.get("title") or "").strip()
            if not t_title:
                continue
            try:
                est_h = Decimal(str(ticket.get("estimated_hours") or 1))
            except Exception:
                est_h = Decimal("1")
            if est_h <= 0:
                est_h = Decimal("1")
            # Hard stop if we would far exceed capacity after at least one task
            if created_tasks and hours + est_h > cap:
                continue

            criteria = str(ticket.get("acceptance_criteria") or "")
            paths = list(ticket.get("owned_paths") or [])
            difficulty = str(ticket.get("difficulty") or "normal")
            req_ids = [str(x) for x in (ticket.get("req_ids") or [])]

            backlog_id = ticket.get("backlog_id")
            if backlog_id:
                try:
                    item = db.get(BacklogItem, uuid.UUID(str(backlog_id)))
                    if item:
                        item.status = "scheduled"
                except ValueError:
                    pass
            else:
                db.add(
                    BacklogItem(
                        id=uuid.uuid4(),
                        product_id=product_id,
                        title=t_title,
                        acceptance_criteria=criteria,
                        owned_paths=paths,
                        difficulty=difficulty,
                        estimated_spend_usd=budget / 2,
                        req_ids=req_ids,
                        status="scheduled",
                    )
                )

            for req_id in req_ids:
                try:
                    req = db.get(PrdRequirement, uuid.UUID(str(req_id)))
                    if req:
                        req.traced = True
                except ValueError:
                    pass

            task = Task(
                id=uuid.uuid4(),
                title=t_title,
                state=TaskState.planned.value,
                role="test_author",
                stage="test_author",
                tier=role_tier("test_author"),
                difficulty=difficulty,
                acceptance_criteria=criteria,
                owned_paths=paths,
                budget_usd=budget,
                max_attempts=max_attempts,
                product_id=product_id,
                project_id=project.id,
                sprint_id=sprint.id,
                epic_id=epic.id,
                parent_epic=title,
                req_ids=req_ids,
                deps=[],
            )
            db.add(task)
            created_tasks.append(task)
            hours += est_h
            spend += budget / 2

    if not created_tasks:
        db.rollback()
        raise ValueError("PM plan produced no tasks")

    db.flush()
    for i, task in enumerate(created_tasks):
        deps: list[str] = []
        for prev in created_tasks[:i]:
            if owned_paths_overlap(task.owned_paths or [], prev.owned_paths or []):
                deps.append(str(prev.id))
        task.deps = deps

    sprint.estimated_hours = hours
    sprint.estimated_spend_usd = spend
    add_daily_spend(db, cost)
    emit(
        db,
        kind="pm.sprint_proposed",
        summary=f"PM sprint: {len(created_tasks)} tasks, ~{hours}h (cap {cap}h)",
        payload={
            "sprint_id": str(sprint.id),
            "project_id": str(project.id),
            "task_count": len(created_tasks),
            "estimated_hours": float(hours),
            "capacity_hours": float(cap),
            "mode": mode,
        },
        role="pm",
        cost_usd=cost,
    )
    # Keep legacy event name for HUD filters
    emit(
        db,
        kind="sprint.proposed",
        summary=f"Sprint {sprint.id}: {len(created_tasks)} tasks, ~{hours}h (cap {cap}h)",
        payload={"sprint_id": str(sprint.id), "project_id": str(project.id)},
        role="pm",
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
