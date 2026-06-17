import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.config import get_settings
from backend.app.database import create_tables
from backend.app.routers.auth import router as auth_router
from backend.app.routers.dashboard import router as dashboard_router
from backend.app.routers.paper_trading import router as paper_trading_router
from backend.app.routers.webhook import router as webhook_router


settings = get_settings()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting TradingView webhook application")
    create_tables()
    logger.info("Database tables are ready")
    yield
    logger.info("Shutting down TradingView webhook application")


app = FastAPI(
    title="TradingView Webhook Receiver",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(dashboard_router)
app.include_router(paper_trading_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
