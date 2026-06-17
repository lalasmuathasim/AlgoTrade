import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError

from backend.app.config import get_settings
from backend.app.queue import enqueue_signal
from backend.app.schemas import QueuedTradingSignal, TradingViewWebhookPayload, WebhookResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])
settings = get_settings()


@router.post("/tradingview", response_model=WebhookResponse)
def receive_tradingview_webhook(
    payload: TradingViewWebhookPayload,
) -> WebhookResponse:
    if payload.secret != settings.webhook_secret:
        logger.warning("Rejected webhook with invalid secret for symbol %s", payload.symbol)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    signal_id = uuid.uuid4()
    queued_signal = QueuedTradingSignal(
        signal_id=signal_id,
        retry_count=0,
        **payload.model_dump(),
    )

    try:
        enqueue_signal(queued_signal)
        logger.info(
            "Queued webhook signal %s for %s %s (%s)",
            signal_id,
            payload.exchange,
            payload.symbol,
            payload.action or payload.line_type or payload.event_type,
        )
    except RedisError:
        logger.exception("Redis failure while queueing webhook payload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue trading signal",
        ) from None

    return WebhookResponse(
        status="queued",
        signal_id=signal_id,
        queued=True,
    )
