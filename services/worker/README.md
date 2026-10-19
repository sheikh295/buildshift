# services/worker

On-demand container image for a single Buildshift task.

## Modes

| `HARNESS` | Behavior |
|-----------|----------|
| `mock` | Writes `.buildshift/mock-result.md` and commits (default, no LLM spend) |
| `claude` | Runs Claude Code headless (`claude -p`) via `ANTHROPIC_BASE_URL` (LiteLLM) |

Built by Compose as `buildshift-worker:local`. The orchestrator starts one container per task with the worktree mounted at `/workspace`.
