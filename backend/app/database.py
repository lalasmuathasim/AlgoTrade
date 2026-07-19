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


def verify_database_connectivity() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def initialize_runtime_state() -> None:
    from backend.app.mock_data import seed_mock_data_if_enabled
    from backend.app.services.auth_service import ensure_initial_admin_user
    from backend.app.services.watchlists import ensure_selected_watchlist

    verify_database_connectivity()
    with SessionLocal() as db:
        ensure_initial_admin_user(db)
    seed_mock_data_if_enabled()
    with SessionLocal() as db:
        ensure_selected_watchlist(db)
