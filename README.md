# Qubitx Zerodha Trading Platform

Qubitx is a FastAPI-based trading platform built around Zerodha-native market data and staged execution. It scans Daily candles after market close, stores active trigger lines in PostgreSQL, consumes live Zerodha ticks during market hours, aggregates completed 3-minute candles, validates breakouts with volume rules, and generates paper trades by default.

Live Zerodha order placement remains feature-gated and placeholder-only in this build. No real broker order is placed unless that path is explicitly implemented later.

## What Changed

TradingView webhook ingestion has been removed from the production architecture.

The platform is now centered on:

1. Zerodha historical candle scans after market close
2. Zerodha-native instrument sync
3. Zerodha tick-driven intraday candle building
4. Breakout and breakdown detection from stored trigger lines
5. Paper trading first
6. Live execution only behind `ZERODHA_LIVE_TRADING_ENABLED`

## Current Architecture

```text
Daily market close
  -> scheduler
  -> Zerodha historical candle provider
  -> swing detection
  -> untouched trigger-line generation
  -> PostgreSQL trigger_lines

Market hours
  -> live-engine
  -> Zerodha tick stream
  -> 3-minute candle builder
  -> breakout / breakdown detector
  -> volume validator
  -> trading_signals
  -> Redis signal dispatch queue
  -> worker
  -> paper execution
  -> Telegram notification
  -> live execution placeholder
```

## Core Capabilities

- Admin-approved login with optional TOTP 2FA
- Watchlist and symbol storage
- Instrument master sync
- Daily OHLCV scan execution tracking
- Swing high and swing low detection
- Untouched BUY resistance and SELL support line detection
- Multiple active or historical trigger lines per symbol
- Completed 3-minute candle aggregation from ticks
- BUY breakout validation using `BUY_VOLUME_MULTIPLIER`
- SELL breakdown validation using `SELL_VOLUME_MULTIPLIER`
- Duplicate-signal protection
- Paper trade generation
- Live execution placeholder behind feature flag
- Broker order and position reconciliation placeholders
- Protected dashboard APIs

## Project Layout

```text
.
├── app/                         # compatibility wrappers
├── backend/app/
│   ├── live_engine.py
│   ├── main.py
│   ├── migrate.py
│   ├── queue.py
│   ├── scheduler.py
│   ├── worker.py
│   ├── migrations/
│   ├── models/
│   ├── routers/
│   ├── schemas/
│   └── services/
├── docs/
├── frontend/
├── mock_data/
├── tests/
├── .env.example
├── AGENT.md
├── AWS_DEPLOYMENT.md
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Data Model

### Existing reusable domain entities

- `User`
- `Watchlist`
- `WatchlistSymbol`
- `TriggerLine`
- `BreakoutEvent`
- `TradingSignal`
- `PaperTradingSetting`
- `PaperTrade`

### New Zerodha-native entities

- `Instrument`
- `MarketCandle`
- `ScanExecution`
- `BrokerOrder`
- `PositionSnapshot`

## Environment Variables

The main runtime template is [.env.example](/Users/lalasmuathasim/Works/AlgoTrade/.env.example).

### Required

- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_QUEUE_PREFIX`
- `JWT_SECRET`

### Zerodha credentials

- `ZERODHA_API_KEY`
- `ZERODHA_API_SECRET`
- `ZERODHA_ACCESS_TOKEN`
- `ZERODHA_REDIRECT_URL`

### Execution flags

- `ZERODHA_LIVE_TRADING_ENABLED=false`
- `PAPER_TRADING_ENABLED=true`

### Scanner and market behavior

- `DAILY_SCAN_TIME`
- `MARKET_TIMEZONE`
- `BUY_VOLUME_MULTIPLIER`
- `SELL_VOLUME_MULTIPLIER`
- `ENTRY_BUFFER_TICKS`
- `STOP_BUFFER_TICKS`
- `DAILY_CANDLE_LOOKBACK`
- `SWING_WINDOW`
- `MAX_GAP_PERCENT`
- `MIN_SWING_DISTANCE`

### App runtime

- `API_HOST_PORT`
- `API_HOST_BIND`
- `LOG_LEVEL`
- `WORKER_POLL_TIMEOUT`
- `WORKER_MAX_RETRIES`
- `SCHEDULER_POLL_INTERVAL_SECONDS`
- `RECONCILIATION_POLL_INTERVAL_SECONDS`

### Auth and admin bootstrap

- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `INITIAL_ADMIN_NAME`
- `TOTP_ISSUER`

### Optional

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MOCK_DATA`

## Shared PostgreSQL Setup

Qubitx is intended to use a dedicated database inside a shared PostgreSQL server.

Recommended example:

```sql
CREATE USER qubitx_user WITH PASSWORD 'change-me';
CREATE DATABASE qubitx OWNER qubitx_user;
GRANT ALL PRIVILEGES ON DATABASE qubitx TO qubitx_user;
```

Example `DATABASE_URL`:

```text
postgresql+psycopg2://qubitx_user:change-me@postgres-host:5432/qubitx
```

Do not start another PostgreSQL container if your shared PostgreSQL server is already available.

## Redis Usage

Redis remains part of the architecture, but it is no longer used for webhook payload buffering. It now carries internal Qubitx dispatch jobs such as signal execution handoff.

Use one shared Redis instance with:

- a dedicated Redis database number for Qubitx
- a dedicated `REDIS_QUEUE_PREFIX`

You do not need to rename Redis containers. Isolation comes from the database number and key prefix.

Examples:

```text
REDIS_URL=redis://redis:6379/12
# or, if Redis is published on the VPS host:
# REDIS_URL=redis://host.docker.internal:6397/12
REDIS_QUEUE_PREFIX=qubitx
```

## Migrations

This repository now includes an explicit migration runner instead of relying on `create_all()` at startup.

Run migrations with:

```bash
python3 -m backend.app.migrate upgrade
```

Inside Docker:

```bash
docker compose run --rm migrate
```

## Local Development

### 1. Create the environment file

```bash
cp .env.example .env
```

### 2. Update the important values

At minimum:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `INITIAL_ADMIN_*`
- Zerodha credentials if you are testing real integrations

### 3. Run migrations

```bash
python3 -m backend.app.migrate upgrade
```

### 4. Start the services

```bash
docker compose up --build -d api worker scheduler live-engine
```

### 5. Verify health

```bash
curl http://127.0.0.1:8095/health
```

## Docker Services

The Compose stack now includes:

- `api`
- `worker`
- `scheduler`
- `live-engine`
- `migrate`

There are no fixed container names, and the Compose project name is `qubitx` to reduce conflicts with other local or VPS deployments.

## API Surface

### Public

- `GET /`
- `GET /health`

### Protected auth and dashboard

- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/status`
- `GET /dashboard`
- `GET /dashboard/watchlists`
- `GET /dashboard/watchlists/{watchlist_id}`
- `GET /dashboard/symbols/{exchange}/{symbol}`
- `GET /dashboard/trigger-lines`
- `GET /dashboard/breakout-events`
- `GET /dashboard/paper-trades`
- `GET /paper-trading/settings`
- `POST /paper-trading/settings`

### Admin-only system endpoints

- `GET /system/dependencies`
- `POST /system/instruments/sync`
- `POST /system/scans/daily`
- `POST /system/ticks/replay`

## Zerodha Authentication Workflow

This codebase assumes the access token is managed explicitly through environment configuration for now.

Recommended daily workflow:

1. Generate a fresh Zerodha access token through your existing auth process.
2. Update `ZERODHA_ACCESS_TOKEN` in the production environment.
3. Restart only the Qubitx services if needed.
4. Confirm `/system/dependencies` reports Zerodha credentials as configured.

This build does not implement automated daily token refresh yet.

## Scheduler Behavior

The scheduler checks the configured `DAILY_SCAN_TIME` in `MARKET_TIMEZONE` and records one completed daily market scan per trading day.

Each scan:

1. loads active watchlist symbols
2. resolves linked instrument tokens
3. fetches the last `DAILY_CANDLE_LOOKBACK` completed daily candles
4. detects swings
5. validates untouched trigger-line candidates
6. upserts active trigger lines
7. expires outdated active lines for that symbol when necessary
8. records the run in `scan_executions`

## Paper Trading vs Live Trading

### Paper mode

- controlled by `PAPER_TRADING_ENABLED`
- enabled by default
- generates `paper_trades`
- does not place broker orders

### Live mode

- controlled by `ZERODHA_LIVE_TRADING_ENABLED`
- still placeholder-only in this build
- records a broker-order placeholder row
- does not place a real order during local validation

## Test Commands

### Compile

```bash
python3 -m compileall backend app
```

### Unit tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

### Lint

```bash
.venv/bin/ruff check backend app tests
```

### Focused type check

```bash
.venv/bin/mypy backend/app/services backend/app/routers/system.py backend/app/live_engine.py backend/app/scheduler.py tests --ignore-missing-imports
```

## Deployment

The GitHub Actions deployment workflow has been updated to:

- build the updated backend bundle
- generate `.env` from individual secrets
- map legacy repository secrets to the new Zerodha-native variable names where possible
- run migrations before starting services
- tear down the active Qubitx Compose stack before restart
- remove only known legacy Qubitx containers when they block the configured API port
- start only Qubitx services
- verify internal health on the server
- verify reverse-proxy health through `https://qubitx.ai/health`

See:

- [AWS_DEPLOYMENT.md](/Users/lalasmuathasim/Works/AlgoTrade/AWS_DEPLOYMENT.md)
- [.github/workflows/deploy-linode.yml](/Users/lalasmuathasim/Works/AlgoTrade/.github/workflows/deploy-linode.yml)

## Linode Deployment Notes

Current production host:

- `qubitx.ai`
- Linode VPS behind Apache reverse proxy
- Qubitx API expected on `127.0.0.1:${API_HOST_PORT}`

### Legacy-container port conflict

During the July 18, 2026 deployment work, the main blocker was not another application but an older Qubitx-era container still holding the API port:

- legacy API container: `trading-webhook-api`
- legacy worker container: `trading-worker`
- expected new API container: `qubitx-api-1`

Observed VPS state at that point:

- `qubitx-worker-1`, `qubitx-scheduler-1`, and `qubitx-live-engine-1` were already running
- `qubitx-api-1` could not start because `trading-webhook-api` still owned `127.0.0.1:8095`

The deployment workflow now handles this case by:

1. running `docker compose down --remove-orphans`
2. removing `trading-webhook-api` and `trading-worker` if they still exist
3. refusing to kill unrelated containers automatically
4. failing with the exact port owner if some non-Qubitx container still holds the port

If manual recovery is needed on the VPS:

```bash
docker rm -f trading-webhook-api trading-worker
cd /var/www/clients/client0/web13/private/qubitx
docker compose up -d api
docker compose ps
curl http://127.0.0.1:8095/health
```

## Rollback Guidance

If deployment health checks fail:

1. SSH into the VPS deployment directory.
2. Inspect `docker compose logs api worker scheduler live-engine`.
3. Re-run `python -m backend.app.migrate status` if needed.
4. Check the last known good commit.
5. Redeploy that commit and rebuild only the Qubitx services.

## GitHub Actions Secrets

The deployment workflow now supports a mix of current and legacy secret names.

### Required existing secrets

- `LINODE_HOST`
- `LINODE_USERNAME`
- `LINODE_PORT`
- `LINODE_SSH_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `INITIAL_ADMIN_NAME`
- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `LOG_LEVEL`
- `MOCK_DATA`
- `TOTP_ISSUER`

### Preferred new secrets

- `REDIS_QUEUE_PREFIX`
- `API_HOST_PORT`
- `ZERODHA_API_KEY`
- `ZERODHA_API_SECRET`
- `ZERODHA_ACCESS_TOKEN`
- `ZERODHA_REDIRECT_URL`
- `ZERODHA_LIVE_TRADING_ENABLED`
- `PAPER_TRADING_ENABLED`
- `DAILY_SCAN_TIME`
- `MARKET_TIMEZONE`
- `BUY_VOLUME_MULTIPLIER`
- `SELL_VOLUME_MULTIPLIER`
- `ENTRY_BUFFER_TICKS`
- `STOP_BUFFER_TICKS`
- `DAILY_CANDLE_LOOKBACK`
- `SWING_WINDOW`
- `MAX_GAP_PERCENT`
- `MIN_SWING_DISTANCE`

### Legacy secrets still accepted by the workflow

- `APP_PORT` -> `API_HOST_PORT`
- `STRATEGY_TUNING__BUYVOLUMEMULTIPLIER` -> `BUY_VOLUME_MULTIPLIER`
- `STRATEGY_TUNING__SELLVOLUMEMULTIPLIER` -> `SELL_VOLUME_MULTIPLIER`
- `STRATEGY_TUNING__ENTRYBUFFERTICKS` -> `ENTRY_BUFFER_TICKS`
- `STRATEGY_TUNING__STOPLOSSBUFFERTICKS` -> `STOP_BUFFER_TICKS`
- `STRATEGY_TUNING__MAXGAPPERCENT` -> `MAX_GAP_PERCENT`
- `STRATEGY_TUNING__MINSWINGDISTANCE` -> `MIN_SWING_DISTANCE`

## Validation Status In This Refactor

Completed locally:

- compile check
- unit tests for scanner, swing detection, untouched-level validation, candle aggregation, volume validation, signal dedupe, paper trade generation, and restart-state behavior
- Ruff lint
- focused mypy pass

Not completed in this workspace yet:

- migration run against a real local Qubitx PostgreSQL database
- live Redis connectivity verification from this sandbox
- Docker build and Compose startup validation from this sandbox
- production push to `main`

Completed outside the local sandbox:

- GitHub Actions workflow syntax fixes and deployment-secret fallback updates were pushed to `main`
- Linode reverse proxy for `qubitx.ai` was confirmed to forward to the internal Qubitx API port
- VPS container inspection confirmed the July 18, 2026 deployment blocker was the legacy `trading-webhook-api` container owning `127.0.0.1:8095`

Not yet confirmed end-to-end:

- a clean GitHub Actions deployment with `qubitx-api-1` successfully replacing the legacy API container
- post-deploy production health after the legacy container is removed and the new API is up
