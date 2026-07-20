from datetime import date
import uuid

from pydantic import BaseModel


class InstrumentSyncRequest(BaseModel):
    instruments: list[dict] | None = None
    watchlist_id: uuid.UUID | None = None
    full_sync: bool = False


class InstrumentSyncResponse(BaseModel):
    synced: int


class DailyScanRequest(BaseModel):
    watchlist_id: uuid.UUID | None = None
    scan_date: date | None = None
    dry_run: bool = False


class TickReplayRequest(BaseModel):
    ticks: list[dict]
