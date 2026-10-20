# AI Software House: Solution Design

**Version:** 1.1 (October 19, 2026)
**Owner:** Mamoor
**Purpose:** An orchestration layer that turns one large PRD into a production-grade web product, with agents working in shifts and a human steering, monitoring and handling what only a human can.

---

## 1. Summary

You provide one big PRD. The system plans it in waves (index the PRD once, kick off each product, plan each shift fresh every morning), builds it through parallel agent workers, verifies every change with independent tests and reviews, and lands work as pull requests. You review at end of day (EOD), unblock what needs a human (keys, accounts, store publishing), and steer by priorities and comments, not by instructions on every task.

Core idea: **a pipeline with verification, not a role-play simulation.** Agents are workers with isolated workspaces. Quality comes from clear specs, independent tests, cross-model review, deterministic checks and a disciplined merge queue. Cost stays controlled through tiered model routing, caching, batching and hard budgets.

## 2. Assumptions

1. The goal is shipping production web apps with minimal human typing. You are the only human, reviewing at EOD.
2. It is for your own products or client work through your agency, so cost per merged feature and reliability matter more than demo appeal.
3. The stack is chosen purely on fit, not on any language preference.
4. Autonomy is bounded: you approve the spec, handle secrets, billing and publishing, and merge. Agents never touch `main`.
5. You want to watch the system work and steer it, not only receive PRs the next morning.
6. Budget is real. No frontier models by default.
7. It starts as a single-user tool. Multi-tenant or sellable-as-a-product is a later decision.
8. Target: the build engine works end to end by about day 16 and is reliable on a defined class of tasks by about day 23 (the planning model adds about 2 days). Building the products themselves takes however long they take.
9. The PRD is effectively 8 to 9 products in one, so it cannot be planned in a single pass. Planning is rolling: index the PRD once, kick off each product, plan each day.

## 3. Requirements

**Functional**
- Ingest one large PRD (several products in one) and plan it in waves: index it once, kick off each product, and plan each shift fresh every morning, with traceability from requirements to tests.
- Run 6 to 8 hour shifts daily; resume next day from durable state.
- Parallel workers writing code, tests and reviews.
- Review loops for UI/UX, business logic, tests, bugs, security, frontend, and responsive behavior, including vision-based review and browser automation.
- Human-in-the-loop (HITL) queue for keys, accounts, publishing and irreversible actions.
- EOD digest and a live view of what is happening.
- Agents must work with current (2026) documentation and can search the web or browse when needed.

**Non-functional**
- Production-grade output: tests, CI, security checks, reviewable PRs.
- Cost control: per-task and daily caps, tiered model routing.
- Safety: sandboxed execution, scoped credentials, protected `main`.
- Recoverability: crash-safe state, resumable runs.

## 4. Design principles

1. **Git is the memory.** Source of truth for code, specs (`AGENTS.md`, ADRs), and task history.
2. **Short, fresh sessions.** A shift is a scheduler window. Each task is its own session with state in Postgres and git. Long sessions degrade and waste tokens.
3. **Deterministic checks before LLM checks.** Lint, types, tests, scanners first. Model review second.
4. **Independent verification.** Test author is separate from implementer. Reviewer is a different model family from the coder.
5. **Mechanical escalation.** Retry and escalation are rules in the orchestrator, not a model's opinion.
6. **Never block on a human.** Build against interfaces and fakes while real keys and accounts are pending.
7. **Measure cost per merged PR**, not price per token.
8. **Plan in waves, not all at once.** Index the PRD once, kick off one product at a time, and plan each day fresh from the PRD slice plus current state. The backlog and decision records persist, so fresh planning never means starting over.

## 5. Architecture

```
You (PRD · approvals · HITL · EOD review · merge)
        │
        ▼
Dashboard (Next.js, live via SSE)
        │
        ▼
Orchestrator (Python / FastAPI)
  ├─ Planner            PRD index → product kickoff → daily plan (tasks as JSON)
  ├─ Scheduler          shifts, dependency order, path-ownership locks
  ├─ Runner             worktree + container per task, starts workers
  ├─ Router             role/tier → model, escalation, budgets
  ├─ Integrator         merge queue: rebase → CI → PR
  ├─ Event log          every action, cost and state change
  └─ HITL manager       needs_human items, replies, secret injection
        │
        ▼
Postgres (state, queue, events)      Git remote (code, specs, history)
        │
        ▼
Worker containers (rootless Docker, one per task)
  coding harness (Claude Code headless, OpenCode as fallback)
  Playwright / Chromium · test runners · docs lookup tool
        │
        ▼
LLM gateway (LiteLLM or similar) → providers per tier
```

## 6. Technology choices

| Layer | Choice | Why |
|---|---|---|
| Orchestrator | Python + FastAPI | Best ecosystem for process supervision, Docker control, agent tooling |
| State and queue | Postgres only (`SELECT ... FOR UPDATE SKIP LOCKED`) | Enough for this scale; no Redis or Temporal to operate |
| Workers | Claude Code headless (`claude -p`) in rootless Docker, one git worktree per task | Mature coding loop; do not rebuild it |
| Fallback harness | OpenCode behind the same adapter | Provider-agnostic option |
| Model access | LLM gateway (LiteLLM or similar) | One place for routing, budgets, spend tracking, provider switching |
| Dashboard | Next.js + SSE | Best fit for live logs and boards |
| Browser automation | Playwright | Deterministic, cheap; vision model only for judgment |
| Network | Tailscale/WireGuard between you and the box | Smaller attack surface than a public endpoint |
| Host | One dedicated box to start (e.g., 32 GB RAM class) | LLMs are API-based; CPU/RAM is for builds, browsers and containers |

LangGraph is not used in v1. The hard parts here are job scheduling, retries, budgets, worktrees, path locks and merges, which a Postgres state machine handles directly. It can wrap the planner later if that grows into a multi-step loop.

## 7. Task lifecycle

States: `planned → ready → test_authoring → coding → testing → reviewing → integrating → merged`
Side states: `blocked_human`, `parked`, `failed`.

Rules:
- A task becomes `ready` when its dependencies are merged and its owned paths are free.
- The test author writes tests from the acceptance criteria **before** the implementer starts.
- The implementer works in its own worktree and branch inside a container.
- Retry limit: 2 attempts per tier, then one escalation to the next tier, then `parked` with a flag for you.
- Each task has a token/spend budget. Exceeding it parks the task.
- `blocked_human` is set when a worker reports it needs a key, account, decision or action only a human can do.

## 8. PRD indexing and rolling-wave planning

The PRD is effectively 8 to 9 products in one, so it is not planned in a single pass. It is uploaded once and indexed, each product gets a kickoff when you start it, and every shift is planned fresh each morning against the PRD slice and current state. Fresh daily planning is not planning from scratch: the backlog and decisions persist.

**Level 1: one-time PRD indexing (no planning).** The system splits the PRD into products, modules and numbered requirements, stored in the repo under `docs/prd/`. It records cross-product dependencies and proposes a build order, with shared platform pieces (identity, data model, design system, CI) first. It decides no tickets. You review the split and the order once. A short global clarification pass covers only cross-product conflicts and shared decisions.

**Level 2: per-product kickoff.** When you start a product, the planner reads only that slice, asks its clarifying questions in one batch, and writes the architecture decision records (ADRs) and the product's milestones. Answers are saved under `docs/decisions/`.

**Level 3: daily morning planning.** At shift start the planner reads the relevant PRD slice and current state: what is merged, parked or blocked, yesterday's EOD digest, the human-dependency manifest, remaining budget and your steering notes. It proposes today's goals, tickets, acceptance criteria (with owned paths and difficulty tags) and estimated spend. You iterate with it for 5 to 10 minutes, approve, and the shift starts.

**Guardrails that keep daily planning consistent**

1. **Persistent backlog.** Each morning's planner picks from the backlog and adds to it instead of regenerating it.
2. **Decision records.** Decisions live in the repo. The planner must flag any change to a merged contract instead of silently making it.
3. **Plan diffs.** Changes to a plan are shown as diffs, not rewrites.
4. **Traceability matrix.** Every PRD requirement maps to tasks, tests and PRs, so the planner knows what is actually done instead of relying on memory. A requirement with no passing test is visibly "not done".
5. **Approval gate.** No worker starts on a day's plan until you approve it.
6. **Re-planning.** When you steer (priorities file or task comment), the planner re-plans at the next task boundary and records why.

## 9. Human-in-the-loop

**Human-dependency manifest.** Each product kickoff adds to a list of everything only you can do, with when it will be needed, and the morning plan keeps it current:
- API keys and secrets
- Accounts (third-party services, cloud, payment providers)
- DNS, certificates, domains
- App store and platform publishing
- Billing and irreversible migrations
- Ambiguous product decisions

**Working around pending items.** Agents build against interfaces and fakes or sandbox providers, so work continues. You clear the manifest in batches and the real credentials are swapped in.

**Runtime flow.** A worker raises `needs_human`; the task enters `blocked_human`; the dashboard HITL inbox shows the question; your reply is injected into the next run. Secrets are stored outside the repo and injected through a credential proxy or per-task scoped keys. Workers never see long-lived real secrets.

**Always human-gated:** production deploys, billing, DNS/certs, store publishing, irreversible data migrations, merges touching auth/payments/data-access paths.

## 10. Model strategy and routing

Prices below are per million input/output tokens as reported in October 2026. Verify against official pricing before budgeting. Benchmark figures are vendor- or aggregator-reported; your own task bake-off is the deciding evidence.

**Tiers**

| Tier | Use | Candidates |
|---|---|---|
| T0 Mechanical | Triage, summaries, log compression, commit messages, digest drafts | Claude Haiku 5.5 (about $0.10/$0.50 for prompts up to 100K tokens, higher above), Flash-class models |
| T1 Default coder | Everyday implementation | Open-weight coders: Kimi K2.6, GLM-5.1, MiniMax M3, DeepSeek V4-Pro/Flash. Choose by bake-off |
| T2 Escalation / reviewer / indexer | Failed tasks, cross-model review, business-logic review, PRD indexing | Claude Sonnet 5.5 (about $2/$10) |
| T3 Planner / hard | Product kickoff and daily planning, architecture, hard tasks, security-sensitive review | Claude Opus 5.5 (about $4/$20); Fable 5.1 (about $10/$50) only on explicit "hard" tags |
| Vision | UI and responsive review on Playwright screenshots | Gemini Flash-class model; escalate ambiguous screens to Sonnet 5.5 |

Reported reference points: Kimi K2.6 about 58.6% on SWE-Bench Pro with stronger stability over long sessions; GLM-5.1 about 58.4% and strong on front-end; MiniMax M3 about 59.0% on SWE-Bench Pro at roughly $0.30/$1.20; DeepSeek V4-Pro about 55.4% versus Opus 4.7 at 64.3%, a gap that matters on hard agentic work.

**Routing rules**
1. The planner tags tasks easy/normal/hard. Role plus tag sets the starting tier.
2. Escalation is mechanical: two failures at a tier, one step up, then park.
3. The reviewer is always a different model family from the coder.
4. Security-sensitive paths always get T2/T3 review plus your sign-off.
5. Vision runs only on UI-affecting PRs.

**Cost levers**
- Track **cost per merged PR**. Effort setting moves the bill more than per-token price; tune effort per role.
- Prompt caching: keep `AGENTS.md`, repo map and specs stable at the top of prompts (Sonnet 5.5 cache reads reported at $0.10/M after October 7).
- Batch API for non-urgent work (reported 50% discount), e.g., overnight whole-repo reviews.
- Small tasks, fresh sessions, per-task budgets, daily cap, global kill switch.
- Deterministic checks before any LLM review.

**Using non-Claude models in Claude Code.** Claude Code talks to any endpoint speaking the Anthropic Messages API via `ANTHROPIC_BASE_URL`. DeepSeek exposes an Anthropic-compatible endpoint; gateways like LiteLLM and agentgateway translate for others. Caveats: this is not the officially tuned path for non-Claude models, tool-use quality can drop, and model-name handling differs by Claude Code version (some guides report an allowlist forcing alias mapping). Verify which route lets you select the exact model you want on day 2. If an open-weight model is the default coder, also test OpenCode as the harness.

**Data location.** Hosted DeepSeek and other third-party APIs receive repo context. Check client contract and data obligations before using them on client code. Open weights (MIT for DeepSeek V4) allow third-party hosting in a region you choose.

**Example router config**

```yaml
roles:
  prd_indexer:   { tier: T2, model: claude-sonnet-5-5 }
  planner:       { tier: T3, model: claude-opus-5-5, effort: high }   # kickoff + daily plan
  test_author:   { tier: T1, model: <bake-off winner> }
  implementer:   { tier: T1, model: <bake-off winner>, escalate_to: T2 }
  reviewer:      { tier: T2, model: claude-sonnet-5-5, family_differs_from: implementer }
  ui_reviewer:   { tier: V,  model: <gemini-flash-class>, escalate_to: claude-sonnet-5-5 }
  security:      { tier: T3, model: claude-opus-5-5, plus: [semgrep, gitleaks, dep-audit] }
  triage:        { tier: T0, model: claude-haiku-5-5 }
limits:
  task_budget_usd: 3.00
  daily_budget_usd: 60.00
  max_attempts_per_tier: 2
  max_parallel_workers: 4
```

(Values are placeholders; set them from baseline measurements.)

## 11. Quality gates

| Gate | How |
|---|---|
| Lint, types, unit | CI on every PR plus local runs by the worker |
| Test authoring | Separate session writes tests from acceptance criteria before implementation |
| E2E | Playwright against a preview environment |
| Business logic | Reviewer (T2) checks the diff against the spec and traceability matrix |
| UI/UX and responsive | Playwright screenshots at 3 breakpoints reviewed by a vision model, plus deterministic checks (overflow, a11y audit) |
| Bugs | Failing-test-first bug workflow: reproduce, fix, re-run |
| Security | Scanners (semgrep, gitleaks, dependency audit) then T2/T3 review; human sign-off on sensitive paths |
| Integration | Merge queue rebases and reruns CI before a PR is marked ready |

A PR is "ready for you" only when every gate is green.

## 12. Documentation freshness

- Do not trust model memory for library APIs.
- Give workers a docs-lookup tool (a Context7-style docs server or `llms.txt` fetch), web search and a browser.
- Pin dependency versions in the repo. Require a doc check before using any API not already in the codebase.
- Record in ADRs which doc version a decision relied on.
- Allowlist the web egress used for docs.

## 13. Isolation and security

- Rootless containers, non-root user, one per task.
- Git token scoped to branch pushes; `main` protected; no force-push.
- Egress allowlist proxy that also injects credentials.
- Secrets never in git or worker environments.
- Prompt-injection posture: web content and fetched docs are untrusted data; tools that can exfiltrate are restricted; no secrets reachable from workers.
- Backups of Postgres and the git remote; crash recovery resumes unfinished tasks on restart.

## 14. Control UI and EOD standup

Dashboard (Next.js, SSE):
- Task board by state, with owner worker, tier, spend and attempts.
- Live log stream per task.
- HITL inbox and the human-dependency manifest.
- Spend: per task, per role, per day, versus budget.
- Traceability view: PRD requirement → tasks → tests → PRs.
- **EOD digest** generated from the event log: merged, in review, blocked on you, parked, spend, top risks, proposed plan for tomorrow.
- **Morning planning screen:** the planner's proposed goals, tickets, acceptance criteria and estimated spend for the day, shown as a diff against the backlog. You edit, discuss with the planner and approve here before the shift starts.
- Steering: priorities file and task comments; changes take effect at the next task boundary.
- Optional later: a visual "office" view driven by the same event stream.

## 15. Build plan (about 23 days)

**Phase 1: one task, end to end**
- Days 1-2: provision box, build worker image, choose proving repo, run a 10-task bake-off across candidate harnesses and models. Exit: harness and default-model choice, measured cost per task.
- Days 3-5: orchestrator skeleton (Postgres schema, state machine, runner: worktree → container → run → push → PR), per-task caps, kill switch. Exit: a CLI task produces a green PR.
- Days 6-7: integrator v0 (rebase, rerun CI, route failures back with retry cap). Exit: 10 sequential tasks with a measured success rate.

**Phase 2: the real pipeline**
- Days 8-10: PRD indexer, per-product kickoff and the daily planning flow (CLI and markdown first): persistent backlog, plan diffs, approval gate, human-dependency manifest. Exit: an indexed PRD and an approved day plan for one product.
- Days 11-12: test-author split, cross-model reviewer, retry loops.
- Days 13-16: parallel workers with path locks and merge queue. Exit: a real feature of about 12 tasks lands with you only approving the plan and merging.

**Phase 3: trustworthy**
- Days 17-18: dashboard (including the morning-planning screen), HITL inbox, EOD digest.
- Days 19-20: hardening (egress proxy, scoped tokens, protected main, spend caps, stuck-task detection, crash recovery, backups).
- Days 21-23: burn-in on a stretch of real work; tune `AGENTS.md` and prompts; fix top failure classes.

Rolling-wave planning adds about 2 days over the original schedule (about 23 days in total). To stay at 21, defer dashboard polish until after burn-in; the planning flow works from the CLI first.

**Deferred:** office visualization, multi-project support, per-PR preview deploys (if not needed earlier), auth beyond Tailscale.

**What decides the schedule**
- Test coverage and CI quality in the proving repo (weak tests mean building a safety net first).
- Day-2 bake-off outcome (a harness needing heavy wrapping stretches Phase 1).

## 16. Success metrics

Targets to calibrate after Phase 1:
- CI first-pass rate of 80% or higher.
- 60% or more of PRs merged without your edits.
- Cost per merged PR tracked daily and trending down.
- Parked-task rate and time-to-unblock for human items.
- Share of PRD requirements with passing tests (traceability coverage).

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ambiguous PRD causes silent drift | Global clarification pass, per-product kickoff questions, traceability matrix, daily plan approval |
| Daily replanning drifts or re-litigates earlier decisions | Persistent backlog, decision records in the repo, contract-change flags, plan diffs |
| Merge conflicts across parallel workers | Path ownership locks, dependency-ordered scheduling, merge queue |
| Runaway spend | Per-task/daily caps, mechanical escalation, parked state, kill switch |
| Non-Claude model underperforms in the harness | Day-2 bake-off, fallback harness, escalation tier |
| Prompt injection / secret exfiltration | Isolation, credential proxy, egress allowlist, untrusted-content rules |
| Stale library knowledge | Docs lookup tool, version pinning, doc-check rule |
| Weak test base in target repo | Add safety-net work first; test-author runs before implementer |
| Third-party API data exposure | Check contracts; use third-party hosting of open weights where needed |

## 18. Open questions

1. Which repo is the proving ground, and how strong are its tests and CI?
2. Is the box already provisioned?
3. Any constraints on where client code may be sent (affects hosted DeepSeek vs third-party hosts)?
4. Daily budget target to set initial caps?
5. Which platforms need publishing (affects the human-dependency manifest)?
6. What build order do you want across the 8 to 9 products, and which shared platform pieces (identity, data model, design system) come first?
7. In what format will the PRD be uploaded, and can it be split into product files now?

## Appendix A: Data model sketch

- `prd_products`, `prd_requirements` (the indexed PRD), `projects`, `milestones`, `epics`
- `backlog`, `daily_plans` (plan diffs, approvals), `decisions`
- `tasks`: id, epic, state, tier, difficulty, deps[], owned_paths[], acceptance_criteria, budget_usd, spent_usd, attempts, branch, pr_url
- `runs`: task_id, role, model, tokens_in/out, cost, status, started/ended, logs_url
- `events`: ts, task_id, role, kind, payload (drives dashboard and digest)
- `human_items`: id, task_id, kind (key/account/decision/publish), needed_by, status, reply
- `reviews`: task_id, reviewer_model, findings[], severity, resolved
- `requirements` and `req_trace`: PRD requirement → task → test → PR

## Appendix B: Event contract

```json
{
  "ts": "...",
  "task_id": "...",
  "role": "implementer",
  "model": "...",
  "tier": "T1",
  "status": "running | blocked | failed | done",
  "summary": "...",
  "cost_usd": 0.0
}
```

## Appendix C: Sources (October 2026)

- Claude Code LLM gateway docs: https://docs.anthropic.com/en/docs/claude-code/llm-gateway
- Claude Haiku 5.5 launch and pricing: https://vpsranking.com/news/ai/ai-2026-10-07-anthropic-haiku-5-5/
- Claude Sonnet 5.5 pricing: https://apidog.com/blog/claude-sonnet-5-5-pricing/
- Claude API pricing guide: https://claudecoworkcourse.com/ai-api-pricing/claude
- DeepSeek V4 in Claude Code: https://www.verdent.ai/guides/deepseek-v4-in-claude-code
- DeepSeek V4 benchmarks: https://letsdatascience.com/blog/deepseek-v4-matches-frontier-models-fraction-cost
- Open-weight coding model comparison: https://www.atlascloud.ai/hi/blog/guides/kimi-k2-6-vs-glm-5-1-vs-qwen-3-6-plus-vs-minimax-m2-7-coding-2026
- Best open-source models, July 2026: https://www.buildfastwithai.com/blogs/best-open-source-ai-models-2026
- Cheapest LLMs for vision: https://www.swfte.com/cheapest/vision
- TrueForge: https://github.com/truefoundry/trueforge
- MetaGPT: https://github.com/FoundationAgents/MetaGPT
