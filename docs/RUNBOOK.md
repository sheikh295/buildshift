# Runbook — bring Buildshift up and down anywhere

Works on a laptop or a VPS with Docker. No PaaS required.

## Prerequisites

- Docker Engine + Compose v2
- Git
- Make
- Open ports only as needed (default: orchestrator on `127.0.0.1:8080`)

## First-time setup

```bash
git clone <this-repo> buildshift && cd buildshift
cp .env.example .env
# Edit .env if you have keys / a proving repo. Defaults use HARNESS=mock.
make up    # exports HOST_DATA_DIR for docker-from-docker mounts
make smoke
make smoke-week2
```

`make` sets `HOST_DATA_DIR` to `$(CURDIR)/data` so the orchestrator can ask the host Docker daemon to mount checkouts correctly (required on Docker Desktop and any docker-from-docker setup).

## Everyday controls

| Command | Effect |
|---------|--------|
| `make up` | Build + start Postgres, LiteLLM, orchestrator |
| `make down` | Stop containers; keep DB and `data/` |
| `make down-wipe` | Stop and wipe DB volume + local repo cache |
| `make logs` | Tail orchestrator |
| `make health` | `GET /health` |
| `make smoke` | Week 1: one mock task end-to-end |
| `make smoke-week2` | Week 2: PRD → plan approve → multi-role tasks |
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

Role → model routing lives in `apps/orchestrator/config/router.yaml` (aliases must exist in `services/litellm/config.yaml`).

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
