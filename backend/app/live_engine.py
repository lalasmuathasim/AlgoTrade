import logging
import time

from backend.app.config import get_settings
from backend.app.database import SessionLocal, initialize_runtime_state
from backend.app.services.market_stream import MarketDataProcessor
from backend.app.services.zerodha import ZerodhaWebSocketClient


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

    def handle_ticks(ticks):
        with SessionLocal() as db:
            processor.process_ticks(db, ticks)

    while True:
        client.connect_forever(handle_ticks)
        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    run_live_engine()
