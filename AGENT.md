# AGENT.md

This is the working brief for future developers and coding agents continuing Qubitx.

## Mission

Build and operate a Zerodha-native trading platform that:

1. scans Daily candles after market close
2. derives untouched trigger lines
3. watches market ticks during trading hours
4. generates validated signals from completed 3-minute candles
5. executes paper trades by default
6. keeps live execution behind a deliberate feature flag

## Current Design Principles

- No TradingView dependency in the production path
- No synchronous ingestion bottleneck for execution handoff
- Keep PostgreSQL shared at the server level but isolated by database
- Keep Redis shared at the server level but isolated by queue prefix
- Preserve dashboard and auth workflows where they still fit
- Do not place real orders during local development or CI validation

## Runtime Services

- `api`
- `worker`
- `scheduler`
- `live-engine`
- `migrate`

## Current Operational Status

As of July 18, 2026:

- the Zerodha-native refactor is merged on `main`
- Linode deploy automation has been updated to build `.env` from individual GitHub secrets
- the VPS is running `qubitx-worker-1`, `qubitx-scheduler-1`, and `qubitx-live-engine-1`
- the main deployment blocker identified on the VPS is the legacy container `trading-webhook-api` holding `127.0.0.1:8095`
- `qubitx-api-1` cannot start until that legacy API container is removed or replaced

Do not assume port conflicts on Linode come from unrelated projects first. On July 18, 2026, the actual conflict was inside the project's own transition from the old AlgoTrade deployment to the new Qubitx stack.

## Primary Runtime Flow

### After market close

- scheduler triggers daily scan
- scanner fetches the last 100 completed Daily candles from Zerodha
- swing detector finds swing highs and lows
- untouched-level validator derives active BUY and SELL trigger lines
- trigger lines are persisted in PostgreSQL

### During market hours

- live engine consumes Zerodha ticks
- candle builder aggregates completed 3-minute candles
- breakout detector and volume validator evaluate active lines
- signal generator creates trade setups
- duplicate-signal protection prevents repeated records
- signal dispatch queue hands execution work to the worker

### Downstream execution path

- worker creates paper trades when enabled
- worker records live-execution placeholders when the feature flag is on
- worker sends Telegram notifications
- reconciliation service is available for broker order and position snapshots

## What Must Be Preserved

- auth and admin approval flow
- dashboard endpoints unless there is a strong reason to change them
- watchlist, trigger-line, breakout-event, trading-signal, and paper-trade lineage
- environment-driven deployment
- shared PostgreSQL server usage through `DATABASE_URL`
- shared Redis usage through `REDIS_URL`

## What Has Been Removed

- TradingView webhook request path
- TradingView-specific webhook secrets
- TradingView event payload contracts
- TradingView as a source-of-truth assumption in the architecture

## Important Environment Variables

- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_QUEUE_PREFIX`
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
- `API_HOST_PORT`
- `JWT_SECRET`

## Deployment Notes For Agents

- production host domain is `qubitx.ai`
- Apache reverse proxy forwards traffic to the internal Qubitx API port on `127.0.0.1`
- do not introduce public host bindings for worker, scheduler, or live-engine
- preserve the current strategy of generating `.env` on deploy from GitHub Actions secrets
- when changing deployment workflow, protect unrelated VPS containers from accidental cleanup

The deployment workflow now intentionally:

1. supports fallback from legacy secret names such as `APP_PORT` and `STRATEGY_TUNING__*`
2. shuts down the current Qubitx Compose stack before restart
3. removes only known legacy Qubitx containers:
   - `trading-webhook-api`
   - `trading-worker`
4. refuses to force-remove unknown containers occupying the API port

If deployment fails with a port-allocation error again, inspect `docker ps` first and confirm the exact container name before changing the workflow further.

## Database Guidance

- Use a dedicated Qubitx database such as `qubitx`
- Prefer a dedicated Qubitx database user
- Run explicit migrations before app startup
- Do not depend on `metadata.create_all()` for schema rollout
- Avoid destructive changes that could drop production data

## Required Domain Separation

Do not collapse these concepts into one table:

- trigger lines
- breakout events
- trading signals
- paper trades
- broker orders
- position snapshots

They represent different stages of the trading lifecycle and are required for analysis, audit, and future live-trading linkage.

## Near-Term Priorities

1. Finish the Qubitx API cutover on Linode by fully replacing the legacy `trading-webhook-api` container.
2. Replace placeholder Zerodha credential management with a safer token workflow.
3. Connect the live engine to the actual Zerodha websocket transport.
4. Run migrations and Docker validation against a real local Qubitx PostgreSQL and Redis target.
5. Add richer integration tests once shared infra access is available.
6. Extend the dashboard with instrument sync and scan-execution visibility.

## Non-Goals For This Stage

- accidental live order placement
- adding Celery, RabbitMQ, or Kafka
- adding default PostgreSQL or Redis containers for production
- rewriting the dashboard frontend before the backend data path is stable

## Related Documentation

- [README.md](/Users/lalasmuathasim/Works/AlgoTrade/README.md)
- [AWS_DEPLOYMENT.md](/Users/lalasmuathasim/Works/AlgoTrade/AWS_DEPLOYMENT.md)
- [docs/architecture.md](/Users/lalasmuathasim/Works/AlgoTrade/docs/architecture.md)
- [docs/strategy.md](/Users/lalasmuathasim/Works/AlgoTrade/docs/strategy.md)
- [docs/dashboard-design.md](/Users/lalasmuathasim/Works/AlgoTrade/docs/dashboard-design.md)
