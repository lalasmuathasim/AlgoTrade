# TradingView Webhook Receiver

A Dockerized FastAPI, Redis queue, worker, and dashboard setup that accepts TradingView webhook events, persists analytics data in PostgreSQL, and supports paper-trading review before real execution is enabled.

Zerodha order execution is intentionally not implemented yet.

## Architecture

TradingView
→ trading-webhook-api
→ Redis Queue
→ trading-worker
→ PostgreSQL
→ Dashboard APIs
→ Telegram

The architecture is intentionally designed now for future low-latency trade execution, even though actual Zerodha order placement is not yet enabled.

## Access Control

- Public routes:
  - `/`
  - `/health`
  - `/webhook/tradingview`
- Protected routes:
  - `/dashboard`
  - `/dashboard/*`
  - `/paper-trading/*`
- Signup creates a pending user account.
- An approved admin user must review and approve new signups before they can log in.
- Optional TOTP-based two-factor authentication can be enabled from the dashboard after login.

## Project Layout

```text
backend/
  app/
    models/
    routers/
    schemas/
    services/
frontend/
docs/
app/
```

- `backend/app` is the canonical backend package for the API, worker, models, schemas, and services.
- `app` remains as a compatibility layer so existing imports and container entrypoints do not break during the refactor.
- `frontend` is a placeholder for the future React and TypeScript dashboard.
- `docs` holds architecture, strategy, and dashboard design notes for the next development phase.

## Dashboard Scope

The dashboard layer supports:

- Watchlists and watchlist symbols
- Multiple active or historical trigger lines per symbol
- Swing candidate details and gap percentages
- Breakout and breakdown event history
- Historical trading signals
- Paper-trading summaries and settings
- Mock-data seeding through JSON files while live webhook feeds are still evolving

## Setup

1. Create your environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and provide:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `SIGNAL_QUEUE_NAME`
- `MOCK_DATA`
- `WEBHOOK_SECRET`
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` if you want Telegram notifications
- `APP_PORT` if you want a different host port than `8095`
- `LOG_LEVEL` if you want different logging verbosity
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `INITIAL_ADMIN_NAME`
- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `TOTP_ISSUER`

When `MOCK_DATA=true`, the app seeds the dashboard from:

- `mock_data/dashboard_seed.json`
- `mock_data/trading_signals_seed.json`

## Run With Docker Compose

```bash
docker compose up --build -d
```

The API will be available on `http://localhost:8095` by default, or on the port set in `APP_PORT`. The worker runs from the same image and does not expose any host ports.

For reverse-proxy deployments, set `APP_HOST_BIND=127.0.0.1` so the container only binds on the VPS loopback interface.

## Authentication Flow

1. Visit `http://localhost:8095/`.
2. Log in using the seeded admin from `.env`, or request access through the signup form.
3. Admin users can approve pending accounts from the protected dashboard.
4. Approved users can optionally enable two-factor authentication from the dashboard security panel.

## Linode Deployment

This repository includes [deploy-linode.yml](/Users/lalasmuathasim/Works/AlgoTrade/.github/workflows/deploy-linode.yml) for automatic deployment to a Linode VPS on pushes to `main`.

Deployment behavior:

- Uses the ISPConfig site base `/var/www/clients/client0/web13`
- Deploys the Docker project into `/var/www/clients/client0/web13/private/algotrade` when `private/` exists
- Falls back to `/var/www/clients/client0/web13/algotrade` if `private/` is unavailable
- Uploads the repository bundle and a production `.env`
- Runs `docker compose up --build -d` on the VPS
- Verifies the deployed app with `curl http://127.0.0.1:${APP_PORT}/health` on the server

Recommended production env values inside the Linode `.env`:

- `MOCK_DATA=false`
- `APP_HOST_BIND=127.0.0.1`
- `APP_PORT=8095`
- `SESSION_COOKIE_SECURE=true`

GitHub Actions secrets to create:

- `LINODE_HOST`
- `LINODE_USERNAME`
- `LINODE_PORT`
- `LINODE_SSH_KEY`
- `LINODE_APP_ENV`

What `LINODE_APP_ENV` should contain:

- The complete production `.env` file content for the VPS, including:
  - `DATABASE_URL`
  - `REDIS_URL`
  - `JWT_SECRET`
  - `WEBHOOK_SECRET`
  - `SIGNAL_QUEUE_NAME`
  - `MOCK_DATA`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `APP_HOST_BIND`
  - `APP_PORT`
  - `LOG_LEVEL`
  - `ACCESS_TOKEN_EXPIRE_MINUTES`
  - `SESSION_COOKIE_NAME`
  - `SESSION_COOKIE_SECURE`
  - `INITIAL_ADMIN_EMAIL`
  - `INITIAL_ADMIN_PASSWORD`
  - `INITIAL_ADMIN_NAME`
  - `TOTP_ISSUER`
  - optional `STRATEGY_TUNING__*` values

VPS prerequisites:

- Docker Engine installed
- Docker Compose plugin installed
- The domain `https://qubitx.ai` reverse-proxied by ISPConfig or your web server to `127.0.0.1:8095`

## Responsibilities

API responsibilities:

- Validate webhook payloads
- Verify the shared secret
- Queue accepted signals into Redis
- Return an immediate response without waiting for database or Telegram work

Worker responsibilities:

- Read queued signals from Redis
- Run the future execution placeholder
- Persist trigger lines, breakout events, trading signals, and paper trades to PostgreSQL
- Retry Telegram notifications
- Update processing metadata and log failures

Redis responsibilities:

- Decouple the webhook response path from slower downstream processing
- Buffer accepted signals for worker consumption using `LPUSH` and `BRPOP`

Execution responsibilities:

- `backend/app/execution.py` is the reserved future integration point for Zerodha execution
- Execution is intentionally disabled for now and only logged

Dashboard responsibilities:

- `/dashboard` renders a lightweight review UI
- `/` renders the public landing page and auth entry point
- `/dashboard/watchlists` summarizes tracked lists
- `/dashboard/watchlists/{watchlist_id}` drills into symbols and summaries
- `/dashboard/symbols/{exchange}/{symbol}` shows line, event, signal, and paper-trade history
- `/dashboard/trigger-lines` lists all lines with filters
- `/dashboard/breakout-events` lists all breakout or breakdown events with filters
- `/dashboard/paper-trades` returns trade analytics and detailed rows
- `/paper-trading/settings` manages paper-trading assumptions

## Health Check

```bash
curl http://localhost:8095/health
```

## Dashboard

- Landing page: `http://localhost:8095/`
- HTML dashboard: `http://localhost:8095/dashboard`
- Watchlist summary API: `http://localhost:8095/dashboard/watchlists`
- Paper-trading settings API: `http://localhost:8095/paper-trading/settings`

## Sample Trading Signal Webhook JSON

```json
{
  "secret": "change-me",
  "event_category": "TRADING_SIGNAL",
  "exchange": "NSE",
  "symbol": "RELIANCE",
  "action": "BUY",
  "trigger_price": 1520,
  "entry_price": 1524.10,
  "stop_loss": 1519.90,
  "target": 1560,
  "volume_ratio": 5.8,
  "timeframe": "3m",
  "strategy": "daily_structure_breakout"
}
```

## Sample Trigger Line Webhook JSON

```json
{
  "secret": "change-me",
  "event_category": "TRIGGER_LINE",
  "exchange": "NSE",
  "symbol": "RELIANCE",
  "watchlist_name": "NSE 80-2000 Watchlist",
  "line_type": "BUY",
  "line_price": 1520,
  "line_drawn_date": "2026-06-17",
  "swing_1_price": 1518,
  "swing_1_date": "2026-05-20",
  "swing_2_price": 1509,
  "swing_2_date": "2026-06-05",
  "swing_gap_percent": 0.59,
  "nearest_target": 1560,
  "lookback_candles": 100,
  "max_gap_percent_used": 1.5,
  "min_swing_distance_used": 5
}
```

## Sample Breakout Event Webhook JSON

```json
{
  "secret": "change-me",
  "event_category": "BREAKOUT_EVENT",
  "exchange": "NSE",
  "symbol": "INFY",
  "trigger_line_id": "22950979-91d1-4772-b6c7-46f091a7e519",
  "event_type": "BREAKDOWN",
  "event_time": "2026-06-17T09:21:00+05:30",
  "breakout_or_breakdown_price": 1497.8,
  "breakout_candle_high": 1500.3,
  "breakout_candle_low": 1496.7,
  "breakout_candle_volume": 1820000,
  "previous_candle_volume": 430000,
  "volume_ratio": 4.23,
  "volume_condition_required": true,
  "volume_condition_passed": true,
  "entry_price": 1497.8,
  "stop_loss": 1502.0,
  "target": 1488.0,
  "breakout_status": "PASSED"
}
```

## Sample curl Request

```bash
curl -X POST http://localhost:8095/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "change-me",
    "event_category": "TRADING_SIGNAL",
    "exchange": "NSE",
    "symbol": "RELIANCE",
    "action": "BUY",
    "trigger_price": 1520,
    "entry_price": 1524.10,
    "stop_loss": 1519.90,
    "target": 1560,
    "volume_ratio": 5.8,
    "timeframe": "3m",
    "strategy": "daily_structure_breakout"
  }'
```

## Sample Webhook Response

```json
{
  "status": "queued",
  "signal_id": "00000000-0000-0000-0000-000000000000",
  "queued": true
}
```

## Notes

- PostgreSQL is not included by default in `docker-compose.yml`.
- Redis is not included by default in `docker-compose.yml`.
- Set `DATABASE_URL` and `REDIS_URL` to existing shared infrastructure or external hosts.
- The webhook API returns after queueing and never waits for PostgreSQL or Telegram.
- Database tables are created automatically on startup using SQLAlchemy metadata, with compatibility updates for the existing `trading_signals` table.
- Telegram failures are retried and logged by the worker without failing webhook acceptance.
- `MOCK_DATA=true` seeds watchlists, trigger lines, breakout events, trading signals, and paper trades from JSON so the dashboard is immediately usable.
