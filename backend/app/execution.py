import logging

from backend.app.config import get_settings
from backend.app.models import TradingSignal


logger = logging.getLogger(__name__)
settings = get_settings()


def execute_order_placeholder(signal: TradingSignal) -> None:
    logger.info(
        "Execution placeholder invoked for signal %s (%s %s %s)",
        signal.id,
        signal.exchange,
        signal.symbol,
        signal.action,
    )
    if settings.zerodha_live_trading_enabled:
        logger.info("Live trading flag is enabled, but order placement remains placeholder-only in this build")
    else:
        logger.info("Live Zerodha execution is disabled by environment flag")
