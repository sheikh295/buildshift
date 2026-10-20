#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Load local .env for OPERATOR_TOKEN when present (do not echo secrets)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

URL="${BUILDSHIFT_URL:-http://127.0.0.1:8080}"
AUTH=()
if [[ -n "${OPERATOR_TOKEN:-}" ]]; then
  AUTH=(-H "Authorization: Bearer ${OPERATOR_TOKEN}")
fi

echo "==> waiting for orchestrator at $URL"
for i in $(seq 1 90); do
  if curl -sf "$URL/health" >/dev/null; then
    break
  fi
  if [[ "$i" -eq 90 ]]; then
    echo "orchestrator did not become healthy" >&2
    exit 1
  fi
  sleep 1
done

SLUG="smoke-hud-$(date +%s)"
echo "==> create project ($SLUG)"
PROJ="$(curl -sf "${AUTH[@]}" -X POST "$URL/projects" \
  -H 'content-type: application/json' \
  -d "{\"title\":\"Smoke HUD App\",\"slug\":\"$SLUG\"}")"
PID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PROJ")"
echo "project=$PID"

echo "==> upload PRD"
curl -sf "${AUTH[@]}" -X POST "$URL/projects/$PID/prd" \
  -H 'content-type: application/json' \
  -d '{"markdown":"## Auth\n1. Users can sign in\n2. Sessions expire\n\n## Billing\n1. Invoice PDF export\n","source_name":"smoke.md"}' \
  | python3 -m json.tool >/dev/null

echo "==> propose sprint"
SP="$(curl -sf "${AUTH[@]}" -X POST "$URL/projects/$PID/sprints/propose" \
  -H 'content-type: application/json' \
  -d '{"capacity_hours":6}')"
SID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$SP")"
echo "sprint=$SID"

echo "==> sprint detail"
curl -sf "${AUTH[@]}" "$URL/sprints/$SID" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["sprint"]["status"]=="planned", d
assert len(d["epics"])>=1, d
print("epics", len(d["epics"]), "ok")
'

echo "==> kickoff sprint"
curl -sf "${AUTH[@]}" -X POST "$URL/sprints/$SID/kickoff" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["status"]=="active", d
assert d["task_count"]>=1, d
print("tasks", d["task_count"], "ok")
'

echo "==> hitl tree"
curl -sf "${AUTH[@]}" "$URL/hitl?group=tree&status=open" | python3 -m json.tool >/dev/null

echo "==> usage"
curl -sf "${AUTH[@]}" "$URL/usage?group_by=day" | python3 -m json.tool >/dev/null

echo "==> eod with project"
curl -sf "${AUTH[@]}" "$URL/digest/eod?project_id=$PID" | python3 -m json.tool >/dev/null

echo "SMOKE-HUD OK"
