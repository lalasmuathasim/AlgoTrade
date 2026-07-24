ALTER TABLE IF EXISTS paper_trading_settings
    ADD COLUMN IF NOT EXISTS enable_breakout_quality BOOLEAN,
    ADD COLUMN IF NOT EXISTS minimum_close_position_percent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS minimum_candle_body_percent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS maximum_rejection_wick_percent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS minimum_close_beyond_level_ticks DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS require_volume_confirmation BOOLEAN;

UPDATE paper_trading_settings
SET
    enable_breakout_quality = COALESCE(enable_breakout_quality, TRUE),
    minimum_close_position_percent = COALESCE(minimum_close_position_percent, 80.0),
    minimum_candle_body_percent = COALESCE(minimum_candle_body_percent, 60.0),
    maximum_rejection_wick_percent = COALESCE(maximum_rejection_wick_percent, 20.0),
    minimum_close_beyond_level_ticks = COALESCE(minimum_close_beyond_level_ticks, 2.0),
    require_volume_confirmation = COALESCE(require_volume_confirmation, TRUE);

ALTER TABLE paper_trading_settings
    ALTER COLUMN enable_breakout_quality SET DEFAULT TRUE,
    ALTER COLUMN enable_breakout_quality SET NOT NULL,
    ALTER COLUMN minimum_close_position_percent SET DEFAULT 80.0,
    ALTER COLUMN minimum_close_position_percent SET NOT NULL,
    ALTER COLUMN minimum_candle_body_percent SET DEFAULT 60.0,
    ALTER COLUMN minimum_candle_body_percent SET NOT NULL,
    ALTER COLUMN maximum_rejection_wick_percent SET DEFAULT 20.0,
    ALTER COLUMN maximum_rejection_wick_percent SET NOT NULL,
    ALTER COLUMN minimum_close_beyond_level_ticks SET DEFAULT 2.0,
    ALTER COLUMN minimum_close_beyond_level_ticks SET NOT NULL,
    ALTER COLUMN require_volume_confirmation SET DEFAULT TRUE,
    ALTER COLUMN require_volume_confirmation SET NOT NULL;
