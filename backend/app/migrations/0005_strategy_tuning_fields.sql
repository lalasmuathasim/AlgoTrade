ALTER TABLE IF EXISTS paper_trading_settings
    ADD COLUMN IF NOT EXISTS daily_candle_lookback INTEGER,
    ADD COLUMN IF NOT EXISTS swing_window INTEGER,
    ADD COLUMN IF NOT EXISTS max_gap_percent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS min_swing_distance INTEGER;

UPDATE paper_trading_settings
SET
    daily_candle_lookback = COALESCE(daily_candle_lookback, 100),
    swing_window = COALESCE(swing_window, 2),
    max_gap_percent = COALESCE(max_gap_percent, 0.5),
    min_swing_distance = COALESCE(min_swing_distance, 1);

ALTER TABLE paper_trading_settings
    ALTER COLUMN daily_candle_lookback SET NOT NULL,
    ALTER COLUMN swing_window SET NOT NULL,
    ALTER COLUMN max_gap_percent SET NOT NULL,
    ALTER COLUMN min_swing_distance SET NOT NULL;
