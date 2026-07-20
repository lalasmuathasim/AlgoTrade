from datetime import UTC, datetime
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db, verify_database_connectivity
from backend.app.dependencies import require_admin_user
from backend.app.models import WatchlistSymbol
from backend.app.schemas import (
    DailyScanRequest,
    DependencyStatusResponse,
    InstrumentPayload,
    InstrumentSyncRequest,
    InstrumentSyncResponse,
    ScanExecutionResponse,
    TickPayload,
    TickReplayRequest,
)
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.market_stream import MarketDataProcessor
from backend.app.services.zerodha import InstrumentMasterSyncService, ZerodhaApiClient, ZerodhaAuthService
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.queue import check_redis_connectivity


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
        scan_date=payload.scan_date or datetime.now(UTC).date(),
        dry_run=payload.dry_run,
    )
    return ScanExecutionResponse(
        execution_id=execution.id,
        status=execution.status,
        symbols_scanned=execution.symbols_scanned,
        trigger_lines_created=execution.trigger_lines_created,
        trigger_lines_updated=execution.trigger_lines_updated,
    )


@router.post("/ticks/replay")
def replay_ticks(
    payload: TickReplayRequest,
    db: Session = Depends(get_db),
) -> dict:
    processor = MarketDataProcessor()
    ticks = [TickPayload.model_validate(row) for row in payload.ticks]
    signals = processor.process_ticks(db, ticks)
    return {"signals_created": len(signals), "signal_ids": [str(signal.id) for signal in signals]}
