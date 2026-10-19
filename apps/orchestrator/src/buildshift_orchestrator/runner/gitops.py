from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Worker checkouts are chowned to uid 10001; orchestrator may run as root.
    if cmd and cmd[0] == "git":
        cmd = ["git", "-c", "safe.directory=*", *cmd[1:]]
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def ensure_repo(clone_url: str, dest: Path, branch: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").exists():
        _run(["git", "fetch", "--all", "--prune"], cwd=dest, check=False)
        _run(["git", "checkout", branch], cwd=dest, check=False)
        _run(["git", "reset", "--hard", f"origin/{branch}"], cwd=dest, check=False)
        _run(["git", "reset", "--hard", branch], cwd=dest, check=False)
        return dest

    if dest.exists():
        shutil.rmtree(dest)
    _run(["git", "clone", "--branch", branch, clone_url, str(dest)])
    return dest


def create_task_checkout(repo: Path, branch: str, dest: Path, base_branch: str) -> Path:
    """Create an isolated checkout (local clone) for one task.

    Prefer this over ``git worktree`` so the worker container owns a private
    ``.git`` directory and can commit without shared-repo permission issues.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--local", str(repo), str(dest)])
    _run(["git", "fetch", "--all", "--prune"], cwd=dest, check=False)
    # Prefer existing task branch on origin (multi-stage), else new from base
    remote_branch = _run(
        ["git", "ls-remote", "--heads", "origin", branch],
        cwd=dest,
        check=False,
    )
    if remote_branch.stdout.strip():
        _run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=dest)
    else:
        local = _run(["git", "rev-parse", "--verify", branch], cwd=dest, check=False)
        if local.returncode == 0:
            _run(["git", "checkout", branch], cwd=dest)
        else:
            _run(["git", "checkout", base_branch], cwd=dest)
            _run(["git", "checkout", "-B", branch], cwd=dest)
    return dest


def remove_checkout(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def push_branch(checkout: Path, branch: str, token: str = "") -> None:
    if token:
        remote = _run(["git", "remote", "get-url", "origin"], cwd=checkout).stdout.strip()
        if remote.startswith("https://") and "@" not in remote:
            authed = remote.replace("https://", f"https://x-access-token:{token}@")
            _run(["git", "remote", "set-url", "origin", authed], cwd=checkout)
    _run(["git", "push", "-u", "origin", branch], cwd=checkout)


def current_head(checkout: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()


def has_commits_ahead(checkout: Path, base_branch: str) -> bool:
    result = _run(
        ["git", "rev-list", "--count", f"{base_branch}..HEAD"],
        cwd=checkout,
        check=False,
    )
    try:
        return int((result.stdout or "0").strip()) > 0
    except ValueError:
        return False
