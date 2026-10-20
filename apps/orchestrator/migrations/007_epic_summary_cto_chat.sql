-- Epic description + CEO↔CTO chat history
ALTER TABLE epics ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS cto_chat_messages (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    cost_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cto_chat_project_created
    ON cto_chat_messages (project_id, created_at);
