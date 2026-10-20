-- Projects (full PRD), sprints, epics

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    prd_markdown TEXT NOT NULL DEFAULT '',
    prd_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sprints (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'capacity_6h',
    status TEXT NOT NULL DEFAULT 'draft',
    capacity_hours NUMERIC(8, 2) NOT NULL DEFAULT 6,
    goals JSONB NOT NULL DEFAULT '[]'::jsonb,
    estimated_spend_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    estimated_hours NUMERIC(8, 2) NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sprints_project ON sprints (project_id);

CREATE TABLE IF NOT EXISTS epics (
    id UUID PRIMARY KEY,
    sprint_id UUID NOT NULL REFERENCES sprints (id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    product_id UUID REFERENCES prd_products (id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_epics_sprint ON epics (sprint_id);
CREATE INDEX IF NOT EXISTS idx_epics_project ON epics (project_id);

ALTER TABLE prd_products ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects (id) ON DELETE CASCADE;

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects (id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sprint_id UUID REFERENCES sprints (id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS epic_id UUID REFERENCES epics (id) ON DELETE SET NULL;

ALTER TABLE human_items ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects (id) ON DELETE SET NULL;
ALTER TABLE human_items ADD COLUMN IF NOT EXISTS sprint_id UUID REFERENCES sprints (id) ON DELETE SET NULL;

ALTER TABLE daily_plans ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects (id) ON DELETE SET NULL;
ALTER TABLE daily_plans ADD COLUMN IF NOT EXISTS sprint_id UUID REFERENCES sprints (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_sprint ON tasks (sprint_id);
CREATE INDEX IF NOT EXISTS idx_human_items_project ON human_items (project_id);
CREATE INDEX IF NOT EXISTS idx_human_items_sprint ON human_items (sprint_id);
CREATE INDEX IF NOT EXISTS idx_prd_products_project ON prd_products (project_id);

-- Backfill: one project per orphaned prd_product
DO $$
DECLARE
    r RECORD;
    pid UUID;
    pslug TEXT;
BEGIN
    FOR r IN SELECT id, slug, title, summary FROM prd_products WHERE project_id IS NULL
    LOOP
        pslug := 'proj-' || r.slug;
        pid := gen_random_uuid();
        INSERT INTO projects (id, slug, title, status, prd_markdown)
        VALUES (pid, pslug, r.title, 'active', COALESCE(r.summary, ''))
        ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title
        RETURNING id INTO pid;

        IF pid IS NULL THEN
            SELECT id INTO pid FROM projects WHERE slug = pslug;
        END IF;

        UPDATE prd_products SET project_id = pid WHERE id = r.id AND project_id IS NULL;
        UPDATE tasks SET project_id = pid WHERE product_id = r.id AND project_id IS NULL;
        UPDATE human_items SET project_id = pid WHERE product_id = r.id AND project_id IS NULL;
        UPDATE daily_plans SET project_id = pid WHERE product_id = r.id AND project_id IS NULL;
    END LOOP;
END $$;
