-- Buildshift core schema (Week 1 subset)

CREATE TABLE IF NOT EXISTS control (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO control (key, value)
VALUES ('kill_switch', '{"enabled": false}'::jsonb)
ON CONFLICT (key) DO NOTHING;

INSERT INTO control (key, value)
VALUES ('daily_spend', '{"usd": 0, "day": null}'::jsonb)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'T1',
    difficulty TEXT NOT NULL DEFAULT 'normal',
    role TEXT NOT NULL DEFAULT 'implementer',
    acceptance_criteria TEXT NOT NULL DEFAULT '',
    owned_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    deps JSONB NOT NULL DEFAULT '[]'::jsonb,
    budget_usd NUMERIC(12, 4) NOT NULL DEFAULT 3.0,
    spent_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    branch TEXT,
    pr_url TEXT,
    worktree_path TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks (state);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at);

CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    model TEXT,
    harness TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    logs TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runs_task ON runs (task_id);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    task_id UUID REFERENCES tasks (id) ON DELETE SET NULL,
    role TEXT,
    model TEXT,
    tier TEXT,
    kind TEXT NOT NULL,
    status TEXT,
    summary TEXT,
    cost_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_events_task ON events (task_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
