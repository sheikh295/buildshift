-- Week 2: PRD, planning, path locks, task extensions

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS product_id UUID;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS plan_id UUID;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_epic TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS req_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'implementer';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS review_verdict TEXT;

CREATE TABLE IF NOT EXISTS prd_products (
    id UUID PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    build_order INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'indexed',
    source_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prd_requirements (
    id UUID PRIMARY KEY,
    product_id UUID NOT NULL REFERENCES prd_products (id) ON DELETE CASCADE,
    req_key TEXT NOT NULL,
    text TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    traced BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, req_key)
);

CREATE INDEX IF NOT EXISTS idx_prd_requirements_product ON prd_requirements (product_id);

CREATE TABLE IF NOT EXISTS backlog_items (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES prd_products (id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL DEFAULT '',
    owned_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    difficulty TEXT NOT NULL DEFAULT 'normal',
    estimated_spend_usd NUMERIC(12, 4) NOT NULL DEFAULT 1.0,
    req_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_plans (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES prd_products (id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    goals JSONB NOT NULL DEFAULT '[]'::jsonb,
    tickets JSONB NOT NULL DEFAULT '[]'::jsonb,
    diff JSONB NOT NULL DEFAULT '{}'::jsonb,
    estimated_spend_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES prd_products (id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    adr_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, key)
);

CREATE TABLE IF NOT EXISTS human_items (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES prd_products (id) ON DELETE SET NULL,
    task_id UUID REFERENCES tasks (id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    needed_by TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    reply TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS path_locks (
    id UUID PRIMARY KEY,
    path_glob TEXT NOT NULL,
    task_id UUID NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    held_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (path_glob)
);

CREATE INDEX IF NOT EXISTS idx_path_locks_task ON path_locks (task_id);
CREATE INDEX IF NOT EXISTS idx_daily_plans_status ON daily_plans (status);
CREATE INDEX IF NOT EXISTS idx_backlog_status ON backlog_items (status);
