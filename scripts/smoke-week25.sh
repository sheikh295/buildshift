#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL="${BUILDSHIFT_URL:-http://127.0.0.1:8080}"
PRD="${ROOT}/fixtures/sample-prd-12.md"
DATA_DIR="${HOST_DATA_DIR:-$ROOT/data}"
MIRROR="${DATA_DIR}/repos/demo-app"

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

echo "==> index 12-req proving PRD"
INDEX="$(python3 - <<PY
import json
from pathlib import Path
import urllib.request
md = Path(r"""$PRD""").read_text()
req = urllib.request.Request(
    "$URL/prd/index",
    data=json.dumps({"markdown": md, "source_name": "sample-prd-12.md"}).encode(),
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

echo "==> propose plan (12 tickets)"
PLAN="$(curl -sf -X POST "$URL/plans/propose" \
  -H 'content-type: application/json' \
  -d "{\"product_id\":\"$PRODUCT_ID\",\"max_tickets\":12}")"
echo "$PLAN" | python3 -m json.tool
PLAN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PLAN")"
TICKET_COUNT="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)["tickets"]))' <<<"$PLAN")"
if [[ "$TICKET_COUNT" -lt 12 ]]; then
  echo "expected 12 tickets, got $TICKET_COUNT" >&2
  exit 1
fi

# Capture owned paths (non-.buildshift) for post-merge assertions
OWNED_JSON="$(python3 -c 'import json,sys
p=json.load(sys.stdin)
paths=[]
for t in p["tickets"]:
  for x in t.get("owned_paths") or []:
    if x and not x.startswith(".buildshift"):
      paths.append(x)
print(json.dumps(paths))
' <<<"$PLAN")"

echo "==> approve plan $PLAN_ID"
APPROVED="$(curl -sf -X POST "$URL/plans/$PLAN_ID/approve")"
echo "$APPROVED" | python3 -m json.tool
TASK_IDS="$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["task_ids"]))' <<<"$APPROVED")"
TASK_COUNT="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)["task_ids"]))' <<<"$APPROVED")"
echo "tasks ($TASK_COUNT): $TASK_IDS"
if [[ "$TASK_COUNT" -lt 12 ]]; then
  echo "expected 12 tasks, got $TASK_COUNT" >&2
  exit 1
fi

echo "==> wait for all 12 tasks to land on base"
for i in $(seq 1 360); do
  ALL_MERGED=1
  for tid in $TASK_IDS; do
    STATE="$(curl -sf "$URL/tasks/$tid" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    echo "  [$i] $tid -> $STATE"
    case "$STATE" in
      merged) ;;
      parked|failed|stopped)
        curl -sf "$URL/tasks/$tid" | python3 -m json.tool
        echo "SMOKE-WEEK25 FAILED: $tid terminal $STATE" >&2
        exit 1
        ;;
      *) ALL_MERGED=0 ;;
    esac
  done
  if [[ "$ALL_MERGED" -eq 1 ]]; then
    echo "==> assert owned paths exist on proving base"
    if [[ ! -d "$MIRROR/.git" ]]; then
      echo "mirror missing at $MIRROR — fetch after land should have created it" >&2
      exit 1
    fi
    git -C "$MIRROR" fetch --all --prune >/dev/null 2>&1 || true
    git -C "$MIRROR" checkout main >/dev/null 2>&1 || true
    git -C "$MIRROR" reset --hard origin/main >/dev/null 2>&1 || true
    python3 - <<PY
import json, subprocess, sys
from pathlib import Path
mirror = Path(r"""$MIRROR""")
paths = json.loads(r"""$OWNED_JSON""")
missing = []
for p in paths:
    r = subprocess.run(
        ["git", "-C", str(mirror), "cat-file", "-e", f"HEAD:{p}"],
        capture_output=True,
    )
    if r.returncode != 0:
        missing.append(p)
if missing:
    print("missing on base:", missing, file=sys.stderr)
    sys.exit(1)
print(f"verified {len(paths)} owned paths on base")
PY
    echo "SMOKE-WEEK25 OK"
    exit 0
  fi
  sleep 3
done

echo "SMOKE-WEEK25 FAILED: timed out" >&2
exit 1
