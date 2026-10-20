#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL="${BUILDSHIFT_URL:-http://127.0.0.1:8080}"
PRD="${ROOT}/fixtures/sample-prd.md"

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

echo "==> index sample PRD"
INDEX="$(python3 - <<PY
import json
from pathlib import Path
import urllib.request
md = Path(r"""$PRD""").read_text()
req = urllib.request.Request(
    "$URL/prd/index",
    data=json.dumps({"markdown": md, "source_name": "sample-prd.md"}).encode(),
    headers={"content-type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=60).read().decode())
PY
)"
echo "$INDEX" | python3 -m json.tool
PRODUCT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["products"][0]["id"])' <<<"$INDEX")"
echo "product_id=$PRODUCT_ID"

echo "==> kickoff"
KICK="$(curl -s -w '\n%{http_code}' -X POST "$URL/products/$PRODUCT_ID/kickoff")"
KICK_BODY="$(echo "$KICK" | sed '$d')"
KICK_CODE="$(echo "$KICK" | tail -n1)"
echo "$KICK_BODY" | python3 -m json.tool || echo "kickoff raw: $KICK_BODY"
if [[ "$KICK_CODE" != "200" ]]; then
  echo "kickoff HTTP $KICK_CODE" >&2
  exit 1
fi

echo "==> propose plan"
PLAN="$(curl -sf -X POST "$URL/plans/propose" \
  -H 'content-type: application/json' \
  -d "{\"product_id\":\"$PRODUCT_ID\",\"max_tickets\":2}")"
echo "$PLAN" | python3 -m json.tool
PLAN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PLAN")"

echo "==> approve plan $PLAN_ID"
APPROVED="$(curl -sf -X POST "$URL/plans/$PLAN_ID/approve")"
echo "$APPROVED" | python3 -m json.tool
TASK_IDS="$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["task_ids"]))' <<<"$APPROVED")"
echo "tasks: $TASK_IDS"

echo "==> wait for all approved tasks to merge"
for i in $(seq 1 180); do
  ALL_MERGED=1
  for tid in $TASK_IDS; do
    STATE="$(curl -sf "$URL/tasks/$tid" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    echo "  [$i] $tid -> $STATE"
    case "$STATE" in
      merged) ;;
      parked|failed|stopped)
        curl -sf "$URL/tasks/$tid" | python3 -m json.tool
        echo "SMOKE-PLAN FAILED: $tid terminal $STATE" >&2
        exit 1
        ;;
      *) ALL_MERGED=0 ;;
    esac
  done
  if [[ "$ALL_MERGED" -eq 1 ]]; then
    echo "SMOKE-PLAN OK"
    exit 0
  fi
  sleep 3
done

echo "SMOKE-PLAN FAILED: timed out" >&2
exit 1
