import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class ScanExecution(Base):
    __tablename__ = "scan_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_name: Mapped[str] = mapped_column(String(50), nullable=False)
    scan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    symbols_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trigger_lines_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trigger_lines_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
