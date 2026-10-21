#!/usr/bin/env bash
set -euo pipefail

HARNESS="${HARNESS:-mock}"
ROLE="${ROLE:-implementer}"
TASK_ID="${TASK_ID:-unknown}"
PROMPT_FILE="${PROMPT_FILE:-.buildshift/task_prompt.md}"
LITELLM_URL="${LITELLM_URL:-http://litellm:4000}"
LITELLM_API_KEY="${LITELLM_API_KEY:-${ANTHROPIC_API_KEY:-sk-buildshift-local}}"
LITELLM_MODEL="${LITELLM_MODEL:-${ANTHROPIC_MODEL:-${DEFAULT_IMPLEMENTER_MODEL:-minimax-m3.1-flash}}}"
GITHUB_PROXY_PORT="${GITHUB_PROXY_PORT:-18741}"
PROXY_PID=""

cleanup() {
  if [[ -n "${PROXY_PID}" ]] && kill -0 "${PROXY_PID}" 2>/dev/null; then
    kill "${PROXY_PID}" 2>/dev/null || true
    wait "${PROXY_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

git config --global user.email "buildshift-worker@local"
git config --global user.name "Buildshift Worker"
git config --global --add safe.directory "*"

# Never leave credentials in the agent-visible remote URL
if git remote get-url origin >/dev/null 2>&1; then
  ORIGIN="$(git remote get-url origin || true)"
  # strip embedded userinfo if any leaked
  CLEAN_ORIGIN="$(echo "$ORIGIN" | sed -E 's#https://[^@]+@#https://#')"
  git remote set-url origin "$CLEAN_ORIGIN" 2>/dev/null || true
fi

echo "worker cwd=$(pwd) harness=${HARNESS} role=${ROLE} task=${TASK_ID} model=${LITELLM_MODEL} sandbox=/workspace"

if [[ "$(pwd)" != "/workspace" ]]; then
  echo "REFUSING: worker must run with cwd=/workspace (got $(pwd))" >&2
  exit 7
fi

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "missing prompt at $PROMPT_FILE (cwd=$(pwd))" >&2
  ls -la . .buildshift 2>/dev/null || true
  exit 2
fi

if [[ ! -d .git && ! -f .git ]]; then
  echo "not a git checkout at $(pwd)" >&2
  exit 6
fi

start_github_proxy() {
  if [[ -z "${GITHUB_TOKEN:-}" || -z "${ALLOWED_GITHUB_REPO:-}" ]]; then
    echo "github proxy skipped (no GITHUB_TOKEN or ALLOWED_GITHUB_REPO)"
    return 0
  fi
  python3 /usr/local/bin/github_proxy.py &
  PROXY_PID=$!
  # Give it a moment; then scrub token from this shell so opencode/children never see it
  sleep 0.3
  if ! kill -0 "${PROXY_PID}" 2>/dev/null; then
    echo "github proxy failed to start" >&2
    PROXY_PID=""
    unset GITHUB_TOKEN
    return 1
  fi
  unset GITHUB_TOKEN
  export GITHUB_PROXY_PORT
  echo "github proxy up pid=${PROXY_PID} repo=${ALLOWED_GITHUB_REPO} (token scrubbed from env)"
}

commit_if_needed() {
  local msg="$1"
  if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    echo "nothing to commit" >&2
    exit 3
  fi
  git add -A
  git commit -m "$msg"
}

write_owned_paths() {
  local IFS=','
  local wrote=0
  for raw in ${OWNED_PATHS:-}; do
    local p
    p="$(echo "$raw" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$p" ]] && continue
    case "$p" in
      .buildshift|.buildshift/*) continue ;;
    esac
    mkdir -p "$(dirname "$p")"
    {
      echo "# Mock implementation"
      echo "task_id: $TASK_ID"
      echo "owned_path: $p"
      echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$p"
    wrote=1
  done
  return $((1 - wrote))
}

mock_by_role() {
  mkdir -p .buildshift/tasks/"$TASK_ID" tests
  META=".buildshift/tasks/${TASK_ID}"
  case "$ROLE" in
    test_author)
      OUT="tests/test_task_${TASK_ID//-/_}.py"
      {
        echo '"""Auto-generated acceptance test stub (mock harness)."""'
        echo "import unittest"
        echo
        echo
        echo "class AcceptanceStub(unittest.TestCase):"
        echo "    def test_acceptance_placeholder(self):"
        echo "        self.assertTrue(True)  # TODO: real criteria"
      } > "$OUT"
      echo "# tests authored" > "$META/tests.md"
      cat "$PROMPT_FILE" >> "$META/tests.md"
      commit_if_needed "buildshift(test_author): tests for ${TASK_ID}"
      ;;
    implementer)
      OUT="$META/impl.md"
      {
        echo "# Implementation (mock)"
        echo
        echo "task_id: $TASK_ID"
        echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo
        cat "$PROMPT_FILE"
      } > "$OUT"
      write_owned_paths || true
      commit_if_needed "buildshift(implementer): apply ${TASK_ID}"
      ;;
    reviewer)
      OUT="$META/review.md"
      if [[ -f "$OUT" ]] && grep -qi 'verdict:[[:space:]]*APPROVE' "$OUT"; then
        echo "review already APPROVE; skipping recommit"
        exit 0
      fi
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
      OUT="$META/mock-result.md"
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

ensure_commits_ahead() {
  local label="$1"
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    git add -A
    git commit -m "buildshift(${label}/${ROLE}): apply task ${TASK_ID}" || true
  fi
  local ahead
  ahead="$(git rev-list --count main..HEAD 2>/dev/null || echo 0)"
  if [[ "$ahead" == "0" ]]; then
    echo "${label} harness produced no commits" >&2
    exit 5
  fi
}

sandbox_preamble() {
  cat <<'EOF'

## Sandbox rules (mandatory)
- Your only project directory is `/workspace` (this git checkout). Do not read, write, or `cd` outside it.
- Do not explore other repos, `/data`, `/repo`, the host, or sibling checkouts.
- Do not clone, fetch, or push with git (the orchestrator handles remotes).
- Direct `curl`/`wget`/`gh` to GitHub is forbidden. To read this project's private GitHub URLs use:
  `buildshift-fetch 'https://github.com/<owner>/<repo>/...'`
  Only the allowlisted project repo works; the PAT is never available to you.
EOF
}

run_opencode() {
  if ! command -v opencode >/dev/null 2>&1; then
    echo "opencode CLI not installed in worker image" >&2
    exit 4
  fi

  start_github_proxy || true

  local base_url model_id
  base_url="${LITELLM_URL%/}/v1"
  model_id="${LITELLM_MODEL}"

  # Inline config (no secrets file left on disk for the agent to cat).
  # external_directory deny keeps tools inside /workspace.
  # webfetch deny — use buildshift-fetch for private GitHub instead.
  export OPENCODE_CONFIG_CONTENT
  OPENCODE_CONFIG_CONTENT="$(cat <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "buildshift": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Buildshift LiteLLM",
      "options": {
        "baseURL": "${base_url}",
        "apiKey": "${LITELLM_API_KEY}"
      },
      "models": {
        "${model_id}": {
          "name": "${model_id}"
        }
      }
    }
  },
  "permission": {
    "external_directory": "deny",
    "webfetch": "deny",
    "websearch": "deny",
    "shell": {
      "*": "allow",
      "curl *github.com*": "deny",
      "curl *githubusercontent.com*": "deny",
      "wget *github.com*": "deny",
      "wget *githubusercontent.com*": "deny",
      "gh *": "deny",
      "git clone *": "deny",
      "git fetch *": "deny",
      "git pull *": "deny",
      "git push *": "deny"
    }
  }
}
EOF
)"
  export OPENCODE_DISABLE_AUTOUPDATE=true
  # Scrub LiteLLM key from env; it lives only inside OPENCODE_CONFIG_CONTENT for the CLI
  unset LITELLM_API_KEY ANTHROPIC_API_KEY || true

  echo "opencode model=buildshift/${model_id} baseURL=${base_url} cwd=/workspace"

  local prompt
  prompt="$(cat "$PROMPT_FILE")$(sandbox_preamble)"
  opencode run --auto --model "buildshift/${model_id}" "$prompt"

  ensure_commits_ahead "opencode"
}

run_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude CLI not installed in worker image" >&2
    exit 4
  fi
  start_github_proxy || true
  unset GITHUB_TOKEN || true
  local prompt
  prompt="$(cat "$PROMPT_FILE")$(sandbox_preamble)"
  claude -p "$prompt" --output-format text
  ensure_commits_ahead "claude"
}

case "$HARNESS" in
  mock)
    mock_by_role
    ;;
  opencode)
    run_opencode
    ;;
  claude)
    run_claude
    ;;
  *)
    echo "unknown HARNESS=$HARNESS (expected mock|opencode|claude)" >&2
    exit 1
    ;;
esac
