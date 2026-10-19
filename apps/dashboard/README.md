# apps/dashboard

Buildshift **office UI** — Phaser 3 floor + React HUD (HITL, board, plan, EOD, control plane).

## Local (outside Compose)

```bash
cd apps/dashboard
npm install
ORCHESTRATOR_URL=http://127.0.0.1:8080 OPERATOR_TOKEN= npm run dev
```

Open http://127.0.0.1:3000 — login with the same `OPERATOR_TOKEN` as the orchestrator (leave empty when both are unset).

## Compose

`make up` starts the `dashboard` service on `127.0.0.1:3000`. Orchestrator API is proxied via `/api/orch/*` and SSE via `/api/events/stream`.

Day-to-day knobs live in **Control** (Postgres `runtime_settings`), not `.env`.

**Plan panel:** upload or paste a markdown PRD → Index & kickoff → Propose → Approve.
