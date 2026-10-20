-- Sprint pause notes on tasks
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pause_notes TEXT;
