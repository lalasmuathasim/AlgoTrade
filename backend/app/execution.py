import logging

from backend.app.schemas import QueuedTradingSignal


logger = logging.getLogger(__name__)


def execute_order_placeholder(signal: QueuedTradingSignal) -> None:
    logger.info(
        "Execution placeholder invoked for payload %s (%s %s %s %s)",
        signal.signal_id,
        signal.event_category,
        signal.exchange,
        signal.symbol,
        signal.action or signal.line_type or signal.event_type,
    )
    logger.info("Zerodha order execution is intentionally disabled")
