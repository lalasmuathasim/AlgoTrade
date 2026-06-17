import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class TriggerLine(Base):
    __tablename__ = "trigger_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("watchlists.id"), nullable=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    line_type: Mapped[str] = mapped_column(String(10), nullable=False)
    line_price: Mapped[float] = mapped_column(Float, nullable=False)
    line_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    line_drawn_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_timeframe: Mapped[str] = mapped_column(String(20), nullable=False, default="Daily", server_default="Daily")
    lookback_candles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_gap_percent_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_swing_distance_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_high_1_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_high_1_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    swing_high_2_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_high_2_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    higher_swing_high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_swing_high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_low_1_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_low_1_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    swing_low_2_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_low_2_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lower_swing_low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    higher_swing_low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    swing_gap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    nearest_daily_swing_high_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    nearest_daily_swing_low_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
