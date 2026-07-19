import logging
from collections.abc import Callable, Iterable
import csv
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import io
import uuid
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Instrument, TriggerLine, WatchlistSymbol
from backend.app.schemas import HistoricalCandlePayload, InstrumentPayload, TickPayload
from backend.app.services.watchlists import get_selected_watchlist


logger = logging.getLogger(__name__)
settings = get_settings()
india_tz = ZoneInfo("Asia/Kolkata")


class ZerodhaAuthService:
    login_base_url = "https://kite.zerodha.com/connect/login"
    api_base_url = "https://api.kite.trade"

    def has_credentials(self) -> bool:
        return bool(settings.zerodha_api_key and settings.zerodha_api_secret and settings.zerodha_redirect_url)

    def has_access_token(self) -> bool:
        return bool(settings.zerodha_access_token)

    def resolve_access_token(self, access_token: str | None = None) -> str | None:
        return access_token or settings.zerodha_access_token

    def build_login_url(self) -> str | None:
        if not settings.zerodha_api_key:
            return None

        query = {"api_key": settings.zerodha_api_key, "v": 3}
        return f"{self.login_base_url}?{urlencode(query)}"

    def build_auth_headers(self, access_token: str | None = None) -> dict[str, str]:
        token = self.resolve_access_token(access_token)
        if not settings.zerodha_api_key or not token:
            raise RuntimeError("Zerodha API key or access token is not configured")

        return {
            "Authorization": f"token {settings.zerodha_api_key}:{token}",
            "X-Kite-Version": "3",
        }

    def build_session_checksum(self, request_token: str) -> str:
        if not settings.zerodha_api_key or not settings.zerodha_api_secret:
            raise RuntimeError("Zerodha API key or API secret is not configured")
        payload = f"{settings.zerodha_api_key}{request_token}{settings.zerodha_api_secret}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def exchange_request_token(self, request_token: str) -> dict:
        if not self.has_credentials():
            raise RuntimeError("Zerodha credentials are not configured")

        response = httpx.post(
            f"{self.api_base_url}/session/token",
            headers={"X-Kite-Version": "3"},
            data={
                "api_key": settings.zerodha_api_key,
                "request_token": request_token,
                "checksum": self.build_session_checksum(request_token),
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Unexpected Zerodha token exchange response")
        return data

    def fetch_user_profile(self, access_token: str) -> dict:
        response = httpx.get(
            f"{self.api_base_url}/user/profile",
            headers=self.build_auth_headers(access_token=access_token),
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Zerodha profile response")
        return data

    def parse_login_time(self, login_time_value: str | None) -> datetime | None:
        if not login_time_value:
            return None
        parsed = datetime.strptime(login_time_value, "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=india_tz)

    def compute_access_token_expiry(self, login_time: datetime | None) -> datetime:
        reference = login_time.astimezone(india_tz) if login_time else datetime.now(india_tz)
        next_day = reference.date() + timedelta(days=1)
        return datetime.combine(next_day, time(hour=6, minute=0), tzinfo=india_tz)


class ZerodhaApiClient:
    base_url = "https://api.kite.trade"

    def __init__(self, auth_service: ZerodhaAuthService | None = None, access_token: str | None = None) -> None:
        self.auth_service = auth_service or ZerodhaAuthService()
        self.access_token = access_token

    def _get(self, path: str, params: dict | None = None) -> dict:
        headers = self.auth_service.build_auth_headers(access_token=self.access_token)
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
        return self.fetch_exchange_instruments()

    def fetch_exchange_instruments(self, exchange: str | None = None) -> list[InstrumentPayload]:
        path = f"/instruments/{exchange}" if exchange else "/instruments"
        headers = self.auth_service.build_auth_headers(access_token=self.access_token)
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                headers=headers,
                timeout=40.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exchange and exc.response.status_code == 405:
                response = httpx.get(
                    f"{self.base_url}/instruments",
                    headers=headers,
                    timeout=40.0,
                )
                response.raise_for_status()
            else:
                raise

        reader = csv.DictReader(io.StringIO(response.text))
        instruments: list[InstrumentPayload] = []
        for row in reader:
            tradingsymbol = (row.get("tradingsymbol") or "").strip()
            exchange_value = (row.get("exchange") or exchange or "").strip()
            instrument_token = (row.get("instrument_token") or "").strip()
            if not tradingsymbol or not exchange_value or not instrument_token:
                continue
            instruments.append(
                InstrumentPayload(
                    instrument_token=int(instrument_token),
                    exchange_token=(row.get("exchange_token") or "").strip() or None,
                    tradingsymbol=tradingsymbol,
                    name=(row.get("name") or "").strip() or None,
                    exchange=exchange_value,
                    segment=(row.get("segment") or "").strip() or None,
                    instrument_type=(row.get("instrument_type") or "").strip() or None,
                    tick_size=float(row["tick_size"]) if row.get("tick_size") else None,
                    lot_size=int(float(row["lot_size"])) if row.get("lot_size") else None,
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
        selected_watchlist = get_selected_watchlist(db)

        watchlist_query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
        if selected_watchlist is not None:
            watchlist_query = watchlist_query.where(WatchlistSymbol.watchlist_id == selected_watchlist.id)
        watchlist_symbols = db.scalars(watchlist_query).all()
        for symbol in watchlist_symbols:
            if symbol.instrument_token:
                subscriptions[symbol.instrument_token] = (symbol.instrument_token, symbol.exchange, symbol.symbol)

        instruments = db.scalars(select(Instrument).where(Instrument.is_active.is_(True))).all()
        instrument_map = {instrument.id: instrument for instrument in instruments}

        active_lines_query = select(TriggerLine).where(TriggerLine.line_status == "ACTIVE")
        if selected_watchlist is not None:
            active_lines_query = active_lines_query.where(TriggerLine.watchlist_id == selected_watchlist.id)
        active_lines = db.scalars(active_lines_query).all()
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
