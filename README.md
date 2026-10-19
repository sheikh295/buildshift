# Buildshift

**An open-source AI software house:** turn one large PRD into production-grade web work through planned shifts, isolated agent workers, independent verification, and pull requests — with you steering, not micromanaging every task.

Design: [`docs/AI-Software-House-Solution.md`](docs/AI-Software-House-Solution.md)

License: [Apache-2.0](LICENSE)

## Status

Week 1 vertical slice is in progress: portable Docker Compose stack, orchestrator API/CLI, Postgres state machine, mock (and optional Claude Code) worker path, budgets, and a kill switch.

## Quick start (laptop or VPS)

```bash
cp .env.example .env
make up
make smoke
make down
```

Defaults use `HARNESS=mock` and the in-repo [`fixtures/demo-app`](fixtures/demo-app) so you can exercise the pipeline with **zero LLM spend**.

## Monorepo layout

```
apps/           Deployable apps (orchestrator, dashboard placeholder)
services/       Worker image + LiteLLM config
packages/       Shared libraries (add when a second consumer appears)
fixtures/       Local proving targets
docs/           Design + operator docs
scripts/        Host helpers
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Operator docs

- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — up / down / VPS / wipe
- [`SECURITY.md`](SECURITY.md) — reporting and hardening notes

## API sketch

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + kill-switch flag |
| POST | `/tasks` | Enqueue a task |
| GET | `/tasks/{id}` | Task status (branch, PR URL, spend) |
| POST | `/control/kill` | `{"enabled": true\|false}` |

## Contributing

PRs welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
