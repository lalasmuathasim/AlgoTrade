ALTER TABLE trigger_lines
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archive_reason VARCHAR(40);

ALTER TABLE paper_trading_settings
    ADD COLUMN IF NOT EXISTS daily_structure_rebuild_enabled BOOLEAN,
    ADD COLUMN IF NOT EXISTS daily_structure_rebuild_time VARCHAR(10);

UPDATE paper_trading_settings
SET daily_structure_rebuild_enabled = COALESCE(daily_structure_rebuild_enabled, TRUE),
    daily_structure_rebuild_time = COALESCE(NULLIF(TRIM(daily_structure_rebuild_time), ''), '15:45');

ALTER TABLE paper_trading_settings
    ALTER COLUMN daily_structure_rebuild_enabled SET DEFAULT TRUE,
    ALTER COLUMN daily_structure_rebuild_enabled SET NOT NULL,
    ALTER COLUMN daily_structure_rebuild_time SET DEFAULT '15:45',
    ALTER COLUMN daily_structure_rebuild_time SET NOT NULL;
