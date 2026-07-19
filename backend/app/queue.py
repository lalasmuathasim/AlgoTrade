import json
import logging
from functools import lru_cache
from urllib.parse import urlparse

from redis import Redis

from backend.app.config import get_settings
from backend.app.schemas import SignalDispatchJob


logger = logging.getLogger(__name__)
settings = get_settings()


def describe_redis_url(redis_url: str | None = None) -> dict[str, str | int | None]:
    parsed = urlparse(redis_url or settings.redis_url)
    database = 0
    if parsed.path and parsed.path != "/":
        try:
            database = int(parsed.path.lstrip("/"))
        except ValueError:
            database = 0

    return {
        "scheme": parsed.scheme or "redis",
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6379,
        "db": database,
    }


def redis_diagnostics() -> dict[str, str | int | bool | None]:
    details = describe_redis_url()
    diagnostics: dict[str, str | int | bool | None] = {
        "scheme": details["scheme"],
        "host": details["host"],
        "port": details["port"],
        "db": details["db"],
        "connected": False,
        "error": None,
    }
    try:
        diagnostics["connected"] = bool(get_redis_client().ping())
    except Exception as exc:  # noqa: BLE001
        diagnostics["error"] = exc.__class__.__name__
    return diagnostics


def log_redis_diagnostics() -> dict[str, str | int | bool | None]:
    diagnostics = redis_diagnostics()
    if diagnostics["connected"]:
        logger.info(
            "Redis diagnostics: host=%s port=%s db=%s connected=%s",
            diagnostics["host"],
            diagnostics["port"],
            diagnostics["db"],
            diagnostics["connected"],
        )
    else:
        logger.warning(
            "Redis diagnostics: host=%s port=%s db=%s connected=%s error=%s",
            diagnostics["host"],
            diagnostics["port"],
            diagnostics["db"],
            diagnostics["connected"],
            diagnostics["error"],
        )
    return diagnostics


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
        diagnostics = describe_redis_url()
        logger.exception(
            "Redis connectivity check failed for host=%s port=%s db=%s",
            diagnostics["host"],
            diagnostics["port"],
            diagnostics["db"],
        )
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
