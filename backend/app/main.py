import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.config import get_settings
from backend.app.database import initialize_runtime_state
from backend.app.routers.auth import router as auth_router
from backend.app.routers.dashboard import router as dashboard_router
from backend.app.routers.paper_trading import router as paper_trading_router
from backend.app.routers.system import router as system_router


settings = get_settings()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting Qubitx Zerodha-native trading application")
    initialize_runtime_state()
    logger.info("Runtime state is ready")
    yield
    logger.info("Shutting down Qubitx Zerodha-native trading application")


app = FastAPI(
    title="Qubitx Zerodha Trading Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(system_router)
app.include_router(paper_trading_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
