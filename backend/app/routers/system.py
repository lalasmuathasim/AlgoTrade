from datetime import UTC, datetime
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db, verify_database_connectivity
from backend.app.dependencies import require_admin_user
from backend.app.queue import check_redis_connectivity, get_live_engine_runtime
from backend.app.models import WatchlistSymbol
from backend.app.schemas import (
    DailyScanRequest,
    DependencyStatusResponse,
    InstrumentPayload,
    InstrumentSyncRequest,
    InstrumentSyncResponse,
    LiveEngineRuntimeResponse,
    ScanExecutionResponse,
    TickPayload,
    TickReplayRequest,
    TickReplayResponse,
)
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.live_engine_runtime import build_live_engine_runtime_snapshot
from backend.app.services.market_stream import MarketDataProcessor
from backend.app.services.paper_trading_service import ensure_settings
from backend.app.services.trading_time import current_trading_date
from backend.app.services.zerodha import InstrumentMasterSyncService, ZerodhaApiClient, ZerodhaAuthService
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.services.zerodha import SubscriptionManager


router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_admin_user)])
settings = get_settings()
logger = logging.getLogger(__name__)


def _resolve_instrument_sync_scope(db: Session, watchlist_id=None) -> dict[str, set[str]]:
    query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
    if watchlist_id is not None:
        query = query.where(WatchlistSymbol.watchlist_id == watchlist_id)
    else:
        selected_watchlist = get_selected_watchlist(db)
        if selected_watchlist is not None:
            query = query.where(WatchlistSymbol.watchlist_id == selected_watchlist.id)

    rows = db.scalars(query).all()
    scope: dict[str, set[str]] = {}
    for row in rows:
        symbol = (row.symbol or "").strip().upper()
        exchange = (row.exchange or "NSE").strip().upper()
        if not symbol:
            continue
        scope.setdefault(exchange, set()).add(symbol)
    return scope


@router.get("/dependencies", response_model=DependencyStatusResponse)
def dependency_status(db: Session = Depends(get_db)) -> DependencyStatusResponse:
    database_ok = False
    try:
        verify_database_connectivity()
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    return DependencyStatusResponse(
        database=database_ok,
        redis=check_redis_connectivity(),
        zerodha_credentials_configured=bool(settings.zerodha_api_key and access_token),
    )


@router.get("/live-engine/runtime", response_model=LiveEngineRuntimeResponse)
def live_engine_runtime(db: Session = Depends(get_db)) -> LiveEngineRuntimeResponse:
    snapshot = get_live_engine_runtime()
    if snapshot is None:
        selected_watchlist = get_selected_watchlist(db)
        subscriptions = SubscriptionManager().describe_active_subscriptions(db)
        snapshot = build_live_engine_runtime_snapshot(
            status="NOT_PUBLISHED",
            message="Live engine has not published runtime state yet.",
            selected_watchlist=selected_watchlist,
            subscriptions=subscriptions,
            credentials_configured=bool(settings.zerodha_api_key and settings.zerodha_api_secret and settings.zerodha_redirect_url),
            access_token_configured=bool(get_current_zerodha_access_token(db) or settings.zerodha_access_token),
        )
    return LiveEngineRuntimeResponse.model_validate(snapshot)


@router.post("/instruments/sync", response_model=InstrumentSyncResponse)
def sync_instruments(
    payload: InstrumentSyncRequest,
    db: Session = Depends(get_db),
) -> InstrumentSyncResponse:
    access_token = get_current_zerodha_access_token(db)
    service = InstrumentMasterSyncService(
        client=ZerodhaApiClient(
            auth_service=ZerodhaAuthService(),
            access_token=access_token,
        )
    )
    instruments = None
    if payload.instruments is not None:
        instruments = [InstrumentPayload.model_validate(row) for row in payload.instruments]
    try:
        if instruments is not None:
            synced = service.sync(db, instruments=instruments)
        elif payload.full_sync:
            logger.info("Running full Zerodha instrument sync")
            synced = service.sync(db)
        else:
            scope = _resolve_instrument_sync_scope(db, watchlist_id=payload.watchlist_id)
            logger.info(
                "Running scoped Zerodha instrument sync",
                extra={
                    "exchanges": sorted(scope.keys()),
                    "symbols_considered": sum(len(symbols) for symbols in scope.values()),
                },
            )
            synced = service.sync_watchlist_scope(db, exchange_symbols=scope)
        return InstrumentSyncResponse(synced=synced)
    except RuntimeError as exc:
        logger.warning("Instrument sync blocked: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("Instrument sync failed while calling Zerodha")
        raise HTTPException(status_code=502, detail="Zerodha instrument sync failed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Instrument sync failed unexpectedly")
        raise HTTPException(status_code=500, detail="Instrument sync failed") from exc


@router.post("/scans/daily", response_model=ScanExecutionResponse)
def run_daily_scan(
    payload: DailyScanRequest,
    db: Session = Depends(get_db),
) -> ScanExecutionResponse:
    scanner = DailyMarketScanner()
    execution = scanner.run(
        db,
        watchlist_id=payload.watchlist_id,
        scan_date=payload.scan_date or current_trading_date(ensure_settings(db)),
        dry_run=payload.dry_run,
    )
    return ScanExecutionResponse(
        execution_id=execution.id,
        status=execution.status,
        symbols_scanned=execution.symbols_scanned,
        trigger_lines_created=execution.trigger_lines_created,
        trigger_lines_updated=execution.trigger_lines_updated,
    )


@router.post("/ticks/replay", response_model=TickReplayResponse)
def replay_ticks(
    payload: TickReplayRequest,
    db: Session = Depends(get_db),
) -> TickReplayResponse:
    processor = MarketDataProcessor()
    ticks = [TickPayload.model_validate(row) for row in payload.ticks]
    result = processor.process_ticks(db, ticks)
    last_finalized_candle = result.finalized_candles[-1] if result.finalized_candles else None
    return TickReplayResponse(
        ticks_processed=result.ticks_processed,
        finalized_candles_count=result.finalized_candles_count,
        signals_created=result.signals_created_count,
        signal_ids=[str(signal.id) for signal in result.signals],
        last_finalized_candle={
            "symbol": last_finalized_candle.symbol,
            "exchange": last_finalized_candle.exchange,
            "candle_start": last_finalized_candle.candle_start.astimezone(UTC).isoformat(),
            "candle_end": last_finalized_candle.candle_end.astimezone(UTC).isoformat(),
            "open": last_finalized_candle.open,
            "high": last_finalized_candle.high,
            "low": last_finalized_candle.low,
            "close": last_finalized_candle.close,
            "volume": last_finalized_candle.volume,
        }
        if last_finalized_candle
        else None,
    )
