from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from buildshift_orchestrator.models import Event


def emit(
    db: Session,
    *,
    kind: str,
    task_id: uuid.UUID | None = None,
    role: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    cost_usd: float | Decimal = 0,
    payload: dict | None = None,
) -> Event:
    event = Event(
        task_id=task_id,
        role=role,
        model=model,
        tier=tier,
        kind=kind,
        status=status,
        summary=summary,
        cost_usd=Decimal(str(cost_usd)),
        payload=payload or {},
    )
    db.add(event)
    db.flush()
    return event
