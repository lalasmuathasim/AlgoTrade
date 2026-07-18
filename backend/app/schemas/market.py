from datetime import date, datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class InstrumentPayload(BaseModel):
    instrument_token: int
    tradingsymbol: str
    exchange: str = "NSE"
    exchange_token: str | None = None
    name: str | None = None
    segment: str | None = None
    instrument_type: str | None = None
    tick_size: float | None = None
    lot_size: int | None = None


class HistoricalCandlePayload(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class TickPayload(BaseModel):
    instrument_token: int
    symbol: str
    exchange: str = "NSE"
    timestamp: datetime
    last_price: float
    volume_traded: float | None = None


class CompletedCandlePayload(BaseModel):
    instrument_token: int | None = None
    symbol: str
    exchange: str = "NSE"
    timeframe: str = "3minute"
    candle_start: datetime
    candle_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class SwingPointPayload(BaseModel):
    kind: Literal["HIGH", "LOW"]
    index: int
    price: float
    candle_date: date


class TriggerLineCandidatePayload(BaseModel):
    symbol: str
    exchange: str = "NSE"
    line_type: Literal["BUY", "SELL"]
    line_price: float
    level_key: str
    line_drawn_date: date
    lookback_candles: int
    max_gap_percent_used: float
    min_swing_distance_used: float
    swing_gap_percent: float | None = None
    swing_high_1_price: float | None = None
    swing_high_1_date: date | None = None
    swing_high_2_price: float | None = None
    swing_high_2_date: date | None = None
    higher_swing_high_price: float | None = None
    lower_swing_high_price: float | None = None
    swing_low_1_price: float | None = None
    swing_low_1_date: date | None = None
    swing_low_2_price: float | None = None
    swing_low_2_date: date | None = None
    lower_swing_low_price: float | None = None
    higher_swing_low_price: float | None = None
    nearest_daily_swing_high_target: float | None = None
    nearest_daily_swing_low_target: float | None = None
    notes: str | None = None


class BreakoutCandidatePayload(BaseModel):
    trigger_line_id: uuid.UUID
    symbol: str
    exchange: str = "NSE"
    event_type: Literal["BREAKOUT", "BREAKDOWN"]
    event_time: datetime
    breakout_or_breakdown_price: float
    breakout_candle_high: float
    breakout_candle_low: float
    breakout_candle_volume: float
    previous_candle_volume: float | None = None
    volume_ratio: float | None = None
    volume_condition_passed: bool
    entry_price: float
    stop_loss: float
    target: float
    market_candle_id: uuid.UUID | None = None


class TradeSetupPayload(BaseModel):
    signal_id: uuid.UUID | None = None
    exchange: str = "NSE"
    symbol: str
    action: Literal["BUY", "SELL"]
    trigger_line_id: uuid.UUID | None = None
    breakout_event_id: uuid.UUID | None = None
    entry_price: float
    stop_loss: float
    target: float
    trigger_price: float | None = None
    quantity: int | None = None
    capital_used: float | None = None
    risk_amount: float | None = None
    volume_ratio: float | None = None
    timeframe: str = "3minute"
    strategy: str = "zerodha_daily_structure"
    dedupe_key: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SignalDispatchJob(BaseModel):
    signal_id: uuid.UUID
    retry_count: int = 0


class ScanExecutionResponse(BaseModel):
    execution_id: uuid.UUID
    status: str
    symbols_scanned: int
    trigger_lines_created: int
    trigger_lines_updated: int


class DependencyStatusResponse(BaseModel):
    database: bool
    redis: bool
    zerodha_credentials_configured: bool
