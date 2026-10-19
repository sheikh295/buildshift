# Buildshift

**An open-source AI software house:** turn one large PRD into production-grade web work through planned shifts, isolated agent workers, independent verification, and pull requests — with you steering, not micromanaging every task.

Design: [`docs/AI-Software-House-Solution.md`](docs/AI-Software-House-Solution.md)

License: [Apache-2.0](LICENSE)

## Status

Week 1–2.5 pipeline plus Week 3 **office UI**: Compose stack, orchestrator, PRD → plan → multi-role merge onto proving base, and a Phaser office floor with HITL / plan / EOD / **control-plane** settings (Postgres — not day-to-day `.env` edits).

## Quick start (laptop or VPS)

```bash
cp .env.example .env
make up
make smoke           # Week 1 single task
make smoke-week2     # Week 2 PRD → plan → multi-role
make smoke-week25    # Week 2.5: 12 tasks land on base
make smoke-week3     # Week 3: settings + SSE + HITL + office
make down
```

Open the office at `http://127.0.0.1:3000` (login with `OPERATOR_TOKEN` if set). Defaults use `HARNESS=mock` and in-repo fixtures so you can exercise the pipeline with **zero LLM spend**.

**Control plane first:** models, budgets, harness, parallel workers, kill, and proving defaults are edited in the office **Control** panel (`GET/PUT /control/settings`). `.env` is secrets + bootstrap seed only.

## Monorepo layout

```
apps/           Deployable apps (orchestrator, dashboard/office)
services/       Worker image + LiteLLM config
packages/       Shared libraries (add when a second consumer appears)
fixtures/       Local proving targets
docs/           Design + operator docs
scripts/        Host helpers
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Operator docs

- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — up / down / VPS / wipe / control plane
- [`SECURITY.md`](SECURITY.md) — reporting and hardening notes

## API sketch

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + kill-switch flag |
| POST | `/tasks` | Enqueue an ad-hoc task |
| GET | `/tasks/{id}` | Task status (branch, PR URL, spend) |
| GET | `/events`, `/events/stream` | Event history + SSE |
| GET/POST | `/hitl`, `POST /hitl/{id}/reply` | HITL inbox |
| GET | `/digest/eod` | End-of-day digest |
| GET/PUT | `/control/settings` | Runtime control plane |
| POST | `/prd/index` | Index markdown PRD |
| GET | `/prd/products` | List indexed products |
| POST | `/products/{id}/kickoff` | Kickoff + human-item stubs |
| POST | `/plans/propose` | Draft daily plan |
| POST | `/plans/{id}/approve` | Approve plan → spawn multi-role tasks |
| POST | `/control/kill` | `{"enabled": true\|false}` |

Initial model seed: [`apps/orchestrator/config/router.yaml`](apps/orchestrator/config/router.yaml) (imported once into `runtime_settings`).

## Contributing

PRs welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
