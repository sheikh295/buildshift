from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from buildshift_orchestrator.models import PathLock, Task, TaskState

# Shared worker metadata — never exclusive-lock these
_SKIP_PREFIXES = (".buildshift",)

INFLIGHT_STATES = {
    TaskState.test_authoring.value,
    TaskState.coding.value,
    TaskState.testing.value,
    TaskState.reviewing.value,
    TaskState.integrating.value,
}

TERMINAL_STATES = {
    TaskState.merged.value,
    TaskState.parked.value,
    TaskState.failed.value,
    TaskState.stopped.value,
}

# Mid-flight crash recovery (not used on cold start — see force=True).
ORPHAN_AGE = timedelta(minutes=30)


def _normalize(path: str) -> str:
    return path.strip().rstrip("/") or path.strip()


def lockable_paths(owned_paths: list) -> list[str]:
    out: list[str] = []
    for p in owned_paths or []:
        if not p:
            continue
        n = _normalize(p)
        if any(n == s or n.startswith(s + "/") for s in _SKIP_PREFIXES):
            continue
        out.append(n)
    return out


def _is_orphan(task: Task, now: datetime, *, max_age: timedelta) -> bool:
    updated = task.updated_at or task.claimed_at or task.created_at
    if updated is None:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated) > max_age


def recover_orphaned_inflight(db: Session, *, force: bool = False) -> int:
    """Reset abandoned inflight tasks to ready and drop their locks.

    force=True (orchestrator startup): every inflight task is orphaned because
    no worker threads survived the process restart.
    """
    now = datetime.now(timezone.utc)
    max_age = timedelta(0) if force else ORPHAN_AGE
    recovered = 0
    for task in list(db.scalars(select(Task).where(Task.state.in_(INFLIGHT_STATES)))):
        if not force and not _is_orphan(task, now, max_age=max_age):
            continue
        release_locks(db, task.id)
        task.state = TaskState.ready.value
        task.error = ((task.error or "") + " | recovered from orphaned inflight").strip(" |")
        task.updated_at = now
        recovered += 1
    # Drop skipped-prefix locks left by older builds
    for lock in list(db.scalars(select(PathLock))):
        n = _normalize(lock.path_glob)
        if any(n == s or n.startswith(s + "/") for s in _SKIP_PREFIXES):
            db.delete(lock)
    if recovered:
        db.commit()
    else:
        db.flush()
    return recovered


def _purge_stale(db: Session) -> None:
    """Drop locks for terminal/missing tasks, expired holds, or long-orphaned inflight.

    Ready tasks may still hold locks between multi-role stages — do not purge those.
    """
    now = datetime.now(timezone.utc)
    locks = list(db.scalars(select(PathLock)))
    for lock in locks:
        n = _normalize(lock.path_glob)
        if any(n == s or n.startswith(s + "/") for s in _SKIP_PREFIXES):
            db.delete(lock)
            continue
        if lock.held_until and lock.held_until < now:
            db.delete(lock)
            continue
        task = db.get(Task, lock.task_id)
        if task is None or task.state in TERMINAL_STATES:
            db.delete(lock)
            continue
        if task.state in INFLIGHT_STATES and _is_orphan(task, now, max_age=ORPHAN_AGE):
            db.delete(lock)
    db.flush()


def paths_overlap(a: str, b: str) -> bool:
    """True when paths are equal or one is a prefix of the other."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return na == nb or na.startswith(nb + "/") or nb.startswith(na + "/")


def owned_paths_overlap(left: list, right: list) -> bool:
    lp = lockable_paths(left)
    rp = lockable_paths(right)
    for a in lp:
        for b in rp:
            if paths_overlap(a, b):
                return True
    return False


def can_acquire(db: Session, task_id: uuid.UUID, owned_paths: list) -> bool:
    _purge_stale(db)
    paths = lockable_paths(owned_paths)
    if not paths:
        return True
    held = list(db.scalars(select(PathLock)))
    for path in paths:
        for existing in held:
            if existing.task_id == task_id:
                continue
            if paths_overlap(path, existing.path_glob):
                return False
    return True


def acquire_locks(db: Session, task_id: uuid.UUID, owned_paths: list, hours: int = 6) -> bool:
    if not can_acquire(db, task_id, owned_paths):
        return False
    paths = lockable_paths(owned_paths)
    if not paths:
        return True
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    try:
        with db.begin_nested():
            held = list(db.scalars(select(PathLock)))
            for path in paths:
                existing = next((h for h in held if h.path_glob == path), None)
                if existing and existing.task_id == task_id:
                    existing.held_until = until
                    continue
                if existing:
                    raise IntegrityError("path taken", params=None, orig=None)
                # Also reject prefix conflicts that slipped in
                for h in held:
                    if h.task_id != task_id and paths_overlap(path, h.path_glob):
                        raise IntegrityError("path overlap", params=None, orig=None)
                lock = PathLock(
                    id=uuid.uuid4(),
                    path_glob=path,
                    task_id=task_id,
                    held_until=until,
                )
                db.add(lock)
                held.append(lock)
            db.flush()
        return True
    except IntegrityError:
        return False


def release_locks(db: Session, task_id: uuid.UUID) -> None:
    db.execute(delete(PathLock).where(PathLock.task_id == task_id))
    db.flush()
