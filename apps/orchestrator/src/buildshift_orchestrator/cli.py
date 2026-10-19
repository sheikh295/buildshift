from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
import typer

app = typer.Typer(help="Buildshift CLI", no_args_is_help=True)
tasks_app = typer.Typer(help="Task commands")
control_app = typer.Typer(help="Control plane")
prd_app = typer.Typer(help="PRD indexing")
product_app = typer.Typer(help="Product kickoff")
plan_app = typer.Typer(help="Daily plans")
app.add_typer(tasks_app, name="task")
app.add_typer(control_app, name="control")
app.add_typer(prd_app, name="prd")
app.add_typer(product_app, name="product")
app.add_typer(plan_app, name="plan")


def _base_url() -> str:
    return os.environ.get("BUILDSHIFT_URL", "http://127.0.0.1:8080").rstrip("/")


def _echo(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@app.command("health")
def health() -> None:
    """Check orchestrator health."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/health")
        resp.raise_for_status()
        _echo(resp.json())


@tasks_app.command("create")
def task_create(
    title: str = typer.Argument(..., help="Short task title"),
    criteria: str = typer.Option("", "--criteria", "-c", help="Acceptance criteria"),
    path: Optional[list[str]] = typer.Option(None, "--path", "-p", help="Owned path (repeatable)"),
    budget: Optional[float] = typer.Option(None, "--budget", help="Per-task USD budget"),
    tier: str = typer.Option("T1", "--tier"),
) -> None:
    """Enqueue an ad-hoc task (Week 1 single-role path)."""
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
        _echo(resp.json())


@tasks_app.command("get")
def task_get(task_id: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/tasks/{task_id}")
        resp.raise_for_status()
        _echo(resp.json())


@tasks_app.command("list")
def task_list(limit: int = typer.Option(20, "--limit")) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/tasks", params={"limit": limit})
        resp.raise_for_status()
        _echo(resp.json())


@control_app.command("kill")
def kill(enabled: bool = typer.Argument(..., help="true/false")) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f"{_base_url()}/control/kill", json={"enabled": enabled})
        resp.raise_for_status()
        _echo(resp.json())


settings_app = typer.Typer(help="Runtime settings (control plane)")
control_app.add_typer(settings_app, name="settings")


@settings_app.command("get")
def settings_get() -> None:
    """Show merged runtime settings from the control plane."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/control/settings")
        resp.raise_for_status()
        _echo(resp.json())


@settings_app.command("set")
def settings_set(
    patch_json: str = typer.Argument(
        ...,
        help='JSON patch, e.g. \'{"harness":"mock","limits":{"daily_budget_usd":80}}\'',
    ),
) -> None:
    """Deep-merge a JSON patch into runtime settings (no redeploy)."""
    payload = json.loads(patch_json)
    with httpx.Client(timeout=10.0) as client:
        resp = client.put(f"{_base_url()}/control/settings", json=payload)
        resp.raise_for_status()
        _echo(resp.json())


@prd_app.command("index")
def prd_index(file: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Index a markdown PRD into products + requirements."""
    markdown = file.read_text()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{_base_url()}/prd/index",
            json={"markdown": markdown, "source_name": file.name},
        )
        resp.raise_for_status()
        _echo(resp.json())


@prd_app.command("list")
def prd_list() -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/prd/products")
        resp.raise_for_status()
        _echo(resp.json())


@product_app.command("kickoff")
def product_kickoff(product_id: str = typer.Argument(...)) -> None:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{_base_url()}/products/{product_id}/kickoff")
        resp.raise_for_status()
        _echo(resp.json())


@plan_app.command("propose")
def plan_propose(
    product: str = typer.Option(..., "--product", "-p", help="Product UUID"),
    max_tickets: int = typer.Option(3, "--max-tickets"),
) -> None:
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{_base_url()}/plans/propose",
            json={"product_id": product, "max_tickets": max_tickets},
        )
        resp.raise_for_status()
        _echo(resp.json())


@plan_app.command("show")
def plan_show(plan_id: str = typer.Argument(...)) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/plans/{plan_id}")
        resp.raise_for_status()
        _echo(resp.json())


@plan_app.command("diff")
def plan_diff(plan_id: str = typer.Argument(...)) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{_base_url()}/plans/{plan_id}")
        resp.raise_for_status()
        data = resp.json()
        _echo({"plan_id": data["id"], "status": data["status"], "diff": data.get("diff")})


@plan_app.command("approve")
def plan_approve(plan_id: str = typer.Argument(...)) -> None:
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f"{_base_url()}/plans/{plan_id}/approve")
        resp.raise_for_status()
        _echo(resp.json())


if __name__ == "__main__":
    app()
