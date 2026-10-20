#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

URL="${BUILDSHIFT_URL:-http://127.0.0.1:8080}"
DASH="${DASHBOARD_URL:-http://127.0.0.1:3000}"
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

echo "==> waiting for office UI at $DASH"
for i in $(seq 1 120); do
  if curl -sf "$DASH" >/dev/null || curl -sf "$DASH/login" >/dev/null; then
    break
  fi
  if [[ "$i" -eq 120 ]]; then
    echo "dashboard did not become ready" >&2
    exit 1
  fi
  sleep 1
done

echo "==> GET /control/settings"
BEFORE="$(curl -sf "${AUTH[@]}" "$URL/control/settings")"
echo "$BEFORE" | python3 -m json.tool >/dev/null

echo "==> PUT /control/settings (budget + harness round-trip)"
AFTER="$(curl -sf "${AUTH[@]}" -X PUT "$URL/control/settings" \
  -H 'content-type: application/json' \
  -d '{"harness":"mock","limits":{"daily_budget_usd":61.5,"task_budget_usd":3.25}}')"
echo "$AFTER" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d.get("harness")=="mock", d
assert float(d["limits"]["daily_budget_usd"])==61.5, d
assert float(d["limits"]["task_budget_usd"])==3.25, d
print("settings ok")
'

echo "==> GET /events"
curl -sf "${AUTH[@]}" "$URL/events?since=0&limit=5" | python3 -m json.tool >/dev/null

echo "==> SSE /events/stream (connect + brief read)"
# Stream stays open; --max-time bounds the smoke. Exit 28 (timeout) still means connect worked.
set +e
curl -sf "${AUTH[@]}" -N --max-time 3 "$URL/events/stream?since=0" >/tmp/buildshift-sse.out 2>/tmp/buildshift-sse.err
SSE_EC=$?
set -e
if [[ "$SSE_EC" -ne 0 && "$SSE_EC" -ne 28 ]]; then
  echo "SSE failed ec=$SSE_EC" >&2
  cat /tmp/buildshift-sse.err >&2 || true
  exit 1
fi
echo "sse connect ok"

echo "==> HITL list"
curl -sf "${AUTH[@]}" "$URL/hitl?status=open" | python3 -m json.tool >/dev/null

echo "==> create + reply HITL"
HITL="$(curl -sf "${AUTH[@]}" -X POST "$URL/hitl" \
  -H 'content-type: application/json' \
  -d '{"kind":"smoke","summary":"week3 smoke hitl"}')"
HITL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$HITL")"
curl -sf "${AUTH[@]}" -X POST "$URL/hitl/$HITL_ID/reply" \
  -H 'content-type: application/json' \
  -d '{"reply":"ack from smoke"}' | python3 -m json.tool >/dev/null

echo "==> EOD digest"
curl -sf "${AUTH[@]}" "$URL/digest/eod" | python3 -m json.tool >/dev/null

echo "SMOKE-WEEK3 OK"
