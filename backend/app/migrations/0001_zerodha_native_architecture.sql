CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'USER',
    approval_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    two_factor_secret VARCHAR(64),
    approved_at TIMESTAMPTZ,
    approved_by_user_id UUID,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlists (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    description TEXT,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS instruments (
    id UUID PRIMARY KEY,
    instrument_token BIGINT NOT NULL UNIQUE,
    exchange_token VARCHAR(50),
    tradingsymbol VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    segment VARCHAR(50),
    instrument_type VARCHAR(50),
    tick_size DOUBLE PRECISION,
    lot_size INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scan_executions (
    id UUID PRIMARY KEY,
    scan_name VARCHAR(50) NOT NULL,
    scan_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    symbols_scanned INTEGER NOT NULL DEFAULT 0,
    trigger_lines_created INTEGER NOT NULL DEFAULT 0,
    trigger_lines_updated INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlist_symbols (
    id UUID PRIMARY KEY,
    watchlist_id UUID NOT NULL,
    instrument_id UUID,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    instrument_token BIGINT,
    company_name VARCHAR(255),
    price_filter_min DOUBLE PRECISION,
    price_filter_max DOUBLE PRECISION,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trigger_lines (
    id UUID PRIMARY KEY,
    watchlist_id UUID,
    instrument_id UUID,
    scan_execution_id UUID,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'ZERODHA',
    line_type VARCHAR(10) NOT NULL,
    line_price DOUBLE PRECISION NOT NULL,
    level_key VARCHAR(255),
    line_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    is_untouched BOOLEAN NOT NULL DEFAULT TRUE,
    line_drawn_date DATE,
    source_timeframe VARCHAR(20) NOT NULL DEFAULT 'Daily',
    lookback_candles INTEGER,
    max_gap_percent_used DOUBLE PRECISION,
    min_swing_distance_used DOUBLE PRECISION,
    swing_high_1_price DOUBLE PRECISION,
    swing_high_1_date DATE,
    swing_high_2_price DOUBLE PRECISION,
    swing_high_2_date DATE,
    higher_swing_high_price DOUBLE PRECISION,
    lower_swing_high_price DOUBLE PRECISION,
    swing_low_1_price DOUBLE PRECISION,
    swing_low_1_date DATE,
    swing_low_2_price DOUBLE PRECISION,
    swing_low_2_date DATE,
    lower_swing_low_price DOUBLE PRECISION,
    higher_swing_low_price DOUBLE PRECISION,
    swing_gap_percent DOUBLE PRECISION,
    nearest_daily_swing_high_target DOUBLE PRECISION,
    nearest_daily_swing_low_target DOUBLE PRECISION,
    last_validated_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    triggered_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_candles (
    id UUID PRIMARY KEY,
    instrument_token BIGINT,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(20) NOT NULL,
    candle_start TIMESTAMPTZ NOT NULL,
    candle_end TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_final BOOLEAN NOT NULL DEFAULT TRUE,
    source VARCHAR(30) NOT NULL DEFAULT 'ZERODHA',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS breakout_events (
    id UUID PRIMARY KEY,
    trigger_line_id UUID,
    market_candle_id UUID,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    event_type VARCHAR(20) NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    breakout_or_breakdown_price DOUBLE PRECISION,
    breakout_candle_high DOUBLE PRECISION,
    breakout_candle_low DOUBLE PRECISION,
    breakout_candle_volume DOUBLE PRECISION,
    previous_candle_volume DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    volume_condition_required BOOLEAN NOT NULL DEFAULT TRUE,
    volume_condition_passed BOOLEAN NOT NULL DEFAULT FALSE,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    target DOUBLE PRECISION,
    signal_generated BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_trading_settings (
    id UUID PRIMARY KEY,
    starting_capital DOUBLE PRECISION NOT NULL,
    capital_per_trade DOUBLE PRECISION NOT NULL,
    fixed_quantity INTEGER,
    risk_per_trade DOUBLE PRECISION NOT NULL,
    brokerage_estimate DOUBLE PRECISION NOT NULL,
    slippage_estimate DOUBLE PRECISION NOT NULL,
    max_trades_per_day INTEGER NOT NULL,
    max_daily_loss DOUBLE PRECISION NOT NULL,
    default_quantity_mode VARCHAR(20) NOT NULL DEFAULT 'RISK_BASED',
    buy_volume_multiplier DOUBLE PRECISION NOT NULL,
    sell_volume_multiplier DOUBLE PRECISION NOT NULL,
    entry_buffer_ticks DOUBLE PRECISION NOT NULL,
    stop_loss_buffer_ticks DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading_signals (
    id UUID PRIMARY KEY,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    action VARCHAR(10) NOT NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'ZERODHA',
    watchlist_id UUID,
    trigger_line_id UUID,
    breakout_event_id UUID,
    scan_execution_id UUID,
    trigger_price DOUBLE PRECISION,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    target DOUBLE PRECISION,
    quantity INTEGER,
    capital_used DOUBLE PRECISION,
    risk_amount DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    timeframe VARCHAR(20),
    strategy VARCHAR(100),
    dedupe_key VARCHAR(255),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_EXECUTION',
    processed_at TIMESTAMPTZ,
    notification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id UUID PRIMARY KEY,
    signal_id UUID,
    trigger_line_id UUID,
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    action VARCHAR(10) NOT NULL,
    simulated_entry_price DOUBLE PRECISION,
    simulated_stop_loss DOUBLE PRECISION,
    simulated_target DOUBLE PRECISION,
    quantity INTEGER NOT NULL DEFAULT 0,
    capital_used DOUBLE PRECISION NOT NULL DEFAULT 0,
    risk_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    execution_mode VARCHAR(20) NOT NULL DEFAULT 'PAPER',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    simulated_exit_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    pnl_percent DOUBLE PRECISION,
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS broker_orders (
    id UUID PRIMARY KEY,
    signal_id UUID,
    broker_order_id VARCHAR(100),
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER,
    average_price DOUBLE PRECISION,
    mode VARCHAR(20) NOT NULL DEFAULT 'PAPER',
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    request_payload JSONB,
    response_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id UUID PRIMARY KEY,
    source VARCHAR(30) NOT NULL DEFAULT 'ZERODHA',
    exchange VARCHAR(20) NOT NULL DEFAULT 'NSE',
    symbol VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    average_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    raw_payload JSONB,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE watchlist_symbols ADD COLUMN IF NOT EXISTS instrument_id UUID;
ALTER TABLE watchlist_symbols ADD COLUMN IF NOT EXISTS instrument_token BIGINT;

ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS instrument_id UUID;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS scan_execution_id UUID;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'ZERODHA';
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS level_key VARCHAR(255);
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS is_untouched BOOLEAN DEFAULT TRUE;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMPTZ;
ALTER TABLE trigger_lines ADD COLUMN IF NOT EXISTS notes TEXT;

ALTER TABLE breakout_events ADD COLUMN IF NOT EXISTS market_candle_id UUID;
ALTER TABLE breakout_events ADD COLUMN IF NOT EXISTS signal_generated BOOLEAN DEFAULT FALSE;
ALTER TABLE breakout_events ALTER COLUMN status SET DEFAULT 'PENDING';

ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'ZERODHA';
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS scan_execution_id UUID;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS quantity INTEGER;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS capital_used DOUBLE PRECISION;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS risk_amount DOUBLE PRECISION;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255);
ALTER TABLE trading_signals ALTER COLUMN status SET DEFAULT 'PENDING_EXECUTION';

ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(20) DEFAULT 'PAPER';

CREATE INDEX IF NOT EXISTS idx_watchlist_symbols_symbol ON watchlist_symbols(symbol);
CREATE INDEX IF NOT EXISTS idx_instruments_token ON instruments(instrument_token);
CREATE INDEX IF NOT EXISTS idx_instruments_symbol_exchange ON instruments(tradingsymbol, exchange);
CREATE INDEX IF NOT EXISTS idx_scan_executions_date ON scan_executions(scan_date);
CREATE INDEX IF NOT EXISTS idx_trigger_lines_symbol_status ON trigger_lines(symbol, line_status);
CREATE INDEX IF NOT EXISTS idx_trigger_lines_level_key ON trigger_lines(level_key);
CREATE INDEX IF NOT EXISTS idx_market_candles_symbol_start ON market_candles(symbol, candle_start);
CREATE INDEX IF NOT EXISTS idx_breakout_events_symbol_time ON breakout_events(symbol, event_time);
CREATE INDEX IF NOT EXISTS idx_trading_signals_symbol_created ON trading_signals(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_trading_signals_dedupe_key ON trading_signals(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_broker_orders_signal_id ON broker_orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_symbol_time ON position_snapshots(symbol, captured_at);
