import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.app.config import get_settings
from backend.app.database import initialize_runtime_state
from backend.app.routers.analytics import router as analytics_router
from backend.app.routers.auth import router as auth_router
from backend.app.routers.configuration import router as configuration_router
from backend.app.routers.dashboard import router as dashboard_router
from backend.app.routers.paper_trading import router as paper_trading_router
from backend.app.routers.system import router as system_router
from backend.app.routers.zerodha import router as zerodha_router


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
app.include_router(configuration_router)
app.include_router(analytics_router)
app.include_router(system_router)
app.include_router(paper_trading_router)
app.include_router(zerodha_router)


AUTH_REDIRECT_STATUSES = {
    "Authentication required": "auth_required",
    "Invalid session": "session_expired",
    "User not found": "session_expired",
}
HTML_AUTH_PATHS = {"/dashboard", "/configuration", "/analytics"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    accept_header = request.headers.get("accept", "").lower()
    auth_status = AUTH_REDIRECT_STATUSES.get(str(exc.detail))
    if exc.status_code == 401 and request.method == "GET" and request.url.path in HTML_AUTH_PATHS and "text/html" in accept_header and auth_status:
        return RedirectResponse(url=f"/?auth_status={auth_status}", status_code=302)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
