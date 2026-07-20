import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings
from backend.app.database import SessionLocal, initialize_runtime_state
from backend.app.models import TradingSignal
from backend.app.queue import dequeue_signal_dispatch, enqueue_signal_dispatch
from backend.app.schemas import SignalDispatchJob
from backend.app.services.execution_runtime import LiveExecutionService, OrderReconciliationService
from backend.app.services.paper_trading_service import ensure_settings, generate_paper_trade_from_signal
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
        if notification_status != "FAILED":
            signal.error_message = None
        db.commit()


def requeue_signal(job: SignalDispatchJob, error_message: str) -> None:
    if job.retry_count >= settings.worker_max_retries:
        logger.error("Signal %s exhausted retries after %s attempts", job.signal_id, job.retry_count)
        mark_signal_failed(job.signal_id, error_message)
        return

    retry_job = job.model_copy(update={"retry_count": job.retry_count + 1})
    enqueue_signal_dispatch(retry_job)
    mark_signal_retrying(job.signal_id, error_message)
    logger.warning(
        "Re-queued signal %s for retry %s/%s",
        retry_job.signal_id,
        retry_job.retry_count,
        settings.worker_max_retries,
    )


def process_signal(job: SignalDispatchJob) -> None:
    logger.info("Processing signal dispatch job for %s", job.signal_id)
    live_execution_service = LiveExecutionService()
    reconciliation_service = OrderReconciliationService()

    with SessionLocal() as db:
        signal = db.get(TradingSignal, job.signal_id)
        if signal is None:
            logger.warning("Signal %s no longer exists; skipping", job.signal_id)
            return

        if signal.status == "PROCESSED":
            logger.info("Signal %s already processed; skipping idempotently", signal.id)
            return

        try:
            runtime_settings = ensure_settings(db)
            if runtime_settings.paper_trading_enabled:
                paper_trade = generate_paper_trade_from_signal(db, signal)
                if paper_trade is not None:
                    db.add(paper_trade)

            live_execution_service.execute(db, signal)
            reconciliation_service.reconcile(db)

            db.commit()

            notification_status = "SKIPPED"
            try:
                if send_telegram_notification(signal):
                    notification_status = "SENT"
            except Exception:  # noqa: BLE001
                logger.exception("Telegram notification failed for signal %s", signal.id)
                notification_status = "FAILED"

            finalize_signal(signal.id, notification_status)
        except SQLAlchemyError as exc:
            db.rollback()
            raise RuntimeError(str(exc)) from exc


def run_worker() -> None:
    logger.info("Starting Qubitx worker")
    initialize_runtime_state()
    while True:
        try:
            job = dequeue_signal_dispatch()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read from Redis queue")
            time.sleep(2)
            continue

        if job is None:
            continue

        try:
            process_signal(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Signal processing failed for %s", job.signal_id)
            requeue_signal(job, str(exc))
            time.sleep(1)


if __name__ == "__main__":
    run_worker()
