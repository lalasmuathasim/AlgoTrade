CREATE TABLE IF NOT EXISTS service_runtime_state (
    service_name VARCHAR(64) PRIMARY KEY,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
