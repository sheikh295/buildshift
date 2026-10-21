from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

import docker
from docker.errors import DockerException, ImageNotFound

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.router_config import role_model

log = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def tail_lines(text: str, n: int = 20) -> str:
    """Return the last n non-empty-aware lines (keeps blanks inside the window)."""
    lines = (text or "").splitlines()
    if n <= 0 or len(lines) <= n:
        return "\n".join(lines)
    return "\n".join(lines[-n:])


def live_worker_logs(settings: Settings, task_id: str, *, lines: int = 20) -> str | None:
    """Tail stdout/stderr from a running worker container labeled with this task."""
    try:
        client = get_client(settings)
        containers = client.containers.list(
            filters={"label": f"buildshift.task_id={task_id}", "status": "running"}
        )
        if not containers:
            return None
        raw = containers[0].logs(stdout=True, stderr=True, tail=max(lines, 50))
        text = (
            raw.decode("utf-8", errors="replace")
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        )
        return tail_lines(strip_ansi(text), lines)
    except DockerException as exc:
        log.debug("live worker logs unavailable for %s: %s", task_id, exc)
        return None


def get_client(settings: Settings) -> docker.DockerClient:
    if settings.docker_host:
        return docker.DockerClient(base_url=settings.docker_host)
    return docker.from_env()


def _host_worktree_path(settings: Settings, worktree: Path) -> Path:
    """Map orchestrator-container worktree path → absolute path on the Docker host."""
    if settings.host_data_dir is None:
        raise RuntimeError(
            "HOST_DATA_DIR is required so worker containers can mount task checkouts"
        )
    data = settings.data_dir.resolve()
    wt = worktree.resolve()
    try:
        rel = wt.relative_to(data)
    except ValueError as exc:
        raise RuntimeError(
            f"worktree {wt} is outside DATA_DIR {data}; refusing to mount"
        ) from exc
    return (settings.host_data_dir.resolve() / rel).resolve()


def github_owner_repo(clone_url: str) -> str | None:
    """Extract owner/repo from a GitHub HTTPS or SSH URL."""
    url = (clone_url or "").strip()
    if not url:
        return None
    if url.startswith("git@"):
        # git@github.com:owner/repo.git
        try:
            path = url.split(":", 1)[1]
        except IndexError:
            return None
    else:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if "github.com" not in host:
            return None
        path = parts.path or ""
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segs = [s for s in path.split("/") if s]
    if len(segs) < 2:
        return None
    return f"{segs[0]}/{segs[1]}"


def run_worker(
    *,
    settings: Settings,
    task_id: str,
    worktree: Path,
    prompt: str,
    role: str = "implementer",
    owned_paths: list[str] | None = None,
    clone_url: str = "",
) -> tuple[int, str]:
    """Run the worker container against a mounted task checkout. Returns (exit_code, logs)."""
    client = get_client(settings)
    prompt_file = worktree / ".buildshift" / "task_prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt)

    model = role_model(role) if settings.harness != "mock" else "mock"
    litellm_base = settings.litellm_url.rstrip("/")
    allowed_repo = github_owner_repo(clone_url) or ""

    env = {
        "HARNESS": settings.harness,
        "ROLE": role,
        "TASK_ID": task_id,
        "OWNED_PATHS": ",".join(owned_paths or []),
        # Control-plane model alias → LiteLLM (opencode + shared)
        "LITELLM_URL": litellm_base,
        "LITELLM_API_KEY": settings.litellm_master_key,
        "LITELLM_MODEL": model,
        "DEFAULT_IMPLEMENTER_MODEL": model,
        # Claude Code harness (Anthropic-compatible providers via LiteLLM)
        "ANTHROPIC_BASE_URL": litellm_base,
        "ANTHROPIC_API_KEY": settings.litellm_master_key,
        "ANTHROPIC_MODEL": model,
        # GitHub PAT is scrubbed by entrypoint after starting the local proxy
        "ALLOWED_GITHUB_REPO": allowed_repo,
        "GITHUB_PROXY_PORT": "18741",
    }
    if settings.github_token and allowed_repo:
        env["GITHUB_TOKEN"] = settings.github_token

    try:
        client.images.get(settings.worker_image)
    except ImageNotFound:
        log.warning(
            "worker image %s missing; attempting build is host responsibility",
            settings.worker_image,
        )
        raise

    # worktree lives at DATA_DIR inside the orchestrator; Docker needs the
    # matching HOST_DATA_DIR path for the bind mount (daemon resolves on host).
    if not worktree.is_dir():
        raise RuntimeError(f"worktree missing in orchestrator: {worktree}")
    host_wt = _host_worktree_path(settings, worktree)

    container = None
    try:
        # Mount ONLY this task checkout — never the whole data/ tree or monorepo.
        container = client.containers.run(
            settings.worker_image,
            detach=True,
            environment=env,
            volumes={
                str(host_wt): {"bind": "/workspace", "mode": "rw"},
            },
            network=settings.worker_network,
            working_dir="/workspace",
            user="buildshift",
            labels={"buildshift.task_id": task_id, "buildshift.role": role},
            # Drop dangerous caps; no docker.sock; no host PID/net
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            remove=False,
        )
        result = container.wait(timeout=60 * 60)
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        status = int(result.get("StatusCode", 1))
        return status, logs
    except DockerException as exc:
        raise RuntimeError(f"docker run failed: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass
