import logging
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies import require_admin_user
from backend.app.models import User
from backend.app.schemas import ZerodhaConnectionTestResponse
from backend.app.services.zerodha import ZerodhaAuthService
from backend.app.services.zerodha_sessions import (
    get_current_zerodha_session,
    mark_zerodha_session_status,
    upsert_zerodha_session,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/zerodha", tags=["zerodha"], dependencies=[Depends(require_admin_user)])


def _configuration_redirect(**params: str) -> RedirectResponse:
    query = urlencode(params)
    url = f"/configuration?{query}" if query else "/configuration"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/login")
def zerodha_login() -> RedirectResponse:
    auth = ZerodhaAuthService()
    login_url = auth.build_login_url()
    if not auth.has_credentials() or not login_url:
        raise HTTPException(status_code=503, detail="Zerodha is not configured")
    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
def zerodha_callback(
    request_token: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    auth = ZerodhaAuthService()
    if not auth.has_credentials():
        return _configuration_redirect(zerodha_status="not_configured")

    if status_value and status_value.lower() != "success":
        return _configuration_redirect(zerodha_status="error")

    if not request_token:
        return _configuration_redirect(zerodha_status="missing_request_token")

    try:
        token_data = auth.exchange_request_token(request_token)
        login_time = auth.parse_login_time(token_data.get("login_time"))
        expires_at = auth.compute_access_token_expiry(login_time)
        upsert_zerodha_session(
            db,
            access_token=token_data["access_token"],
            connected_by_user_id=current_user.id,
            login_time=login_time,
            access_token_expires_at=expires_at,
            profile_user_id=token_data.get("user_id"),
            profile_user_name=token_data.get("user_name"),
            profile_email=token_data.get("email"),
            status="CONNECTED",
        )
        return _configuration_redirect(zerodha_status="connected")
    except httpx.HTTPError:
        logger.warning("Zerodha token exchange failed during callback")
        return _configuration_redirect(zerodha_status="token_exchange_failed")
    except Exception:
        logger.warning("Unexpected Zerodha callback failure")
        return _configuration_redirect(zerodha_status="callback_failed")


@router.get("/test", response_model=ZerodhaConnectionTestResponse)
def zerodha_test_connection(db: Session = Depends(get_db)) -> ZerodhaConnectionTestResponse:
    auth = ZerodhaAuthService()
    session = get_current_zerodha_session(db)
    credentials_configured = auth.has_credentials()
    token = auth.resolve_access_token(session.access_token if session else None)
    token_present = bool(token)

    if not credentials_configured:
        return ZerodhaConnectionTestResponse(
            status="Not Configured",
            connected=False,
            credentials_configured=False,
            session_present=bool(session),
            token_present=token_present,
            can_connect=False,
            can_test_connection=token_present,
        )

    if session is None and not token_present:
        return ZerodhaConnectionTestResponse(
            status="Ready To Connect",
            connected=False,
            credentials_configured=True,
            session_present=False,
            token_present=False,
            can_connect=True,
            can_test_connection=False,
        )

    if session is not None and session.access_token_expires_at and session.access_token_expires_at <= datetime.now(UTC):
        mark_zerodha_session_status(db, session, status="EXPIRED")
        return ZerodhaConnectionTestResponse(
            status="Expired",
            connected=False,
            credentials_configured=True,
            session_present=True,
            token_present=token_present,
            can_connect=True,
            can_test_connection=token_present,
            login_time=session.login_time,
            access_token_expires_at=session.access_token_expires_at,
            profile_user_id=session.profile_user_id,
            profile_user_name=session.profile_user_name,
            profile_email=session.profile_email,
        )

    try:
        profile = auth.fetch_user_profile(token)
        if session is not None:
            mark_zerodha_session_status(db, session, status="CONNECTED")
        return ZerodhaConnectionTestResponse(
            status="Connected",
            connected=True,
            credentials_configured=True,
            session_present=session is not None,
            token_present=True,
            can_connect=True,
            can_test_connection=True,
            login_time=session.login_time if session else None,
            access_token_expires_at=session.access_token_expires_at if session else None,
            profile_user_id=profile.get("user_id") or (session.profile_user_id if session else None),
            profile_user_name=profile.get("user_name") or (session.profile_user_name if session else None),
            profile_email=profile.get("email") or (session.profile_email if session else None),
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            if session is not None:
                mark_zerodha_session_status(db, session, status="INVALID_TOKEN")
            return ZerodhaConnectionTestResponse(
                status="Invalid Token",
                connected=False,
                credentials_configured=True,
                session_present=session is not None,
                token_present=True,
                can_connect=True,
                can_test_connection=True,
                login_time=session.login_time if session else None,
                access_token_expires_at=session.access_token_expires_at if session else None,
                profile_user_id=session.profile_user_id if session else None,
                profile_user_name=session.profile_user_name if session else None,
                profile_email=session.profile_email if session else None,
            )
        raise HTTPException(status_code=502, detail="Unable to reach Zerodha profile API") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Unable to reach Zerodha profile API") from exc
