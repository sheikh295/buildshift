# services/worker

On-demand container image for a single Buildshift task.

## Modes

| `HARNESS` | Behavior |
|-----------|----------|
| `mock` | Writes fixtures and commits (default for smoke, no LLM spend) |
| `opencode` | Runs [OpenCode](https://opencode.ai) headless (`opencode run --auto`) via LiteLLM OpenAI-compatible API — use with Control role→model aliases (Vercel, etc.) |
| `claude` | Runs Claude Code headless (`claude -p`) via `ANTHROPIC_BASE_URL` (LiteLLM) — use with Anthropic / Anthropic-compatible models |

Built by Compose as `buildshift-worker:local`. The orchestrator starts one container per task with **only that task’s checkout** bind-mounted at `/workspace` (never the whole `data/` tree or the Buildshift monorepo).

Passes:

- `HARNESS` from Control
- `LITELLM_MODEL` / `ANTHROPIC_MODEL` = Control `role_model(role)`
- `LITELLM_URL` + `LITELLM_API_KEY` (scrubbed from the shell before OpenCode starts; key lives in OpenCode config content)
- `GITHUB_TOKEN` + `ALLOWED_GITHUB_REPO` only long enough to start a localhost GitHub fetch proxy; the token is then unset. Agents use `buildshift-fetch <url>` (allowlisted repo only) — they never see the PAT.
- OpenCode permissions deny `external_directory`, direct `webfetch`, and `git clone/fetch/push` / raw GitHub `curl`.

OpenCode is always installed. Claude Code requires `INSTALL_CLAUDE=true` at image build time.
