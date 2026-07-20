ALTER TABLE breakout_events
ADD COLUMN IF NOT EXISTS required_volume_multiplier DOUBLE PRECISION;

ALTER TABLE breakout_events
ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(50);
