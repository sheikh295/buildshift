from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.control import add_daily_spend
from buildshift_orchestrator.events import emit
from buildshift_orchestrator.models import Run, Task, TaskState
from buildshift_orchestrator.runner import gitops
from buildshift_orchestrator.runner.docker_run import run_worker
from buildshift_orchestrator.runner.github import open_pull_request, parse_github_repo

log = logging.getLogger(__name__)


def _fixture_remote(settings: Settings) -> Path:
    """Ensure a local bare remote seeded from fixtures/demo-app."""
    remotes = settings.data_dir / "remotes"
    remotes.mkdir(parents=True, exist_ok=True)
    bare = remotes / "demo-app.git"
    seed = settings.repo_root / "fixtures" / "demo-app"
    if bare.exists():
        return bare

    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
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


def build_prompt(task: Task) -> str:
    paths = ", ".join(task.owned_paths) if task.owned_paths else "(any)"
    return (
        f"# Buildshift task\n\n"
        f"**ID:** {task.id}\n"
        f"**Title:** {task.title}\n\n"
        f"## Acceptance criteria\n\n{task.acceptance_criteria or '(none)'}\n\n"
        f"## Owned paths\n\n{paths}\n\n"
        f"Implement the change, add or update tests if appropriate, and commit.\n"
        f"Do not push or open a PR — the orchestrator handles that.\n"
    )


def run_task(db: Session, settings: Settings, task: Task) -> None:
    run = Run(
        id=uuid.uuid4(),
        task_id=task.id,
        role=task.role,
        model=settings.default_implementer_model if settings.harness != "mock" else "mock",
        harness=settings.harness,
        status="running",
    )
    db.add(run)
    task.state = TaskState.coding.value
    task.attempts += 1
    task.claimed_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    emit(
        db,
        kind="task.started",
        task_id=task.id,
        role=task.role,
        tier=task.tier,
        status="running",
        summary=f"Attempt {task.attempts} with harness={settings.harness}",
        model=run.model,
    )
    db.commit()

    clone_url = resolve_clone_url(settings)
    repos_dir = settings.data_dir / "repos"
    worktrees_dir = settings.data_dir / "worktrees"
    repo_name = "proving" if settings.proving_repo_url else "demo-app"
    repo_path = repos_dir / repo_name
    branch = f"buildshift/{task.id.hex[:12]}"
    worktree = worktrees_dir / task.id.hex

    try:
        gitops.ensure_repo(clone_url, repo_path, settings.proving_repo_branch)
        gitops.create_task_checkout(repo_path, branch, worktree, settings.proving_repo_branch)
        # Worker container runs as uid 10001
        subprocess.run(["chown", "-R", "10001:10001", str(worktree)], check=False)
        task.branch = branch
        task.worktree_path = str(worktree)
        db.commit()

        exit_code, logs = run_worker(
            settings=settings,
            task_id=str(task.id),
            worktree=worktree,
            prompt=build_prompt(task),
        )
        run.logs = logs[-100_000:]
        if exit_code != 0:
            raise RuntimeError(f"worker exited {exit_code}\n{logs[-4000:]}")

        # Mock / harness should have committed; ensure identity for any leftover ops
        subprocess.run(
            ["git", "config", "user.email", "buildshift@local"],
            cwd=worktree,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Buildshift Worker"],
            cwd=worktree,
            check=False,
            capture_output=True,
        )

        if not gitops.has_commits_ahead(worktree, settings.proving_repo_branch):
            raise RuntimeError(
                f"worker produced no commits ahead of {settings.proving_repo_branch}\n{logs[-2000:]}"
            )

        task.state = TaskState.testing.value
        emit(db, kind="task.testing", task_id=task.id, status="running", summary="Worker finished; integrating")
        db.commit()

        task.state = TaskState.integrating.value
        db.commit()

        token = settings.github_token
        gitops.push_branch(worktree, branch, token=token)

        pr_url = None
        repo_full = parse_github_repo(clone_url) if token else None
        if token and repo_full:
            pr_url = open_pull_request(
                api_url=settings.github_api_url,
                token=token,
                repo_full_name=repo_full,
                title=f"[buildshift] {task.title}",
                head=branch,
                base=settings.proving_repo_branch,
                body=build_prompt(task),
            )
            task.pr_url = pr_url
        else:
            # Local fixture path: PR URL is a synthetic pointer to the branch tip
            tip = gitops.current_head(worktree)
            task.pr_url = f"local://{repo_name}/{branch}@{tip[:12]}"

        # Week-1 mock cost accounting (real gateway metering later)
        cost = Decimal("0") if settings.harness == "mock" else Decimal("0.01")
        task.spent_usd = (task.spent_usd or Decimal("0")) + cost
        add_daily_spend(db, cost)
        run.cost_usd = cost
        run.status = "done"
        run.ended_at = datetime.now(timezone.utc)

        task.state = TaskState.merged.value  # Week 1: treat successful PR/push as done
        task.finished_at = datetime.now(timezone.utc)
        task.error = None
        emit(
            db,
            kind="task.completed",
            task_id=task.id,
            role=task.role,
            tier=task.tier,
            status="done",
            summary=f"Completed via {task.pr_url}",
            cost_usd=cost,
            model=run.model,
            payload={"branch": branch, "pr_url": task.pr_url},
        )
        db.commit()
    except Exception as exc:
        log.exception("task %s failed", task.id)
        run.status = "failed"
        run.logs = (run.logs or "") + f"\nERROR: {exc}"
        run.ended_at = datetime.now(timezone.utc)
        task.error = str(exc)[:4000]
        if task.attempts >= task.max_attempts:
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
            role=task.role,
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
