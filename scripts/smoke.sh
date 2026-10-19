#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL="${BUILDSHIFT_URL:-http://127.0.0.1:8080}"

echo "==> waiting for orchestrator at $URL"
for i in $(seq 1 60); do
  if curl -sf "$URL/health" >/dev/null; then
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "orchestrator did not become healthy" >&2
    exit 1
  fi
  sleep 1
done

echo "==> enqueue mock task"
RESP="$(curl -sf -X POST "$URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"title":"smoke: mock worker commit","acceptance_criteria":"Create .buildshift/mock-result.md via mock harness","owned_paths":[".buildshift/"]}')"
TASK_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$RESP")"
echo "task_id=$TASK_ID"

echo "==> wait for terminal state"
for i in $(seq 1 90); do
  STATE_JSON="$(curl -sf "$URL/tasks/$TASK_ID")"
  STATE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])' <<<"$STATE_JSON")"
  echo "  [$i] state=$STATE"
  case "$STATE" in
    merged)
      echo "$STATE_JSON" | python3 -m json.tool
      echo "SMOKE OK"
      exit 0
      ;;
    parked|failed|stopped)
      echo "$STATE_JSON" | python3 -m json.tool
      echo "SMOKE FAILED: terminal state $STATE" >&2
      exit 1
      ;;
  esac
  sleep 2
done

echo "SMOKE FAILED: timed out" >&2
exit 1
