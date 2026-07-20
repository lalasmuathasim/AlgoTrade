from datetime import datetime
import uuid

from pydantic import BaseModel, Field


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
    buy_volume_multiplier: float = Field(gt=0, le=20)
    sell_volume_multiplier: float = Field(gt=0, le=20)
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
