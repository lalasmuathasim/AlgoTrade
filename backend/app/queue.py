import json
import logging
from functools import lru_cache

from redis import Redis

from backend.app.config import get_settings
from backend.app.schemas import QueuedTradingSignal


logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=settings.worker_poll_timeout + 5,
        retry_on_timeout=True,
    )


def enqueue_signal(signal: QueuedTradingSignal) -> None:
    payload = json.dumps(signal.model_dump(mode="json"))
    get_redis_client().lpush(settings.signal_queue_name, payload)


def dequeue_signal() -> QueuedTradingSignal | None:
    result = get_redis_client().brpop(settings.signal_queue_name, timeout=settings.worker_poll_timeout)
    if result is None:
        return None

    _, payload = result
    logger.info("Dequeued signal payload from Redis queue %s", settings.signal_queue_name)
    return QueuedTradingSignal.model_validate(json.loads(payload))
