from __future__ import annotations

import json
import os
from typing import Optional

import httpx
import typer

app = typer.Typer(help="Buildshift CLI", no_args_is_help=True)
tasks_app = typer.Typer(help="Task commands")
control_app = typer.Typer(help="Control plane")
app.add_typer(tasks_app, name="task")
app.add_typer(control_app, name="control")


def _base_url() -> str:
    return os.environ.get("BUILDSHIFT_URL", "http://127.0.0.1:8080").rstrip("/")


@app.command("health")
def health() -> None:
    """Check orchestrator health."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/health")
        resp.raise_for_status()
        typer.echo(json.dumps(resp.json(), indent=2))


@tasks_app.command("create")
def task_create(
    title: str = typer.Argument(..., help="Short task title"),
    criteria: str = typer.Option("", "--criteria", "-c", help="Acceptance criteria"),
    path: Optional[list[str]] = typer.Option(None, "--path", "-p", help="Owned path (repeatable)"),
    budget: Optional[float] = typer.Option(None, "--budget", help="Per-task USD budget"),
    tier: str = typer.Option("T1", "--tier"),
) -> None:
    """Enqueue a task."""
    payload = {
        "title": title,
        "acceptance_criteria": criteria,
        "owned_paths": path or [],
        "tier": tier,
    }
    if budget is not None:
        payload["budget_usd"] = budget
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{_base_url()}/tasks", json=payload)
        resp.raise_for_status()
        typer.echo(json.dumps(resp.json(), indent=2, default=str))


@tasks_app.command("get")
def task_get(task_id: str) -> None:
    """Fetch a task by id."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/tasks/{task_id}")
        resp.raise_for_status()
        typer.echo(json.dumps(resp.json(), indent=2, default=str))


@tasks_app.command("list")
def task_list(limit: int = typer.Option(20, "--limit")) -> None:
    """List recent tasks."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/tasks", params={"limit": limit})
        resp.raise_for_status()
        typer.echo(json.dumps(resp.json(), indent=2, default=str))


@control_app.command("kill")
def kill(enabled: bool = typer.Argument(..., help="true/false")) -> None:
    """Enable or disable the global kill switch."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f"{_base_url()}/control/kill", json={"enabled": enabled})
        resp.raise_for_status()
        typer.echo(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    app()
