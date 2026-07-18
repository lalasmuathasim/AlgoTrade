import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_token: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    exchange_token: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, default="NSE", server_default="NSE")
    segment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
