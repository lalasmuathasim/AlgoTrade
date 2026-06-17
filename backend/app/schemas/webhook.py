from datetime import date, datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HealthResponse(BaseModel):
    status: str


class TradingViewWebhookPayload(BaseModel):
    secret: str
    event_category: Literal["TRIGGER_LINE", "BREAKOUT_EVENT", "TRADING_SIGNAL"] = "TRADING_SIGNAL"
    exchange: str = "NSE"
    symbol: str = Field(min_length=1)
    action: Literal["BUY", "SELL"] | None = None
    watchlist_id: uuid.UUID | None = None
    watchlist_name: str | None = None
    watchlist_description: str | None = None
    trigger_line_id: uuid.UUID | None = None
    breakout_event_id: uuid.UUID | None = None
    trigger_price: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    volume_ratio: float | None = None
    timeframe: str | None = None
    strategy: str | None = None
    line_type: Literal["BUY", "SELL"] | None = None
    line_price: float | None = None
    line_status: Literal["ACTIVE", "TRIGGERED", "INVALIDATED", "EXPIRED"] | None = None
    line_drawn_date: date | None = None
    source_timeframe: str | None = "Daily"
    lookback_candles: int | None = None
    max_gap_percent_used: float | None = None
    min_swing_distance_used: float | None = None
    swing_1_price: float | None = None
    swing_1_date: date | None = None
    swing_2_price: float | None = None
    swing_2_date: date | None = None
    swing_gap_percent: float | None = None
    nearest_target: float | None = None
    event_type: Literal["BREAKOUT", "BREAKDOWN"] | None = None
    event_time: datetime | None = None
    breakout_or_breakdown_price: float | None = None
    breakout_candle_high: float | None = None
    breakout_candle_low: float | None = None
    breakout_candle_volume: float | None = None
    previous_candle_volume: float | None = None
    volume_condition_required: bool | None = True
    volume_condition_passed: bool | None = None
    breakout_status: Literal["PASSED", "FAILED", "IGNORED"] | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_by_event_category(self) -> "TradingViewWebhookPayload":
        if self.event_category == "TRADING_SIGNAL" and self.action is None:
            raise ValueError("action is required for TRADING_SIGNAL events")
        if self.event_category == "TRIGGER_LINE":
            required = [self.line_type, self.line_price, self.line_drawn_date]
            if any(value is None for value in required):
                raise ValueError("line_type, line_price, and line_drawn_date are required for TRIGGER_LINE events")
        if self.event_category == "BREAKOUT_EVENT":
            required = [self.event_type, self.event_time, self.breakout_or_breakdown_price]
            if any(value is None for value in required):
                raise ValueError(
                    "event_type, event_time, and breakout_or_breakdown_price are required for BREAKOUT_EVENT events"
                )
        return self


class WebhookResponse(BaseModel):
    status: Literal["queued"]
    signal_id: uuid.UUID
    queued: bool


class QueuedTradingSignal(TradingViewWebhookPayload):
    signal_id: uuid.UUID
    retry_count: int = 0
