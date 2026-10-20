-- Per-project git repository (local mirror under DATA_DIR/repos/{slug})
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_url TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_branch TEXT NOT NULL DEFAULT 'main';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_path TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_synced_at TIMESTAMPTZ;
