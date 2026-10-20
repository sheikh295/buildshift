from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


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


def strip_git_credentials(url: str) -> str:
    """Remove embedded userinfo from an HTTPS git URL (never persist tokens)."""
    url = (url or "").strip()
    if not url.startswith("https://") or "@" not in url.split("://", 1)[-1].split("/", 1)[0]:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def with_github_token(url: str, token: str) -> str:
    """Inject a GitHub PAT into an HTTPS clone URL for non-interactive auth."""
    url = strip_git_credentials((url or "").strip())
    token = (token or "").strip()
    if not token or not url.startswith("https://"):
        return url
    # Only rewrite GitHub hosts — leave other remotes untouched
    host = (urlsplit(url).hostname or "").lower()
    if host not in {"github.com", "www.github.com"} and not host.endswith(".github.com"):
        # Still allow github.com paths; also accept api-less HTTPS github
        if "github.com" not in host:
            return url
    return url.replace("https://", f"https://x-access-token:{token}@", 1)


def _set_origin(checkout: Path, url: str) -> None:
    existing = _run(["git", "remote"], cwd=checkout, check=False)
    if "origin" in (existing.stdout or "").split():
        _run(["git", "remote", "set-url", "origin", url], cwd=checkout)
    else:
        _run(["git", "remote", "add", "origin", url], cwd=checkout)


def ensure_repo(clone_url: str, dest: Path, branch: str, token: str = "") -> Path:
    """Clone or refresh a local mirror. Uses GITHUB_TOKEN for private HTTPS remotes."""
    clean = strip_git_credentials(clone_url)
    authed = with_github_token(clean, token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").exists():
        if token and clean.startswith("https://"):
            _set_origin(dest, authed)
        _run(["git", "fetch", "--all", "--prune"], cwd=dest, check=False)
        _run(["git", "checkout", branch], cwd=dest, check=False)
        _run(["git", "reset", "--hard", f"origin/{branch}"], cwd=dest, check=False)
        _run(["git", "reset", "--hard", branch], cwd=dest, check=False)
        # Never leave credentials in .git/config
        if clean.startswith("https://") or clean.startswith("git@"):
            _set_origin(dest, clean)
        return dest

    if dest.exists():
        shutil.rmtree(dest)
    _run(["git", "clone", "--branch", branch, authed, str(dest)])
    if clean.startswith("https://") or clean.startswith("git@"):
        _set_origin(dest, clean)
    return dest


def create_task_checkout(
    repo: Path, branch: str, dest: Path, base_branch: str, *, token: str = ""
) -> Path:
    """Create an isolated checkout (local clone) for one task.

    Prefer this over ``git worktree`` so the worker container owns a private
    ``.git`` directory and can commit without shared-repo permission issues.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # --no-local: avoid hardlinks into the mirror so land_on_base cannot dirty siblings
    _run(["git", "clone", "--no-local", str(repo), str(dest)])

    # Point origin at the real remote (GitHub) so push/PR can reach the network
    upstream = _run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    upstream = strip_git_credentials(upstream)
    network = upstream.startswith("https://") or upstream.startswith("git@")
    try:
        if network:
            _set_origin(dest, with_github_token(upstream, token) if token else upstream)
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
    finally:
        if network:
            _set_origin(dest, upstream)
    return dest


def remove_checkout(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def push_branch(checkout: Path, branch: str, token: str = "", *, force: bool = False) -> None:
    remote = _run(["git", "remote", "get-url", "origin"], cwd=checkout).stdout.strip()
    clean = strip_git_credentials(remote)
    if token and clean.startswith("https://"):
        _set_origin(checkout, with_github_token(clean, token))
    try:
        cmd = ["git", "push", "-u", "origin", branch]
        if force:
            # Required after rebase rewrites commits already pushed during earlier stages
            cmd.insert(2, "--force-with-lease")
        _run(cmd, cwd=checkout)
    finally:
        # Scrub credentials from the checkout remote
        if token and clean.startswith("https://"):
            _set_origin(checkout, clean)


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


class RebaseConflict(GitError):
    """Task branch could not rebase cleanly onto base."""


def fetch_origin(checkout: Path, token: str = "") -> None:
    remote = _run(["git", "remote", "get-url", "origin"], cwd=checkout, check=False).stdout.strip()
    clean = strip_git_credentials(remote)
    if token and clean.startswith("https://"):
        _set_origin(checkout, with_github_token(clean, token))
    try:
        _run(["git", "fetch", "--all", "--prune"], cwd=checkout, check=False)
    finally:
        if token and clean.startswith("https://"):
            _set_origin(checkout, clean)


def _ensure_commit_identity(checkout: Path) -> None:
    """Orchestrator may run as root without a global git identity."""
    _run(["git", "config", "user.email", "buildshift@local"], cwd=checkout, check=False)
    _run(["git", "config", "user.name", "Buildshift"], cwd=checkout, check=False)


def rebase_onto_base(checkout: Path, base_branch: str, token: str = "") -> None:
    """Bring origin/<base> into the task branch (merge).

    Prefer merge over rebase: concurrent landings + Docker bind mounts were
    leaving the tree dirty mid-rebase. Raises RebaseConflict on failure.
    """
    _ensure_commit_identity(checkout)
    # Discard noise from chown / bind mounts before integrating
    _run(["git", "reset", "--hard", "HEAD"], cwd=checkout, check=False)
    _run(["git", "clean", "-fd"], cwd=checkout, check=False)
    fetch_origin(checkout, token=token)
    upstream = f"origin/{base_branch}"
    has_remote = _run(["git", "rev-parse", "--verify", upstream], cwd=checkout, check=False)
    target = upstream if has_remote.returncode == 0 else base_branch
    # Already up to date?
    contains = _run(
        ["git", "merge-base", "--is-ancestor", target, "HEAD"],
        cwd=checkout,
        check=False,
    )
    if contains.returncode == 0:
        return
    result = _run(["git", "merge", "--no-edit", target], cwd=checkout, check=False)
    if result.returncode != 0:
        _run(["git", "merge", "--abort"], cwd=checkout, check=False)
        raise RebaseConflict(
            f"merge {target} into task branch failed\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def run_local_ci(checkout: Path) -> None:
    """Deterministic CI gate (stdlib unittest — no pytest required)."""
    import os

    env = os.environ.copy()
    src = checkout / "src"
    if src.is_dir():
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src}{os.pathsep}{prev}" if prev else str(src)
    result = subprocess.run(
        ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(checkout),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise GitError(
            f"local CI failed ({result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def land_on_base_local(
    *,
    checkout: Path,
    mirror: Path,
    branch: str,
    base_branch: str,
) -> str:
    """Publish the rebased tip as base on the local bare remote.

    Pushes tip → bare directly (mirror has a checked-out worktree and rejects
    pushes to its current branch). Then refreshes the mirror from bare.

    Returns the new base tip SHA.
    """
    tip = current_head(checkout)
    bare = _run(["git", "remote", "get-url", "origin"], cwd=mirror).stdout.strip()
    _run(
        ["git", "push", "--force", bare, f"{tip}:refs/heads/{base_branch}"],
        cwd=checkout,
    )
    # Keep task branch on the mirror for multi-stage / debugging
    push_branch(checkout, branch, force=True)
    # Refresh mirror so the next ensure_repo / checkout sees the new base
    _run(["git", "fetch", "origin"], cwd=mirror, check=False)
    _run(["git", "checkout", base_branch], cwd=mirror, check=False)
    _run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=mirror, check=False)
    return tip
