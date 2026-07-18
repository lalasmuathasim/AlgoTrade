import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
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
    buy_volume_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    sell_volume_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    entry_buffer_ticks: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_buffer_ticks: Mapped[float] = mapped_column(Float, nullable=False)
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
