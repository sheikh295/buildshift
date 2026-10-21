from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from buildshift_orchestrator.config import get_settings


DEFAULT_ROUTER: dict[str, Any] = {
    "roles": {
        # CTO/PM: mistral-nemo (reliable JSON). Workers: $0 Minimax for credit stretch.
        "cto": {"tier": "T3", "model": "mistral-nemo"},
        "pm": {"tier": "T3", "model": "mistral-nemo"},
        "planner": {"tier": "T3", "model": "mistral-nemo"},  # legacy alias → cto
        "prd_indexer": {"tier": "T2", "model": "mistral-nemo"},  # unused; prefer cto
        "test_author": {"tier": "T1", "model": "minimax-m3.1-flash"},
        "implementer": {"tier": "T1", "model": "minimax-m3.1-flash", "escalate_to": "T2"},
        "reviewer": {"tier": "T2", "model": "minimax-m3.1-flash"},
    },
    "limits": {
        "task_budget_usd": 3.0,
        "daily_budget_usd": 60.0,
        "max_attempts_per_tier": 2,
        "max_parallel_workers": 4,
    },
}


@lru_cache
def load_router_yaml() -> dict[str, Any]:
    """Load router.yaml once (seed / fallback). Day-to-day overrides live in runtime_settings."""
    settings = get_settings()
    path = settings.router_config_path
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        merged = {**DEFAULT_ROUTER, **data}
        merged["roles"] = {**DEFAULT_ROUTER["roles"], **(data.get("roles") or {})}
        merged["limits"] = {**DEFAULT_ROUTER["limits"], **(data.get("limits") or {})}
        return merged
    return copy_default()


def copy_default() -> dict[str, Any]:
    return {
        "roles": {k: dict(v) for k, v in DEFAULT_ROUTER["roles"].items()},
        "limits": dict(DEFAULT_ROUTER["limits"]),
    }


def load_router() -> dict[str, Any]:
    """Merged view: defaults → yaml → runtime_settings cache (control plane wins)."""
    from buildshift_orchestrator.runtime_settings import get_cached_runtime

    yaml_router = load_router_yaml()
    runtime = get_cached_runtime()
    roles = {**yaml_router.get("roles", {}), **(runtime.get("roles") or {})}
    limits = {**yaml_router.get("limits", {}), **(runtime.get("limits") or {})}
    return {"roles": roles, "limits": limits}


def role_model(role: str) -> str:
    roles = load_router().get("roles") or {}
    entry = roles.get(role)
    if not entry and role == "cto":
        entry = roles.get("planner")
    if not entry and role == "pm":
        entry = roles.get("cto") or roles.get("planner")
    if not entry:
        entry = roles.get("implementer") or {}
    return str(entry.get("model") or get_settings().default_implementer_model)


def role_tier(role: str) -> str:
    roles = load_router().get("roles") or {}
    entry = roles.get(role)
    if not entry and role == "cto":
        entry = roles.get("planner")
    if not entry and role == "pm":
        entry = roles.get("cto") or roles.get("planner")
    if not entry:
        entry = {}
    return str(entry.get("tier") or "T1")


def router_limits() -> dict[str, Any]:
    return dict(load_router().get("limits") or {})
