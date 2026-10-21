-- CTO living project context + index status for LLM PRD indexing
ALTER TABLE projects ADD COLUMN IF NOT EXISTS context_markdown TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS index_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS index_error TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ;
