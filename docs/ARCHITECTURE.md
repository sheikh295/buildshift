# Architecture (operator view)

Buildshift is a monorepo. Compose is the deploy unit for v1 on any Docker host (laptop or VPS).

```
You (CLI / office UI)
        │
        ▼
apps/dashboard (Next.js + Phaser)
  └─ HUD: HITL, plan, EOD, Control plane
        │
        ▼
apps/orchestrator (FastAPI)
  ├─ task state machine (Postgres)
  ├─ runtime_settings (control plane)
  ├─ scheduler / claim loop
  ├─ runner (worktree + docker run)
  └─ SSE events + kill switch
        │
        ├── services/litellm  → LLM providers
        └── services/worker   → one container per task
                │
                ▼
        per-project git mirror → project remote (or global proving / demo-app)
```

## Boundaries

| Unit | Owns |
|------|------|
| `apps/orchestrator` | API, CLI, scheduling, Docker runner, DB schema, runtime settings |
| `apps/dashboard` | Office floor + operator HUD (control plane UI) |
| `services/worker` | Task execution environment + harness |
| `services/litellm` | Model routing gateway config |
| `packages/*` | Shared libraries when multiple apps need them |
| `fixtures/*` | Local proving targets |

## Planning roles

| Role | When | Writes |
|------|------|--------|
| **CTO** (`role_model("cto")`) | PRD upload/reindex; CEO chat | `context_markdown`, modules/requirements, open backlog, HITL |
| **PM** (`role_model("pm")`) | Plan → Propose | Sprint + epics + tasks (`planned`); marks backlog `scheduled` |
| Kickoff | After Board review | Tasks `planned` → `ready` (workers unchanged) |

No regex PRD scrape on upload; no heuristic hour-packer on Propose.

## Data

- **Postgres:** tasks, runs, events, projects (incl. `repo_url` / `repo_path`, `context_markdown`, `index_status`), backlog, control flags, `runtime_settings`.
- **Host volumes:** per-project mirrors at `data/repos/{slug}` and task checkouts at `data/worktrees/{task-id}` (gitignored). `HOST_DATA_DIR` must point at the host path so worker containers can mount the same tree.
- **Git remote:** each Project connects its own remote (or local path); tasks without a project repo fall back to global proving / demo-app.
- **`.env`:** secrets + bootstrap only; day-to-day knobs live in Control / `runtime_settings`.

## Expandability

Add a new long-lived process as an `apps/` or Compose service. Add a new execution environment under `services/`. Extract shared types into `packages/` only when a second consumer exists.
