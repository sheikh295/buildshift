# Buildshift

**An open-source AI software house:** turn one large PRD into production-grade web work through planned shifts, isolated agent workers, independent verification, and pull requests — with you steering, not micromanaging every task.

Design: [`docs/AI-Software-House-Solution.md`](docs/AI-Software-House-Solution.md)

License: [Apache-2.0](LICENSE)

## Status

Week 1 + Week 2 CLI pipeline: Compose stack, orchestrator, PRD indexing, daily plan approval gate, multi-role workers (test-author → implementer → reviewer), path locks, thin merge queue. Dashboard is still Week 3.

## Quick start (laptop or VPS)

```bash
cp .env.example .env
make up
make smoke          # Week 1 single task
make smoke-week2    # Week 2 PRD → plan → multi-role
make down
```

Defaults use `HARNESS=mock` and the in-repo [`fixtures/demo-app`](fixtures/demo-app) / [`fixtures/sample-prd.md`](fixtures/sample-prd.md) so you can exercise the pipeline with **zero LLM spend**.

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
| POST | `/tasks` | Enqueue an ad-hoc task |
| GET | `/tasks/{id}` | Task status (branch, PR URL, spend) |
| POST | `/prd/index` | Index markdown PRD |
| GET | `/prd/products` | List indexed products |
| POST | `/products/{id}/kickoff` | Kickoff + human-item stubs |
| POST | `/plans/propose` | Draft daily plan |
| POST | `/plans/{id}/approve` | Approve plan → spawn multi-role tasks |
| POST | `/control/kill` | `{"enabled": true\|false}` |

Model routing: [`apps/orchestrator/config/router.yaml`](apps/orchestrator/config/router.yaml).

## Contributing

PRs welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
