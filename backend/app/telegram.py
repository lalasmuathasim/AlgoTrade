import logging
import time

import httpx

from backend.app.config import get_settings
from backend.app.models import TradingSignal


logger = logging.getLogger(__name__)
settings = get_settings()


def send_telegram_notification(signal: TradingSignal, max_retries: int = 3) -> str:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.info("Telegram configuration missing; skipping notification")
        return "SKIPPED"

    message = (
        "Trading signal received\n"
        f"Exchange: {signal.exchange}\n"
        f"Symbol: {signal.symbol}\n"
        f"Action: {signal.action}\n"
        f"Strategy: {signal.strategy or 'N/A'}\n"
        f"Timeframe: {signal.timeframe or 'N/A'}\n"
        f"Entry: {signal.entry_price if signal.entry_price is not None else 'N/A'}\n"
        f"Stop Loss: {signal.stop_loss if signal.stop_loss is not None else 'N/A'}\n"
        f"Target: {signal.target if signal.target is not None else 'N/A'}\n"
        f"Trigger Line ID: {signal.trigger_line_id or 'N/A'}\n"
        f"Breakout Event ID: {signal.breakout_event_id or 'N/A'}\n"
        f"Signal ID: {signal.id}"
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            logger.info("Telegram notification sent for signal %s", signal.id)
            return "SENT"
        except httpx.HTTPError:
            logger.exception(
                "Telegram notification failed for signal %s on attempt %s/%s",
                signal.id,
                attempt,
                max_retries,
            )
            if attempt < max_retries:
                time.sleep(1)

    return "FAILED"
