import logging
import time
from datetime import UTC, datetime

from backend.app.config import get_settings
from backend.app.database import SessionLocal, initialize_runtime_state
from backend.app.queue import publish_live_engine_runtime
from backend.app.services.market_stream import MarketDataProcessor
from backend.app.services.live_engine_runtime import build_live_engine_runtime_snapshot
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.services.zerodha import SubscriptionManager, ZerodhaAuthService, ZerodhaWebSocketClient


settings = get_settings()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def run_live_engine() -> None:
    logger.info("Starting Qubitx live engine")
    initialize_runtime_state()
    processor = MarketDataProcessor()
    client = ZerodhaWebSocketClient()
    subscription_manager = SubscriptionManager()
    auth = ZerodhaAuthService()

    def publish_runtime_state(
        *,
        status: str,
        message: str,
        selected_watchlist,
        subscriptions: list[dict],
        transport: str,
        last_tick_at: datetime | None = None,
        last_tick_symbol: str | None = None,
    ) -> None:
        publish_live_engine_runtime(
            build_live_engine_runtime_snapshot(
                status=status,
                message=message,
                selected_watchlist=selected_watchlist,
                subscriptions=subscriptions,
                transport=transport,
                credentials_configured=auth.has_credentials(),
                access_token_configured=auth.has_access_token(),
                last_tick_at=last_tick_at,
                last_tick_symbol=last_tick_symbol,
            )
        )

    def handle_ticks(ticks):
        latest_tick = max(ticks, key=lambda item: item.timestamp) if ticks else None
        with SessionLocal() as db:
            processor.process_ticks(db, ticks)
            subscriptions = subscription_manager.describe_active_subscriptions(db)
            publish_runtime_state(
                status="STREAMING",
                message=f"Processed {len(ticks)} ticks for the selected watchlist.",
                selected_watchlist=get_selected_watchlist(db),
                subscriptions=subscriptions,
                transport="kite_ticker",
                last_tick_at=latest_tick.timestamp if latest_tick else datetime.now(UTC),
                last_tick_symbol=latest_tick.symbol if latest_tick else None,
            )

    while True:
        with SessionLocal() as db:
            selected_watchlist = get_selected_watchlist(db)
            subscriptions = subscription_manager.describe_active_subscriptions(db)
        result = client.connect_forever(
            subscriptions,
            handle_ticks,
            on_state_change=lambda state: publish_runtime_state(
                status=state["status"],
                message=state["message"],
                selected_watchlist=selected_watchlist,
                subscriptions=subscriptions,
                transport=state.get("transport", "kite_ticker"),
            )
        )
        publish_runtime_state(
            status=result["status"],
            message=result["message"],
            selected_watchlist=selected_watchlist,
            subscriptions=subscriptions,
            transport=result.get("transport", "kite_ticker"),
        )
        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    run_live_engine()
