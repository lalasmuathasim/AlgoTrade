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
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token, get_current_zerodha_session


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
    latest_prices_state: dict[str, dict] = {}
    current_access_token_configured = auth.has_access_token()
    runtime_finalized_candles_count = 0
    runtime_signals_created_count = 0
    runtime_breakout_events_count = 0
    runtime_last_breakout_event_id: str | None = None
    runtime_last_breakout_event_symbol: str | None = None

    def publish_runtime_state(
        *,
        status: str,
        message: str,
        selected_watchlist,
        subscriptions: list[dict],
        transport: str,
        last_tick_at: datetime | None = None,
        last_tick_symbol: str | None = None,
        latest_prices: dict[str, dict] | None = None,
        finalized_candles_count: int = 0,
        signals_created_count: int = 0,
        breakout_events_count: int = 0,
        last_finalized_candle: dict | None = None,
        last_breakout_event_id: str | None = None,
        last_breakout_event_symbol: str | None = None,
        last_signal_id: str | None = None,
        last_signal_symbol: str | None = None,
    ) -> None:
        subscription_keys = {f"{row['exchange']}:{row['symbol']}" for row in subscriptions}
        scoped_latest_prices = {
            key: value
            for key, value in (latest_prices or latest_prices_state).items()
            if key in subscription_keys
        }
        publish_live_engine_runtime(
            build_live_engine_runtime_snapshot(
                status=status,
                message=message,
                selected_watchlist=selected_watchlist,
                subscriptions=subscriptions,
                transport=transport,
                credentials_configured=auth.has_credentials(),
                access_token_configured=current_access_token_configured,
                last_tick_at=last_tick_at,
                last_tick_symbol=last_tick_symbol,
                finalized_candles_count=finalized_candles_count,
                signals_created_count=signals_created_count,
                breakout_events_count=breakout_events_count,
                last_finalized_candle=last_finalized_candle,
                last_breakout_event_id=last_breakout_event_id,
                last_breakout_event_symbol=last_breakout_event_symbol,
                last_signal_id=last_signal_id,
                last_signal_symbol=last_signal_symbol,
                latest_prices=scoped_latest_prices,
            )
        )

    def handle_ticks(ticks):
        nonlocal runtime_finalized_candles_count
        nonlocal runtime_signals_created_count
        nonlocal runtime_breakout_events_count
        nonlocal runtime_last_breakout_event_id
        nonlocal runtime_last_breakout_event_symbol
        latest_tick = max(ticks, key=lambda item: item.timestamp) if ticks else None
        for tick in ticks:
            latest_prices_state[f"{tick.exchange}:{tick.symbol}"] = {
                "price": tick.last_price,
                "timestamp": tick.timestamp.astimezone(UTC).isoformat(),
                "source": "tick",
            }
        with SessionLocal() as db:
            result = processor.process_ticks(db, ticks)
            subscriptions = subscription_manager.describe_active_subscriptions(db)
            last_finalized_candle = result.finalized_candles[-1] if result.finalized_candles else None
            last_breakout_event = result.breakout_events[-1] if result.breakout_events else None
            last_signal = result.signals[-1] if result.signals else None
            runtime_finalized_candles_count += result.finalized_candles_count
            runtime_signals_created_count += result.signals_created_count
            runtime_breakout_events_count += result.breakout_events_count
            if last_breakout_event is not None:
                runtime_last_breakout_event_id = str(last_breakout_event.id)
                runtime_last_breakout_event_symbol = last_breakout_event.symbol
            publish_runtime_state(
                status="STREAMING",
                message=f"Processed {result.ticks_processed} ticks, finalized {result.finalized_candles_count} candles, and created {result.signals_created_count} signals.",
                selected_watchlist=get_selected_watchlist(db),
                subscriptions=subscriptions,
                transport="kite_ticker",
                last_tick_at=latest_tick.timestamp if latest_tick else datetime.now(UTC),
                last_tick_symbol=latest_tick.symbol if latest_tick else None,
                latest_prices=latest_prices_state,
                finalized_candles_count=runtime_finalized_candles_count,
                signals_created_count=runtime_signals_created_count,
                breakout_events_count=runtime_breakout_events_count,
                last_finalized_candle={
                    "symbol": last_finalized_candle.symbol,
                    "exchange": last_finalized_candle.exchange,
                    "candle_start": last_finalized_candle.candle_start.astimezone(UTC).isoformat(),
                    "candle_end": last_finalized_candle.candle_end.astimezone(UTC).isoformat(),
                    "open": last_finalized_candle.open,
                    "high": last_finalized_candle.high,
                    "low": last_finalized_candle.low,
                    "close": last_finalized_candle.close,
                    "volume": last_finalized_candle.volume,
                }
                if last_finalized_candle
                else None,
                last_breakout_event_id=runtime_last_breakout_event_id,
                last_breakout_event_symbol=runtime_last_breakout_event_symbol,
                last_signal_id=str(last_signal.id) if last_signal else None,
                last_signal_symbol=last_signal.symbol if last_signal else None,
            )

    while True:
        with SessionLocal() as db:
            selected_watchlist = get_selected_watchlist(db)
            subscriptions = subscription_manager.describe_active_subscriptions(db)
            zerodha_session = get_current_zerodha_session(db)
            access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
            if (
                zerodha_session is not None
                and zerodha_session.access_token_expires_at is not None
                and zerodha_session.access_token_expires_at <= datetime.now(UTC)
                and not settings.zerodha_access_token
            ):
                access_token = None
            current_access_token_configured = bool(access_token)
        result = client.connect_forever(
            subscriptions,
            handle_ticks,
            on_state_change=lambda state: publish_runtime_state(
                status=state["status"],
                message=state["message"],
                selected_watchlist=selected_watchlist,
                subscriptions=subscriptions,
                transport=state.get("transport", "kite_ticker"),
            ),
            access_token=access_token,
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
