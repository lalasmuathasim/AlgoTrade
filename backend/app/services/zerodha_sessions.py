import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.models import ZerodhaSession


def get_current_zerodha_session(db: Session) -> ZerodhaSession | None:
    return db.scalar(select(ZerodhaSession).order_by(desc(ZerodhaSession.updated_at), desc(ZerodhaSession.created_at)).limit(1))


def upsert_zerodha_session(
    db: Session,
    *,
    access_token: str,
    connected_by_user_id: uuid.UUID | None,
    login_time: datetime | None,
    access_token_expires_at: datetime | None,
    profile_user_id: str | None,
    profile_user_name: str | None,
    profile_email: str | None,
    status: str = "CONNECTED",
) -> ZerodhaSession:
    session = get_current_zerodha_session(db)
    if session is None:
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token=access_token,
            connected_by_user_id=connected_by_user_id,
            login_time=login_time,
            access_token_expires_at=access_token_expires_at,
            profile_user_id=profile_user_id,
            profile_user_name=profile_user_name,
            profile_email=profile_email,
            status=status,
            last_validated_at=None,
        )
        db.add(session)
    else:
        session.access_token = access_token
        session.connected_by_user_id = connected_by_user_id
        session.login_time = login_time
        session.access_token_expires_at = access_token_expires_at
        session.profile_user_id = profile_user_id
        session.profile_user_name = profile_user_name
        session.profile_email = profile_email
        session.status = status
        session.last_validated_at = None

    db.commit()
    db.refresh(session)
    return session


def mark_zerodha_session_status(db: Session, session: ZerodhaSession, *, status: str) -> ZerodhaSession:
    session.status = status
    session.last_validated_at = datetime.now(UTC)
    db.commit()
    db.refresh(session)
    return session
