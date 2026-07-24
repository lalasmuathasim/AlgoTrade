import logging
import time
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal, initialize_runtime_state
from backend.app.models import ScanExecution
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.paper_trading_service import ensure_settings
from backend.app.services.trading_time import now_in_trading_timezone
from backend.app.services.zerodha import HistoricalCandleProvider, ZerodhaApiClient, ZerodhaAuthService
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token, get_current_zerodha_session


settings = get_settings()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def _scheduled_scan_time(runtime_settings) -> str:
    configured = getattr(runtime_settings, "daily_structure_rebuild_time", None) or settings.daily_scan_time
    return configured


def _should_run(now_local: datetime, scheduled_time: str) -> bool:
    scan_hour, scan_minute = [int(part) for part in scheduled_time.split(":", maxsplit=1)]
    return (now_local.hour, now_local.minute) >= (scan_hour, scan_minute)


def _record_skipped_scan(db, scan_date: date, reason: str) -> None:
    existing = db.scalar(
        select(ScanExecution).where(
            ScanExecution.scan_name == "daily_market_scan",
            ScanExecution.scan_date == scan_date,
            ScanExecution.status == "SKIPPED",
            ScanExecution.error_message == reason,
        )
    )
    if existing is not None:
        return

    now_utc = datetime.now(UTC)
    db.add(
        ScanExecution(
            scan_name="daily_market_scan",
            scan_date=scan_date,
            status="SKIPPED",
            symbols_scanned=0,
            trigger_lines_created=0,
            trigger_lines_updated=0,
            started_at=now_utc,
            finished_at=now_utc,
            error_message=reason,
        )
    )
    db.commit()


def _zerodha_skip_reason(db, now_utc: datetime) -> str | None:
    if not settings.zerodha_api_key:
        return "Skipped daily scan: ZERODHA_API_KEY is not configured."

    session = get_current_zerodha_session(db)
    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    if not access_token:
        return "Skipped daily scan: Zerodha access token is not configured."

    if session is not None and session.access_token_expires_at and session.access_token_expires_at <= now_utc:
        return "Skipped daily scan: Zerodha access token is expired."

    return None


def _skip_reason_from_exception(exc: Exception) -> str | None:
    if isinstance(exc, RuntimeError) and "not configured" in str(exc).lower():
        return "Skipped daily scan: Zerodha authentication is not configured."

    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        return "Skipped daily scan: Zerodha access token is expired or invalid."

    return None


def _build_scheduler_scanner(db) -> DailyMarketScanner:
    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    return DailyMarketScanner(
        provider=HistoricalCandleProvider(
            client=ZerodhaApiClient(
                auth_service=ZerodhaAuthService(),
                access_token=access_token,
            )
        )
    )


def _run_due_scan(db, now_local: datetime, scanner: DailyMarketScanner) -> str:
    existing = db.scalar(
        select(ScanExecution).where(
            ScanExecution.scan_name == "daily_market_scan",
            ScanExecution.scan_date == now_local.date(),
            ScanExecution.status == "COMPLETED",
        )
    )
    if existing is not None:
        return "already_completed"

    skip_reason = _zerodha_skip_reason(db, now_local.astimezone(UTC))
    if skip_reason is not None:
        logger.warning(skip_reason)
        _record_skipped_scan(db, now_local.date(), skip_reason)
        return "skipped"

    logger.info("Running scheduled daily market scan for %s", now_local.date())
    try:
        scanner.run(db, scan_date=now_local.date())
    except Exception as exc:  # noqa: BLE001
        skip_reason = _skip_reason_from_exception(exc)
        if skip_reason is None:
            raise
        logger.warning(skip_reason)
        _record_skipped_scan(db, now_local.date(), skip_reason)
        return "skipped"

    return "completed"


def run_scheduler() -> None:
    logger.info("Starting Qubitx scheduler")
    initialize_runtime_state()

    while True:
        with SessionLocal() as db:
            runtime_settings = ensure_settings(db)
            now_local = now_in_trading_timezone(runtime_settings)
            auto_rebuild_enabled = bool(getattr(runtime_settings, "daily_structure_rebuild_enabled", True))
            scheduled_time = _scheduled_scan_time(runtime_settings)

        if auto_rebuild_enabled and _should_run(now_local, scheduled_time):
            with SessionLocal() as db:
                scanner = _build_scheduler_scanner(db)
                _run_due_scan(db, now_local, scanner)
        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    run_scheduler()
