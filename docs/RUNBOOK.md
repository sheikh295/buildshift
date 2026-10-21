# Runbook — bring Buildshift up and down anywhere

Works on a laptop or a VPS with Docker. No PaaS required.

## Prerequisites

- Docker Engine + Compose v2
- Git
- Make
- Open ports only as needed (default: orchestrator `127.0.0.1:8080`, office `127.0.0.1:3000`)

## First-time setup

```bash
git clone <this-repo> buildshift && cd buildshift
cp .env.example .env
# .env = secrets + bootstrap. Day-to-day knobs → office Control panel.
make up    # exports HOST_DATA_DIR for docker-from-docker mounts
make smoke
make smoke-plan
make smoke-merge-queue
make smoke-office
```

`make` sets `HOST_DATA_DIR` to `$(CURDIR)/data` so the orchestrator can ask the host Docker daemon to mount checkouts correctly (required on Docker Desktop and any docker-from-docker setup).

Office UI: `http://127.0.0.1:3000` — enter `OPERATOR_TOKEN` if set in `.env` (empty token = open local mode).

**Planning flow (CTO + PM):** In **Projects**, upload a narrative PRD — the **CTO** LLM indexes it into modules, requirements, and living `context_markdown`. In **Plan**, **Propose** asks the **PM** LLM to pack a sprint (prefers open backlog). Review the Board, then **Kick off**. After a sprint, use **Chat with CTO** for QA/fixes (CTO files backlog); Propose again for a fix sprint.

## Control plane vs `.env`

| Stay in `.env` | Live in Control (`runtime_settings` / office Control panel) |
|----------------|--------------------------------------------------------------|
| `DATABASE_URL`, ports, `HOST_DATA_DIR` | Role → model map |
| `GITHUB_TOKEN`, LLM API keys, `LITELLM_MASTER_KEY` | Harness (`mock` / `claude`) |
| `OPERATOR_TOKEN` | Budgets, max parallel, max attempts |
| | Kill switch, proving repo/branch, multi-role flag |

Seed: on first boot, settings are imported from env + `apps/orchestrator/config/router.yaml`. Afterwards prefer Control / CLI:

```bash
docker compose exec orchestrator buildshift control settings get
docker compose exec orchestrator buildshift control settings set '{"limits":{"daily_budget_usd":80}}'
```

## Everyday controls

| Command | Effect |
|---------|--------|
| `make up` | Build + start Postgres, LiteLLM, orchestrator, dashboard |
| `make down` | Stop containers; keep DB and `data/` |
| `make down-wipe` | Stop and wipe DB volume + local repo cache |
| `make logs` | Tail orchestrator + dashboard |
| `make health` | `GET /health` |
| `make smoke` | One mock task end-to-end |
| `make smoke-plan` | PRD → plan approve → multi-role tasks |
| `make smoke-merge-queue` | 12 tasks rebase → CI → land on base |
| `make smoke-office` | Settings PUT, SSE, HITL, office up |
| `make smoke-hud` | Projects / sprints / HITL tree / usage |
| `make kill ARGS=true` | Global kill switch on |

### Planning CLI flow (project-scoped)

```bash
# Create project, upload PRD (CTO LLM index), propose sprint (PM LLM), kickoff
curl -s -X POST http://127.0.0.1:8080/projects \
  -H "authorization: Bearer $OPERATOR_TOKEN" -H 'content-type: application/json' \
  -d '{"title":"My app"}'
curl -s -X POST http://127.0.0.1:8080/projects/<project_id>/prd \
  -H "authorization: Bearer $OPERATOR_TOKEN" -H 'content-type: application/json' \
  -d '{"markdown":"# PRD\n...","source_name":"prd.md"}'
curl -s -X POST http://127.0.0.1:8080/projects/<project_id>/sprints/propose \
  -H "authorization: Bearer $OPERATOR_TOKEN" -H 'content-type: application/json' \
  -d '{"capacity_hours":3}'
curl -s -X POST http://127.0.0.1:8080/sprints/<sprint_id>/kickoff \
  -H "authorization: Bearer $OPERATOR_TOKEN"
```

### Post-sprint QA loop

1. Sprint finishes (or Pause when done enough). Manually test the product.
2. **Chat with CTO** (same project): describe fixes/changes in Boss language.
3. CTO applies `add_backlog` (and optionally `update_context` / requirements). Does **not** start workers.
4. **Plan → Propose** (e.g. 1–2h): PM consumes open backlog first.
5. Board review → Kickoff.

Role → model routing (`cto`, `pm`, implementer, …) is edited in the office **Control** panel (seeded from `apps/orchestrator/config/router.yaml`; aliases must exist in `services/litellm/config.yaml`).

### Per-project git repo

In the office **Projects** tab (or API), connect each project to a clone URL or absolute local path:

```bash
curl -s -X PUT http://127.0.0.1:8080/projects/<project_id>/repo \
  -H "authorization: Bearer $OPERATOR_TOKEN" -H 'content-type: application/json' \
  -d '{"repo_url":"https://github.com/org/app.git","repo_branch":"main","sync":true}'
curl -s -X POST http://127.0.0.1:8080/projects/<project_id>/repo/sync \
  -H "authorization: Bearer $OPERATOR_TOKEN"
```

Mirror lands at `./data/repos/{slug}`. Task checkouts are `./data/worktrees/{task-id}`. Workers mount `HOST_DATA_DIR` and run with cwd = that checkout.

### Merge queue

After reviewer approval the orchestrator, under a single-flight lock:

1. Rebases the task branch onto the **project** base branch (or global proving base)
2. Runs local CI (`python -m unittest discover -s tests`)
3. Lands on base (local mirror fast-forward, or GitHub PR + merge when tokenized)

`merged` means the change is on that base tip — not merely that a PR was opened. `make smoke-merge-queue` indexes [`fixtures/sample-prd-12.md`](../fixtures/sample-prd-12.md), approves 12 tickets, and asserts each owned path exists on `main`.

Enqueue an ad-hoc task:

```bash
curl -s http://127.0.0.1:8080/tasks -H 'content-type: application/json' \
  -d '{"title":"Add README note","acceptance_criteria":"README mentions Buildshift","owned_paths":["README.md"]}'
```

## VPS notes

1. Install Docker from the official docs for your distro.
2. Clone the repo; use the same `make up` / `make down`.
3. Keep `ORCHESTRATOR_HOST=127.0.0.1` (default). Reach it over SSH tunnel or Tailscale.
4. Put secrets only in `.env` on the host (mode `600`).
5. For real PRs: set `PROVING_REPO_URL`, `GITHUB_TOKEN`, and optionally `HARNESS=claude` with `INSTALL_CLAUDE=true` on worker rebuild:

```bash
INSTALL_CLAUDE=true HARNESS=claude make build
make up
```

## Data locations

- Compose volume `postgres_data` — orchestrator state
- `./data/repos/{slug}` — per-project git mirrors (plus `proving` / `demo-app` fallback)
- `./data/worktrees/{task-id}` — ephemeral task checkouts (cleaned after tasks)
- `./data/remotes` — local bare remote for `fixtures/demo-app`

## Tear down completely

```bash
make down-wipe
docker image rm buildshift-worker:local || true
```
