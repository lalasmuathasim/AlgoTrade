# Strategy Notes

## Daily Structure Logic

The current strategy layer is based on Daily swing structure and intraday confirmation.

### Daily scan

- fetch the last 100 completed Daily candles
- detect swing highs and swing lows
- pair nearby swings within `MAX_GAP_PERCENT`
- require a minimum structural separation through `MIN_SWING_DISTANCE`
- keep only untouched levels

### Trigger lines

- BUY line uses an untouched Daily resistance level
- SELL line uses an untouched Daily support level
- multiple lines per symbol are allowed

### Intraday confirmation

- market data is aggregated into completed 3-minute candles
- BUY breakout volume must be at least `BUY_VOLUME_MULTIPLIER` times the previous 3-minute candle volume
- SELL breakdown volume must be at least `SELL_VOLUME_MULTIPLIER` times the previous 3-minute candle volume

### Trade setup

- entry uses the trigger line plus or minus `ENTRY_BUFFER_TICKS`
- stop uses breakout-candle structure plus or minus `STOP_BUFFER_TICKS`
- target prefers the nearest stored Daily target level
- quantity and risk are derived from paper-trading settings

## Execution Policy

- paper trading is the default
- live execution is feature-gated
- no real Zerodha order is placed during test validation
