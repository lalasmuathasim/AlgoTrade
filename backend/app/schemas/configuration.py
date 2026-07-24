from datetime import datetime
import uuid

from pydantic import BaseModel, Field
from typing import Literal


class WatchlistCreatePayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    exchange: str = Field(default="NSE", min_length=2, max_length=20)


class SymbolValidationPayload(BaseModel):
    exchange: str = Field(default="NSE", min_length=2, max_length=20)
    symbols_text: str = Field(min_length=1)


class WatchlistSymbolCreatePayload(SymbolValidationPayload):
    watchlist_id: uuid.UUID | None = None


class StrategySettingsPayload(BaseModel):
    daily_candle_lookback: int = Field(ge=20, le=300)
    swing_window: int = Field(ge=1, le=10)
    max_gap_percent: float = Field(gt=0, le=10)
    min_swing_distance: int = Field(ge=1, le=50)
    daily_structure_rebuild_enabled: bool
    daily_structure_rebuild_time: str = Field(min_length=4, max_length=10)
    trading_timezone: str = Field(default="Asia/Kolkata", min_length=3, max_length=64)
    prediction_proximity_percent: float = Field(gt=0, le=20)
    entry_buffer_ticks: float = Field(gt=0, le=10)
    stop_loss_buffer_ticks: float = Field(gt=0, le=10)


class StrategySettingsResponse(StrategySettingsPayload):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExecutionModePayload(BaseModel):
    live_trading_enabled: bool


class ExecutionModeResponse(BaseModel):
    paper_trading_enabled: bool
    live_trading_enabled: bool
    effective_mode: str
    zerodha_credentials_configured: bool
    zerodha_session_present: bool
    zerodha_access_token_expires_at: datetime | None = None


class ExecutionRulesPayload(BaseModel):
    paper_trading_enabled: bool
    live_trading_enabled: bool
    daily_candle_lookback: int | None = Field(default=None, ge=20, le=300)
    swing_window: int | None = Field(default=None, ge=1, le=10)
    max_gap_percent: float | None = Field(default=None, gt=0, le=10)
    min_swing_distance: int | None = Field(default=None, ge=1, le=50)
    daily_structure_rebuild_enabled: bool | None = None
    daily_structure_rebuild_time: str | None = Field(default=None, min_length=4, max_length=10)
    trading_timezone: str | None = Field(default=None, min_length=3, max_length=64)
    prediction_proximity_percent: float | None = Field(default=None, gt=0, le=20)
    require_candle_close_beyond_line: bool
    enable_breakout_quality: bool
    minimum_close_position_percent: float = Field(ge=0, le=100)
    minimum_candle_body_percent: float = Field(ge=0, le=100)
    maximum_rejection_wick_percent: float = Field(ge=0, le=100)
    minimum_close_beyond_level_ticks: float = Field(ge=0, le=100)
    require_volume_confirmation: bool
    entry_buffer_ticks: float = Field(gt=0, le=10)
    stop_loss_buffer_ticks: float = Field(gt=0, le=10)
    target_mode: Literal["NEAREST_DAILY_SWING", "FIXED_RISK_REWARD"]
    fallback_risk_reward_ratio: float = Field(gt=0, le=20)
    use_nearest_daily_swing_target: bool
    minimum_reward_risk_ratio: float = Field(gt=0, le=20)
    order_type: Literal["LIMIT", "MARKET"]
    product_type: Literal["MIS", "CNC", "NRML"]
    reentry_cooldown_minutes: int = Field(ge=0, le=1440)
    allow_repeat_entry_same_line: bool
    default_quantity_mode: Literal["RISK_BASED", "FIXED"]
    fixed_quantity: int | None = Field(default=None, ge=1, le=100000)
    capital_per_trade: float = Field(gt=0)
    risk_per_trade: float = Field(gt=0)
    max_quantity_per_order: int | None = Field(default=None, ge=1, le=100000)
    buy_volume_multiplier: float = Field(gt=0, le=20)
    sell_volume_multiplier: float = Field(gt=0, le=20)
    skip_zero_previous_volume: bool
    minimum_price: float | None = Field(default=None, gt=0)
    maximum_price: float | None = Field(default=None, gt=0)
    allowed_exchanges: list[Literal["NSE", "BSE"]] = Field(default_factory=lambda: ["NSE", "BSE"])
    max_trades_per_day: int = Field(ge=1, le=100)
    max_open_positions: int = Field(ge=1, le=100)
    max_daily_loss: float = Field(gt=0)
    max_loss_per_symbol_per_day: float = Field(gt=0)
    block_new_trades_after_max_daily_loss: bool
    no_trade_after_time: str | None = Field(default="15:00", max_length=10)
    market_hours_guard: bool
    brokerage_estimate: float = Field(ge=0)
    slippage_estimate: float = Field(ge=0)
    exchange_charges_estimate: float = Field(ge=0)
    use_cost_adjusted_pnl: bool
    enable_confidence_filter: bool
    minimum_confidence_score: float = Field(ge=0, le=1)
    confidence_source: Literal["RULES_ONLY", "ANALYTICS_MODEL", "AI_MODEL"]
    allow_low_confidence_paper_trades_only: bool
    block_live_trades_below_confidence_threshold: bool


class ExecutionRulesResponse(ExecutionRulesPayload):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
