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
    buy_volume_multiplier: float
    sell_volume_multiplier: float
    entry_buffer_ticks: float
    stop_loss_buffer_ticks: float
    daily_candle_lookback: int = 100
    swing_window: int = 2
    max_gap_percent: float = 0.5
    min_swing_distance: int = 1


class PaperTradingSettingsResponse(PaperTradingSettingsPayload):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
