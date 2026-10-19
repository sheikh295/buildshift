from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.control import add_daily_spend
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import Run, Task, TaskState
from buildshift_orchestrator.router_config import role_model, role_tier
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.runner.docker_run import run_worker
from buildshift_orchestrator.runner.github import (
    merge_pull_request,
    open_pull_request,
    parse_github_repo,
)
from buildshift_orchestrator.runner.locks import acquire_locks, release_locks

log = logging.getLogger(__name__)

# Single-orchestrator merge queue (avoids pg advisory locks across pooled connections)
_MERGE_LOCK = threading.Lock()
_FIXTURE_LOCK = threading.Lock()
PATH_LOCK_BACKOFF_SEC = 3.0

STAGE_ORDER = ("test_author", "implementer", "reviewer")
STAGE_STATE = {
    "test_author": TaskState.test_authoring.value,
    "implementer": TaskState.coding.value,
    "reviewer": TaskState.reviewing.value,
}


def _fixture_needs_reseed(bare: Path) -> bool:
    if not bare.exists():
        return True
    # Prefer explicit main tip — bare repos may lack a symbolic HEAD
    probe = subprocess.run(
        ["git", "--git-dir", str(bare), "cat-file", "-e", "refs/heads/main:tests/test_smoke.py"],
        capture_output=True,
        check=False,
    )
    return probe.returncode != 0


def _fixture_remote(settings: Settings) -> Path:
    remotes = settings.data_dir / "remotes"
    remotes.mkdir(parents=True, exist_ok=True)
    bare = remotes / "demo-app.git"
    seed = settings.repo_root / "fixtures" / "demo-app"
    if not _fixture_needs_reseed(bare):
        return bare

    with _FIXTURE_LOCK:
        # Another worker may have finished reseeding while we waited
        if not _fixture_needs_reseed(bare):
            return bare

        if bare.exists():
            shutil.rmtree(bare)
        mirror = settings.data_dir / "repos" / "demo-app"
        if mirror.exists():
            shutil.rmtree(mirror)

        bare.mkdir(parents=True)
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        # Ensure clone --branch main works
        subprocess.run(
            ["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=True,
            capture_output=True,
        )
        tmp = settings.data_dir / "tmp-seed-demo"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(seed, tmp, ignore=shutil.ignore_patterns(".git"))
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "buildshift@local"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "Buildshift"], cwd=tmp, check=True)
        subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: seed demo-app fixture"],
            cwd=tmp,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=tmp, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=tmp, check=True, capture_output=True)
        shutil.rmtree(tmp)
        return bare


def resolve_clone_url(settings: Settings) -> str:
    if settings.proving_repo_url.strip():
        return settings.proving_repo_url.strip()
    return str(_fixture_remote(settings))


def build_prompt(task: Task, role: str) -> str:
    paths = ", ".join(task.owned_paths) if task.owned_paths else "(any)"
    role_blurb = {
        "test_author": "Write failing/acceptance tests from the criteria. Commit only tests.",
        "implementer": "Implement the change to satisfy the criteria and existing tests. Commit.",
        "reviewer": (
            "Review the diff against the criteria. Write .buildshift/review.md with "
            "verdict: APPROVE or verdict: REQUEST_CHANGES and a short rationale."
        ),
    }.get(role, "Complete the task and commit.")
    return (
        f"# Buildshift task ({role})\n\n"
        f"**ID:** {task.id}\n"
        f"**Title:** {task.title}\n\n"
        f"## Acceptance criteria\n\n{task.acceptance_criteria or '(none)'}\n\n"
        f"## Owned paths\n\n{paths}\n\n"
        f"## Instructions\n\n{role_blurb}\n"
        f"Do not push or open a PR — the orchestrator handles that.\n"
    )


def _parse_review_verdict(worktree: Path, task_id: uuid.UUID | None = None) -> str:
    candidates = []
    if task_id is not None:
        candidates.append(worktree / ".buildshift" / "tasks" / str(task_id) / "review.md")
    candidates.append(worktree / ".buildshift" / "review.md")
    review = next((p for p in candidates if p.exists()), None)
    if review is None:
        return "APPROVE"
    text_body = review.read_text()
    for line in text_body.splitlines():
        if "REQUEST_CHANGES" in line.upper():
            return "REQUEST_CHANGES"
        if "APPROVE" in line.upper():
            return "APPROVE"
    return "APPROVE"


def _use_multi_role(settings: Settings, task: Task) -> bool:
    if not settings.multi_role_pipeline:
        return False
    if task.plan_id is not None:
        return True
    return (task.stage or "") in ("test_author", "reviewer") or task.role == "test_author"


def _prepare_checkout(
    settings: Settings, task: Task
) -> tuple[str, Path, Path, str, Path]:
    clone_url = resolve_clone_url(settings)
    repos_dir = settings.data_dir / "repos"
    worktrees_dir = settings.data_dir / "worktrees"
    repo_name = "proving" if settings.proving_repo_url else "demo-app"
    repo_path = repos_dir / repo_name
    branch = task.branch or f"buildshift/{task.id.hex[:12]}"
    worktree = worktrees_dir / task.id.hex
    gitops.ensure_repo(clone_url, repo_path, settings.proving_repo_branch)
    gitops.create_task_checkout(repo_path, branch, worktree, settings.proving_repo_branch)
    subprocess.run(["chown", "-R", "10001:10001", str(worktree)], check=False)
    return clone_url, repo_path, worktree, branch, Path(repo_name)


def _integrate(
    db: Session,
    settings: Settings,
    task: Task,
    *,
    clone_url: str,
    repo_path: Path,
    worktree: Path,
    branch: str,
    repo_name: str,
) -> None:
    """Single-flight merge queue: rebase → local CI → land on base → merged."""
    with _MERGE_LOCK:
        task.state = TaskState.integrating.value
        task.updated_at = datetime.now(timezone.utc)
        db.commit()

        base = settings.proving_repo_branch
        token = settings.github_token
        try:
            gitops.rebase_onto_base(worktree, base)
            gitops.run_local_ci(worktree)
            gitops.push_branch(worktree, branch, token=token, force=True)

            repo_full = parse_github_repo(clone_url) if token else None
            if token and repo_full:
                task.pr_url = open_pull_request(
                    api_url=settings.github_api_url,
                    token=token,
                    repo_full_name=repo_full,
                    title=f"[buildshift] {task.title}",
                    head=branch,
                    base=base,
                    body=build_prompt(task, "implementer"),
                )
                merge_pull_request(
                    api_url=settings.github_api_url,
                    token=token,
                    repo_full_name=repo_full,
                    pr_url=task.pr_url,
                    commit_title=f"[buildshift] {task.title}",
                )
                tip = gitops.current_head(worktree)
                # Refresh local mirror so subsequent checkouts see the merge
                gitops.ensure_repo(clone_url, repo_path, base)
            else:
                tip = gitops.land_on_base_local(
                    checkout=worktree,
                    mirror=repo_path,
                    branch=branch,
                    base_branch=base,
                )
                # Mirror already at tip; refresh from bare for consistency
                gitops.ensure_repo(clone_url, repo_path, base)
                task.pr_url = f"local://{repo_name}/{base}@{tip[:12]}"

            release_locks(db, task.id)
            task.state = TaskState.merged.value
            task.finished_at = datetime.now(timezone.utc)
            task.error = None
            emit(
                db,
                kind="task.completed",
                task_id=task.id,
                role=task.role,
                tier=task.tier,
                status="done",
                summary=f"Landed on {base} via {task.pr_url}",
                payload={"branch": branch, "pr_url": task.pr_url, "base_tip": tip[:12]},
            )
            db.commit()
        except gitops.RebaseConflict as exc:
            log.warning("task %s rebase conflict: %s", task.id, exc)
            task.error = str(exc)[:4000]
            # Do not bump attempts — reviewer stage already counted; retry share that budget
            release_locks(db, task.id)
            if task.attempts >= task.max_attempts:
                task.state = TaskState.parked.value
                summary = f"Parked after rebase conflicts: {exc}"
            else:
                task.state = TaskState.ready.value
                summary = f"Rebase conflict; will retry (attempt {task.attempts})"
            task.updated_at = datetime.now(timezone.utc)
            emit(
                db,
                kind="task.rebase_conflict",
                task_id=task.id,
                status=task.state,
                summary=summary[:2000],
            )
            db.commit()
        except Exception as exc:
            log.exception("task %s integrate failed", task.id)
            task.error = str(exc)[:4000]
            release_locks(db, task.id)
            if task.attempts >= task.max_attempts:
                task.state = TaskState.parked.value
            else:
                task.state = TaskState.ready.value
            task.updated_at = datetime.now(timezone.utc)
            emit(
                db,
                kind="task.integrate_failed",
                task_id=task.id,
                status=task.state,
                summary=str(exc)[:2000],
            )
            db.commit()


def _run_stage(db: Session, settings: Settings, task: Task, role: str) -> None:
    model = role_model(role) if settings.harness != "mock" else "mock"
    run = Run(
        id=uuid.uuid4(),
        task_id=task.id,
        role=role,
        model=model,
        harness=settings.harness,
        status="running",
    )
    db.add(run)
    task.role = role
    task.stage = role
    task.tier = role_tier(role)
    task.state = STAGE_STATE.get(role, TaskState.coding.value)
    task.attempts += 1
    task.claimed_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="task.stage_started",
        task_id=task.id,
        role=role,
        tier=task.tier,
        status="running",
        summary=f"Stage {role} attempt {task.attempts}",
        model=model,
    )
    db.commit()

    # Hold path locks for the full multi-role pipeline (acquire on first stage)
    if not acquire_locks(db, task.id, task.owned_paths or []):
        task.state = TaskState.ready.value
        task.attempts = max(0, task.attempts - 1)
        run.status = "skipped"
        run.ended_at = datetime.now(timezone.utc)
        run.logs = "path locks busy; will retry"
        emit(
            db,
            kind="task.path_lock_wait",
            task_id=task.id,
            status="ready",
            summary="Owned paths locked by another task",
        )
        db.commit()
        time.sleep(PATH_LOCK_BACKOFF_SEC)
        return

    clone_url, repo_path, worktree, branch, repo_name = _prepare_checkout(settings, task)
    task.branch = branch
    task.worktree_path = str(worktree)
    db.commit()

    # Integrate-only retry: reviewer already approved; skip the worker
    if role == "reviewer" and (task.review_verdict or "").upper() == "APPROVE":
        run.status = "skipped"
        run.logs = "review already APPROVE; retry integrate only"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        try:
            _integrate(
                db,
                settings,
                task,
                clone_url=clone_url,
                repo_path=repo_path,
                worktree=worktree,
                branch=branch,
                repo_name=str(repo_name),
            )
        finally:
            try:
                gitops.remove_checkout(worktree)
            except Exception:
                log.warning("failed to clean checkout %s", worktree, exc_info=True)
        return

    try:
        exit_code, logs = run_worker(
            settings=settings,
            task_id=str(task.id),
            worktree=worktree,
            prompt=build_prompt(task, role),
            role=role,
            owned_paths=list(task.owned_paths or []),
        )
        run.logs = logs[-100_000:]
        if exit_code != 0:
            raise RuntimeError(f"worker exited {exit_code}\n{logs[-4000:]}")

        if not gitops.has_commits_ahead(worktree, settings.proving_repo_branch):
            raise RuntimeError(
                f"worker produced no commits ahead of {settings.proving_repo_branch}\n{logs[-2000:]}"
            )

        # Persist stage commits for the next stage
        gitops.push_branch(worktree, branch, token=settings.github_token)

        cost = Decimal("0") if settings.harness == "mock" else Decimal("0.01")
        task.spent_usd = (task.spent_usd or Decimal("0")) + cost
        add_daily_spend(db, cost)
        run.cost_usd = cost
        run.status = "done"
        run.ended_at = datetime.now(timezone.utc)

        if role == "reviewer":
            verdict = _parse_review_verdict(worktree, task.id)
            task.review_verdict = verdict
            if verdict == "REQUEST_CHANGES":
                if task.attempts >= task.max_attempts:
                    release_locks(db, task.id)
                    task.state = TaskState.parked.value
                    task.error = "reviewer requested changes; attempts exhausted"
                else:
                    task.stage = "implementer"
                    task.role = "implementer"
                    task.state = TaskState.ready.value
                    task.error = "reviewer requested changes"
                emit(
                    db,
                    kind="task.review",
                    task_id=task.id,
                    role=role,
                    status=task.state,
                    summary=f"Review verdict: {verdict}",
                )
                db.commit()
                return
            _integrate(
                db,
                settings,
                task,
                clone_url=clone_url,
                repo_path=repo_path,
                worktree=worktree,
                branch=branch,
                repo_name=str(repo_name),
            )
            return

        # Advance to next stage
        idx = STAGE_ORDER.index(role)
        if idx + 1 < len(STAGE_ORDER):
            nxt = STAGE_ORDER[idx + 1]
            task.stage = nxt
            task.role = nxt
            task.state = TaskState.ready.value
            task.attempts = 0  # per-stage attempts reset
            emit(
                db,
                kind="task.stage_done",
                task_id=task.id,
                role=role,
                status="ready",
                summary=f"Advance to {nxt}",
            )
            db.commit()
        else:
            _integrate(
                db,
                settings,
                task,
                clone_url=clone_url,
                repo_path=repo_path,
                worktree=worktree,
                branch=branch,
                repo_name=str(repo_name),
            )
    except Exception as exc:
        log.exception("task %s stage %s failed", task.id, role)
        run.status = "failed"
        run.logs = (run.logs or "") + f"\nERROR: {exc}"
        run.ended_at = datetime.now(timezone.utc)
        task.error = str(exc)[:4000]
        if task.attempts >= task.max_attempts:
            release_locks(db, task.id)
            task.state = TaskState.parked.value
            summary = f"Parked after {task.attempts} attempts: {exc}"
        else:
            task.state = TaskState.ready.value
            summary = f"Retryable failure (attempt {task.attempts}): {exc}"
        task.updated_at = datetime.now(timezone.utc)
        emit(
            db,
            kind="task.failed",
            task_id=task.id,
            role=role,
            tier=task.tier,
            status=task.state,
            summary=summary[:2000],
        )
        db.commit()
    finally:
        try:
            gitops.remove_checkout(worktree)
        except Exception:
            log.warning("failed to clean checkout %s", worktree, exc_info=True)


def run_task_legacy(db: Session, settings: Settings, task: Task) -> None:
    """Week 1 single-shot implementer path (ad-hoc tasks without a plan)."""
    run = Run(
        id=uuid.uuid4(),
        task_id=task.id,
        role="implementer",
        model=settings.default_implementer_model if settings.harness != "mock" else "mock",
        harness=settings.harness,
        status="running",
    )
    db.add(run)
    task.state = TaskState.coding.value
    task.role = "implementer"
    task.stage = "implementer"
    task.attempts += 1
    task.claimed_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="task.started",
        task_id=task.id,
        role="implementer",
        tier=task.tier,
        status="running",
        summary=f"Legacy attempt {task.attempts}",
        model=run.model,
    )
    db.commit()

    clone_url, repo_path, worktree, branch, repo_name = _prepare_checkout(settings, task)
    task.branch = branch
    task.worktree_path = str(worktree)
    db.commit()

    try:
        if not acquire_locks(db, task.id, task.owned_paths or []):
            time.sleep(PATH_LOCK_BACKOFF_SEC)
            raise RuntimeError("path locks busy")

        exit_code, logs = run_worker(
            settings=settings,
            task_id=str(task.id),
            worktree=worktree,
            prompt=build_prompt(task, "implementer"),
            role="implementer",
            owned_paths=list(task.owned_paths or []),
        )
        run.logs = logs[-100_000:]
        if exit_code != 0:
            raise RuntimeError(f"worker exited {exit_code}\n{logs[-4000:]}")
        if not gitops.has_commits_ahead(worktree, settings.proving_repo_branch):
            raise RuntimeError("worker produced no commits ahead of base branch")

        cost = Decimal("0") if settings.harness == "mock" else Decimal("0.01")
        task.spent_usd = (task.spent_usd or Decimal("0")) + cost
        add_daily_spend(db, cost)
        run.cost_usd = cost
        run.status = "done"
        run.ended_at = datetime.now(timezone.utc)
        _integrate(
            db,
            settings,
            task,
            clone_url=clone_url,
            repo_path=repo_path,
            worktree=worktree,
            branch=branch,
            repo_name=str(repo_name),
        )
    except Exception as exc:
        log.exception("legacy task %s failed", task.id)
        run.status = "failed"
        run.logs = (run.logs or "") + f"\nERROR: {exc}"
        run.ended_at = datetime.now(timezone.utc)
        task.error = str(exc)[:4000]
        release_locks(db, task.id)
        if task.attempts >= task.max_attempts:
            task.state = TaskState.parked.value
        else:
            task.state = TaskState.ready.value
        emit(
            db,
            kind="task.failed",
            task_id=task.id,
            role="implementer",
            status=task.state,
            summary=str(exc)[:2000],
        )
        db.commit()
    finally:
        try:
            gitops.remove_checkout(worktree)
        except Exception:
            log.warning("failed to clean checkout %s", worktree, exc_info=True)


def run_task(db: Session, settings: Settings, task: Task) -> None:
    if _use_multi_role(settings, task):
        role = task.stage or task.role or "test_author"
        if role not in STAGE_ORDER:
            role = "test_author"
        _run_stage(db, settings, task, role)
    else:
        run_task_legacy(db, settings, task)
