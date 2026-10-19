# packages/

Shared libraries for Buildshift apps.

Keep this directory empty of code until a second consumer needs the same module. Prefer copying once over a premature package; extract here when duplication is real.

Suggested future packages (not created yet):

- `packages/events` — event envelope types shared by orchestrator and dashboard
- `packages/schemas` — task/plan JSON schemas
