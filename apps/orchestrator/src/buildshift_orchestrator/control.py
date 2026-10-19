from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.models import Control


def _get_or_create(db: Session, key: str, default: dict) -> Control:
    row = db.get(Control, key)
    if row is None:
        row = Control(key=key, value=default)
        db.add(row)
        db.flush()
    return row


def is_kill_switch_on(db: Session) -> bool:
    row = _get_or_create(db, "kill_switch", {"enabled": False})
    return bool(row.value.get("enabled"))


def set_kill_switch(db: Session, enabled: bool) -> bool:
    row = _get_or_create(db, "kill_switch", {"enabled": False})
    row.value = {"enabled": enabled}
    db.add(row)
    return enabled


def daily_spend_usd(db: Session) -> Decimal:
    today = date.today().isoformat()
    row = _get_or_create(db, "daily_spend", {"usd": 0, "day": today})
    if row.value.get("day") != today:
        row.value = {"usd": 0, "day": today}
        db.add(row)
        return Decimal("0")
    return Decimal(str(row.value.get("usd", 0)))


def add_daily_spend(db: Session, amount: Decimal) -> Decimal:
    today = date.today().isoformat()
    row = _get_or_create(db, "daily_spend", {"usd": 0, "day": today})
    current = Decimal("0")
    if row.value.get("day") == today:
        current = Decimal(str(row.value.get("usd", 0)))
    total = current + amount
    row.value = {"usd": float(total), "day": today}
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    return total


def under_daily_budget(db: Session, settings: Settings) -> bool:
    from buildshift_orchestrator.runtime_settings import effective_settings

    eff = effective_settings(settings)
    return daily_spend_usd(db) < Decimal(str(eff.daily_budget_usd))
