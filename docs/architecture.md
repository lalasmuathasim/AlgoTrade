# Qubitx Architecture

## Service Layout

- `api` serves auth, dashboard, paper-trading settings, and admin system endpoints
- `worker` processes generated trading signals asynchronously
- `scheduler` runs the daily market scan after market close
- `live-engine` processes Zerodha ticks and builds completed 3-minute candles
- `migrate` applies explicit SQL migrations

## Data Flow

### Daily scan flow

1. scheduler starts a scan at `DAILY_SCAN_TIME`
2. historical candle provider fetches the last 100 completed Daily candles
3. swing detector derives swing highs and lows
4. untouched-level validator derives BUY resistance and SELL support lines
5. trigger-line manager upserts active lines in PostgreSQL
6. scan execution metadata is recorded

### Intraday flow

1. live engine receives ticks
2. candle builder aligns them into completed 3-minute candles
3. breakout detector checks active trigger lines
4. volume validator enforces BUY and SELL thresholds
5. signal generator creates a trade setup
6. duplicate-signal protection prevents repeated entries
7. Redis queue hands signal execution to the worker
8. worker records paper trades and notifications

## Persistence Areas

- watchlists and symbols
- instruments
- trigger lines
- scan executions
- market candles
- breakout events
- trading signals
- paper trades
- broker-order placeholders
- position snapshots
