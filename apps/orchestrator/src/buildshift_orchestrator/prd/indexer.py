from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import PrdProduct, PrdRequirement

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
    """Split PRD into products (## headings) with numbered requirements."""
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
            # Accept numbered lists under a product even without ### Requirements
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
    # Drop empty products with no requirements
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
    docs_root: Path | None = None,
    source_name: str = "uploaded.md",
) -> list[PrdProduct]:
    parsed = _parse_markdown(markdown)
    if not parsed:
        raise ValueError("no products found; use ## Product headings and numbered requirements")

    created: list[PrdProduct] = []
    for i, item in enumerate(parsed):
        slug = item["slug"]
        existing = db.scalar(select(PrdProduct).where(PrdProduct.slug == slug))
        if existing:
            product = existing
            product.title = item["title"]
            product.summary = item.get("summary") or product.summary
            product.build_order = _build_order(item["title"], i)
            # replace requirements
            for req in list(product.requirements):
                db.delete(req)
            db.flush()
        else:
            product = PrdProduct(
                id=uuid.uuid4(),
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
        summary=f"Indexed {len(created)} products from {source_name}",
        payload={"product_ids": [str(p.id) for p in created]},
    )
    db.commit()
    for p in created:
        db.refresh(p)
    return sorted(created, key=lambda p: p.build_order)


def list_products(db: Session) -> list[PrdProduct]:
    return list(db.scalars(select(PrdProduct).order_by(PrdProduct.build_order, PrdProduct.title)))
