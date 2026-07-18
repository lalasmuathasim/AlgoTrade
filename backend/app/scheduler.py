import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal, initialize_runtime_state
from backend.app.models import ScanExecution
from backend.app.services.market_scanner import DailyMarketScanner


settings = get_settings()
market_tz = ZoneInfo(settings.market_timezone)


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def _should_run(now_local: datetime) -> bool:
    scan_hour, scan_minute = [int(part) for part in settings.daily_scan_time.split(":", maxsplit=1)]
    return (now_local.hour, now_local.minute) >= (scan_hour, scan_minute)


def run_scheduler() -> None:
    logger.info("Starting Qubitx scheduler")
    initialize_runtime_state()
    scanner = DailyMarketScanner()

    while True:
        now_local = datetime.now(market_tz)
        if _should_run(now_local):
            with SessionLocal() as db:
                existing = db.scalar(
                    select(ScanExecution).where(
                        ScanExecution.scan_name == "daily_market_scan",
                        ScanExecution.scan_date == now_local.date(),
                        ScanExecution.status == "COMPLETED",
                    )
                )
                if existing is None:
                    logger.info("Running scheduled daily market scan for %s", now_local.date())
                    scanner.run(db, scan_date=now_local.date())
        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    run_scheduler()
