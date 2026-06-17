from datetime import date, datetime
import uuid

from pydantic import BaseModel


class WatchlistSummaryItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    exchange: str
    symbol_count: int
    symbols_with_active_buy_lines: int
    symbols_with_active_sell_lines: int
    active_trigger_lines: int
    triggered_lines: int
    paper_trades: int
    total_paper_pnl: float


class TriggerLineSummary(BaseModel):
    id: uuid.UUID
    watchlist_id: uuid.UUID | None = None
    exchange: str
    symbol: str
    line_type: str
    line_price: float
    line_status: str
    line_drawn_date: date | None = None
    swing_gap_percent: float | None = None
    nearest_daily_swing_high_target: float | None = None
    nearest_daily_swing_low_target: float | None = None
    created_at: datetime
    updated_at: datetime


class BreakoutEventSummary(BaseModel):
    id: uuid.UUID
    trigger_line_id: uuid.UUID | None = None
    exchange: str
    symbol: str
    event_type: str
    event_time: datetime
    breakout_or_breakdown_price: float | None = None
    volume_ratio: float | None = None
    status: str


class PaperTradeSummary(BaseModel):
    id: uuid.UUID
    signal_id: uuid.UUID | None = None
    trigger_line_id: uuid.UUID | None = None
    exchange: str
    symbol: str
    action: str
    status: str
    quantity: int
    capital_used: float
    pnl: float | None = None
    pnl_percent: float | None = None


class SymbolDashboardResponse(BaseModel):
    exchange: str
    symbol: str
    watchlists: list[dict]
    active_trigger_lines: list[dict]
    historical_trigger_lines: list[dict]
    latest_signals: list[dict]
    breakout_history: list[dict]
    paper_trades: list[dict]
    paper_trade_summary: dict
