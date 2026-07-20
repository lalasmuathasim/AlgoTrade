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


class LiveEngineRuntimeResponse(BaseModel):
    status: str
    message: str
    transport: str
    selected_watchlist: dict | None = None
    subscription_count: int
    subscriptions: list[dict]
    credentials_configured: bool
    access_token_configured: bool
    last_tick_at: str | None = None
    last_tick_symbol: str | None = None
    published_at: str | None = None
