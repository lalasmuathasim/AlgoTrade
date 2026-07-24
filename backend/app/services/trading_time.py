import logging
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()
DEFAULT_TRADING_TIMEZONE = "Asia/Kolkata"


@lru_cache(maxsize=32)
def _load_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def validate_trading_timezone_name(name: str | None) -> str:
    candidate = (name or "").strip() or settings.market_timezone or DEFAULT_TRADING_TIMEZONE
    try:
        _load_timezone(candidate)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown trading time zone: {candidate}") from exc
    return candidate


def resolve_trading_timezone_name(runtime_settings=None) -> str:
    candidate = getattr(runtime_settings, "trading_timezone", None) if runtime_settings is not None else None
    candidate = (candidate or "").strip() or settings.market_timezone or DEFAULT_TRADING_TIMEZONE
    try:
        _load_timezone(candidate)
        return candidate
    except ZoneInfoNotFoundError:
        logger.warning(
            "Invalid trading timezone configured (%s). Falling back to %s.",
            candidate,
            DEFAULT_TRADING_TIMEZONE,
        )
        return DEFAULT_TRADING_TIMEZONE


def get_trading_timezone(runtime_settings=None) -> ZoneInfo:
    return _load_timezone(resolve_trading_timezone_name(runtime_settings))


def now_in_trading_timezone(runtime_settings=None) -> datetime:
    return datetime.now(get_trading_timezone(runtime_settings))


def current_trading_date(runtime_settings=None) -> date:
    return now_in_trading_timezone(runtime_settings).date()


def trading_day_bounds(day: date, runtime_settings=None) -> tuple[datetime, datetime]:
    timezone = get_trading_timezone(runtime_settings)
    start_local = datetime.combine(day, time.min, tzinfo=timezone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def to_trading_timezone(value: datetime, runtime_settings=None) -> datetime:
    timezone = get_trading_timezone(runtime_settings)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)
