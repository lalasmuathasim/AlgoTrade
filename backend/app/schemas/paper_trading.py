from datetime import datetime
import uuid
from typing import Literal

from pydantic import BaseModel


class PaperTradingSettingsPayload(BaseModel):
    starting_capital: float
    capital_per_trade: float
    fixed_quantity: int | None = None
    risk_per_trade: float
    brokerage_estimate: float
    slippage_estimate: float
    max_trades_per_day: int
    max_daily_loss: float
    default_quantity_mode: Literal["RISK_BASED", "FIXED"] = "RISK_BASED"
    paper_trading_enabled: bool = True
    live_trading_enabled: bool = False
    require_candle_close_beyond_line: bool = True
    enable_breakout_quality: bool = True
    minimum_close_position_percent: float = 80.0
    minimum_candle_body_percent: float = 60.0
    maximum_rejection_wick_percent: float = 20.0
    minimum_close_beyond_level_ticks: float = 2.0
    require_volume_confirmation: bool = True
    buy_volume_multiplier: float
    sell_volume_multiplier: float
    entry_buffer_ticks: float
    stop_loss_buffer_ticks: float
    target_mode: Literal["NEAREST_DAILY_SWING", "FIXED_RISK_REWARD"] = "NEAREST_DAILY_SWING"
    fallback_risk_reward_ratio: float = 2.0
    use_nearest_daily_swing_target: bool = True
    minimum_reward_risk_ratio: float = 1.0
    order_type: Literal["LIMIT", "MARKET"] = "LIMIT"
    product_type: Literal["MIS", "CNC", "NRML"] = "MIS"
    reentry_cooldown_minutes: int = 0
    allow_repeat_entry_same_line: bool = False
    max_quantity_per_order: int | None = None
    skip_zero_previous_volume: bool = True
    minimum_price: float | None = None
    maximum_price: float | None = None
    allowed_exchanges: list[Literal["NSE", "BSE"]] = ["NSE", "BSE"]
    daily_candle_lookback: int = 100
    swing_window: int = 2
    max_gap_percent: float = 0.5
    min_swing_distance: int = 1
    daily_structure_rebuild_enabled: bool = True
    daily_structure_rebuild_time: str = "15:45"
    prediction_proximity_percent: float = 2.0
    max_open_positions: int = 3
    max_loss_per_symbol_per_day: float = 2500.0
    block_new_trades_after_max_daily_loss: bool = True
    no_trade_after_time: str | None = "15:00"
    market_hours_guard: bool = True
    exchange_charges_estimate: float = 0.0
    use_cost_adjusted_pnl: bool = True
    enable_confidence_filter: bool = False
    minimum_confidence_score: float = 0.6
    confidence_source: Literal["RULES_ONLY", "ANALYTICS_MODEL", "AI_MODEL"] = "RULES_ONLY"
    allow_low_confidence_paper_trades_only: bool = True
    block_live_trades_below_confidence_threshold: bool = True


class PaperTradingSettingsResponse(PaperTradingSettingsPayload):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
