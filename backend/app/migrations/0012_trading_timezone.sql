ALTER TABLE paper_trading_settings
    ADD COLUMN IF NOT EXISTS trading_timezone VARCHAR(64);

UPDATE paper_trading_settings
SET trading_timezone = COALESCE(NULLIF(TRIM(trading_timezone), ''), 'Asia/Kolkata');

ALTER TABLE paper_trading_settings
    ALTER COLUMN trading_timezone SET DEFAULT 'Asia/Kolkata',
    ALTER COLUMN trading_timezone SET NOT NULL;
