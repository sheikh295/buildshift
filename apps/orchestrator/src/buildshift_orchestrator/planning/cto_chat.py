from __future__ import annotations

import json
import logging
import re
import uuid
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.control import add_daily_spend, is_kill_switch_on, under_daily_budget
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import (
    BacklogItem,
    CtoChatMessage,
    Epic,
    HumanItem,
    PrdProduct,
    Project,
    Sprint,
    Task,
)
from buildshift_orchestrator.router_config import role_model
from buildshift_orchestrator.runtime_settings import effective_settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the CTO of an AI software house called Buildshift.
The person messaging you is the Boss / CEO. Speak peer-to-peer: crisp, candid, respectful, no fluff.
You own planning — sprints, epics, tickets, priorities, technical tradeoffs, and unblocking work.

You receive a live snapshot of the selected project (PRD modules, sprints, epics, tasks with
acceptance criteria, HITL items, backlog). Use that as ground truth; do not invent merged work.

When the CEO asks you to change the plan or add work, include a JSON actions array.
When they only want discussion, return an empty actions array.

Respond with ONLY a JSON object (no markdown fence):
{
  "reply": "<markdown for the CEO>",
  "actions": [
    {
      "type": "add_backlog",
      "title": "...",
      "acceptance_criteria": "...",
      "owned_paths": ["path/or/glob"],
      "product_id": "<optional uuid from context>"
    },
    {
      "type": "update_task",
      "task_id": "<uuid>",
      "title": "<optional>",
      "acceptance_criteria": "<optional>"
    },
    {
      "type": "create_hitl",
      "summary": "..."
    }
  ]
}

Rules:
- Prefer add_backlog for new work (it enters the next sprint proposal).
- Prefer update_task only for existing task UUIDs in the snapshot.
- Keep reply concise unless the CEO asks for depth.
"""


def _task_line(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "state": t.state,
        "role": t.role,
        "stage": t.stage,
        "acceptance_criteria": t.acceptance_criteria or "",
        "owned_paths": t.owned_paths or [],
        "sprint_id": str(t.sprint_id) if t.sprint_id else None,
        "epic_id": str(t.epic_id) if t.epic_id else None,
        "parent_epic": t.parent_epic,
        "error": t.error,
        "pr_url": t.pr_url,
        "spent_usd": float(t.spent_usd or 0),
    }


def build_project_context(db: Session, project: Project) -> str:
    modules = list(
        db.scalars(
            select(PrdProduct)
            .where(PrdProduct.project_id == project.id)
            .order_by(PrdProduct.build_order)
        )
    )
    sprints = list(
        db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project.id)
            .order_by(Sprint.created_at.desc())
            .limit(8)
        )
    )
    epics = list(db.scalars(select(Epic).where(Epic.project_id == project.id)))
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(80)
        )
    )
    backlog = list(
        db.scalars(
            select(BacklogItem)
            .where(
                BacklogItem.product_id.in_([m.id for m in modules]) if modules else False
            )
            .where(BacklogItem.status == "open")
            .limit(40)
        )
        if modules
        else []
    )
    hitl = list(
        db.scalars(
            select(HumanItem)
            .where(HumanItem.project_id == project.id, HumanItem.status == "open")
            .limit(30)
        )
    )

    by_state: dict[str, int] = {}
    for t in tasks:
        by_state[t.state] = by_state.get(t.state, 0) + 1

    payload = {
        "project": {
            "id": str(project.id),
            "slug": project.slug,
            "title": project.title,
            "repo_url": project.repo_url,
            "repo_branch": project.repo_branch,
            "has_prd": bool((project.prd_markdown or "").strip()),
            "prd_excerpt": (project.prd_markdown or "")[:6000],
        },
        "modules": [
            {
                "id": str(m.id),
                "slug": m.slug,
                "title": m.title,
                "summary": m.summary,
                "status": m.status,
            }
            for m in modules
        ],
        "task_counts_by_state": by_state,
        "sprints": [
            {
                "id": str(s.id),
                "status": s.status,
                "capacity_hours": float(s.capacity_hours),
                "estimated_hours": float(s.estimated_hours),
                "goals": s.goals or [],
            }
            for s in sprints
        ],
        "epics": [
            {
                "id": str(e.id),
                "sprint_id": str(e.sprint_id),
                "title": e.title,
                "summary": e.summary or "",
                "status": e.status,
            }
            for e in epics
        ],
        "tasks": [_task_line(t) for t in tasks],
        "open_backlog": [
            {
                "id": str(b.id),
                "title": b.title,
                "acceptance_criteria": b.acceptance_criteria,
                "owned_paths": b.owned_paths or [],
                "product_id": str(b.product_id) if b.product_id else None,
            }
            for b in backlog
        ],
        "open_hitl": [
            {
                "id": str(h.id),
                "kind": h.kind,
                "summary": h.summary,
                "task_id": str(h.task_id) if h.task_id else None,
            }
            for h in hitl
        ],
    }
    return json.dumps(payload, indent=2, default=str)


def _parse_llm_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Fallback: treat whole body as reply
    return {"reply": text.strip(), "actions": []}


def _call_litellm(settings: Settings, messages: list[dict[str, str]]) -> tuple[str, Decimal]:
    model = role_model("planner")
    url = f"{settings.litellm_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            # Some gateways reject response_format — retry without
            body.pop("response_format", None)
            resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"CTO LLM failed ({resp.status_code}): {resp.text[:800]}")
        data = resp.json()
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    )
    usage = data.get("usage") or {}
    # Rough cost if provider omits dollars — haiku-class default
    prompt_t = int(usage.get("prompt_tokens") or 0)
    completion_t = int(usage.get("completion_tokens") or 0)
    cost = Decimal(str(usage.get("cost") or 0))
    if cost <= 0 and (prompt_t or completion_t):
        cost = (Decimal(prompt_t) * Decimal("0.000001") + Decimal(completion_t) * Decimal("0.000005"))
    if cost <= 0:
        cost = Decimal("0.01")
    return content, cost


def apply_actions(
    db: Session, project: Project, actions: list[Any]
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for raw in actions or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "")
        try:
            if kind == "add_backlog":
                title = (raw.get("title") or "").strip()
                if not title:
                    continue
                product_id = None
                if raw.get("product_id"):
                    try:
                        product_id = uuid.UUID(str(raw["product_id"]))
                    except ValueError:
                        product_id = None
                if product_id is None:
                    first = db.scalar(
                        select(PrdProduct).where(PrdProduct.project_id == project.id)
                    )
                    product_id = first.id if first else None
                item = BacklogItem(
                    id=uuid.uuid4(),
                    product_id=product_id,
                    title=title,
                    acceptance_criteria=str(raw.get("acceptance_criteria") or ""),
                    owned_paths=list(raw.get("owned_paths") or []),
                    difficulty=str(raw.get("difficulty") or "normal"),
                    status="open",
                )
                db.add(item)
                applied.append({"type": kind, "id": str(item.id), "title": title})
            elif kind == "update_task":
                try:
                    tid = uuid.UUID(str(raw.get("task_id")))
                except (TypeError, ValueError):
                    continue
                task = db.get(Task, tid)
                if task is None or task.project_id != project.id:
                    continue
                if raw.get("title"):
                    task.title = str(raw["title"]).strip()
                if raw.get("acceptance_criteria") is not None:
                    task.acceptance_criteria = str(raw["acceptance_criteria"])
                if raw.get("owned_paths") is not None:
                    task.owned_paths = list(raw["owned_paths"] or [])
                applied.append({"type": kind, "id": str(task.id), "title": task.title})
            elif kind == "create_hitl":
                summary = (raw.get("summary") or "").strip()
                if not summary:
                    continue
                item = HumanItem(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    kind="question",
                    summary=summary,
                    status="open",
                )
                db.add(item)
                applied.append({"type": kind, "id": str(item.id)})
        except Exception:
            log.exception("failed applying CTO action %s", raw)
    return applied


def list_messages(db: Session, project_id: uuid.UUID, limit: int = 100) -> list[CtoChatMessage]:
    return list(
        db.scalars(
            select(CtoChatMessage)
            .where(CtoChatMessage.project_id == project_id)
            .order_by(CtoChatMessage.created_at.asc())
            .limit(limit)
        )
    )


def clear_messages(db: Session, project_id: uuid.UUID) -> int:
    rows = list_messages(db, project_id, limit=5000)
    n = len(rows)
    for r in rows:
        db.delete(r)
    db.commit()
    return n


def chat(
    db: Session,
    settings: Settings,
    project_id: uuid.UUID,
    message: str,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")
    if is_kill_switch_on(db):
        raise ValueError("kill switch is on — CTO chat paused")
    eff = effective_settings(settings)
    if not under_daily_budget(db, eff):
        raise ValueError("daily budget exhausted — CTO chat paused")

    user_msg = CtoChatMessage(
        id=uuid.uuid4(),
        project_id=project.id,
        role="user",
        content=text,
        actions=[],
        cost_usd=Decimal("0"),
    )
    db.add(user_msg)
    db.flush()

    history = list_messages(db, project.id, limit=40)
    context = build_project_context(db, project)
    llm_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"## Project snapshot\n```json\n{context}\n```",
        },
    ]
    for m in history:
        llm_messages.append(
            {
                "role": "assistant" if m.role == "assistant" else "user",
                "content": m.content,
            }
        )

    raw, cost = _call_litellm(eff, llm_messages)
    parsed = _parse_llm_json(raw)
    reply_text = str(parsed.get("reply") or raw or "").strip() or "(no reply)"
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    applied = apply_actions(db, project, actions)

    assistant = CtoChatMessage(
        id=uuid.uuid4(),
        project_id=project.id,
        role="assistant",
        content=reply_text,
        actions=applied,
        cost_usd=cost,
    )
    db.add(assistant)
    add_daily_spend(db, cost)
    emit(
        db,
        kind="cto.chat",
        summary=f"CTO chat · {project.title}",
        cost_usd=cost,
        payload={
            "project_id": str(project.id),
            "actions": applied,
            "user_preview": text[:200],
        },
    )
    db.commit()
    db.refresh(assistant)
    return {
        "reply": assistant,
        "history": list_messages(db, project.id),
        "applied_actions": applied,
    }
