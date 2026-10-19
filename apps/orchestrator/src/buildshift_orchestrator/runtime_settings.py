"""Control-plane runtime settings: Postgres is source of truth; env is bootstrap/secrets."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings, get_settings
from buildshift_orchestrator.models import RuntimeSettings
from buildshift_orchestrator.router_config import DEFAULT_ROUTER, load_router_yaml

SETTINGS_ID = "default"
SCHEMA_VERSION = 1

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def default_runtime_blob(settings: Settings | None = None) -> dict[str, Any]:
    """Build initial settings from router.yaml + env bootstrap defaults."""
    settings = settings or get_settings()
    yaml_router = load_router_yaml()
    roles = copy.deepcopy(yaml_router.get("roles") or DEFAULT_ROUTER["roles"])
    limits = {
        **DEFAULT_ROUTER["limits"],
        **(yaml_router.get("limits") or {}),
        "task_budget_usd": float(settings.task_budget_usd),
        "daily_budget_usd": float(settings.daily_budget_usd),
        "max_attempts_per_tier": int(settings.max_attempts_per_tier),
        "max_parallel_workers": int(settings.max_parallel_workers),
    }
    # Prefer yaml limits when present (seed path), then env already applied above for missing.
    for key in ("task_budget_usd", "daily_budget_usd", "max_attempts_per_tier", "max_parallel_workers"):
        if key in (yaml_router.get("limits") or {}):
            limits[key] = (yaml_router["limits"])[key]
    return {
        "version": SCHEMA_VERSION,
        "roles": roles,
        "limits": limits,
        "harness": settings.harness,
        "multi_role_pipeline": bool(settings.multi_role_pipeline),
        "poll_interval_sec": float(settings.poll_interval_sec),
        "proving_repo_url": settings.proving_repo_url or "",
        "proving_repo_branch": settings.proving_repo_branch or "main",
        "ui": {"office_map": "default", "sound": False},
    }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _normalize(blob: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    base = default_runtime_blob(settings)
    merged = _deep_merge(base, blob or {})
    merged["version"] = SCHEMA_VERSION
    return merged


def get_cached_runtime() -> dict[str, Any]:
    with _lock:
        if _cache is None:
            return default_runtime_blob()
        return copy.deepcopy(_cache)


def set_cached_runtime(blob: dict[str, Any]) -> None:
    global _cache
    with _lock:
        _cache = copy.deepcopy(blob)


def ensure_runtime_settings(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    """Load or seed runtime_settings; refresh in-memory cache."""
    settings = settings or get_settings()
    row = db.get(RuntimeSettings, SETTINGS_ID)
    if row is None:
        blob = default_runtime_blob(settings)
        row = RuntimeSettings(id=SETTINGS_ID, value=blob)
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        raw = row.value or {}
        # Empty / version-only seed from migration → fill from yaml+env once
        if not raw.get("roles") or not raw.get("limits"):
            blob = _normalize(raw, settings)
            row.value = blob
            row.updated_at = datetime.now(timezone.utc)
            db.add(row)
            db.commit()
            db.refresh(row)
        else:
            blob = _normalize(raw, settings)
            # Keep DB as written; cache normalized view for consumers
            set_cached_runtime(blob)
            return copy.deepcopy(blob)
    set_cached_runtime(row.value)
    return copy.deepcopy(row.value)


def get_runtime_settings(db: Session) -> dict[str, Any]:
    row = db.get(RuntimeSettings, SETTINGS_ID)
    if row is None:
        return ensure_runtime_settings(db)
    blob = _normalize(row.value or {})
    set_cached_runtime(blob)
    return copy.deepcopy(blob)


def put_runtime_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_runtime_settings(db)
    # Full replace of known top-level keys when provided; deep-merge nested
    merged = _deep_merge(current, patch)
    merged["version"] = SCHEMA_VERSION
    row = db.get(RuntimeSettings, SETTINGS_ID)
    if row is None:
        row = RuntimeSettings(id=SETTINGS_ID, value=merged)
        db.add(row)
    else:
        row.value = merged
        row.updated_at = datetime.now(timezone.utc)
        db.add(row)
    db.flush()
    set_cached_runtime(merged)
    return copy.deepcopy(merged)


def effective_settings(base: Settings | None = None, runtime: dict[str, Any] | None = None) -> Settings:
    """Return Settings with control-plane overlays applied (secrets still from env)."""
    base = base or get_settings()
    runtime = runtime if runtime is not None else get_cached_runtime()
    limits = runtime.get("limits") or {}
    updates: dict[str, Any] = {}
    if "task_budget_usd" in limits:
        updates["task_budget_usd"] = float(limits["task_budget_usd"])
    if "daily_budget_usd" in limits:
        updates["daily_budget_usd"] = float(limits["daily_budget_usd"])
    if "max_attempts_per_tier" in limits:
        updates["max_attempts_per_tier"] = int(limits["max_attempts_per_tier"])
    if "max_parallel_workers" in limits:
        updates["max_parallel_workers"] = int(limits["max_parallel_workers"])
    if "harness" in runtime:
        updates["harness"] = str(runtime["harness"])
    if "multi_role_pipeline" in runtime:
        updates["multi_role_pipeline"] = bool(runtime["multi_role_pipeline"])
    if "poll_interval_sec" in runtime:
        updates["poll_interval_sec"] = float(runtime["poll_interval_sec"])
    if "proving_repo_url" in runtime:
        updates["proving_repo_url"] = str(runtime["proving_repo_url"] or "")
    if "proving_repo_branch" in runtime:
        updates["proving_repo_branch"] = str(runtime["proving_repo_branch"] or "main")
    if not updates:
        return base
    return base.model_copy(update=updates)


def runtime_roles() -> dict[str, Any]:
    return dict(get_cached_runtime().get("roles") or {})


def runtime_limits() -> dict[str, Any]:
    return dict(get_cached_runtime().get("limits") or {})
