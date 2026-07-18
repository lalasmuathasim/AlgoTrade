import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class BrokerOrder(Base):
    __tablename__ = "broker_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="PAPER", server_default="PAPER")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", server_default="PENDING")
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="ZERODHA", server_default="ZERODHA")
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
