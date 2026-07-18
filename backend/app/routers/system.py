from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db, verify_database_connectivity
from backend.app.dependencies import require_admin_user
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
from backend.app.services.zerodha import InstrumentMasterSyncService
from backend.app.queue import check_redis_connectivity


router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_admin_user)])
settings = get_settings()


@router.get("/dependencies", response_model=DependencyStatusResponse)
def dependency_status() -> DependencyStatusResponse:
    database_ok = False
    try:
        verify_database_connectivity()
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    return DependencyStatusResponse(
        database=database_ok,
        redis=check_redis_connectivity(),
        zerodha_credentials_configured=bool(settings.zerodha_api_key and settings.zerodha_access_token),
    )


@router.post("/instruments/sync", response_model=InstrumentSyncResponse)
def sync_instruments(
    payload: InstrumentSyncRequest,
    db: Session = Depends(get_db),
) -> InstrumentSyncResponse:
    service = InstrumentMasterSyncService()
    instruments = None
    if payload.instruments is not None:
        instruments = [InstrumentPayload.model_validate(row) for row in payload.instruments]
    synced = service.sync(db, instruments=instruments)
    return InstrumentSyncResponse(synced=synced)


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
