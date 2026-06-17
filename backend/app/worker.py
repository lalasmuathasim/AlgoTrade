import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings
from backend.app.database import SessionLocal, create_tables
from backend.app.execution import execute_order_placeholder
from backend.app.models import BreakoutEvent, PaperTrade, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.queue import dequeue_signal, enqueue_signal
from backend.app.schemas import QueuedTradingSignal
from backend.app.services.paper_trading_service import generate_paper_trade_from_signal
from backend.app.telegram import send_telegram_notification


settings = get_settings()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def mark_signal_retrying(signal_id: uuid.UUID, error_message: str) -> None:
    with SessionLocal() as db:
        signal = db.get(TradingSignal, signal_id)
        if signal is None:
            return

        signal.status = "RETRYING"
        signal.error_message = error_message[:1000]
        db.commit()


def mark_signal_failed(signal_id: uuid.UUID, error_message: str) -> None:
    with SessionLocal() as db:
        signal = db.get(TradingSignal, signal_id)
        if signal is None:
            return

        signal.status = "FAILED"
        signal.error_message = error_message[:1000]
        signal.processed_at = datetime.now(UTC)
        db.commit()


def finalize_signal(signal_id: uuid.UUID, notification_status: str) -> None:
    with SessionLocal() as db:
        signal = db.get(TradingSignal, signal_id)
        if signal is None:
            return

        signal.status = "PROCESSED"
        signal.notification_status = notification_status
        signal.processed_at = datetime.now(UTC)
        signal.error_message = None
        if notification_status == "FAILED":
            signal.error_message = "Telegram notification failed after retries"
        db.commit()


def requeue_signal(signal_data: QueuedTradingSignal, error_message: str) -> None:
    try:
        if signal_data.retry_count >= settings.worker_max_retries:
            logger.error(
                "Signal %s exhausted retries after %s attempts",
                signal_data.signal_id,
                signal_data.retry_count,
            )
            mark_signal_failed(signal_data.signal_id, error_message)
            return

        retry_payload = signal_data.model_copy(update={"retry_count": signal_data.retry_count + 1})
        enqueue_signal(retry_payload)
        mark_signal_retrying(signal_data.signal_id, error_message)
        logger.warning(
            "Re-queued signal %s for retry %s/%s",
            signal_data.signal_id,
            retry_payload.retry_count,
            settings.worker_max_retries,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to re-queue signal %s", signal_data.signal_id)


def resolve_watchlist(db, signal_data: QueuedTradingSignal) -> Watchlist | None:
    watchlist = None
    if signal_data.watchlist_id:
        watchlist = db.get(Watchlist, signal_data.watchlist_id)
    elif signal_data.watchlist_name:
        watchlist = db.scalar(select(Watchlist).where(Watchlist.name == signal_data.watchlist_name).limit(1))

    if watchlist is None and signal_data.watchlist_name:
        watchlist = Watchlist(
            id=signal_data.watchlist_id or uuid.uuid4(),
            name=signal_data.watchlist_name,
            description=signal_data.watchlist_description,
            exchange=signal_data.exchange,
        )
        db.add(watchlist)
        db.flush()

    return watchlist


def ensure_watchlist_symbol(db, watchlist: Watchlist | None, signal_data: QueuedTradingSignal) -> None:
    if watchlist is None:
        return

    existing = db.scalar(
        select(WatchlistSymbol).where(
            WatchlistSymbol.watchlist_id == watchlist.id,
            WatchlistSymbol.exchange == signal_data.exchange,
            WatchlistSymbol.symbol == signal_data.symbol,
        )
    )
    if existing is not None:
        existing.is_active = True
        return

    db.add(
        WatchlistSymbol(
            watchlist_id=watchlist.id,
            exchange=signal_data.exchange,
            symbol=signal_data.symbol,
            is_active=True,
        )
    )


def upsert_trigger_line(db, signal_data: QueuedTradingSignal, watchlist: Watchlist | None) -> TriggerLine:
    line_id = signal_data.trigger_line_id or uuid.uuid4()
    trigger_line = db.get(TriggerLine, line_id)
    if trigger_line is None:
        trigger_line = TriggerLine(id=line_id)
        db.add(trigger_line)

    trigger_line.watchlist_id = watchlist.id if watchlist else trigger_line.watchlist_id
    trigger_line.exchange = signal_data.exchange
    trigger_line.symbol = signal_data.symbol
    trigger_line.line_type = signal_data.line_type or "BUY"
    trigger_line.line_price = signal_data.line_price or 0.0
    trigger_line.line_status = signal_data.line_status or "ACTIVE"
    trigger_line.line_drawn_date = signal_data.line_drawn_date
    trigger_line.source_timeframe = signal_data.source_timeframe or "Daily"
    trigger_line.lookback_candles = signal_data.lookback_candles
    trigger_line.max_gap_percent_used = signal_data.max_gap_percent_used
    trigger_line.min_swing_distance_used = signal_data.min_swing_distance_used
    trigger_line.swing_gap_percent = signal_data.swing_gap_percent

    if trigger_line.line_type == "BUY":
        trigger_line.swing_high_1_price = signal_data.swing_1_price
        trigger_line.swing_high_1_date = signal_data.swing_1_date
        trigger_line.swing_high_2_price = signal_data.swing_2_price
        trigger_line.swing_high_2_date = signal_data.swing_2_date
        if signal_data.swing_1_price is not None and signal_data.swing_2_price is not None:
            trigger_line.higher_swing_high_price = max(signal_data.swing_1_price, signal_data.swing_2_price)
            trigger_line.lower_swing_high_price = min(signal_data.swing_1_price, signal_data.swing_2_price)
        trigger_line.nearest_daily_swing_high_target = signal_data.nearest_target
    else:
        trigger_line.swing_low_1_price = signal_data.swing_1_price
        trigger_line.swing_low_1_date = signal_data.swing_1_date
        trigger_line.swing_low_2_price = signal_data.swing_2_price
        trigger_line.swing_low_2_date = signal_data.swing_2_date
        if signal_data.swing_1_price is not None and signal_data.swing_2_price is not None:
            trigger_line.lower_swing_low_price = min(signal_data.swing_1_price, signal_data.swing_2_price)
            trigger_line.higher_swing_low_price = max(signal_data.swing_1_price, signal_data.swing_2_price)
        trigger_line.nearest_daily_swing_low_target = signal_data.nearest_target

    return trigger_line


def upsert_breakout_event(db, signal_data: QueuedTradingSignal) -> BreakoutEvent:
    event_id = signal_data.breakout_event_id or uuid.uuid4()
    breakout_event = db.get(BreakoutEvent, event_id)
    if breakout_event is None:
        breakout_event = BreakoutEvent(id=event_id)
        db.add(breakout_event)

    breakout_event.trigger_line_id = signal_data.trigger_line_id
    breakout_event.exchange = signal_data.exchange
    breakout_event.symbol = signal_data.symbol
    breakout_event.event_type = signal_data.event_type or "BREAKOUT"
    breakout_event.event_time = signal_data.event_time or datetime.now(UTC)
    breakout_event.breakout_or_breakdown_price = signal_data.breakout_or_breakdown_price
    breakout_event.breakout_candle_high = signal_data.breakout_candle_high
    breakout_event.breakout_candle_low = signal_data.breakout_candle_low
    breakout_event.breakout_candle_volume = signal_data.breakout_candle_volume
    breakout_event.previous_candle_volume = signal_data.previous_candle_volume
    breakout_event.volume_ratio = signal_data.volume_ratio
    breakout_event.volume_condition_required = bool(signal_data.volume_condition_required)
    breakout_event.volume_condition_passed = bool(signal_data.volume_condition_passed)
    breakout_event.entry_price = signal_data.entry_price
    breakout_event.stop_loss = signal_data.stop_loss
    breakout_event.target = signal_data.target
    breakout_event.status = signal_data.breakout_status or "PASSED"

    if signal_data.trigger_line_id:
        trigger_line = db.get(TriggerLine, signal_data.trigger_line_id)
        if trigger_line is not None and breakout_event.status == "PASSED":
            trigger_line.line_status = "TRIGGERED"

    return breakout_event


def upsert_trading_signal(db, signal_data: QueuedTradingSignal, watchlist: Watchlist | None) -> TradingSignal:
    signal = db.get(TradingSignal, signal_data.signal_id)
    if signal is None:
        signal = TradingSignal(id=signal_data.signal_id, action=signal_data.action or "BUY")
        db.add(signal)

    inferred_watchlist_id = watchlist.id if watchlist else None
    if inferred_watchlist_id is None and signal_data.trigger_line_id:
        trigger_line = db.get(TriggerLine, signal_data.trigger_line_id)
        if trigger_line is not None:
            inferred_watchlist_id = trigger_line.watchlist_id
            if trigger_line.line_status == "ACTIVE":
                trigger_line.line_status = "TRIGGERED"

    signal.exchange = signal_data.exchange
    signal.symbol = signal_data.symbol
    signal.action = signal_data.action or signal.action
    signal.event_category = signal_data.event_category
    signal.watchlist_id = inferred_watchlist_id
    signal.trigger_line_id = signal_data.trigger_line_id
    signal.breakout_event_id = signal_data.breakout_event_id
    signal.trigger_price = signal_data.trigger_price
    signal.entry_price = signal_data.entry_price
    signal.stop_loss = signal_data.stop_loss
    signal.target = signal_data.target
    signal.volume_ratio = signal_data.volume_ratio
    signal.timeframe = signal_data.timeframe
    signal.strategy = signal_data.strategy
    signal.raw_payload = signal_data.model_dump(mode="json", exclude={"secret", "retry_count", "signal_id"})
    signal.status = "RECEIVED"
    signal.notification_status = "PENDING"
    signal.error_message = None
    return signal


def process_signal(signal_data: QueuedTradingSignal) -> None:
    logger.info(
        "Processing payload %s for %s %s (%s)",
        signal_data.signal_id,
        signal_data.exchange,
        signal_data.symbol,
        signal_data.event_category,
    )

    execute_order_placeholder(signal_data)

    signal: TradingSignal | None = None

    with SessionLocal() as db:
        watchlist = resolve_watchlist(db, signal_data)
        ensure_watchlist_symbol(db, watchlist, signal_data)

        if signal_data.event_category == "TRIGGER_LINE":
            trigger_line = upsert_trigger_line(db, signal_data, watchlist)
            db.commit()
            logger.info("Stored trigger line %s for %s %s", trigger_line.id, trigger_line.symbol, trigger_line.line_type)
            return

        if signal_data.event_category == "BREAKOUT_EVENT":
            breakout_event = upsert_breakout_event(db, signal_data)
            db.commit()
            logger.info(
                "Stored breakout event %s for %s %s",
                breakout_event.id,
                breakout_event.symbol,
                breakout_event.event_type,
            )
            return

        signal = upsert_trading_signal(db, signal_data, watchlist)
        db.commit()
        db.refresh(signal)

        paper_trade = generate_paper_trade_from_signal(db, signal)
        if paper_trade is not None:
            existing_trade = db.scalar(select(PaperTrade).where(PaperTrade.signal_id == signal.id).limit(1))
            if existing_trade is None:
                db.add(paper_trade)
                db.commit()
                logger.info("Created paper trade %s for signal %s", paper_trade.id, signal.id)

    if signal is None:
        return

    notification_status = send_telegram_notification(signal, max_retries=settings.worker_max_retries)
    finalize_signal(signal.id, notification_status)
    logger.info("Finished processing trading signal %s", signal.id)


def run_worker() -> None:
    logger.info("Starting trading worker")
    create_tables()
    logger.info("Database tables are ready for worker")

    while True:
        try:
            signal_data = dequeue_signal()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read from Redis queue")
            time.sleep(2)
            continue

        if signal_data is None:
            continue

        try:
            process_signal(signal_data)
        except SQLAlchemyError as exc:
            logger.exception("Database failure while processing payload %s", signal_data.signal_id)
            requeue_signal(signal_data, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected worker failure while processing payload %s", signal_data.signal_id)
            requeue_signal(signal_data, str(exc))
            time.sleep(2)


if __name__ == "__main__":
    run_worker()
