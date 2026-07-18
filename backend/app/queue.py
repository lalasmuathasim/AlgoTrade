import json
import logging
from functools import lru_cache

from redis import Redis

from backend.app.config import get_settings
from backend.app.schemas import SignalDispatchJob


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


def check_redis_connectivity() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:  # noqa: BLE001
        logger.exception("Redis connectivity check failed")
        return False


def enqueue_signal_dispatch(job: SignalDispatchJob) -> None:
    payload = json.dumps(job.model_dump(mode="json"))
    get_redis_client().lpush(settings.signal_dispatch_queue_name, payload)


def dequeue_signal_dispatch() -> SignalDispatchJob | None:
    result = get_redis_client().brpop(settings.signal_dispatch_queue_name, timeout=settings.worker_poll_timeout)
    if result is None:
        return None

    _, payload = result
    logger.info("Dequeued signal dispatch job from Redis queue %s", settings.signal_dispatch_queue_name)
    return SignalDispatchJob.model_validate(json.loads(payload))
