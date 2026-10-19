-- Week 3: control-plane runtime settings (source of truth for operator knobs)

CREATE TABLE IF NOT EXISTS runtime_settings (
    id TEXT PRIMARY KEY DEFAULT 'default',
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO runtime_settings (id, value)
VALUES ('default', '{"version": 1}'::jsonb)
ON CONFLICT (id) DO NOTHING;
