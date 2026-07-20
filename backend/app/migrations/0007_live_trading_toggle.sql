ALTER TABLE IF EXISTS paper_trading_settings
    ADD COLUMN IF NOT EXISTS live_trading_enabled BOOLEAN;

UPDATE paper_trading_settings
SET live_trading_enabled = COALESCE(live_trading_enabled, FALSE);

ALTER TABLE paper_trading_settings
    ALTER COLUMN live_trading_enabled SET DEFAULT FALSE,
    ALTER COLUMN live_trading_enabled SET NOT NULL;
