from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Watchlist


def get_selected_watchlist(db: Session) -> Watchlist | None:
    if not hasattr(db, "scalar"):
        return None
    return db.scalar(select(Watchlist).where(Watchlist.is_selected.is_(True)).limit(1))


def ensure_selected_watchlist(db: Session) -> Watchlist | None:
    if not hasattr(db, "scalar"):
        return None
    selected = get_selected_watchlist(db)
    if selected is not None:
        return selected

    first_watchlist = db.scalar(select(Watchlist).order_by(Watchlist.created_at, Watchlist.name).limit(1))
    if first_watchlist is None:
        return None

    first_watchlist.is_selected = True
    db.commit()
    if hasattr(db, "refresh"):
        db.refresh(first_watchlist)
    return first_watchlist


def set_selected_watchlist(db: Session, watchlist: Watchlist) -> Watchlist:
    existing = db.scalars(select(Watchlist).where(Watchlist.is_selected.is_(True))).all()
    for row in existing:
        row.is_selected = row.id == watchlist.id

    if not existing:
        watchlist.is_selected = True

    db.commit()
    if hasattr(db, "refresh"):
        db.refresh(watchlist)
    return watchlist
