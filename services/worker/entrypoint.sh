#!/usr/bin/env bash
set -euo pipefail

HARNESS="${HARNESS:-mock}"
TASK_ID="${TASK_ID:-unknown}"
PROMPT_FILE="${PROMPT_FILE:-.buildshift/task_prompt.md}"

git config --global user.email "buildshift-worker@local"
git config --global user.name "Buildshift Worker"
# Orchestrator creates worktrees as root; worker runs as uid 10001
git config --global --add safe.directory "*"

echo "worker cwd=$(pwd) harness=${HARNESS} task=${TASK_ID}"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "missing prompt at $PROMPT_FILE (cwd=$(pwd))" >&2
  ls -la . .buildshift 2>/dev/null || true
  exit 2
fi

if [[ ! -d .git && ! -f .git ]]; then
  echo "not a git worktree at $(pwd)" >&2
  exit 6
fi

case "$HARNESS" in
  mock)
    mkdir -p .buildshift
    OUT=".buildshift/mock-result.md"
    {
      echo "# Mock worker result"
      echo
      echo "task_id: $TASK_ID"
      echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo
      echo "## Prompt"
      echo
      cat "$PROMPT_FILE"
    } > "$OUT"
    git add "$OUT"
    if git diff --cached --quiet; then
      echo "nothing to commit" >&2
      exit 3
    fi
    git commit -m "buildshift(mock): apply task ${TASK_ID}"
    echo "mock harness committed $OUT"
    ;;
  claude)
    if ! command -v claude >/dev/null 2>&1; then
      echo "claude CLI not installed in worker image" >&2
      exit 4
    fi
    # Headless print mode; Anthropic-compatible gateway via ANTHROPIC_BASE_URL
    PROMPT="$(cat "$PROMPT_FILE")"
    claude -p "$PROMPT" --output-format text
    # If the harness left changes unstaged, commit them
    if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
      git add -A
      git commit -m "buildshift(claude): apply task ${TASK_ID}" || true
    fi
    if git rev-list --count HEAD ^origin/main 2>/dev/null | grep -q '^0$'; then
      # also try against main without origin
      if git merge-base --is-ancestor HEAD main 2>/dev/null; then
        ahead="$(git rev-list --count main..HEAD 2>/dev/null || echo 0)"
        if [[ "$ahead" == "0" ]]; then
          echo "claude harness produced no commits" >&2
          exit 5
        fi
      fi
    fi
    ;;
  *)
    echo "unknown HARNESS=$HARNESS" >&2
    exit 1
    ;;
esac
