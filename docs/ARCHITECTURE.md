# Architecture (operator view)

Buildshift is a monorepo. Compose is the deploy unit for v1 on any Docker host (laptop or VPS).

```
You (CLI / later dashboard)
        │
        ▼
apps/orchestrator (FastAPI)
  ├─ task state machine (Postgres)
  ├─ scheduler / claim loop
  ├─ runner (worktree + docker run)
  └─ kill switch + budgets
        │
        ├── services/litellm  → LLM providers
        └── services/worker   → one container per task
                │
                ▼
        proving git remote (PRs)
```

## Boundaries

| Unit | Owns |
|------|------|
| `apps/orchestrator` | API, CLI, scheduling, Docker runner, DB schema |
| `apps/dashboard` | Human control UI (later) |
| `services/worker` | Task execution environment + harness |
| `services/litellm` | Model routing gateway config |
| `packages/*` | Shared libraries when multiple apps need them |
| `fixtures/*` | Local proving targets |

## Data

- **Postgres:** tasks, runs, events, control flags.
- **Host volumes:** cloned proving repos and worktrees under `data/` (gitignored).
- **Git remote:** source of truth for product code and PRs.

## Expandability

Add a new long-lived process as an `apps/` or Compose service. Add a new execution environment under `services/`. Extract shared types into `packages/` only when a second consumer exists.
