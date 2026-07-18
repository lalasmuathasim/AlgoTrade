# Dashboard Design

## Current Backend-Facing Views

- Watchlist Summary
- Watchlist Detail
- Symbol Dashboard
- Trigger Line Dashboard
- Breakout Event Dashboard
- Paper Trading Dashboard
- Paper Trading Settings

## Design Intent

The dashboard should explain the full lifecycle:

1. which symbols are being scanned
2. which Daily trigger lines are active
3. which 3-minute breakouts or breakdowns occurred
4. which signals passed validation
5. which paper trades were created
6. what the performance looks like before live trading is enabled

## Important UX Requirements

- multiple trigger lines per symbol must remain visible
- historical triggered and expired lines must not be overwritten
- signal lineage should be traceable from trigger line to breakout event to trade
- future broker orders should be attachable without changing the core dashboard model
