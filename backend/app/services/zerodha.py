import logging
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
import uuid
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Instrument, TriggerLine, WatchlistSymbol
from backend.app.schemas import HistoricalCandlePayload, InstrumentPayload, TickPayload


logger = logging.getLogger(__name__)
settings = get_settings()


class ZerodhaAuthService:
    login_base_url = "https://kite.zerodha.com/connect/login"

    def has_credentials(self) -> bool:
        return bool(settings.zerodha_api_key and settings.zerodha_api_secret)

    def has_access_token(self) -> bool:
        return bool(settings.zerodha_access_token)

    def build_login_url(self) -> str | None:
        if not settings.zerodha_api_key:
            return None

        query = {"api_key": settings.zerodha_api_key, "v": 3}
        if settings.zerodha_redirect_url:
            query["redirect_params"] = settings.zerodha_redirect_url
        return f"{self.login_base_url}?{urlencode(query)}"

    def build_auth_headers(self) -> dict[str, str]:
        if not settings.zerodha_api_key or not settings.zerodha_access_token:
            raise RuntimeError("Zerodha API key or access token is not configured")

        return {"Authorization": f"token {settings.zerodha_api_key}:{settings.zerodha_access_token}"}


class ZerodhaApiClient:
    base_url = "https://api.kite.trade"

    def __init__(self, auth_service: ZerodhaAuthService | None = None) -> None:
        self.auth_service = auth_service or ZerodhaAuthService()

    def _get(self, path: str, params: dict | None = None) -> dict:
        headers = self.auth_service.build_auth_headers()
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{self.base_url}{path}", headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    def fetch_historical_candles(
        self,
        instrument_token: int,
        from_date: date,
        to_date: date,
        interval: str = "day",
    ) -> list[HistoricalCandlePayload]:
        payload = self._get(
            f"/instruments/historical/{instrument_token}/{interval}",
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "continuous": 0,
                "oi": 0,
            },
        )
        candles: list[HistoricalCandlePayload] = []
        for item in payload.get("data", {}).get("candles", []):
            candles.append(
                HistoricalCandlePayload(
                    timestamp=datetime.fromisoformat(item[0].replace("Z", "+00:00")),
                    open=item[1],
                    high=item[2],
                    low=item[3],
                    close=item[4],
                    volume=item[5] if len(item) > 5 else 0.0,
                )
            )
        return candles

    def fetch_instruments(self) -> list[InstrumentPayload]:
        payload = self._get("/instruments")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Zerodha instrument response")

        instruments: list[InstrumentPayload] = []
        for row in rows:
            instruments.append(
                InstrumentPayload(
                    instrument_token=row["instrument_token"],
                    exchange_token=str(row.get("exchange_token", "")) or None,
                    tradingsymbol=row["tradingsymbol"],
                    name=row.get("name"),
                    exchange=row.get("exchange", "NSE"),
                    segment=row.get("segment"),
                    instrument_type=row.get("instrument_type"),
                    tick_size=row.get("tick_size"),
                    lot_size=row.get("lot_size"),
                )
            )
        return instruments


class HistoricalCandleProvider:
    def __init__(
        self,
        client: ZerodhaApiClient | None = None,
        fetcher: Callable[[str, int, int], list[HistoricalCandlePayload]] | None = None,
    ) -> None:
        self.client = client or ZerodhaApiClient()
        self.fetcher = fetcher

    def fetch_last_n_completed_daily_candles(
        self,
        symbol: str,
        instrument_token: int,
        count: int | None = None,
    ) -> list[HistoricalCandlePayload]:
        if self.fetcher is not None:
            return self.fetcher(symbol, instrument_token, count or settings.daily_candle_lookback)

        lookback = count or settings.daily_candle_lookback
        today = datetime.now(UTC).date()
        start = today - timedelta(days=max(lookback * 2, 220))
        candles = self.client.fetch_historical_candles(instrument_token, start, today)
        return candles[-lookback:]


class InstrumentMasterSyncService:
    def __init__(self, client: ZerodhaApiClient | None = None) -> None:
        self.client = client or ZerodhaApiClient()

    def sync(self, db: Session, instruments: Iterable[InstrumentPayload] | None = None) -> int:
        rows = list(instruments) if instruments is not None else self.client.fetch_instruments()
        synced = 0
        for row in rows:
            existing = db.scalar(select(Instrument).where(Instrument.instrument_token == row.instrument_token).limit(1))
            if existing is None:
                existing = Instrument(id=uuid.uuid4(), instrument_token=row.instrument_token)
                db.add(existing)

            existing.exchange_token = row.exchange_token
            existing.tradingsymbol = row.tradingsymbol
            existing.name = row.name
            existing.exchange = row.exchange
            existing.segment = row.segment
            existing.instrument_type = row.instrument_type
            existing.tick_size = row.tick_size
            existing.lot_size = row.lot_size
            existing.is_active = True
            existing.synced_at = datetime.now(UTC)
            synced += 1

            watchlist_memberships = db.scalars(
                select(WatchlistSymbol).where(
                    WatchlistSymbol.symbol == row.tradingsymbol,
                    WatchlistSymbol.exchange == row.exchange,
                )
            ).all()
            for membership in watchlist_memberships:
                membership.instrument_id = existing.id
                membership.instrument_token = row.instrument_token
                membership.company_name = membership.company_name or row.name

        db.commit()
        return synced


class SubscriptionManager:
    def get_active_subscriptions(self, db: Session) -> list[tuple[int, str, str]]:
        subscriptions: dict[int, tuple[int, str, str]] = {}

        watchlist_symbols = db.scalars(select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))).all()
        for symbol in watchlist_symbols:
            if symbol.instrument_token:
                subscriptions[symbol.instrument_token] = (symbol.instrument_token, symbol.exchange, symbol.symbol)

        instruments = db.scalars(select(Instrument).where(Instrument.is_active.is_(True))).all()
        instrument_map = {instrument.id: instrument for instrument in instruments}

        active_lines = db.scalars(select(TriggerLine).where(TriggerLine.line_status == "ACTIVE")).all()
        for line in active_lines:
            if line.instrument_id and line.instrument_id in instrument_map:
                instrument = instrument_map[line.instrument_id]
                subscriptions[instrument.instrument_token] = (
                    instrument.instrument_token,
                    line.exchange,
                    line.symbol,
                )

        return list(subscriptions.values())


class ZerodhaWebSocketClient:
    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.websocket")

    def connect_forever(self, on_ticks: Callable[[list[TickPayload]], None]) -> None:
        auth = ZerodhaAuthService()
        if not auth.has_access_token():
            self._logger.warning("ZERODHA_ACCESS_TOKEN is not configured; websocket client is idle")
            return

        self._logger.info(
            "Zerodha websocket client placeholder initialized for live market ingestion; transport hookup is feature-gated"
        )
        self._logger.info("No real websocket transport is executed during local validation")

    def process_ticks(self, ticks: list[TickPayload], on_ticks: Callable[[list[TickPayload]], None]) -> None:
        on_ticks(ticks)
