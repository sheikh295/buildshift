from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import PrdProduct, PrdRequirement, Project

PLATFORM_KEYWORDS = (
    "identity",
    "auth",
    "platform",
    "design system",
    "data model",
    "ci",
    "shared",
)


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or f"product-{uuid.uuid4().hex[:8]}"


def _parse_markdown(text: str) -> list[dict]:
    """Split PRD into modules (## headings) with numbered requirements."""
    lines = text.splitlines()
    products: list[dict] = []
    current: dict | None = None
    buf: list[str] = []
    in_reqs = False

    def flush_buf() -> None:
        nonlocal buf
        if current is not None and buf:
            summary = " ".join(x.strip() for x in buf if x.strip())
            if summary and not current.get("summary"):
                current["summary"] = summary[:500]
        buf = []

    for line in lines:
        h2 = re.match(r"^##\s+(.+)$", line)
        h3 = re.match(r"^###\s+(.+)$", line)
        req = re.match(r"^(\d+)[.)]\s+(.+)$", line.strip())

        if h2:
            flush_buf()
            in_reqs = False
            title = h2.group(1).strip()
            current = {
                "title": title,
                "slug": _slugify(title),
                "summary": "",
                "requirements": [],
            }
            products.append(current)
            continue

        if current is None:
            continue

        if h3:
            flush_buf()
            in_reqs = "requirement" in h3.group(1).lower()
            continue

        if req and (in_reqs or True):
            if not in_reqs and current["requirements"]:
                pass
            current["requirements"].append(
                {"req_key": f"R{req.group(1)}", "text": req.group(2).strip()}
            )
            continue

        if line.startswith("#"):
            flush_buf()
            continue

        if line.strip():
            buf.append(line)

    flush_buf()
    return [p for p in products if p["requirements"] or p.get("summary")]


def _build_order(title: str, index: int) -> int:
    lower = title.lower()
    for i, kw in enumerate(PLATFORM_KEYWORDS):
        if kw in lower:
            return i
    return 50 + index


def index_prd_markdown(
    db: Session,
    markdown: str,
    *,
    project_id: uuid.UUID | None = None,
    docs_root: Path | None = None,
    source_name: str = "uploaded.md",
) -> list[PrdProduct]:
    parsed = _parse_markdown(markdown)
    if not parsed:
        # Single-module fallback: treat whole doc as one module under project title
        project = db.get(Project, project_id) if project_id else None
        title = project.title if project else "Main"
        base_slug = project.slug if project else "main"
        reqs = []
        for line in markdown.splitlines():
            m = re.match(r"^(\d+)[.)]\s+(.+)$", line.strip())
            if m:
                reqs.append({"req_key": f"R{m.group(1)}", "text": m.group(2).strip()})
        if not reqs and markdown.strip():
            reqs.append({"req_key": "R1", "text": markdown.strip()[:2000]})
        if not reqs:
            raise ValueError(
                "no modules found; use ## headings and numbered requirements, or paste PRD body"
            )
        parsed = [
            {
                "title": title,
                "slug": base_slug,
                "summary": "",
                "requirements": reqs,
            }
        ]

    created: list[PrdProduct] = []
    project = db.get(Project, project_id) if project_id else None
    prefix = f"{project.slug}--" if project else ""

    for i, item in enumerate(parsed):
        slug = f"{prefix}{item['slug']}" if prefix else item["slug"]
        # Keep slug unique globally; prefer match within project
        existing = None
        if project_id:
            existing = db.scalar(
                select(PrdProduct).where(
                    PrdProduct.project_id == project_id,
                    PrdProduct.slug == slug,
                )
            )
        if existing is None:
            existing = db.scalar(select(PrdProduct).where(PrdProduct.slug == slug))

        if existing:
            product = existing
            product.title = item["title"]
            product.summary = item.get("summary") or product.summary
            product.build_order = _build_order(item["title"], i)
            if project_id:
                product.project_id = project_id
            for req in list(product.requirements):
                db.delete(req)
            db.flush()
        else:
            product = PrdProduct(
                id=uuid.uuid4(),
                project_id=project_id,
                slug=slug,
                title=item["title"],
                summary=item.get("summary") or "",
                build_order=_build_order(item["title"], i),
                status="indexed",
            )
            db.add(product)
            db.flush()

        for j, req in enumerate(item["requirements"]):
            db.add(
                PrdRequirement(
                    id=uuid.uuid4(),
                    product_id=product.id,
                    req_key=req["req_key"],
                    text=req["text"],
                    sort_order=j,
                )
            )

        if docs_root is not None:
            docs_root.mkdir(parents=True, exist_ok=True)
            out = docs_root / f"{slug}.md"
            body = [f"# {product.title}", "", product.summary, "", "## Requirements", ""]
            for req in item["requirements"]:
                body.append(f"- {req['req_key']}: {req['text']}")
            out.write_text("\n".join(body) + "\n")
            product.source_path = str(out)

        created.append(product)

    emit(
        db,
        kind="prd.indexed",
        summary=f"Indexed {len(created)} modules from {source_name}",
        payload={
            "product_ids": [str(p.id) for p in created],
            "project_id": str(project_id) if project_id else None,
        },
    )
    db.commit()
    for p in created:
        db.refresh(p)
    return sorted(created, key=lambda p: p.build_order)


def list_products(db: Session, project_id: uuid.UUID | None = None) -> list[PrdProduct]:
    q = select(PrdProduct).order_by(PrdProduct.build_order, PrdProduct.title)
    if project_id:
        q = q.where(PrdProduct.project_id == project_id)
    return list(db.scalars(q))
