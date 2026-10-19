#!/usr/bin/env bash
set -euo pipefail

HARNESS="${HARNESS:-mock}"
ROLE="${ROLE:-implementer}"
TASK_ID="${TASK_ID:-unknown}"
PROMPT_FILE="${PROMPT_FILE:-.buildshift/task_prompt.md}"

git config --global user.email "buildshift-worker@local"
git config --global user.name "Buildshift Worker"
git config --global --add safe.directory "*"

echo "worker cwd=$(pwd) harness=${HARNESS} role=${ROLE} task=${TASK_ID}"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "missing prompt at $PROMPT_FILE (cwd=$(pwd))" >&2
  ls -la . .buildshift 2>/dev/null || true
  exit 2
fi

if [[ ! -d .git && ! -f .git ]]; then
  echo "not a git checkout at $(pwd)" >&2
  exit 6
fi

commit_if_needed() {
  local msg="$1"
  if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    echo "nothing to commit" >&2
    exit 3
  fi
  git add -A
  git commit -m "$msg"
}

mock_by_role() {
  mkdir -p .buildshift tests
  case "$ROLE" in
    test_author)
      OUT="tests/test_task_${TASK_ID//-/_}.py"
      {
        echo '"""Auto-generated acceptance test stub (mock harness)."""'
        echo
        echo "def test_acceptance_placeholder():"
        echo "    assert True  # TODO: replace with real criteria checks"
      } > "$OUT"
      echo "# tests authored" > .buildshift/tests.md
      cat "$PROMPT_FILE" >> .buildshift/tests.md
      commit_if_needed "buildshift(test_author): tests for ${TASK_ID}"
      ;;
    implementer)
      OUT=".buildshift/impl.md"
      {
        echo "# Implementation (mock)"
        echo
        echo "task_id: $TASK_ID"
        echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo
        cat "$PROMPT_FILE"
      } > "$OUT"
      commit_if_needed "buildshift(implementer): apply ${TASK_ID}"
      ;;
    reviewer)
      OUT=".buildshift/review.md"
      {
        echo "# Review (mock)"
        echo
        echo "task_id: $TASK_ID"
        echo "verdict: APPROVE"
        echo
        echo "Looks good for smoke purposes."
      } > "$OUT"
      commit_if_needed "buildshift(reviewer): review ${TASK_ID}"
      ;;
    *)
      OUT=".buildshift/mock-result.md"
      {
        echo "# Mock worker result"
        echo "role: $ROLE"
        echo "task_id: $TASK_ID"
        cat "$PROMPT_FILE"
      } > "$OUT"
      commit_if_needed "buildshift(mock): ${ROLE} ${TASK_ID}"
      ;;
  esac
  echo "mock harness committed for role=$ROLE"
}

case "$HARNESS" in
  mock)
    mock_by_role
    ;;
  claude)
    if ! command -v claude >/dev/null 2>&1; then
      echo "claude CLI not installed in worker image" >&2
      exit 4
    fi
    PROMPT="$(cat "$PROMPT_FILE")"
    claude -p "$PROMPT" --output-format text
    if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
      git add -A
      git commit -m "buildshift(claude/${ROLE}): apply task ${TASK_ID}" || true
    fi
    ahead="$(git rev-list --count main..HEAD 2>/dev/null || echo 0)"
    if [[ "$ahead" == "0" ]]; then
      echo "claude harness produced no commits" >&2
      exit 5
    fi
    ;;
  *)
    echo "unknown HARNESS=$HARNESS" >&2
    exit 1
    ;;
esac
