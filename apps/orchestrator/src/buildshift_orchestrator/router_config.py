from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from buildshift_orchestrator.config import get_settings


DEFAULT_ROUTER: dict[str, Any] = {
    "roles": {
        "prd_indexer": {"tier": "T2", "model": "claude-sonnet-4-5"},
        "planner": {"tier": "T3", "model": "claude-sonnet-4-5"},
        "test_author": {"tier": "T1", "model": "claude-sonnet-4-5"},
        "implementer": {"tier": "T1", "model": "claude-sonnet-4-5", "escalate_to": "T2"},
        "reviewer": {"tier": "T2", "model": "claude-haiku-4-5"},
    },
    "limits": {
        "task_budget_usd": 3.0,
        "daily_budget_usd": 60.0,
        "max_attempts_per_tier": 2,
        "max_parallel_workers": 4,
    },
}


@lru_cache
def load_router() -> dict[str, Any]:
    settings = get_settings()
    path = settings.router_config_path
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        merged = {**DEFAULT_ROUTER, **data}
        merged["roles"] = {**DEFAULT_ROUTER["roles"], **(data.get("roles") or {})}
        merged["limits"] = {**DEFAULT_ROUTER["limits"], **(data.get("limits") or {})}
        return merged
    return DEFAULT_ROUTER


def role_model(role: str) -> str:
    roles = load_router().get("roles") or {}
    entry = roles.get(role) or roles.get("implementer") or {}
    return str(entry.get("model") or get_settings().default_implementer_model)


def role_tier(role: str) -> str:
    roles = load_router().get("roles") or {}
    entry = roles.get(role) or {}
    return str(entry.get("tier") or "T1")


def router_limits() -> dict[str, Any]:
    return dict(load_router().get("limits") or {})
