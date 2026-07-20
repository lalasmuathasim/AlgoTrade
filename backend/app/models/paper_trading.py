import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class PaperTradingSetting(Base):
    __tablename__ = "paper_trading_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    starting_capital: Mapped[float] = mapped_column(Float, nullable=False)
    capital_per_trade: Mapped[float] = mapped_column(Float, nullable=False)
    fixed_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_per_trade: Mapped[float] = mapped_column(Float, nullable=False)
    brokerage_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, nullable=False)
    default_quantity_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="RISK_BASED",
        server_default="RISK_BASED",
    )
    paper_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    live_trading_enabled: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="FALSE")
    require_candle_close_beyond_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    buy_volume_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    sell_volume_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    entry_buffer_ticks: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_buffer_ticks: Mapped[float] = mapped_column(Float, nullable=False)
    target_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="NEAREST_DAILY_SWING", server_default="NEAREST_DAILY_SWING")
    fallback_risk_reward_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=2.0, server_default="2.0")
    use_nearest_daily_swing_target: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    minimum_reward_risk_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="LIMIT", server_default="LIMIT")
    product_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MIS", server_default="MIS")
    reentry_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    allow_repeat_entry_same_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="FALSE")
    max_quantity_per_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_zero_previous_volume: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    minimum_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_exchanges: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default='["NSE","BSE"]')
    daily_candle_lookback: Mapped[int] = mapped_column(Integer, nullable=False)
    swing_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_gap_percent: Mapped[float] = mapped_column(Float, nullable=False)
    min_swing_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    max_loss_per_symbol_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=2500.0, server_default="2500")
    block_new_trades_after_max_daily_loss: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    no_trade_after_time: Mapped[str | None] = mapped_column(String(10), nullable=True, default="15:00")
    market_hours_guard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    exchange_charges_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    use_cost_adjusted_pnl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    enable_confidence_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="FALSE")
    minimum_confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.6, server_default="0.6")
    confidence_source: Mapped[str] = mapped_column(String(30), nullable=False, default="RULES_ONLY", server_default="RULES_ONLY")
    allow_low_confidence_paper_trades_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    block_live_trades_below_confidence_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="TRUE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_signals.id"), nullable=True)
    trigger_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trigger_lines.id"), nullable=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    simulated_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    capital_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    risk_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="PAPER", server_default="PAPER")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default="OPEN")
    simulated_exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
