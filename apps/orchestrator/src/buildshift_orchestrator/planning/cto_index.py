from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.control import add_daily_spend, is_kill_switch_on, under_daily_budget
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import HumanItem, PrdProduct, PrdRequirement, Project
from buildshift_orchestrator.planning.llm import call_role_llm
from buildshift_orchestrator.runtime_settings import effective_settings

log = logging.getLogger(__name__)

CTO_INDEX_SYSTEM = """You are the CTO of an AI software house (Buildshift).
The Boss/CEO uploaded a full product PRD (narrative markdown — not a ticket list).

Your job: index it into a useful engineering backlog structure.

Return ONLY a JSON object:
{
  "context_markdown": "Living CTO brief: product vision, constraints, tech notes, priorities, open risks. Markdown.",
  "modules": [
    {
      "title": "Short feature/domain name (e.g. Calculation Engine)",
      "slug": "calculation-engine",
      "summary": "1-3 sentences on what this module owns",
      "build_order": 10,
      "requirements": [
        {
          "req_key": "R1",
          "text": "Concrete, testable requirement or acceptance-style statement"
        }
      ]
    }
  ],
  "hitl_questions": [
    "Questions only the CEO can answer before build (accounts, brand, countries, etc.)"
  ]
}

Rules:
- Modules are real product areas (engine, UI, SEO pages, methodology, analytics…) — NOT PRD section numbers like "16. Open questions".
- Prefer 4–12 modules. Each module 2–8 requirements that are buildable.
- Order build_order so foundations (engine, data) come before pages/SEO.
- hitl_questions only for true human blockers from the PRD open questions / decisions.
- Do not invent fake file paths here; PM will assign owned_paths later.
"""


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or f"module-{uuid.uuid4().hex[:8]}"


def replace_project_modules(
    db: Session,
    project: Project,
    modules_data: list[dict[str, Any]],
    *,
    docs_root: Path | None = None,
    source_name: str = "cto-index",
) -> list[PrdProduct]:
    """Replace all PRD modules/requirements for a project from CTO structured output."""
    existing = list(
        db.scalars(select(PrdProduct).where(PrdProduct.project_id == project.id))
    )
    for product in existing:
        for req in list(product.requirements):
            db.delete(req)
        db.delete(product)
    db.flush()

    created: list[PrdProduct] = []
    prefix = f"{project.slug}--"
    for i, item in enumerate(modules_data or []):
        title = str(item.get("title") or f"Module {i + 1}").strip()
        slug_base = _slugify(str(item.get("slug") or title))
        slug = f"{prefix}{slug_base}"
        try:
            build_order = int(item.get("build_order") if item.get("build_order") is not None else 50 + i)
        except (TypeError, ValueError):
            build_order = 50 + i
        summary = str(item.get("summary") or "")[:2000]
        product = PrdProduct(
            id=uuid.uuid4(),
            project_id=project.id,
            slug=slug,
            title=title,
            summary=summary,
            build_order=build_order,
            status="indexed",
        )
        db.add(product)
        db.flush()

        reqs = item.get("requirements") or []
        for j, req in enumerate(reqs):
            if isinstance(req, str):
                text = req.strip()
                key = f"R{j + 1}"
            else:
                text = str(req.get("text") or "").strip()
                key = str(req.get("req_key") or f"R{j + 1}")
            if not text:
                continue
            db.add(
                PrdRequirement(
                    id=uuid.uuid4(),
                    product_id=product.id,
                    req_key=key[:64],
                    text=text,
                    sort_order=j,
                    traced=False,
                )
            )

        if docs_root is not None:
            docs_root.mkdir(parents=True, exist_ok=True)
            out = docs_root / f"{slug}.md"
            body = [f"# {product.title}", "", product.summary, "", "## Requirements", ""]
            for req in reqs:
                if isinstance(req, str):
                    body.append(f"- {req}")
                else:
                    body.append(f"- {req.get('req_key', '')}: {req.get('text', '')}")
            out.write_text("\n".join(body) + "\n")
            product.source_path = str(out)

        created.append(product)

    emit(
        db,
        kind="prd.indexed",
        summary=f"CTO indexed {len(created)} modules from {source_name}",
        role="cto",
        payload={
            "product_ids": [str(p.id) for p in created],
            "project_id": str(project.id),
            "source": source_name,
        },
    )
    return sorted(created, key=lambda p: p.build_order)


def index_prd_with_cto(
    db: Session,
    settings: Settings,
    project_id: uuid.UUID,
    markdown: str,
    *,
    docs_root: Path | None = None,
    source_name: str = "uploaded.md",
) -> dict[str, Any]:
    """Store PRD, run CTO LLM index, persist modules + context."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    text = (markdown or "").strip()
    if not text:
        raise ValueError("PRD markdown is empty")

    if is_kill_switch_on(db):
        raise ValueError("kill switch is on — CTO indexing paused")
    eff = effective_settings(settings)
    if not under_daily_budget(db, eff):
        raise ValueError("daily budget exhausted — CTO indexing paused")

    project.prd_markdown = text
    project.index_status = "pending"
    project.index_error = None
    project.updated_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="cto.index_started",
        summary=f"CTO indexing PRD for {project.title}",
        role="cto",
        status="working",
        payload={
            "project_id": str(project.id),
            "source_name": source_name,
            "chars": len(text),
        },
    )
    db.commit()
    db.refresh(project)

    try:
        parsed, cost = call_role_llm(
            eff,
            "cto",
            [
                {"role": "system", "content": CTO_INDEX_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"# Project: {project.title} ({project.slug})\n\n"
                        f"## PRD markdown\n\n{text[:120_000]}"
                    ),
                },
            ],
            temperature=0.25,
            max_tokens=8192,
            timeout=240.0,
        )
        modules_data = parsed.get("modules") or []
        if not isinstance(modules_data, list) or not modules_data:
            raise ValueError("CTO returned no modules")

        context = str(parsed.get("context_markdown") or "").strip()
        created = replace_project_modules(
            db,
            project,
            modules_data,
            docs_root=docs_root,
            source_name=source_name,
        )

        if docs_root is not None:
            path = docs_root / f"{project.slug}.prd.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            project.prd_path = str(path)

        project.context_markdown = context
        project.index_status = "ready"
        project.index_error = None
        project.indexed_at = datetime.now(timezone.utc)
        project.updated_at = datetime.now(timezone.utc)

        for q in parsed.get("hitl_questions") or []:
            summary = str(q).strip()
            if not summary:
                continue
            db.add(
                HumanItem(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    kind="question",
                    summary=f"[CTO index] {summary}",
                    status="open",
                )
            )

        add_daily_spend(db, cost)
        emit(
            db,
            kind="cto.prd_indexed",
            summary=f"CTO indexed PRD for {project.title} ({len(created)} modules)",
            role="cto",
            cost_usd=cost,
            payload={"project_id": str(project.id), "modules": len(created)},
        )
        db.commit()
        return {
            "project_id": str(project.id),
            "modules": len(created),
            "module_ids": [str(m.id) for m in created],
            "index_status": project.index_status,
            "cost_usd": float(cost),
        }
    except Exception as exc:
        log.exception("CTO index failed for project %s", project_id)
        project.index_status = "failed"
        project.index_error = str(exc)[:4000]
        project.updated_at = datetime.now(timezone.utc)
        emit(
            db,
            kind="cto.index_failed",
            summary=f"CTO index failed for {project.title}: {exc}"[:500],
            role="cto",
            status="failed",
            payload={"project_id": str(project.id)},
        )
        db.commit()
        raise ValueError(f"CTO indexing failed: {exc}") from exc
