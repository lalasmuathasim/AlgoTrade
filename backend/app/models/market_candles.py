import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class MarketCandle(Base):
    __tablename__ = "market_candles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False)
    candle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    candle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="ZERODHA", server_default="ZERODHA")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
