import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    from backend.app import models  # noqa: F401
    from backend.app.mock_data import seed_mock_data_if_enabled
    from backend.app.services.auth_service import ensure_initial_admin_user

    logger.info("Creating database tables if they do not exist")
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    with SessionLocal() as db:
        ensure_initial_admin_user(db)
    seed_mock_data_if_enabled()


def ensure_schema_compatibility() -> None:
    statements = [
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS exchange VARCHAR(20) DEFAULT 'NSE'",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS event_category VARCHAR(30) DEFAULT 'TRADING_SIGNAL'",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS watchlist_id UUID",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS trigger_line_id UUID",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS breakout_event_id UUID",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS notification_status VARCHAR(20) DEFAULT 'PENDING'",
        "ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS error_message TEXT",
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
