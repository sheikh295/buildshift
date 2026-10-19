# apps/orchestrator

FastAPI orchestrator for Buildshift: task queue, budgets, kill switch, and the runner that starts worker containers.

## Layout

```
src/buildshift_orchestrator/
  api/          HTTP routes
  runner/       worktree + docker execution
  models.py     SQLAlchemy models
  db.py         engine / sessions
  config.py     settings from env
  worker_loop.py claim + run loop
  cli.py        `buildshift` CLI
migrations/     SQL migrations applied on startup
```

## Local (outside Compose)

```bash
cd apps/orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Prefer `make up` from the repo root for the full stack.
