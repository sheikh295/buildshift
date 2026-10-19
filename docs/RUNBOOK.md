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
make smoke-week2
make smoke-week25
make smoke-week3
```

`make` sets `HOST_DATA_DIR` to `$(CURDIR)/data` so the orchestrator can ask the host Docker daemon to mount checkouts correctly (required on Docker Desktop and any docker-from-docker setup).

Office UI: `http://127.0.0.1:3000` — enter `OPERATOR_TOKEN` if set in `.env` (empty token = open local mode).

In the office **Plan** panel you can upload or paste a markdown PRD (Index & kickoff), then Propose → Approve. CLI still works: `buildshift prd index /path/to.md`.

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
| `make smoke` | Week 1: one mock task end-to-end |
| `make smoke-week2` | Week 2: PRD → plan approve → multi-role tasks |
| `make smoke-week25` | Week 2.5: 12 tasks rebase → CI → land on base |
| `make smoke-week3` | Week 3: settings PUT, SSE, HITL, office up |
| `make kill ARGS=true` | Global kill switch on |

### Week 2 CLI flow

```bash
# Index a PRD (or use fixtures/sample-prd.md via make smoke-week2)
curl -s http://127.0.0.1:8080/prd/products | python3 -m json.tool

# Propose + approve a day plan for a product UUID
curl -s -X POST http://127.0.0.1:8080/plans/propose \
  -H 'content-type: application/json' \
  -d '{"product_id":"<uuid>","max_tickets":3}'
curl -s -X POST http://127.0.0.1:8080/plans/<plan_id>/approve
```

Role → model routing is edited in the office **Control** panel (seeded from `apps/orchestrator/config/router.yaml`; aliases must exist in `services/litellm/config.yaml`).

### Week 2.5 merge queue

After reviewer approval the orchestrator, under a single-flight lock:

1. Rebases the task branch onto the proving base
2. Runs local CI (`python -m unittest discover -s tests`)
3. Lands on base (local bare fast-forward, or GitHub PR + merge when tokenized)

`merged` means the change is on the proving base tip — not merely that a PR was opened. `make smoke-week25` indexes [`fixtures/sample-prd-12.md`](../fixtures/sample-prd-12.md), approves 12 tickets, and asserts each owned path exists on `main`.

Enqueue an ad-hoc Week 1 task:

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
- `./data/repos` — clones
- `./data/worktrees` — ephemeral (cleaned after tasks)
- `./data/remotes` — local bare remote for `fixtures/demo-app`

## Tear down completely

```bash
make down-wipe
docker image rm buildshift-worker:local || true
```
