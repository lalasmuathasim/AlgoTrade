import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import User
from backend.app.schemas.auth import SignupPayload
from backend.app.security import hash_password


logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized = normalize_email(email)
    return db.scalar(select(User).where(User.email == normalized).limit(1))


def create_pending_user(db: Session, payload: SignupPayload) -> User:
    user = User(
        email=normalize_email(payload.email),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="USER",
        approval_status="PENDING",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_initial_admin_user(db: Session) -> None:
    if not settings.initial_admin_email or not settings.initial_admin_password:
        logger.info("Initial admin credentials are not configured")
        return

    admin_email = normalize_email(settings.initial_admin_email)
    existing = get_user_by_email(db, admin_email)
    if existing is None:
        admin = User(
            email=admin_email,
            full_name=settings.initial_admin_name or "Platform Administrator",
            password_hash=hash_password(settings.initial_admin_password),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
            approved_at=datetime.now(UTC),
        )
        db.add(admin)
        db.commit()
        logger.info("Seeded initial admin user %s", admin_email)
        return

    changed = False
    if existing.role != "ADMIN":
        existing.role = "ADMIN"
        changed = True
    if existing.approval_status != "APPROVED":
        existing.approval_status = "APPROVED"
        existing.approved_at = existing.approved_at or datetime.now(UTC)
        changed = True
    if not existing.is_active:
        existing.is_active = True
        changed = True

    if changed:
        db.commit()
        logger.info("Updated initial admin privileges for %s", admin_email)


def list_pending_users(db: Session) -> list[User]:
    return db.scalars(select(User).where(User.approval_status == "PENDING").order_by(User.created_at)).all()


def approve_user(db: Session, user_id: UUID, admin_user: User) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    user.approval_status = "APPROVED"
    user.approved_at = datetime.now(UTC)
    user.approved_by_user_id = admin_user.id
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


def reject_user(db: Session, user_id: UUID, admin_user: User) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    user.approval_status = "REJECTED"
    user.approved_at = None
    user.approved_by_user_id = admin_user.id
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user
