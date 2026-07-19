CREATE TABLE IF NOT EXISTS zerodha_sessions (
    id UUID PRIMARY KEY,
    connected_by_user_id UUID REFERENCES users(id),
    access_token TEXT NOT NULL,
    login_time TIMESTAMPTZ NULL,
    access_token_expires_at TIMESTAMPTZ NULL,
    profile_user_id VARCHAR(64) NULL,
    profile_user_name VARCHAR(255) NULL,
    profile_email VARCHAR(255) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'CONNECTED',
    last_validated_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
