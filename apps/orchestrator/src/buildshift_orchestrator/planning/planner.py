from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import (
    BacklogItem,
    DailyPlan,
    Decision,
    HumanItem,
    PrdProduct,
    PrdRequirement,
    Task,
    TaskState,
)
from buildshift_orchestrator.router_config import role_tier, router_limits
from buildshift_orchestrator.runner.locks import owned_paths_overlap


HUMAN_KEYWORDS = (
    ("api key", "key"),
    ("secret", "key"),
    ("account", "account"),
    ("billing", "billing"),
    ("dns", "dns"),
    ("domain", "dns"),
    ("publish", "publish"),
    ("app store", "publish"),
)


def kickoff_product(db: Session, product_id: uuid.UUID) -> dict:
    product = db.get(PrdProduct, product_id)
    if product is None:
        raise ValueError("product not found")

    reqs = list(
        db.scalars(
            select(PrdRequirement)
            .where(PrdRequirement.product_id == product_id)
            .order_by(PrdRequirement.sort_order)
        )
    )
    human_created = 0
    for req in reqs:
        lower = req.text.lower()
        for needle, kind in HUMAN_KEYWORDS:
            if needle in lower:
                db.add(
                    HumanItem(
                        id=uuid.uuid4(),
                        product_id=product.id,
                        kind=kind,
                        summary=req.text,
                        needed_by="kickoff",
                        status="open",
                    )
                )
                human_created += 1
                break

    existing_decision = db.scalar(
        select(Decision).where(Decision.product_id == product.id, Decision.key == "kickoff")
    )
    if existing_decision is None:
        db.add(
            Decision(
                id=uuid.uuid4(),
                product_id=product.id,
                key="kickoff",
                question="Product kickoff recorded",
                answer=f"Indexed {len(reqs)} requirements; {human_created} human items flagged",
            )
        )
    product.status = "kicked_off"
    emit(
        db,
        kind="product.kickoff",
        summary=f"Kickoff for {product.slug}",
        payload={"product_id": str(product.id), "human_items": human_created},
    )
    db.commit()
    return {
        "product_id": str(product.id),
        "slug": product.slug,
        "requirements": len(reqs),
        "human_items": human_created,
    }


def propose_plan(
    db: Session,
    settings: Settings,
    product_id: uuid.UUID,
    *,
    max_tickets: int = 3,
) -> DailyPlan:
    product = db.get(PrdProduct, product_id)
    if product is None:
        raise ValueError("product not found")

    reqs = list(
        db.scalars(
            select(PrdRequirement)
            .where(PrdRequirement.product_id == product_id)
            .order_by(PrdRequirement.sort_order)
        )
    )
    open_backlog = list(
        db.scalars(
            select(BacklogItem)
            .where(
                BacklogItem.product_id == product_id,
                BacklogItem.status == "open",
            )
            .order_by(BacklogItem.sort_order)
        )
    )

    tickets: list[dict] = []
    # Prefer existing backlog first
    for item in open_backlog[:max_tickets]:
        tickets.append(
            {
                "title": item.title,
                "acceptance_criteria": item.acceptance_criteria,
                "owned_paths": item.owned_paths,
                "difficulty": item.difficulty,
                "estimated_spend_usd": float(item.estimated_spend_usd),
                "req_ids": item.req_ids,
                "backlog_id": str(item.id),
            }
        )

    # Fill from untraced requirements
    if len(tickets) < max_tickets:
        for req in reqs:
            if req.traced:
                continue
            if len(tickets) >= max_tickets:
                break
            slug = product.slug.replace("-", "_")
            path = f"src/{slug}/{req.req_key.lower()}.md"
            tickets.append(
                {
                    "title": f"{product.title}: {req.req_key}",
                    "acceptance_criteria": req.text,
                    # Keep owned paths disjoint; .buildshift metadata is task-scoped in the mock harness
                    "owned_paths": [path],
                    "difficulty": "normal",
                    "estimated_spend_usd": float(settings.task_budget_usd) / 2,
                    "req_ids": [str(req.id)],
                    "backlog_id": None,
                }
            )

    goals = [f"Advance {product.title}", f"Cover up to {len(tickets)} requirements/tickets"]
    spend = sum(float(t["estimated_spend_usd"]) for t in tickets)

    prior = db.scalar(
        select(DailyPlan)
        .where(DailyPlan.product_id == product_id)
        .order_by(DailyPlan.created_at.desc())
        .limit(1)
    )
    prior_titles = {t.get("title") for t in (prior.tickets if prior else [])}
    new_titles = {t["title"] for t in tickets}
    diff = {
        "added": sorted(new_titles - prior_titles),
        "removed": sorted(prior_titles - new_titles),
        "unchanged": sorted(new_titles & prior_titles),
    }

    plan = DailyPlan(
        id=uuid.uuid4(),
        product_id=product.id,
        status="draft",
        goals=goals,
        tickets=tickets,
        diff=diff,
        estimated_spend_usd=Decimal(str(spend)),
    )
    db.add(plan)
    emit(
        db,
        kind="plan.proposed",
        summary=f"Draft plan for {product.slug} with {len(tickets)} tickets",
        payload={"plan_id": str(plan.id), "diff": diff},
        role="planner",
        tier=role_tier("planner"),
    )
    db.commit()
    db.refresh(plan)
    return plan


def show_plan(db: Session, plan_id: uuid.UUID) -> DailyPlan:
    plan = db.get(DailyPlan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    return plan


def approve_plan(db: Session, settings: Settings, plan_id: uuid.UUID) -> dict:
    plan = db.get(DailyPlan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    if plan.status == "approved":
        raise ValueError("plan already approved")

    limits = router_limits()
    # Plan tasks run 3 stages + possible integrate retries; give them headroom
    max_attempts = max(
        int(limits.get("max_attempts_per_tier") or settings.max_attempts_per_tier),
        4,
    )
    budget = Decimal(str(limits.get("task_budget_usd") or settings.task_budget_usd))

    created: list[Task] = []
    for ticket in plan.tickets:
        backlog_id = ticket.get("backlog_id")
        if backlog_id:
            item = db.get(BacklogItem, uuid.UUID(backlog_id))
            if item:
                item.status = "scheduled"
        else:
            item = BacklogItem(
                id=uuid.uuid4(),
                product_id=plan.product_id,
                title=ticket["title"],
                acceptance_criteria=ticket.get("acceptance_criteria") or "",
                owned_paths=ticket.get("owned_paths") or [],
                difficulty=ticket.get("difficulty") or "normal",
                estimated_spend_usd=Decimal(str(ticket.get("estimated_spend_usd") or 1)),
                req_ids=ticket.get("req_ids") or [],
                status="scheduled",
            )
            db.add(item)
            db.flush()

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
            state=TaskState.ready.value,
            role="test_author",
            stage="test_author",
            tier=role_tier("test_author"),
            difficulty=ticket.get("difficulty") or "normal",
            acceptance_criteria=ticket.get("acceptance_criteria") or "",
            owned_paths=ticket.get("owned_paths") or [],
            budget_usd=budget,
            max_attempts=max_attempts,
            product_id=plan.product_id,
            plan_id=plan.id,
            req_ids=ticket.get("req_ids") or [],
            deps=[],
        )
        db.add(task)
        created.append(task)

    # Wire deps: later tickets wait on earlier ones whose owned paths overlap
    db.flush()
    for i, task in enumerate(created):
        deps: list[str] = []
        for prev in created[:i]:
            if owned_paths_overlap(task.owned_paths or [], prev.owned_paths or []):
                deps.append(str(prev.id))
        task.deps = deps

    created_tasks = [str(t.id) for t in created]
    plan.status = "approved"
    plan.approved_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="plan.approved",
        summary=f"Approved plan {plan.id}; spawned {len(created_tasks)} tasks",
        payload={"plan_id": str(plan.id), "task_ids": created_tasks},
        role="planner",
    )
    db.commit()
    return {"plan_id": str(plan.id), "task_ids": created_tasks, "status": "approved"}
