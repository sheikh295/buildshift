from __future__ import annotations

import logging
from pathlib import Path

import docker
from docker.errors import DockerException, ImageNotFound

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.router_config import role_model

log = logging.getLogger(__name__)


def get_client(settings: Settings) -> docker.DockerClient:
    if settings.docker_host:
        return docker.DockerClient(base_url=settings.docker_host)
    return docker.from_env()


def run_worker(
    *,
    settings: Settings,
    task_id: str,
    worktree: Path,
    prompt: str,
    role: str = "implementer",
) -> tuple[int, str]:
    """Run the worker container against a mounted task checkout. Returns (exit_code, logs)."""
    client = get_client(settings)
    prompt_file = worktree / ".buildshift" / "task_prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt)

    model = role_model(role) if settings.harness != "mock" else "mock"
    env = {
        "HARNESS": settings.harness,
        "ROLE": role,
        "TASK_ID": task_id,
        "ANTHROPIC_BASE_URL": f"{settings.litellm_url.rstrip('/')}",
        "ANTHROPIC_API_KEY": settings.litellm_master_key,
        "ANTHROPIC_MODEL": model,
        "DEFAULT_IMPLEMENTER_MODEL": model,
    }

    try:
        client.images.get(settings.worker_image)
    except ImageNotFound:
        log.warning("worker image %s missing; attempting build is host responsibility", settings.worker_image)
        raise

    if settings.host_data_dir is None:
        raise RuntimeError(
            "HOST_DATA_DIR is required so worker containers can mount task checkouts"
        )
    data_mount = str(settings.host_data_dir.resolve())
    work_dir = str(worktree.resolve())
    container = None
    try:
        container = client.containers.run(
            settings.worker_image,
            detach=True,
            environment=env,
            volumes={
                data_mount: {"bind": str(settings.data_dir), "mode": "rw"},
            },
            network=settings.worker_network,
            working_dir=work_dir,
            user="buildshift",
            labels={"buildshift.task_id": task_id, "buildshift.role": role},
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
