import logging
from collections.abc import Callable, Iterable
import csv
from datetime import UTC, date, datetime, time, timedelta
import hashlib
from importlib import import_module
import io
import uuid
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Instrument, TriggerLine, WatchlistSymbol
from backend.app.schemas import HistoricalCandlePayload, InstrumentPayload, TickPayload
from backend.app.services.trading_time import current_trading_date, get_trading_timezone
from backend.app.services.watchlists import get_selected_watchlist


logger = logging.getLogger(__name__)
settings = get_settings()


class ZerodhaAuthService:
    login_base_url = "https://kite.zerodha.com/connect/login"
    api_base_url = "https://api.kite.trade"

    def has_credentials(self) -> bool:
        return bool(settings.zerodha_api_key and settings.zerodha_api_secret and settings.zerodha_redirect_url)

    def has_access_token(self, access_token: str | None = None) -> bool:
        return bool(self.resolve_access_token(access_token))

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
        return parsed.replace(tzinfo=get_trading_timezone())

    def compute_access_token_expiry(self, login_time: datetime | None) -> datetime:
        trading_tz = get_trading_timezone()
        reference = login_time.astimezone(trading_tz) if login_time else datetime.now(trading_tz)
        next_day = reference.date() + timedelta(days=1)
        return datetime.combine(next_day, time(hour=6, minute=0), tzinfo=trading_tz)


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

    def _post(self, path: str, data: dict) -> dict:
        headers = self.auth_service.build_auth_headers(access_token=self.access_token)
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{self.base_url}{path}", headers=headers, data=data)
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

    def fetch_ltp_quotes(self, instruments: list[str]) -> dict[str, float]:
        if not instruments:
            return {}

        params = [("i", instrument) for instrument in instruments]
        payload = self._get("/quote/ltp", params=params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Zerodha LTP response")

        result: dict[str, float] = {}
        for instrument_key, row in data.items():
            if isinstance(row, dict) and row.get("last_price") is not None:
                result[instrument_key] = float(row["last_price"])
        return result

    def place_regular_order(
        self,
        *,
        exchange: str,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "LIMIT",
        product: str = "MIS",
        price: float | None = None,
        validity: str = "DAY",
        tag: str | None = None,
    ) -> dict:
        payload: dict[str, str | int | float] = {
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "validity": validity,
        }
        if price is not None:
            payload["price"] = price
        if tag:
            payload["tag"] = tag

        response = self._post("/orders/regular", payload)
        data = response.get("data")
        if isinstance(data, dict):
            return data
        return response


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
        runtime_settings=None,
    ) -> list[HistoricalCandlePayload]:
        if self.fetcher is not None:
            return self.fetcher(symbol, instrument_token, count or settings.daily_candle_lookback)

        lookback = count or settings.daily_candle_lookback
        today = current_trading_date(runtime_settings)
        start = today - timedelta(days=max(lookback * 2, 220))
        candles = self.client.fetch_historical_candles(instrument_token, start, today)
        return candles[-lookback:]


class InstrumentMasterSyncService:
    def __init__(self, client: ZerodhaApiClient | None = None) -> None:
        self.client = client or ZerodhaApiClient()

    def fetch_scoped_instruments(self, exchange_symbols: dict[str, set[str]]) -> list[InstrumentPayload]:
        scoped_rows: dict[tuple[str, str], InstrumentPayload] = {}
        for exchange, symbols in exchange_symbols.items():
            normalized_symbols = {symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()}
            exchange_rows = self.client.fetch_exchange_instruments(exchange)
            if normalized_symbols:
                exchange_rows = [
                    row for row in exchange_rows if row.tradingsymbol.strip().upper() in normalized_symbols
                ]
            for row in exchange_rows:
                scoped_rows[(row.exchange, row.tradingsymbol)] = row
        return list(scoped_rows.values())

    def sync_watchlist_scope(self, db: Session, exchange_symbols: dict[str, set[str]]) -> int:
        if not exchange_symbols:
            return 0
        rows = self.fetch_scoped_instruments(exchange_symbols)
        return self.sync(db, instruments=rows)

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
    def describe_active_subscriptions(self, db: Session) -> list[dict]:
        selected_watchlist = get_selected_watchlist(db)
        subscriptions: dict[int, dict] = {}
        instruments = db.scalars(select(Instrument).where(Instrument.is_active.is_(True))).all()
        instrument_map = {instrument.id: instrument for instrument in instruments}
        instrument_by_exchange_symbol: dict[tuple[str, str], Instrument] = {}
        for instrument in instruments:
            exchange = getattr(instrument, "exchange", None)
            tradingsymbol = getattr(instrument, "tradingsymbol", None)
            if exchange and tradingsymbol:
                instrument_by_exchange_symbol.setdefault((exchange, tradingsymbol), instrument)

        memberships_query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
        if selected_watchlist is not None:
            memberships_query = memberships_query.where(WatchlistSymbol.watchlist_id == selected_watchlist.id)
        memberships = db.scalars(memberships_query).all()
        membership_by_watchlist_symbol = {
            (membership.watchlist_id, membership.exchange, membership.symbol): membership
            for membership in memberships
        }

        active_lines_query = select(TriggerLine).where(TriggerLine.line_status == "ACTIVE")
        if selected_watchlist is not None:
            active_lines_query = active_lines_query.where(TriggerLine.watchlist_id == selected_watchlist.id)
        active_lines = db.scalars(active_lines_query).all()
        for line in active_lines:
            instrument_token: int | None = None

            if line.instrument_id and line.instrument_id in instrument_map:
                instrument_token = instrument_map[line.instrument_id].instrument_token

            if instrument_token is None:
                membership = membership_by_watchlist_symbol.get((line.watchlist_id, line.exchange, line.symbol))
                if membership is not None:
                    if membership.instrument_token is not None:
                        instrument_token = membership.instrument_token
                    elif membership.instrument_id and membership.instrument_id in instrument_map:
                        instrument_token = instrument_map[membership.instrument_id].instrument_token

            if instrument_token is None:
                instrument = instrument_by_exchange_symbol.get((line.exchange, line.symbol))
                if instrument is not None:
                    instrument_token = instrument.instrument_token

            if instrument_token is not None:
                subscriptions.setdefault(
                    instrument_token,
                    {
                        "instrument_token": instrument_token,
                        "exchange": line.exchange,
                        "symbol": line.symbol,
                        "source": "TRIGGER_LINE",
                    },
                )

        return list(subscriptions.values())

    def get_active_subscriptions(self, db: Session) -> list[tuple[int, str, str]]:
        return [
            (row["instrument_token"], row["exchange"], row["symbol"])
            for row in self.describe_active_subscriptions(db)
        ]


class ZerodhaWebSocketClient:
    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.websocket")
        self._subscription_map: dict[int, dict] = {}

    def _emit_state(
        self,
        callback: Callable[[dict], None] | None,
        *,
        status: str,
        message: str,
        transport: str,
        **extra,
    ) -> dict:
        payload = {
            "status": status,
            "message": message,
            "transport": transport,
            **extra,
        }
        if callback is not None:
            callback(payload.copy())
        return payload

    def _load_kite_ticker_class(self):
        module = import_module("kiteconnect")
        ticker_cls = getattr(module, "KiteTicker", None)
        if ticker_cls is None:
            raise RuntimeError("kiteconnect.KiteTicker is unavailable")
        return ticker_cls

    def _normalize_tick_timestamp(self, tick: dict) -> datetime:
        timestamp = tick.get("exchange_timestamp") or tick.get("last_trade_time")
        if timestamp is None:
            return datetime.now(UTC)
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=india_tz).astimezone(UTC)
        return timestamp.astimezone(UTC)

    def _build_tick_payloads(self, ticks: list[dict]) -> list[TickPayload]:
        payloads: list[TickPayload] = []
        for tick in ticks:
            instrument_token = tick.get("instrument_token")
            last_price = tick.get("last_price")
            if instrument_token is None or last_price is None:
                continue
            mapping = self._subscription_map.get(int(instrument_token))
            if mapping is None:
                continue
            payloads.append(
                TickPayload(
                    instrument_token=int(instrument_token),
                    symbol=mapping["symbol"],
                    exchange=mapping["exchange"],
                    timestamp=self._normalize_tick_timestamp(tick),
                    last_price=float(last_price),
                    volume_traded=float(tick["volume_traded"]) if tick.get("volume_traded") is not None else None,
                )
            )
        return payloads

    def connect_forever(
        self,
        subscriptions: list[dict],
        on_ticks: Callable[[list[TickPayload]], None],
        on_state_change: Callable[[dict], None] | None = None,
        access_token: str | None = None,
    ) -> dict:
        auth = ZerodhaAuthService()
        if not auth.has_credentials():
            self._logger.warning("Zerodha credentials are not configured; websocket client is idle")
            return self._emit_state(
                on_state_change,
                status="IDLE_NOT_CONFIGURED",
                message="Zerodha credentials are not configured.",
                transport="kite_ticker",
            )
        if not auth.has_access_token(access_token):
            self._logger.warning("ZERODHA_ACCESS_TOKEN is not configured; websocket client is idle")
            return self._emit_state(
                on_state_change,
                status="IDLE_NO_TOKEN",
                message="Zerodha access token is not configured.",
                transport="kite_ticker",
            )
        if not subscriptions:
            self._logger.info("No active trigger-line subscriptions are available; websocket client is idle")
            return self._emit_state(
                on_state_change,
                status="IDLE_NO_SUBSCRIPTIONS",
                message="No active trigger-line subscriptions are available.",
                transport="kite_ticker",
            )

        try:
            kite_ticker_cls = self._load_kite_ticker_class()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("kiteconnect is unavailable for ticker transport: %s", exc)
            return self._emit_state(
                on_state_change,
                status="IDLE_DEPENDENCY_MISSING",
                message="kiteconnect is unavailable for Zerodha ticker transport.",
                transport="kite_ticker",
                error=exc.__class__.__name__,
            )

        resolved_access_token = auth.resolve_access_token(access_token)
        if not settings.zerodha_api_key or not resolved_access_token:
            return self._emit_state(
                on_state_change,
                status="IDLE_NO_TOKEN",
                message="Zerodha access token is not configured.",
                transport="kite_ticker",
            )

        self._subscription_map = {
            int(row["instrument_token"]): row
            for row in subscriptions
            if row.get("instrument_token") is not None
        }
        instrument_tokens = list(self._subscription_map.keys())
        self._logger.info(
            "Starting KiteTicker transport for %s active trigger-line subscriptions",
            len(instrument_tokens),
        )

        runtime_state = self._emit_state(
            on_state_change,
            status="CONNECTING",
            message=f"Connecting KiteTicker for {len(instrument_tokens)} subscriptions.",
            transport="kite_ticker",
        )
        kws = kite_ticker_cls(settings.zerodha_api_key, resolved_access_token)

        def on_connect(ws, response):
            ws.subscribe(instrument_tokens)
            ws.set_mode(ws.MODE_FULL, instrument_tokens)
            self._logger.info("KiteTicker connected and subscribed to %s instruments", len(instrument_tokens))
            runtime_state.update(
                self._emit_state(
                    on_state_change,
                    status="CONNECTED_SUBSCRIBED",
                    message=f"Connected and subscribed to {len(instrument_tokens)} instruments.",
                    transport="kite_ticker",
                )
            )

        def on_ticks_callback(_ws, ticks):
            payloads = self._build_tick_payloads(ticks)
            if payloads:
                on_ticks(payloads)

        def on_error(_ws, code, reason):
            self._logger.warning("KiteTicker error: code=%s reason=%s", code, reason)
            runtime_state.update(
                self._emit_state(
                    on_state_change,
                    status="ERROR",
                    message=f"KiteTicker error {code}: {reason}",
                    transport="kite_ticker",
                )
            )

        def on_close(_ws, code, reason):
            self._logger.warning("KiteTicker closed: code=%s reason=%s", code, reason)
            runtime_state.update(
                self._emit_state(
                    on_state_change,
                    status="CLOSED",
                    message=f"KiteTicker closed with code {code}.",
                    transport="kite_ticker",
                )
            )

        def on_reconnect(_ws, attempts_count):
            self._logger.info("KiteTicker reconnect attempt %s", attempts_count)
            runtime_state.update(
                self._emit_state(
                    on_state_change,
                    status="RECONNECTING",
                    message=f"KiteTicker reconnect attempt {attempts_count}.",
                    transport="kite_ticker",
                )
            )

        def on_noreconnect(_ws):
            self._logger.warning("KiteTicker exhausted reconnect attempts")
            runtime_state.update(
                self._emit_state(
                    on_state_change,
                    status="NO_RECONNECT",
                    message="KiteTicker exhausted reconnect attempts.",
                    transport="kite_ticker",
                )
            )

        kws.on_connect = on_connect
        kws.on_ticks = on_ticks_callback
        kws.on_error = on_error
        kws.on_close = on_close
        kws.on_reconnect = on_reconnect
        kws.on_noreconnect = on_noreconnect
        kws.connect(threaded=False)
        return runtime_state

    def process_ticks(self, ticks: list[TickPayload], on_ticks: Callable[[list[TickPayload]], None]) -> None:
        on_ticks(ticks)
