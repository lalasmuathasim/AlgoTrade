ALTER TABLE IF EXISTS paper_trading_settings
    ADD COLUMN IF NOT EXISTS prediction_proximity_percent DOUBLE PRECISION;

UPDATE paper_trading_settings
SET prediction_proximity_percent = COALESCE(prediction_proximity_percent, 2.0);

ALTER TABLE paper_trading_settings
    ALTER COLUMN prediction_proximity_percent SET DEFAULT 2.0,
    ALTER COLUMN prediction_proximity_percent SET NOT NULL;
