# Contributing to Buildshift

Thanks for helping. Buildshift is an open-source AI software-house orchestrator.

## Monorepo layout

| Path | Purpose |
|------|---------|
| `apps/` | Deployable applications (`orchestrator`, later `dashboard`) |
| `services/` | Runtime images and sidecar configs (`worker`, `litellm`) |
| `packages/` | Shared libraries imported by apps (add packages here as they appear) |
| `fixtures/` | Local proving targets for dry-run and CI |
| `docs/` | Design docs and operator runbooks |
| `scripts/` | Host helpers (smoke tests, bootstrap) |

Keep application code inside its app or package. Prefer small, reviewable PRs.

## Prerequisites

- Docker and Docker Compose v2
- Make
- Python 3.12+ (for local orchestrator work outside Compose)
- A GitHub token only if you exercise the real PR path

## Local loop

```bash
cp .env.example .env
make up
make smoke
make down
```

Default harness is `mock` so you can exercise the pipeline without LLM spend.

## Development tips

- Orchestrator package lives at `apps/orchestrator` (`buildshift_orchestrator`).
- Schema changes go in `apps/orchestrator/migrations/` and must be additive when possible.
- Do not commit `.env`, tokens, or `data/`.
- Agents never merge to `main` in target repos; Buildshift itself follows normal PR review.

## Pull requests

1. Fork and branch from `main`.
2. Describe the problem and the approach.
3. Note how you tested (`make smoke`, unit tests, etc.).
4. Keep secrets and customer PRDs out of the diff.

## License

By contributing, you agree that your contributions are licensed under the Apache License 2.0.
