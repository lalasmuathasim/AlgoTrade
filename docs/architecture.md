# Architecture Placeholder

## Current Direction

The codebase is organized to support a clean separation between:

- `backend/app/routers` for API surface area
- `backend/app/services` for reusable business logic
- `backend/app/models` for persistence entities
- `backend/app/schemas` for request and response contracts

## Target Flow

TradingView -> FastAPI webhook API -> Redis queue -> worker -> PostgreSQL -> dashboard APIs -> Telegram

## Future Expansion

This structure is prepared for:

- Watchlist management
- Trigger-line lifecycle tracking
- Breakout and breakdown event analytics
- Paper-trading simulation
- Future Zerodha execution and order-audit linkage

