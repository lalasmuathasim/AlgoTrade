import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db, verify_database_connectivity
from backend.app.dependencies import require_admin_user
from backend.app.models import BreakoutEvent, Instrument, MarketCandle, PaperTrade, ScanExecution, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.queue import check_redis_connectivity, get_live_engine_runtime
from backend.app.schemas import (
    ExecutionModePayload,
    ExecutionModeResponse,
    ExecutionRulesPayload,
    ExecutionRulesResponse,
    InstrumentPayload,
    StrategySettingsPayload,
    StrategySettingsResponse,
    SymbolValidationPayload,
    WatchlistCreatePayload,
    WatchlistSymbolCreatePayload,
)
from backend.app.services.paper_trading_service import (
    ensure_settings,
    get_execution_mode_payload,
    get_execution_rules_payload,
    update_live_trading_enabled,
    update_execution_rules,
    update_strategy_settings,
)
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.live_engine_runtime import build_live_engine_runtime_snapshot
from backend.app.services.watchlists import ensure_selected_watchlist, set_selected_watchlist
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token, get_current_zerodha_session
from backend.app.services.zerodha import HistoricalCandleProvider, InstrumentMasterSyncService, SubscriptionManager, ZerodhaApiClient, ZerodhaAuthService
from backend.app.ui import render_app_shell


router = APIRouter(tags=["configuration"], dependencies=[Depends(require_admin_user)])
settings = get_settings()
logger = logging.getLogger(__name__)


def _normalize_exchange(exchange: str) -> str:
    value = exchange.strip().upper()
    if value not in {"NSE", "BSE"}:
        raise HTTPException(status_code=422, detail="Exchange must be NSE or BSE")
    return value


def _validate_time_string(value: str, *, field_name: str) -> str:
    candidate = value.strip()
    if not re.fullmatch(r"\d{2}:\d{2}", candidate):
        raise HTTPException(status_code=422, detail=f"{field_name} must use HH:MM format")
    hour, minute = [int(part) for part in candidate.split(":", maxsplit=1)]
    if hour not in range(24) or minute not in range(60):
        raise HTTPException(status_code=422, detail=f"{field_name} must use a valid 24-hour time")
    return candidate


def _parse_symbols(symbols_text: str) -> list[str]:
    values = [item.strip().upper() for item in re.split(r"[\s,]+", symbols_text) if item.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _symbol_validation_result(db: Session, exchange: str, parsed_symbols: list[str]) -> dict:
    if not parsed_symbols:
        return {
            "exchange": exchange,
            "requested_symbols": [],
            "valid_symbols": [],
            "invalid_symbols": [],
            "instrument_matches": [],
            "valid_count": 0,
            "invalid_count": 0,
        }

    auth = ZerodhaAuthService()
    if not auth.has_credentials():
        raise HTTPException(status_code=503, detail="Zerodha is not configured for symbol validation")

    try:
        remote_instruments = ZerodhaApiClient(
            auth_service=auth,
            access_token=get_current_zerodha_access_token(db) if db is not None else None,
        ).fetch_exchange_instruments(exchange)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Unable to validate symbols via Zerodha") from exc

    instrument_map = {
        instrument.tradingsymbol.upper(): instrument
        for instrument in remote_instruments
        if instrument.exchange.upper() == exchange
    }

    valid_symbols = [symbol for symbol in parsed_symbols if symbol in instrument_map]
    invalid_symbols = [symbol for symbol in parsed_symbols if symbol not in instrument_map]
    matches = [
        {
            "symbol": symbol,
            "instrument_token": instrument_map[symbol].instrument_token,
            "company_name": instrument_map[symbol].name or instrument_map[symbol].tradingsymbol,
            "segment": instrument_map[symbol].segment,
            "instrument_type": instrument_map[symbol].instrument_type,
        }
        for symbol in valid_symbols
    ]
    return {
        "exchange": exchange,
        "requested_symbols": parsed_symbols,
        "valid_symbols": valid_symbols,
        "invalid_symbols": invalid_symbols,
        "instrument_matches": matches,
        "valid_count": len(valid_symbols),
        "invalid_count": len(invalid_symbols),
        "source": "zerodha",
    }


def _upsert_validated_instruments(db: Session, exchange: str, validation: dict) -> dict[str, Instrument]:
    matches_by_symbol = {
        row["symbol"]: InstrumentPayload(
            instrument_token=row["instrument_token"],
            tradingsymbol=row["symbol"],
            exchange=exchange,
            name=row.get("company_name"),
            segment=row.get("segment"),
            instrument_type=row.get("instrument_type"),
        )
        for row in validation["instrument_matches"]
    }
    if not matches_by_symbol:
        return {}

    InstrumentMasterSyncService().sync(db, instruments=matches_by_symbol.values())
    instruments = db.scalars(
        select(Instrument).where(
            Instrument.exchange == exchange,
            Instrument.tradingsymbol.in_(list(matches_by_symbol.keys())),
        )
    ).all()
    return {instrument.tradingsymbol.upper(): instrument for instrument in instruments}


def _watchlist_payload(db: Session) -> list[dict]:
    watchlists = db.scalars(select(Watchlist).order_by(desc(Watchlist.is_selected), Watchlist.name)).all()
    symbols = db.scalars(
        select(WatchlistSymbol).order_by(WatchlistSymbol.watchlist_id, WatchlistSymbol.exchange, WatchlistSymbol.symbol)
    ).all()

    symbols_by_watchlist: dict[uuid.UUID, list[WatchlistSymbol]] = {}
    for symbol in symbols:
        symbols_by_watchlist.setdefault(symbol.watchlist_id, []).append(symbol)

    payload: list[dict] = []
    for watchlist in watchlists:
        members = symbols_by_watchlist.get(watchlist.id, [])
        mapped_symbols = sum(1 for member in members if member.instrument_token is not None)
        payload.append(
            {
                "id": str(watchlist.id),
                "name": watchlist.name,
                "description": watchlist.description,
                "exchange": watchlist.exchange,
                "is_selected": watchlist.is_selected,
                "symbol_count": len(members),
                "mapped_symbol_count": mapped_symbols,
                "symbols": [
                    {
                        "id": str(member.id),
                        "exchange": member.exchange,
                        "symbol": member.symbol,
                        "company_name": member.company_name,
                        "instrument_token": member.instrument_token,
                        "is_active": member.is_active,
                    }
                    for member in members
                ],
            }
        )
    return payload


def _watchlist_detail_payload(db: Session, watchlist_id: uuid.UUID) -> dict:
    watchlist = db.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = db.scalars(
        select(WatchlistSymbol)
        .where(WatchlistSymbol.watchlist_id == watchlist_id)
        .order_by(WatchlistSymbol.exchange, WatchlistSymbol.symbol)
    ).all()

    latest_candle_map: dict[tuple[str, str], MarketCandle] = {}
    if symbols:
        exchange_groups: dict[str, list[str]] = {}
        for symbol in symbols:
            exchange_groups.setdefault(symbol.exchange, []).append(symbol.symbol)
        recent_threshold = datetime.now(UTC) - timedelta(days=7)
        for exchange, exchange_symbols in exchange_groups.items():
            candles = db.scalars(
                select(MarketCandle)
                .where(
                    MarketCandle.exchange == exchange,
                    MarketCandle.symbol.in_(exchange_symbols),
                    MarketCandle.timeframe == "3minute",
                    MarketCandle.candle_end >= recent_threshold,
                )
                .order_by(desc(MarketCandle.candle_end))
                .limit(max(len(exchange_symbols) * 12, 200))
            ).all()
            for candle in candles:
                key = (candle.exchange, candle.symbol)
                if key not in latest_candle_map:
                    latest_candle_map[key] = candle

    ltp_map: dict[str, float] = {}
    access_token = get_current_zerodha_access_token(db)
    if symbols and access_token:
        quote_keys = [f"{symbol.exchange}:{symbol.symbol}" for symbol in symbols]
        try:
            ltp_map = ZerodhaApiClient(
                auth_service=ZerodhaAuthService(),
                access_token=access_token,
            ).fetch_ltp_quotes(quote_keys)
        except Exception:  # noqa: BLE001
            logger.warning("Unable to fetch watchlist LTP quotes from Zerodha", exc_info=True)

    symbol_payload = []
    for symbol in symbols:
        quote_key = f"{symbol.exchange}:{symbol.symbol}"
        latest_candle = latest_candle_map.get((symbol.exchange, symbol.symbol))
        current_price = ltp_map.get(quote_key)
        price_source = "zerodha_ltp" if current_price is not None else None
        price_timestamp = None
        if current_price is None and latest_candle is not None:
            current_price = latest_candle.close
            price_source = "latest_3minute_close"
            price_timestamp = latest_candle.candle_end.isoformat()

        symbol_payload.append(
            {
                "id": str(symbol.id),
                "exchange": symbol.exchange,
                "symbol": symbol.symbol,
                "company_name": symbol.company_name,
                "instrument_token": symbol.instrument_token,
                "is_active": symbol.is_active,
                "current_price": round(float(current_price), 2) if current_price is not None else None,
                "price_source": price_source,
                "price_timestamp": price_timestamp,
            }
        )

    return {
        "watchlist": {
            "id": str(watchlist.id),
            "name": watchlist.name,
            "description": watchlist.description,
            "exchange": watchlist.exchange,
            "is_selected": watchlist.is_selected,
            "symbol_count": len(symbols),
            "mapped_symbol_count": sum(1 for symbol in symbols if symbol.instrument_token is not None),
        },
        "symbols": symbol_payload,
    }


def _resolve_live_engine_runtime_payload(
    db: Session,
    *,
    selected_watchlist: Watchlist | None,
    zerodha_auth: ZerodhaAuthService,
    zerodha_token_present: bool,
) -> dict:
    try:
        snapshot = get_live_engine_runtime()
    except Exception:  # noqa: BLE001
        logger.exception("Live engine runtime snapshot could not be loaded from Redis")
        snapshot = None
    if snapshot is not None:
        snapshot.setdefault("published_at", None)
        return snapshot

    try:
        subscriptions = SubscriptionManager().describe_active_subscriptions(db)
    except Exception:  # noqa: BLE001
        logger.exception("Active live subscriptions could not be described for readiness payload")
        subscriptions = []
    return {
        **build_live_engine_runtime_snapshot(
            status="NOT_PUBLISHED",
            message="Live engine runtime is unavailable or has not published state yet.",
            selected_watchlist=selected_watchlist,
            subscriptions=subscriptions,
            credentials_configured=zerodha_auth.has_credentials(),
            access_token_configured=zerodha_token_present,
        ),
        "published_at": None,
    }


def _fallback_readiness_payload() -> dict:
    zerodha_auth = ZerodhaAuthService()
    redis_connected = check_redis_connectivity()
    return {
        "database_connected": False,
        "redis_connected": redis_connected,
        "selected_watchlist": None,
        "zerodha_credentials_configured": zerodha_auth.has_credentials(),
        "zerodha_access_token_configured": zerodha_auth.has_access_token(),
        "zerodha_connection_state": "UNKNOWN",
        "zerodha_can_connect": zerodha_auth.has_credentials(),
        "zerodha_profile_test_ready": zerodha_auth.has_access_token(),
        "zerodha_login_url": zerodha_auth.build_login_url(),
        "zerodha_login_time": None,
        "zerodha_access_token_expires_at": None,
        "zerodha_last_validated_at": None,
        "instrument_master_ready": False,
        "instrument_count": 0,
        "active_instrument_count": 0,
        "last_instrument_sync_at": None,
        "watched_symbol_count": 0,
        "mapped_symbol_count": 0,
        "unmapped_symbol_count": 0,
        "unmapped_symbols": [],
        "active_subscription_count": 0,
        "live_engine_ready": False,
        "three_minute_volume_ready": False,
        "symbols_with_recent_3minute_data": 0,
        "latest_3minute_candle_at": None,
        "live_engine_runtime": {
            **build_live_engine_runtime_snapshot(
                status="READINESS_UNAVAILABLE",
                message="Configuration readiness is temporarily unavailable; dependency summary only.",
                selected_watchlist=None,
                subscriptions=[],
                credentials_configured=zerodha_auth.has_credentials(),
                access_token_configured=zerodha_auth.has_access_token(),
            ),
            "published_at": None,
        },
        "symbol_activity": [],
    }


def _truncate_market_structure_tables(db: Session) -> dict[str, int]:
    deleted_counts = {
        "paper_trades": db.execute(delete(PaperTrade)).rowcount or 0,
        "trading_signals": db.execute(
            delete(TradingSignal).where(TradingSignal.source == "ZERODHA")
        ).rowcount
        or 0,
        "breakout_events": db.execute(delete(BreakoutEvent)).rowcount or 0,
        "trigger_lines": db.execute(delete(TriggerLine)).rowcount or 0,
        "scan_executions": db.execute(
            delete(ScanExecution).where(ScanExecution.scan_name == "daily_market_scan")
        ).rowcount
        or 0,
        "market_candles": db.execute(
            delete(MarketCandle).where(MarketCandle.timeframe.in_(["day", "3minute"]))
        ).rowcount
        or 0,
    }
    db.commit()
    return deleted_counts


def _readiness_payload(db: Session) -> dict:
    database_ok = False
    try:
        verify_database_connectivity()
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    zerodha_auth = ZerodhaAuthService()
    zerodha_session = get_current_zerodha_session(db)
    zerodha_token_present = bool(zerodha_session or zerodha_auth.has_access_token())
    zerodha_connection_state = (
        zerodha_session.status
        if zerodha_session is not None
        else "READY_TO_CONNECT"
        if zerodha_auth.has_credentials()
        else "NOT_CONFIGURED"
    )
    subscriptions = SubscriptionManager().get_active_subscriptions(db)
    instruments_count = db.scalar(
        select(func.count()).select_from(Instrument).where(Instrument.exchange.in_(["NSE", "BSE"]))
    ) or 0
    active_instruments_count = db.scalar(
        select(func.count()).select_from(Instrument).where(Instrument.exchange.in_(["NSE", "BSE"]), Instrument.is_active.is_(True))
    ) or 0
    last_instrument_sync = db.scalar(select(func.max(Instrument.synced_at)))
    selected_watchlist = ensure_selected_watchlist(db)

    watched_symbols_query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
    if selected_watchlist is not None:
        watched_symbols_query = watched_symbols_query.where(WatchlistSymbol.watchlist_id == selected_watchlist.id)
    watched_symbols = db.scalars(
        watched_symbols_query.order_by(WatchlistSymbol.exchange, WatchlistSymbol.symbol)
    ).all()
    watched_symbol_keys = {(symbol.exchange, symbol.symbol) for symbol in watched_symbols}
    mapped_symbol_count = sum(1 for symbol in watched_symbols if symbol.instrument_token is not None)
    unmapped_symbols = [
        f"{symbol.exchange}:{symbol.symbol}"
        for symbol in watched_symbols
        if symbol.instrument_token is None
    ]

    recent_threshold = datetime.now(UTC) - timedelta(days=2)
    latest_candles = db.scalars(
        select(MarketCandle)
        .where(MarketCandle.timeframe == "3minute", MarketCandle.candle_end >= recent_threshold)
        .order_by(desc(MarketCandle.candle_end))
        .limit(2000)
    ).all()
    latest_candle_by_symbol: dict[tuple[str, str], MarketCandle] = {}
    for candle in latest_candles:
        key = (candle.exchange, candle.symbol)
        if key in watched_symbol_keys and key not in latest_candle_by_symbol:
            latest_candle_by_symbol[key] = candle

    symbol_activity = [
        {
            "exchange": symbol.exchange,
            "symbol": symbol.symbol,
            "instrument_token": symbol.instrument_token,
            "company_name": symbol.company_name,
            "latest_3minute_candle_at": latest_candle_by_symbol.get((symbol.exchange, symbol.symbol)).candle_end.isoformat()
            if (symbol.exchange, symbol.symbol) in latest_candle_by_symbol
            else None,
            "latest_3minute_volume": latest_candle_by_symbol.get((symbol.exchange, symbol.symbol)).volume
            if (symbol.exchange, symbol.symbol) in latest_candle_by_symbol
            else None,
        }
        for symbol in watched_symbols[:25]
    ]

    latest_three_minute_candle = max(
        (candle.candle_end for candle in latest_candle_by_symbol.values()),
        default=None,
    )
    symbols_with_recent_candles = len(latest_candle_by_symbol)
    watched_symbol_count = len(watched_symbols)
    live_engine_runtime = _resolve_live_engine_runtime_payload(
        db,
        selected_watchlist=selected_watchlist,
        zerodha_auth=zerodha_auth,
        zerodha_token_present=zerodha_token_present,
    )

    return {
        "database_connected": database_ok,
        "redis_connected": check_redis_connectivity(),
        "selected_watchlist": {
            "id": str(selected_watchlist.id),
            "name": selected_watchlist.name,
            "exchange": selected_watchlist.exchange,
        }
        if selected_watchlist
        else None,
        "zerodha_credentials_configured": zerodha_auth.has_credentials(),
        "zerodha_access_token_configured": zerodha_token_present,
        "zerodha_connection_state": zerodha_connection_state,
        "zerodha_can_connect": zerodha_auth.has_credentials(),
        "zerodha_profile_test_ready": zerodha_token_present,
        "zerodha_login_url": zerodha_auth.build_login_url(),
        "zerodha_login_time": zerodha_session.login_time.isoformat() if zerodha_session and zerodha_session.login_time else None,
        "zerodha_access_token_expires_at": zerodha_session.access_token_expires_at.isoformat()
        if zerodha_session and zerodha_session.access_token_expires_at
        else None,
        "zerodha_last_validated_at": zerodha_session.last_validated_at.isoformat()
        if zerodha_session and zerodha_session.last_validated_at
        else None,
        "instrument_master_ready": active_instruments_count > 0,
        "instrument_count": int(instruments_count),
        "active_instrument_count": int(active_instruments_count),
        "last_instrument_sync_at": last_instrument_sync.isoformat() if last_instrument_sync else None,
        "watched_symbol_count": watched_symbol_count,
        "mapped_symbol_count": mapped_symbol_count,
        "unmapped_symbol_count": watched_symbol_count - mapped_symbol_count,
        "unmapped_symbols": unmapped_symbols[:20],
        "active_subscription_count": len(subscriptions),
        "live_engine_ready": zerodha_token_present and mapped_symbol_count > 0,
        "three_minute_volume_ready": symbols_with_recent_candles > 0,
        "symbols_with_recent_3minute_data": symbols_with_recent_candles,
        "latest_3minute_candle_at": latest_three_minute_candle.isoformat() if latest_three_minute_candle else None,
        "live_engine_runtime": live_engine_runtime,
        "symbol_activity": symbol_activity,
    }


@router.get("/configuration", response_class=HTMLResponse)
def configuration_page() -> str:
    body_html = """
    <section id="configSummary" class="metric-strip"></section>
    <section class="layout-main-aside">
      <div class="rail-stack">
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2>Configured Watchlists</h2>
              <p class="panel-copy">Open a list to inspect it, or switch the runtime focus with a single action.</p>
            </div>
          </div>
          <table id="watchlistsTable"></table>
        </div>
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Watchlist Builder</h2>
              <p class="panel-copy">Step 1 creates or selects the watchlist. Step 2 validates symbols against Zerodha and adds the clean set into that chosen watchlist.</p>
            </div>
            <div class="badge">2 Steps</div>
          </div>
          <div class="builder-steps" style="margin-top: 14px;">
            <section class="builder-step">
              <div class="step-tag">Step 1</div>
              <h3>Choose Watchlist</h3>
              <p class="panel-copy">Create a fresh watchlist or choose one you already maintain. You can also mark the chosen watchlist as the one used for scans and live monitoring.</p>
              <p id="watchlistStatus" class="inline-note">Create a watchlist first, or choose an existing watchlist to continue the builder flow.</p>
              <div class="field">
                <label for="watchlistName">Watchlist name</label>
                <input id="watchlistName" type="text" placeholder="NSE Core Swing Watchlist" />
              </div>
              <div class="field">
                <label for="watchlistDescription">Description</label>
                <input id="watchlistDescription" type="text" placeholder="Daily draw/redraw universe for swing structures" />
              </div>
              <div class="field">
                <label for="watchlistExchange">Default exchange</label>
                <select id="watchlistExchange">
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                </select>
              </div>
              <div class="inline" style="margin-bottom: 12px;">
                <button id="createWatchlistButton" class="primary" type="button">Create Watchlist</button>
              </div>
              <div class="field">
                <label for="targetWatchlist">Working watchlist</label>
                <select id="targetWatchlist"></select>
                <div class="field-help">This selected watchlist is the destination for validated symbols in step 2.</div>
              </div>
              <div class="inline">
                <button id="useTargetWatchlistButton" class="secondary" type="button">Use Selected Watchlist</button>
              </div>
            </section>
            <section id="symbolBuilderStep" class="builder-step">
              <div class="step-tag">Step 2</div>
              <h3>Validate And Add Symbols</h3>
              <p id="validationStatus" class="inline-note">Choose or create a watchlist in step 1, then validate symbols against Zerodha before saving only the clean set.</p>
              <div class="field">
                <label for="symbolsExchange">Exchange</label>
                <select id="symbolsExchange">
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                </select>
              </div>
              <div class="field">
                <label for="symbolsInput">Symbols</label>
                <textarea id="symbolsInput" placeholder="RELIANCE, INFY, TCS&#10;HDFCBANK&#10;SBIN"></textarea>
              </div>
              <div class="inline">
                <button id="validateSymbolsButton" class="primary" type="button">Validate Symbols</button>
                <button id="saveSymbolsButton" class="secondary" type="button">Add Valid Symbols</button>
              </div>
            </section>
          </div>
          <hr />
          <div class="panel-header">
            <div>
              <h3>Validation Result</h3>
              <p class="panel-copy">Review the matched company name and instrument token before committing symbols into the watchlist.</p>
            </div>
          </div>
          <div id="validationBreakdown" class="validation-summary">No validation run yet.</div>
          <table id="validationTable"></table>
        </section>
      </div>
      <div class="rail-stack">
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2>External Readiness</h2>
              <p class="panel-copy">This rail tracks Zerodha session health, mapping coverage, and the 3-minute monitoring readiness path.</p>
            </div>
          </div>
          <div id="readinessStatus" class="status-box">Checking Zerodha, Redis, and 3-minute data readiness...</div>
          <div id="zerodhaConnectionStatus" class="status-box" style="margin-top: 12px;">Checking Zerodha connection status...</div>
          <div id="zerodhaConnectionBadge" class="inline" style="margin-top: 10px;"></div>
          <div id="readinessPills" class="readiness-links"></div>
          <div id="liveRuntimeDetails" class="validation-summary" style="margin-top: 14px;">Loading live runtime details...</div>
          <div class="inline" style="margin-top: 12px;">
            <button id="connectZerodhaButton" class="primary" type="button">Connect Zerodha</button>
            <button id="testZerodhaButton" class="secondary" type="button">Test Connection</button>
            <button id="syncInstrumentsButton" class="secondary" type="button">Sync Instruments From Zerodha</button>
            <button id="refreshReadinessButton" class="secondary" type="button">Refresh Readiness</button>
          </div>
        </div>
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>3-Minute Coverage Notes</h2>
              <p class="panel-copy">This quick reference helps explain if the live engine is ready, partially mapped, or still waiting on instrument and candle activity.</p>
            </div>
          </div>
          <ul class="list">
            <li class="pill">Mapped watchlist symbols improve live-engine readiness</li>
            <li class="pill">Recent 3-minute candles confirm that market monitoring is active</li>
            <li class="pill">Use Zerodha connection and sync controls from the readiness rail</li>
          </ul>
        </section>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Strategy Tuning</h2>
          <p class="panel-copy">Adjust the daily structure scan and 3-minute breakout thresholds here. These values directly change which lines appear and which breakouts become valid signals.</p>
        </div>
        <div class="badge">Runtime</div>
      </div>
      <div id="strategySettingsStatus" class="inline-note">Loading strategy tuning values from the runtime settings store...</div>
      <div class="compact-grid">
        <div class="field">
          <label for="dailyCandleLookbackInput">Daily candle lookback</label>
          <input id="dailyCandleLookbackInput" type="number" min="20" max="300" step="1" />
          <div class="field-help">Completed daily candles reviewed for swing highs and lows.</div>
        </div>
        <div class="field">
          <label for="swingWindowInput">Swing window</label>
          <input id="swingWindowInput" type="number" min="1" max="10" step="1" />
          <div class="field-help">Candles on each side required to confirm a swing point.</div>
        </div>
        <div class="field">
          <label for="maxGapPercentInput">Max gap percent</label>
          <input id="maxGapPercentInput" type="number" min="0.1" max="10" step="0.1" />
          <div class="field-help">Rejects swing pairs when the level gap becomes too wide.</div>
        </div>
        <div class="field">
          <label for="minSwingDistanceInput">Min swing distance</label>
          <input id="minSwingDistanceInput" type="number" min="1" max="50" step="1" />
          <div class="field-help">Minimum candle spacing between the two chosen swings.</div>
        </div>
        <div class="field">
          <label for="dailyStructureRebuildEnabledInput">Enable daily market structure rebuild</label>
          <select id="dailyStructureRebuildEnabledInput"><option value="true">ON</option><option value="false">OFF</option></select>
          <div class="field-help">When ON, the scheduler rebuilds active support and resistance once each trading day after market close.</div>
        </div>
        <div class="field">
          <label for="dailyStructureRebuildTimeInput">Daily rebuild time</label>
          <input id="dailyStructureRebuildTimeInput" type="time" step="60" />
          <div class="field-help">24-hour market-local time used by the automatic daily rebuild scheduler.</div>
        </div>
        <div class="field">
          <label for="predictionProximityPercentInput">Prediction proximity percent</label>
          <input id="predictionProximityPercentInput" type="number" min="0.1" max="20" step="0.1" />
          <div class="field-help">A symbol appears in the potential-hit table when its latest daily close stays within this percent of an active support or resistance line and recent closes are moving toward that line.</div>
        </div>
        <div class="field">
          <label for="buyVolumeMultiplierInput">Buy volume multiplier</label>
          <input id="buyVolumeMultiplierInput" type="number" min="0.1" max="20" step="0.1" />
          <div class="field-help">BUY breakout volume required versus the prior 3-minute candle.</div>
        </div>
        <div class="field">
          <label for="sellVolumeMultiplierInput">Sell volume multiplier</label>
          <input id="sellVolumeMultiplierInput" type="number" min="0.1" max="20" step="0.1" />
          <div class="field-help">SELL breakdown volume required versus the prior 3-minute candle.</div>
        </div>
        <div class="field">
          <label for="entryBufferTicksInput">Entry buffer ticks</label>
          <input id="entryBufferTicksInput" type="number" min="0.01" max="10" step="0.01" />
          <div class="field-help">Extra ticks added before generating the entry trigger.</div>
        </div>
        <div class="field">
          <label for="stopLossBufferTicksInput">Stop-loss buffer ticks</label>
          <input id="stopLossBufferTicksInput" type="number" min="0.01" max="10" step="0.01" />
          <div class="field-help">Extra ticks added beyond the trigger line for protection.</div>
        </div>
      </div>
      <ul class="guide-list">
        <li>Smaller swing window creates more swing points and more candidate lines.</li>
        <li>Larger max gap percent allows looser swing matching at the same level.</li>
        <li>Larger minimum swing distance filters out crowded nearby swing pairs.</li>
        <li>Higher volume multipliers produce fewer but stronger breakout confirmations.</li>
        <li>Entry and stop buffers reduce exact-line fills when price is noisy.</li>
      </ul>
      <p class="inline-note" style="margin-top: 14px;">
        Use the truncate action only when cached candles or derived market-structure records are clearly wrong. It clears stored daily and 3-minute market-structure data so the next redraw can rebuild from a clean state without touching watchlists, instruments, users, or Zerodha login state.
      </p>
      <div class="inline" style="margin-top: 14px;">
        <button id="saveStrategySettingsButton" class="primary" type="button">Save Strategy Tuning</button>
        <button id="refreshStrategySettingsButton" class="secondary" type="button">Reload Values</button>
        <button id="redrawMarketStructureButton" class="secondary" type="button">Redraw Market Structure Now</button>
        <button id="truncateMarketStructureButton" class="ghost" type="button">Truncate Market Structure Tables</button>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Execution &amp; Risk Rules</h2>
          <p class="panel-copy">Define how valid breakouts become orders, how targets and quantity are chosen, what risk caps apply, and how future confidence gating should behave.</p>
        </div>
        <div id="executionModeBadge" class="badge warn">Paper Only</div>
      </div>
      <p id="executionModeStatus" class="inline-note">Loading execution and risk rules...</p>
      <ul id="executionModeDetails" class="guide-list"></ul>
      <details open style="margin-top: 14px;">
        <summary><strong>Entry Rules</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="requireCandleCloseBeyondLineInput">Require candle close beyond line</label>
            <select id="requireCandleCloseBeyondLineInput"><option value="true">Yes</option><option value="false">No</option></select>
            <div class="field-help">BUY confirms only after 3-minute close above resistance, SELL only after close below support.</div>
          </div>
          <div class="field">
            <label for="entryBufferTicksExecutionInput">Entry buffer ticks</label>
            <input id="entryBufferTicksExecutionInput" type="number" min="0.01" max="10" step="0.01" />
            <div class="field-help">Extra ticks above breakout high or below breakdown low before entry.</div>
          </div>
          <div class="field">
            <label for="orderTypeInput">Order type</label>
            <select id="orderTypeInput"><option value="LIMIT">LIMIT</option><option value="MARKET">MARKET</option></select>
          </div>
          <div class="field">
            <label for="productTypeInput">Product type</label>
            <select id="productTypeInput"><option value="MIS">MIS</option><option value="CNC">CNC</option><option value="NRML">NRML</option></select>
          </div>
          <div class="field">
            <label for="reentryCooldownMinutesInput">Re-entry cooldown minutes</label>
            <input id="reentryCooldownMinutesInput" type="number" min="0" max="1440" step="1" />
          </div>
          <div class="field">
            <label for="allowRepeatEntrySameLineInput">Allow repeat entry on same trigger line</label>
            <select id="allowRepeatEntrySameLineInput"><option value="false">No</option><option value="true">Yes</option></select>
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>Stop Loss &amp; Target</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="stopLossBufferTicksExecutionInput">Stop loss buffer ticks</label>
            <input id="stopLossBufferTicksExecutionInput" type="number" min="0.01" max="10" step="0.01" />
          </div>
          <div class="field">
            <label for="targetModeInput">Target mode</label>
            <select id="targetModeInput"><option value="NEAREST_DAILY_SWING">Nearest Daily Swing</option><option value="FIXED_RISK_REWARD">Fixed Risk Reward</option></select>
          </div>
          <div class="field">
            <label for="fallbackRiskRewardRatioInput">Fallback risk reward ratio</label>
            <input id="fallbackRiskRewardRatioInput" type="number" min="0.1" max="20" step="0.1" />
          </div>
          <div class="field">
            <label for="useNearestDailySwingTargetInput">Use nearest daily swing target</label>
            <select id="useNearestDailySwingTargetInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div class="field">
            <label for="minimumRewardRiskRatioInput">Minimum reward to risk ratio</label>
            <input id="minimumRewardRiskRatioInput" type="number" min="0.1" max="20" step="0.1" />
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>Position Sizing</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="defaultQuantityModeInput">Quantity mode</label>
            <select id="defaultQuantityModeInput"><option value="RISK_BASED">Risk Based</option><option value="FIXED">Fixed</option></select>
          </div>
          <div class="field">
            <label for="fixedQuantityInput">Fixed quantity</label>
            <input id="fixedQuantityInput" type="number" min="1" max="100000" step="1" />
          </div>
          <div class="field">
            <label for="capitalPerTradeInput">Capital per trade</label>
            <input id="capitalPerTradeInput" type="number" min="1" step="0.01" />
          </div>
          <div class="field">
            <label for="riskPerTradeInput">Risk per trade</label>
            <input id="riskPerTradeInput" type="number" min="1" step="0.01" />
          </div>
          <div class="field">
            <label for="maxQuantityPerOrderInput">Max quantity per order</label>
            <input id="maxQuantityPerOrderInput" type="number" min="1" max="100000" step="1" />
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>Trade Filters</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="buyVolumeMultiplierExecutionInput">BUY volume multiplier</label>
            <input id="buyVolumeMultiplierExecutionInput" type="number" min="0.1" max="20" step="0.1" />
          </div>
          <div class="field">
            <label for="sellVolumeMultiplierExecutionInput">SELL volume multiplier</label>
            <input id="sellVolumeMultiplierExecutionInput" type="number" min="0.1" max="20" step="0.1" />
          </div>
          <div class="field">
            <label for="skipZeroPreviousVolumeInput">Skip if previous candle volume is zero</label>
            <select id="skipZeroPreviousVolumeInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div class="field">
            <label for="minimumPriceInput">Minimum price</label>
            <input id="minimumPriceInput" type="number" min="0.01" step="0.01" />
          </div>
          <div class="field">
            <label for="maximumPriceInput">Maximum price</label>
            <input id="maximumPriceInput" type="number" min="0.01" step="0.01" />
          </div>
          <div class="field">
            <label for="allowedExchangesInput">Allowed exchanges</label>
            <input id="allowedExchangesInput" type="text" placeholder="NSE,BSE" />
            <div class="field-help">Comma separated. Example: `NSE,BSE`.</div>
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>Risk Controls</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="paperTradingEnabledInput">Enable paper trading</label>
            <select id="paperTradingEnabledInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div class="field">
            <label for="liveTradingEnabledInput">Enable live trading</label>
            <select id="liveTradingEnabledInput"><option value="false">No</option><option value="true">Yes</option></select>
          </div>
          <div class="field">
            <label for="maxTradesPerDayInput">Max trades per day</label>
            <input id="maxTradesPerDayInput" type="number" min="1" max="100" step="1" />
          </div>
          <div class="field">
            <label for="maxOpenPositionsInput">Max open positions</label>
            <input id="maxOpenPositionsInput" type="number" min="1" max="100" step="1" />
          </div>
          <div class="field">
            <label for="maxDailyLossInput">Max daily loss</label>
            <input id="maxDailyLossInput" type="number" min="1" step="0.01" />
          </div>
          <div class="field">
            <label for="maxLossPerSymbolPerDayInput">Max loss per symbol per day</label>
            <input id="maxLossPerSymbolPerDayInput" type="number" min="1" step="0.01" />
          </div>
          <div class="field">
            <label for="blockAfterDailyLossInput">Block new trades after max daily loss</label>
            <select id="blockAfterDailyLossInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div class="field">
            <label for="noTradeAfterTimeInput">No-trade after time</label>
            <input id="noTradeAfterTimeInput" type="text" placeholder="15:00" />
          </div>
          <div class="field">
            <label for="marketHoursGuardInput">Market hours guard</label>
            <select id="marketHoursGuardInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>Execution Cost Assumptions</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="brokerageEstimateInput">Brokerage estimate</label>
            <input id="brokerageEstimateInput" type="number" min="0" step="0.01" />
          </div>
          <div class="field">
            <label for="slippageEstimateInput">Slippage estimate</label>
            <input id="slippageEstimateInput" type="number" min="0" step="0.01" />
          </div>
          <div class="field">
            <label for="exchangeChargesEstimateInput">Exchange charges estimate</label>
            <input id="exchangeChargesEstimateInput" type="number" min="0" step="0.01" />
          </div>
          <div class="field">
            <label for="useCostAdjustedPnlInput">Use cost-adjusted P&amp;L</label>
            <select id="useCostAdjustedPnlInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
        </div>
      </details>
      <details style="margin-top: 14px;">
        <summary><strong>AI Confidence</strong></summary>
        <div class="compact-grid" style="margin-top: 12px;">
          <div class="field">
            <label for="enableConfidenceFilterInput">Enable confidence filter</label>
            <select id="enableConfidenceFilterInput"><option value="false">No</option><option value="true">Yes</option></select>
          </div>
          <div class="field">
            <label for="minimumConfidenceScoreInput">Minimum confidence score</label>
            <input id="minimumConfidenceScoreInput" type="number" min="0" max="1" step="0.01" />
          </div>
          <div class="field">
            <label for="confidenceSourceInput">Confidence source</label>
            <select id="confidenceSourceInput"><option value="RULES_ONLY">Rules Only</option><option value="ANALYTICS_MODEL">Analytics Model</option><option value="AI_MODEL">AI Model</option></select>
          </div>
          <div class="field">
            <label for="allowLowConfidencePaperOnlyInput">Allow low-confidence paper trades only</label>
            <select id="allowLowConfidencePaperOnlyInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div class="field">
            <label for="blockLiveTradesBelowConfidenceThresholdInput">Block live trades below confidence threshold</label>
            <select id="blockLiveTradesBelowConfidenceThresholdInput"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
        </div>
      </details>
      <div class="inline" style="margin-top: 16px;">
        <button id="saveExecutionRulesButton" class="primary" type="button">Save Execution &amp; Risk Rules</button>
        <button id="refreshExecutionRulesButton" class="secondary" type="button">Reload Values</button>
      </div>
    </section>
    <section id="watchlistDetailSection" class="panel">
      <div class="panel-header">
        <div>
          <h2>Watchlist Detail</h2>
          <p class="panel-copy">Inspect the selected or opened watchlist with mapped symbols, companies, and latest available market price reference.</p>
        </div>
      </div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p id="watchlistDetailMeta" class="table-toolbar-copy">Select a watchlist to inspect its tracked symbols and current prices.</p>
          <button id="watchlistDetailToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
        </div>
        <div id="watchlistDetailFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 820px;">
          <table id="watchlistDetailTable"></table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>3-Minute Coverage Snapshot</h2>
          <p class="panel-copy">Recent candle visibility for the currently watched symbols. This is the fastest way to confirm that monitoring is producing fresh market data.</p>
        </div>
      </div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p class="table-toolbar-copy">Preview mode trims large coverage lists while keeping horizontal scrolling available for the full market monitor view.</p>
          <button id="symbolActivityToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
        </div>
        <div id="symbolActivityFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 760px;">
          <table id="symbolActivityTable"></table>
        </div>
      </div>
    </section>
    """
    script = """
    let cachedValidation = null;
    let cachedWatchlists = [];
    let currentWatchlistDetailId = null;
    let activeBuilderWatchlistId = null;
    let latestReadiness = null;
    let latestZerodhaStatus = null;
    let latestStrategySettings = null;
    let latestExecutionSettings = null;
    const syncWatchlistDetailPreview = bindCollapsibleTable({
      buttonId: "watchlistDetailToggle",
      frameId: "watchlistDetailFrame",
      tableId: "watchlistDetailTable",
      previewRows: 8,
    });
    const syncSymbolActivityPreview = bindCollapsibleTable({
      buttonId: "symbolActivityToggle",
      frameId: "symbolActivityFrame",
      tableId: "symbolActivityTable",
      previewRows: 8,
    });
    const zerodhaStatusMessages = {
      connected: { message: "Zerodha connection established successfully.", tone: "success" },
      error: { message: "Zerodha login did not complete successfully.", tone: "error" },
      not_configured: { message: "Zerodha credentials are not configured on the server.", tone: "warn" },
      missing_request_token: { message: "Zerodha callback did not include a request token.", tone: "warn" },
      token_exchange_failed: { message: "Zerodha token exchange failed. Please retry the connection flow.", tone: "error" },
      callback_failed: { message: "Unexpected Zerodha callback failure. Please retry.", tone: "error" },
    };

    function renderZerodhaConnectionStatus(result) {
      const toneMap = {
        Connected: "success",
        "Ready To Connect": "warn",
        Expired: "warn",
        "Invalid Token": "error",
        "Not Configured": "warn",
      };
      const badgeClassMap = {
        Connected: "badge",
        "Ready To Connect": "badge warn",
        Expired: "badge warn",
        "Invalid Token": "badge danger",
        "Not Configured": "badge warn",
      };
      const tone = toneMap[result.status] || "";
      const detail = result.connected
        ? `${result.profile_user_name || result.profile_user_id || "Connected"} · token expires ${result.access_token_expires_at ? new Date(result.access_token_expires_at).toLocaleString() : "unknown"}`
        : result.status === "Ready To Connect"
          ? "Zerodha credentials are configured. Use Connect Zerodha to complete login and create a testable session."
          : `${result.status}${result.access_token_expires_at ? ` · token expiry ${new Date(result.access_token_expires_at).toLocaleString()}` : ""}`;
      setBox("zerodhaConnectionStatus", detail, tone);
      document.getElementById("zerodhaConnectionBadge").innerHTML = `<span class="${badgeClassMap[result.status] || "badge warn"}">${result.status}</span>`;
      document.getElementById("testZerodhaButton").disabled = !result.can_connect;
    }

    function applyZerodhaCallbackMessage() {
      const params = new URLSearchParams(window.location.search);
      const status = params.get("zerodha_status");
      if (!status || !zerodhaStatusMessages[status]) {
        return;
      }
      const { message, tone } = zerodhaStatusMessages[status];
      setBox("zerodhaConnectionStatus", message, tone);
      params.delete("zerodha_status");
      const nextQuery = params.toString();
      const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}`;
      window.history.replaceState({}, "", nextUrl);
    }

    function optionMarkup(items) {
      return items.map((item) => `<option value="${item.id}">${item.name} (${item.exchange})</option>`).join("");
    }

    function scrollToSection(selector) {
      const element = document.querySelector(selector);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function setInlineMessage(id, message, tone = "") {
      const element = document.getElementById(id);
      element.textContent = message;
      element.className = `inline-note ${tone}`.trim();
    }

    function setToolbarCopyMessage(id, message, tone = "") {
      const element = document.getElementById(id);
      element.textContent = message;
      element.className = `table-toolbar-copy ${tone}`.trim();
    }

    function setSummaryMessage(id, message, tone = "") {
      const element = document.getElementById(id);
      element.textContent = message;
      element.className = `validation-summary ${tone}`.trim();
    }

    function updateBuilderState() {
      const targetWatchlist = document.getElementById("targetWatchlist");
      const watchlistId = targetWatchlist.value;
      const selectedWatchlist = cachedWatchlists.find((item) => item.id === watchlistId) || null;
      const hasWatchlist = Boolean(selectedWatchlist);
      const stepTwoIds = ["symbolsExchange", "symbolsInput", "validateSymbolsButton", "saveSymbolsButton", "useTargetWatchlistButton"];
      stepTwoIds.forEach((id) => {
        const element = document.getElementById(id);
        if (element) {
          element.disabled = !hasWatchlist;
        }
      });
      document.getElementById("symbolBuilderStep").classList.toggle("is-disabled", !hasWatchlist);
      if (selectedWatchlist) {
        document.getElementById("symbolsExchange").value = selectedWatchlist.exchange;
        setInlineMessage(
          "validationStatus",
          `Working watchlist: ${selectedWatchlist.name} (${selectedWatchlist.exchange}). Validate symbols against Zerodha, then add the valid set.`,
          "",
        );
      } else {
        setInlineMessage(
          "validationStatus",
          "Choose or create a watchlist in step 1, then validate symbols against Zerodha before saving only the clean set.",
          "warn",
        );
      }
    }

    function renderConfigCards(readiness, watchlists) {
      const totalSymbols = watchlists.reduce((sum, item) => sum + item.symbol_count, 0);
      const mappedSymbols = watchlists.reduce((sum, item) => sum + item.mapped_symbol_count, 0);
      const selected = watchlists.find((item) => item.is_selected);
      renderMetricStrip(document.getElementById("configSummary"), [
        { label: "Watchlists", value: watchlists.length, meta: "Configured draw and redraw groups" },
        { label: "In Use", value: selected ? selected.name : "None", meta: "The only watchlist used for scan and live monitoring" },
        { label: "Watched Symbols", value: totalSymbols, meta: "Symbols queued for daily structure scanning" },
        { label: "Mapped Symbols", value: mappedSymbols, meta: "Symbols linked to Zerodha instrument tokens" },
        { label: "3-Minute Coverage", value: readiness.symbols_with_recent_3minute_data, meta: "Watched symbols with recent candle volume" },
      ]);
    }

    function renderStrategySettings(settingsPayload) {
      latestStrategySettings = settingsPayload;
      document.getElementById("dailyCandleLookbackInput").value = settingsPayload.daily_candle_lookback;
      document.getElementById("swingWindowInput").value = settingsPayload.swing_window;
      document.getElementById("maxGapPercentInput").value = settingsPayload.max_gap_percent;
      document.getElementById("minSwingDistanceInput").value = settingsPayload.min_swing_distance;
      document.getElementById("dailyStructureRebuildEnabledInput").value = booleanSelectValue(settingsPayload.daily_structure_rebuild_enabled);
      document.getElementById("dailyStructureRebuildTimeInput").value = settingsPayload.daily_structure_rebuild_time;
      document.getElementById("predictionProximityPercentInput").value = settingsPayload.prediction_proximity_percent;
      document.getElementById("buyVolumeMultiplierInput").value = settingsPayload.buy_volume_multiplier;
      document.getElementById("sellVolumeMultiplierInput").value = settingsPayload.sell_volume_multiplier;
      document.getElementById("entryBufferTicksInput").value = settingsPayload.entry_buffer_ticks;
      document.getElementById("stopLossBufferTicksInput").value = settingsPayload.stop_loss_buffer_ticks;
      setInlineMessage(
        "strategySettingsStatus",
        `Daily scan uses ${settingsPayload.daily_candle_lookback} candles with swing window ${settingsPayload.swing_window}. Gap filter ${settingsPayload.max_gap_percent}% · min swing distance ${settingsPayload.min_swing_distance} candles · auto rebuild ${settingsPayload.daily_structure_rebuild_enabled ? `ON at ${settingsPayload.daily_structure_rebuild_time}` : "OFF"} · potential-hit threshold ${settingsPayload.prediction_proximity_percent}% · BUY volume ${settingsPayload.buy_volume_multiplier}x · SELL volume ${settingsPayload.sell_volume_multiplier}x.`,
        "success",
      );
    }

    function booleanSelectValue(value) {
      return value ? "true" : "false";
    }

    function nullableNumberValue(value) {
      return value ?? "";
    }

    function parseBooleanSelect(id) {
      return document.getElementById(id).value === "true";
    }

    function parseNullableFloat(id) {
      const raw = document.getElementById(id).value.trim();
      return raw ? Number(raw) : null;
    }

    function parseNullableInt(id) {
      const raw = document.getElementById(id).value.trim();
      return raw ? Number(raw) : null;
    }

    function parseAllowedExchanges() {
      const value = document.getElementById("allowedExchangesInput").value.trim();
      if (!value) {
        return ["NSE", "BSE"];
      }
      return value
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter((item, index, values) => (item === "NSE" || item === "BSE") && values.indexOf(item) === index);
    }

    function renderExecutionSettings(settingsPayload) {
      latestExecutionSettings = settingsPayload;
      const liveEnabled = Boolean(settingsPayload.live_trading_enabled);
      const paperEnabled = Boolean(settingsPayload.paper_trading_enabled);
      document.getElementById("executionModeBadge").className = liveEnabled ? "badge danger" : paperEnabled ? "badge warn" : "badge";
      document.getElementById("executionModeBadge").textContent = liveEnabled ? "Paper + Live" : paperEnabled ? "Paper Only" : "Live Disabled";
      setInlineMessage(
        "executionModeStatus",
        liveEnabled
          ? "Live Zerodha order placement is enabled. Valid signals will continue generating paper trades and will also place live limit entry orders."
          : "Execution rules are loaded. Paper trading, live trading, filters, risk caps, and future confidence gating can all be controlled from this panel.",
        liveEnabled ? "warn" : "",
      );
      document.getElementById("executionModeDetails").innerHTML = [
        `Paper trading: ${paperEnabled ? "enabled" : "disabled"}`,
        `Live trading: ${liveEnabled ? "enabled" : "disabled"}`,
        `Entry confirmation: ${settingsPayload.require_candle_close_beyond_line ? "candle close beyond line" : "intrabar line cross"}`,
        `Target mode: ${settingsPayload.target_mode === "NEAREST_DAILY_SWING" ? "nearest daily swing" : "fixed risk reward fallback"}`,
        `Confidence filter: ${settingsPayload.enable_confidence_filter ? "enabled" : "disabled"}`,
        `Order path: ${settingsPayload.order_type} ${settingsPayload.product_type} entry orders with saved stop, target, and cost assumptions.`,
      ].map((line) => `<li>${line}</li>`).join("");

      document.getElementById("paperTradingEnabledInput").value = booleanSelectValue(settingsPayload.paper_trading_enabled);
      document.getElementById("liveTradingEnabledInput").value = booleanSelectValue(settingsPayload.live_trading_enabled);
      document.getElementById("requireCandleCloseBeyondLineInput").value = booleanSelectValue(settingsPayload.require_candle_close_beyond_line);
      document.getElementById("entryBufferTicksExecutionInput").value = settingsPayload.entry_buffer_ticks;
      document.getElementById("stopLossBufferTicksExecutionInput").value = settingsPayload.stop_loss_buffer_ticks;
      document.getElementById("targetModeInput").value = settingsPayload.target_mode;
      document.getElementById("fallbackRiskRewardRatioInput").value = settingsPayload.fallback_risk_reward_ratio;
      document.getElementById("useNearestDailySwingTargetInput").value = booleanSelectValue(settingsPayload.use_nearest_daily_swing_target);
      document.getElementById("minimumRewardRiskRatioInput").value = settingsPayload.minimum_reward_risk_ratio;
      document.getElementById("orderTypeInput").value = settingsPayload.order_type;
      document.getElementById("productTypeInput").value = settingsPayload.product_type;
      document.getElementById("reentryCooldownMinutesInput").value = settingsPayload.reentry_cooldown_minutes;
      document.getElementById("allowRepeatEntrySameLineInput").value = booleanSelectValue(settingsPayload.allow_repeat_entry_same_line);
      document.getElementById("defaultQuantityModeInput").value = settingsPayload.default_quantity_mode;
      document.getElementById("fixedQuantityInput").value = nullableNumberValue(settingsPayload.fixed_quantity);
      document.getElementById("capitalPerTradeInput").value = settingsPayload.capital_per_trade;
      document.getElementById("riskPerTradeInput").value = settingsPayload.risk_per_trade;
      document.getElementById("maxQuantityPerOrderInput").value = nullableNumberValue(settingsPayload.max_quantity_per_order);
      document.getElementById("buyVolumeMultiplierExecutionInput").value = settingsPayload.buy_volume_multiplier;
      document.getElementById("sellVolumeMultiplierExecutionInput").value = settingsPayload.sell_volume_multiplier;
      document.getElementById("skipZeroPreviousVolumeInput").value = booleanSelectValue(settingsPayload.skip_zero_previous_volume);
      document.getElementById("minimumPriceInput").value = nullableNumberValue(settingsPayload.minimum_price);
      document.getElementById("maximumPriceInput").value = nullableNumberValue(settingsPayload.maximum_price);
      document.getElementById("allowedExchangesInput").value = (settingsPayload.allowed_exchanges || []).join(",");
      document.getElementById("maxTradesPerDayInput").value = settingsPayload.max_trades_per_day;
      document.getElementById("maxOpenPositionsInput").value = settingsPayload.max_open_positions;
      document.getElementById("maxDailyLossInput").value = settingsPayload.max_daily_loss;
      document.getElementById("maxLossPerSymbolPerDayInput").value = settingsPayload.max_loss_per_symbol_per_day;
      document.getElementById("blockAfterDailyLossInput").value = booleanSelectValue(settingsPayload.block_new_trades_after_max_daily_loss);
      document.getElementById("noTradeAfterTimeInput").value = settingsPayload.no_trade_after_time || "";
      document.getElementById("marketHoursGuardInput").value = booleanSelectValue(settingsPayload.market_hours_guard);
      document.getElementById("brokerageEstimateInput").value = settingsPayload.brokerage_estimate;
      document.getElementById("slippageEstimateInput").value = settingsPayload.slippage_estimate;
      document.getElementById("exchangeChargesEstimateInput").value = settingsPayload.exchange_charges_estimate;
      document.getElementById("useCostAdjustedPnlInput").value = booleanSelectValue(settingsPayload.use_cost_adjusted_pnl);
      document.getElementById("enableConfidenceFilterInput").value = booleanSelectValue(settingsPayload.enable_confidence_filter);
      document.getElementById("minimumConfidenceScoreInput").value = settingsPayload.minimum_confidence_score;
      document.getElementById("confidenceSourceInput").value = settingsPayload.confidence_source;
      document.getElementById("allowLowConfidencePaperOnlyInput").value = booleanSelectValue(settingsPayload.allow_low_confidence_paper_trades_only);
      document.getElementById("blockLiveTradesBelowConfidenceThresholdInput").value = booleanSelectValue(settingsPayload.block_live_trades_below_confidence_threshold);
    }

    function renderExecutionSettingsUnavailable(message) {
      latestExecutionSettings = null;
      document.getElementById("executionModeBadge").className = "badge warn";
      document.getElementById("executionModeBadge").textContent = "Unavailable";
      setInlineMessage("executionModeStatus", message, "warn");
      document.getElementById("executionModeDetails").innerHTML = [
        "Paper trading remains available through the existing backend runtime.",
        "Execution and risk rules could not be loaded right now.",
        "Run the latest database migrations, then refresh this page if the issue persists.",
      ].map((line) => `<li>${line}</li>`).join("");
      document.getElementById("saveExecutionRulesButton").disabled = true;
    }

    function renderWatchlists(watchlists) {
      cachedWatchlists = watchlists;
      document.getElementById("targetWatchlist").innerHTML = watchlists.length
        ? optionMarkup(watchlists)
        : '<option value="">Create a watchlist first</option>';
      const selected = watchlists.find((item) => item.is_selected);
      setInlineMessage(
        "watchlistStatus",
        selected
          ? `Currently using ${selected.name} (${selected.exchange}) for scans, subscriptions, and 3-minute monitoring.`
          : "Create a watchlist first, or choose an existing watchlist to continue the builder flow.",
        selected ? "success" : "",
      );
      renderTable(
        document.getElementById("watchlistsTable"),
        ["Name", "In Use", "Exchange", "Symbols", "Mapped", "Actions"],
        watchlists.map((item) => [
          `<button class="table-link" type="button" onclick="openWatchlistDetail('${item.id}', true)">${item.name}</button>`,
          item.is_selected ? '<span class="badge">IN USE</span>' : '<span class="badge warn">STANDBY</span>',
          item.exchange,
          item.symbol_count,
          item.mapped_symbol_count,
          `<div class="table-actions">
            <button class="table-link subtle" type="button" onclick="openWatchlistDetail('${item.id}', true)">View</button>
            ${item.is_selected
              ? '<span class="table-link subtle" style="cursor: default; color: var(--ok);">Current</span>'
              : `<button class="table-link subtle" type="button" onclick="selectWatchlist('${item.id}')">Use This Watchlist</button>`
            }
          </div>`,
        ]),
      );
      const preferredWatchlist = watchlists.find((item) => item.id === activeBuilderWatchlistId)
        || selected
        || watchlists[0]
        || null;
      activeBuilderWatchlistId = preferredWatchlist ? preferredWatchlist.id : null;
      document.getElementById("targetWatchlist").value = activeBuilderWatchlistId || "";
      updateBuilderState();
    }

    function renderWatchlistDetail(payload) {
      currentWatchlistDetailId = payload.watchlist.id;
      const watchlist = payload.watchlist;
      const statusMessage = `${watchlist.name} · ${watchlist.exchange} · ${watchlist.symbol_count} symbols · ${watchlist.mapped_symbol_count} mapped${watchlist.description ? ` · ${watchlist.description}` : ""}`;
      setToolbarCopyMessage("watchlistDetailMeta", statusMessage, watchlist.is_selected ? "success" : "");
      renderTable(
        document.getElementById("watchlistDetailTable"),
        ["Symbol", "Company", "Instrument Token", "Current Price", "Price Source", "Active"],
        payload.symbols.map((item) => [
          `${item.exchange}:${item.symbol}`,
          item.company_name || "Unknown company",
          item.instrument_token ?? "Unmapped",
          item.current_price ?? "Unavailable",
          item.price_source === "zerodha_ltp"
            ? "Zerodha LTP"
            : item.price_source === "latest_3minute_close"
              ? "Latest 3-min close"
              : "Unavailable",
          item.is_active ? '<span class="badge">ACTIVE</span>' : '<span class="badge warn">INACTIVE</span>',
        ]),
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter watchlist symbols" } },
      );
      syncWatchlistDetailPreview();
    }

    function renderReadiness(readiness, zerodhaStatus) {
      latestReadiness = readiness;
      latestZerodhaStatus = zerodhaStatus;
      const runtime = readiness.live_engine_runtime || null;
      const tone = readiness.database_connected && readiness.redis_connected && readiness.live_engine_ready
        ? "success"
        : readiness.database_connected && readiness.redis_connected
          ? "warn"
          : "error";
      const zerodhaSummary = zerodhaStatus
        ? `Zerodha ${zerodhaStatus.status.toLowerCase()} · connect ${zerodhaStatus.can_connect ? "ready" : "blocked"} · profile test ${zerodhaStatus.can_test_connection ? "ready" : "pending login"}`
        : `Zerodha ${readiness.zerodha_connection_state.toLowerCase().replaceAll("_", " ")} · connect ${readiness.zerodha_can_connect ? "ready" : "blocked"} · profile test ${readiness.zerodha_profile_test_ready ? "ready" : "pending login"}`;
      setBox(
        "readinessStatus",
        `${readiness.selected_watchlist ? `Using ${readiness.selected_watchlist.name} · ` : ""}DB ${readiness.database_connected ? "connected" : "down"} · Redis ${readiness.redis_connected ? "connected" : "down"} · ${zerodhaSummary} · Engine ${runtime?.status ? runtime.status.toLowerCase().replaceAll("_", " ") : "unknown"} · ${readiness.symbols_with_recent_3minute_data}/${readiness.watched_symbol_count} watched symbols have recent 3-minute candle data.`,
        tone,
      );
      const pillData = [
        ["zerodha-credentials", "Zerodha credentials", readiness.zerodha_credentials_configured],
        ["connect-flow", "Connect flow", readiness.zerodha_can_connect],
        ["profile-test", "Profile test", readiness.zerodha_profile_test_ready],
        ["instrument-sync", "Instrument sync", readiness.instrument_master_ready],
        ["token-ready", "Token ready", readiness.zerodha_access_token_configured],
        ["mapped-watchlist", "Mapped watchlist", readiness.mapped_symbol_count > 0 && readiness.unmapped_symbol_count === 0],
        ["live-engine-ready", "Live-engine ready", readiness.live_engine_ready],
        ["three-minute-volume", "3-minute volume", readiness.three_minute_volume_ready],
      ];
      document.getElementById("readinessPills").innerHTML = pillData.map(([key, label, ok]) => `
        <button class="readiness-link" type="button" data-readiness-action="${key}">
          <span class="readiness-mark ${ok ? "ok" : "warn"}">${ok ? "✓" : "!"}</span><span>${label}</span>
        </button>
      `).join("");
      document.querySelectorAll("[data-readiness-action]").forEach((element) => {
        element.addEventListener("click", handleReadinessAction);
      });
      const lastFinalizedCandle = runtime?.last_finalized_candle
        ? `${runtime.last_finalized_candle.exchange}:${runtime.last_finalized_candle.symbol} · end ${runtime.last_finalized_candle.candle_end ? new Date(runtime.last_finalized_candle.candle_end).toLocaleString() : "pending"} · close ${runtime.last_finalized_candle.close ?? "N/A"} · volume ${runtime.last_finalized_candle.volume ?? "N/A"}`
        : "No finalized 3-minute candle published yet";
      const runtimeLines = [
        `Live engine status: ${runtime?.status ? runtime.status.replaceAll("_", " ") : "Unknown"}`,
        `Transport: ${runtime?.transport || "Unavailable"}`,
        `Subscriptions: ${runtime?.subscription_count ?? readiness.active_subscription_count}`,
        `Last tick: ${runtime?.last_tick_symbol ? `${runtime.last_tick_symbol} at ${runtime.last_tick_at ? new Date(runtime.last_tick_at).toLocaleString() : "recently"}` : "No tick published yet"}`,
        `Finalized 3-minute candles: ${runtime?.finalized_candles_count ?? 0}`,
        `Latest finalized candle: ${lastFinalizedCandle}`,
        `Signals created: ${runtime?.signals_created_count ?? 0}${runtime?.last_signal_symbol ? ` · latest ${runtime.last_signal_symbol}` : ""}`,
      ];
      document.getElementById("liveRuntimeDetails").innerHTML = `<ul class="guide-list" style="margin-top: 0;">${runtimeLines.map((line) => `<li>${line}</li>`).join("")}</ul>`;
      renderTable(
        document.getElementById("symbolActivityTable"),
        ["Symbol", "Token", "Latest 3-Min Candle", "Volume"],
        readiness.symbol_activity.map((row) => [
          `${row.exchange}:${row.symbol}`,
          row.instrument_token ?? "Unmapped",
          row.latest_3minute_candle_at ? new Date(row.latest_3minute_candle_at).toLocaleString() : "No recent candle",
          row.latest_3minute_volume ?? "N/A",
        ]),
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter coverage symbols" } },
      );
      syncSymbolActivityPreview();
    }

    async function handleReadinessAction(event) {
      const action = event.currentTarget.dataset.readinessAction;
      if (!latestReadiness) {
        return;
      }
      const runtime = latestReadiness.live_engine_runtime || null;

      if (action === "zerodha-credentials") {
        setBox(
          "readinessStatus",
          latestReadiness.zerodha_credentials_configured
            ? "Zerodha credentials are present in the running backend environment."
            : "Zerodha credentials are missing in the running backend environment. Redeploy after updating secrets.",
          latestReadiness.zerodha_credentials_configured ? "success" : "error",
        );
        return;
      }

      if (action === "connect-flow") {
        if (latestReadiness.zerodha_can_connect) {
          window.location.href = "/api/zerodha/login";
        } else {
          setBox("readinessStatus", "Connect flow is blocked because Zerodha credentials are not configured on the backend.", "error");
        }
        return;
      }

      if (action === "profile-test") {
        if (!latestReadiness.zerodha_can_connect) {
          setBox("readinessStatus", "Profile test is unavailable until Zerodha credentials are configured.", "error");
          return;
        }
        try {
          const [readiness, zerodhaStatus] = await Promise.all([loadReadiness(), loadZerodhaConnectionStatus()]);
          renderReadiness(readiness, zerodhaStatus);
          setBox(
            "readinessStatus",
            `Zerodha profile test completed with status ${zerodhaStatus.status}.`,
            zerodhaStatus.connected ? "success" : "warn",
          );
        } catch (error) {
          setBox("readinessStatus", error.message, "error");
        }
        return;
      }

      if (action === "instrument-sync") {
        document.getElementById("syncInstrumentsButton").click();
        return;
      }

      if (action === "token-ready") {
        if (latestReadiness.zerodha_access_token_configured) {
          setBox("readinessStatus", "A Zerodha access token is available to the backend runtime.", "success");
        } else if (latestReadiness.zerodha_can_connect) {
          window.location.href = "/api/zerodha/login";
        } else {
          setBox("readinessStatus", "Token readiness is blocked until Zerodha credentials are configured.", "error");
        }
        return;
      }

      if (action === "mapped-watchlist") {
        scrollToSection("#watchlistsTable");
        setInlineMessage(
          "watchlistStatus",
          latestReadiness.mapped_symbol_count > 0 && latestReadiness.unmapped_symbol_count === 0
            ? "All symbols in the active watchlist are mapped to instrument tokens."
            : "Some watchlist symbols are not mapped yet. Review the watchlist and validate/sync symbols.",
          latestReadiness.mapped_symbol_count > 0 && latestReadiness.unmapped_symbol_count === 0 ? "success" : "warn",
        );
        return;
      }

      if (action === "live-engine-ready") {
        setBox(
          "readinessStatus",
          latestReadiness.live_engine_ready
            ? "Live engine prerequisites are satisfied for subscriptions and monitoring."
            : runtime?.message || "Live engine is waiting for both a Zerodha token and fully mapped watchlist symbols.",
          latestReadiness.live_engine_ready ? "success" : "warn",
        );
        return;
      }

      if (action === "three-minute-volume") {
        scrollToSection("#symbolActivityTable");
        setBox(
          "readinessStatus",
          latestReadiness.three_minute_volume_ready
            ? "Recent 3-minute candle data is available for at least one watched symbol."
            : "No recent 3-minute candle data is available yet. Check Zerodha login, subscriptions, and market hours.",
          latestReadiness.three_minute_volume_ready ? "success" : "warn",
        );
      }
    }

    function renderValidation(result) {
      cachedValidation = result;
      const tone = result.invalid_count ? "warn" : "success";
      setSummaryMessage(
        "validationBreakdown",
        `${result.valid_count} valid · ${result.invalid_count} invalid · Exchange ${result.exchange}`,
        tone,
      );
      renderTable(
        document.getElementById("validationTable"),
        ["Symbol", "Status", "Company", "Instrument Token"],
        result.requested_symbols.map((symbol) => {
          const match = result.instrument_matches.find((row) => row.symbol === symbol);
          return [
            symbol,
            match ? '<span class="badge">VALID</span>' : '<span class="badge warn">INVALID</span>',
            match?.company_name ?? "Not found",
            match?.instrument_token ?? "N/A",
          ];
        }),
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter validation symbols" } },
      );
    }

    async function loadWatchlists() {
      const watchlists = await apiGet("/configuration/watchlists");
      renderWatchlists(watchlists);
      return watchlists;
    }

    async function selectWatchlist(id) {
      try {
        activeBuilderWatchlistId = id;
        const result = await apiSend(`/configuration/watchlists/${id}/select`, "POST");
        setInlineMessage("watchlistStatus", `Now using ${result.name} for scans and live monitoring.`, "success");
        await refreshAll(id);
      } catch (error) {
        setInlineMessage("watchlistStatus", error.message, "error");
      }
    }
    window.selectWatchlist = selectWatchlist;

    async function openWatchlistDetail(id, shouldScroll = false) {
      try {
        const detail = await apiGet(`/configuration/watchlists/${id}`);
        renderWatchlistDetail(detail);
        if (shouldScroll) {
          scrollToSection("#watchlistDetailSection");
        }
      } catch (error) {
        setToolbarCopyMessage("watchlistDetailMeta", error.message, "error");
      }
    }
    window.openWatchlistDetail = openWatchlistDetail;

    async function loadReadiness() {
      const readiness = await apiGet("/configuration/readiness");
      return readiness;
    }

    async function loadStrategySettings() {
      const strategySettings = await apiGet("/configuration/strategy-settings");
      renderStrategySettings(strategySettings);
      return strategySettings;
    }

    async function loadExecutionSettings() {
      try {
        const executionSettings = await apiGet("/configuration/execution-rules");
        renderExecutionSettings(executionSettings);
        document.getElementById("saveExecutionRulesButton").disabled = false;
        return executionSettings;
      } catch (error) {
        renderExecutionSettingsUnavailable(error.message);
        return null;
      }
    }

    async function loadZerodhaConnectionStatus() {
      const result = await apiGet("/api/zerodha/test");
      renderZerodhaConnectionStatus(result);
      return result;
    }

    async function refreshAll(preferredWatchlistId = null) {
      activeBuilderWatchlistId = preferredWatchlistId || activeBuilderWatchlistId;
      const [readiness, watchlists, zerodhaStatus, strategySettings] = await Promise.all([
        loadReadiness(),
        loadWatchlists(),
        loadZerodhaConnectionStatus(),
        loadStrategySettings(),
      ]);
      await loadExecutionSettings();
      renderReadiness(readiness, zerodhaStatus);
      renderConfigCards(readiness, watchlists);
      renderStrategySettings(strategySettings);
      const detailWatchlist = watchlists.find((item) => item.id === preferredWatchlistId)
        || watchlists.find((item) => item.id === currentWatchlistDetailId)
        || watchlists.find((item) => item.is_selected)
        || watchlists[0];
      if (detailWatchlist) {
        await openWatchlistDetail(detailWatchlist.id);
      } else {
        setToolbarCopyMessage("watchlistDetailMeta", "Create a watchlist to inspect its symbols and current prices.", "warn");
        renderTable(
          document.getElementById("watchlistDetailTable"),
          ["Symbol", "Company", "Instrument Token", "Current Price", "Price Source", "Active"],
          [],
          { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter watchlist symbols" } },
        );
        syncWatchlistDetailPreview();
      }
    }

    document.getElementById("createWatchlistButton").addEventListener("click", async () => {
      try {
        const payload = {
          name: document.getElementById("watchlistName").value,
          description: document.getElementById("watchlistDescription").value || null,
          exchange: document.getElementById("watchlistExchange").value,
        };
        const created = await apiSend("/configuration/watchlists", "POST", payload);
        activeBuilderWatchlistId = created.id;
        setInlineMessage("watchlistStatus", `Created watchlist ${created.name}.`, "success");
        await refreshAll(created.id);
      } catch (error) {
        setInlineMessage("watchlistStatus", error.message, "error");
      }
    });

    document.getElementById("targetWatchlist").addEventListener("change", async (event) => {
      activeBuilderWatchlistId = event.target.value || null;
      updateBuilderState();
      if (activeBuilderWatchlistId) {
        await openWatchlistDetail(activeBuilderWatchlistId);
      }
    });

    document.getElementById("useTargetWatchlistButton").addEventListener("click", async () => {
      const watchlistId = document.getElementById("targetWatchlist").value;
      if (!watchlistId) {
        setInlineMessage("watchlistStatus", "Choose a watchlist first.", "warn");
        return;
      }
      await selectWatchlist(watchlistId);
    });

    document.getElementById("validateSymbolsButton").addEventListener("click", async () => {
      try {
        const result = await apiSend("/configuration/validate-symbols", "POST", {
          exchange: document.getElementById("symbolsExchange").value,
          symbols_text: document.getElementById("symbolsInput").value,
        });
        renderValidation(result);
        setInlineMessage("validationStatus", "Validation complete. Review the result list before saving symbols to the watchlist.", result.invalid_count ? "warn" : "success");
      } catch (error) {
        setInlineMessage("validationStatus", error.message, "error");
      }
    });

    document.getElementById("saveSymbolsButton").addEventListener("click", async () => {
      try {
        const watchlistId = document.getElementById("targetWatchlist").value;
        if (!watchlistId) {
          throw new Error("Create or select a watchlist first.");
        }
        const payload = {
          exchange: document.getElementById("symbolsExchange").value,
          symbols_text: document.getElementById("symbolsInput").value,
        };
        const result = await apiSend(`/configuration/watchlists/${watchlistId}/symbols`, "POST", payload);
        setInlineMessage(
          "validationStatus",
          `Added ${result.added_count} symbols. ${result.existing_count} already existed. ${result.invalid_count} invalid.`,
          result.invalid_count ? "warn" : "success",
        );
        if (cachedValidation) {
          renderValidation(result.validation);
        }
        await refreshAll();
      } catch (error) {
        setInlineMessage("validationStatus", error.message, "error");
      }
    });

    document.getElementById("syncInstrumentsButton").addEventListener("click", async () => {
      try {
        setBox("readinessStatus", "Syncing instruments from Zerodha...", "");
        const result = await apiSend("/system/instruments/sync", "POST", {});
        setBox("readinessStatus", `Instrument sync complete. ${result.synced} instruments refreshed from Zerodha.`, "success");
        await refreshAll();
      } catch (error) {
        setBox("readinessStatus", error.message, "error");
      }
    });

    document.getElementById("refreshReadinessButton").addEventListener("click", async () => {
      try {
        await refreshAll();
      } catch (error) {
        setBox("readinessStatus", error.message, "error");
      }
    });

    document.getElementById("saveStrategySettingsButton").addEventListener("click", async () => {
      try {
        const payload = {
          daily_candle_lookback: Number(document.getElementById("dailyCandleLookbackInput").value),
          swing_window: Number(document.getElementById("swingWindowInput").value),
          max_gap_percent: Number(document.getElementById("maxGapPercentInput").value),
          min_swing_distance: Number(document.getElementById("minSwingDistanceInput").value),
          daily_structure_rebuild_enabled: parseBooleanSelect("dailyStructureRebuildEnabledInput"),
          daily_structure_rebuild_time: document.getElementById("dailyStructureRebuildTimeInput").value,
          prediction_proximity_percent: Number(document.getElementById("predictionProximityPercentInput").value),
          buy_volume_multiplier: Number(document.getElementById("buyVolumeMultiplierInput").value),
          sell_volume_multiplier: Number(document.getElementById("sellVolumeMultiplierInput").value),
          entry_buffer_ticks: Number(document.getElementById("entryBufferTicksInput").value),
          stop_loss_buffer_ticks: Number(document.getElementById("stopLossBufferTicksInput").value),
        };
        const result = await apiSend("/configuration/strategy-settings", "POST", payload);
        renderStrategySettings(result);
        setInlineMessage("strategySettingsStatus", "Strategy tuning saved. Daily scans, line review, and breakout checks will use these values.", "success");
      } catch (error) {
        setInlineMessage("strategySettingsStatus", error.message, "error");
      }
    });

    document.getElementById("refreshStrategySettingsButton").addEventListener("click", async () => {
      try {
        const result = await loadStrategySettings();
        renderStrategySettings(result);
      } catch (error) {
        setInlineMessage("strategySettingsStatus", error.message, "error");
      }
    });

    document.getElementById("redrawMarketStructureButton").addEventListener("click", async () => {
      try {
        setInlineMessage("strategySettingsStatus", "Running the same daily market-structure rebuild used by the scheduler.", "warn");
        const result = await apiSend("/configuration/market-structure/redraw-now", "POST", {});
        setInlineMessage(
          "strategySettingsStatus",
          `Redraw completed. Scan ${result.status.toLowerCase()} · ${result.symbols_scanned} symbols scanned · ${result.trigger_lines_created} new lines · ${result.trigger_lines_updated} refreshed lines.`,
          "success",
        );
      } catch (error) {
        setInlineMessage("strategySettingsStatus", error.message, "error");
      }
    });

    document.getElementById("truncateMarketStructureButton").addEventListener("click", async () => {
      const confirmed = window.confirm(
        "This will clear stored daily and 3-minute market structure data, trigger lines, breakout history, and derived paper-signal rows. Watchlists, instruments, users, and Zerodha login state will remain. Continue?",
      );
      if (!confirmed) {
        return;
      }

      try {
        setInlineMessage("strategySettingsStatus", "Clearing stored market-structure data so the next redraw starts clean.", "warn");
        const result = await apiSend("/configuration/market-structure/truncate", "POST", {});
        await refreshAll();
        setInlineMessage(
          "strategySettingsStatus",
          `Market structure data cleared. ${result.market_candles} candles, ${result.trigger_lines} trigger lines, ${result.breakout_events} breakout events, ${result.trading_signals} signals, ${result.paper_trades} paper trades, and ${result.scan_executions} scan runs removed.`,
          "success",
        );
      } catch (error) {
        setInlineMessage("strategySettingsStatus", error.message, "error");
      }
    });

    document.getElementById("saveExecutionRulesButton").addEventListener("click", async () => {
      try {
        const payload = {
          paper_trading_enabled: parseBooleanSelect("paperTradingEnabledInput"),
          live_trading_enabled: parseBooleanSelect("liveTradingEnabledInput"),
          require_candle_close_beyond_line: parseBooleanSelect("requireCandleCloseBeyondLineInput"),
          entry_buffer_ticks: Number(document.getElementById("entryBufferTicksExecutionInput").value),
          stop_loss_buffer_ticks: Number(document.getElementById("stopLossBufferTicksExecutionInput").value),
          target_mode: document.getElementById("targetModeInput").value,
          fallback_risk_reward_ratio: Number(document.getElementById("fallbackRiskRewardRatioInput").value),
          use_nearest_daily_swing_target: parseBooleanSelect("useNearestDailySwingTargetInput"),
          minimum_reward_risk_ratio: Number(document.getElementById("minimumRewardRiskRatioInput").value),
          order_type: document.getElementById("orderTypeInput").value,
          product_type: document.getElementById("productTypeInput").value,
          reentry_cooldown_minutes: Number(document.getElementById("reentryCooldownMinutesInput").value),
          allow_repeat_entry_same_line: parseBooleanSelect("allowRepeatEntrySameLineInput"),
          default_quantity_mode: document.getElementById("defaultQuantityModeInput").value,
          fixed_quantity: parseNullableInt("fixedQuantityInput"),
          capital_per_trade: Number(document.getElementById("capitalPerTradeInput").value),
          risk_per_trade: Number(document.getElementById("riskPerTradeInput").value),
          max_quantity_per_order: parseNullableInt("maxQuantityPerOrderInput"),
          buy_volume_multiplier: Number(document.getElementById("buyVolumeMultiplierExecutionInput").value),
          sell_volume_multiplier: Number(document.getElementById("sellVolumeMultiplierExecutionInput").value),
          skip_zero_previous_volume: parseBooleanSelect("skipZeroPreviousVolumeInput"),
          minimum_price: parseNullableFloat("minimumPriceInput"),
          maximum_price: parseNullableFloat("maximumPriceInput"),
          allowed_exchanges: parseAllowedExchanges(),
          max_trades_per_day: Number(document.getElementById("maxTradesPerDayInput").value),
          max_open_positions: Number(document.getElementById("maxOpenPositionsInput").value),
          max_daily_loss: Number(document.getElementById("maxDailyLossInput").value),
          max_loss_per_symbol_per_day: Number(document.getElementById("maxLossPerSymbolPerDayInput").value),
          block_new_trades_after_max_daily_loss: parseBooleanSelect("blockAfterDailyLossInput"),
          no_trade_after_time: document.getElementById("noTradeAfterTimeInput").value.trim() || null,
          market_hours_guard: parseBooleanSelect("marketHoursGuardInput"),
          brokerage_estimate: Number(document.getElementById("brokerageEstimateInput").value),
          slippage_estimate: Number(document.getElementById("slippageEstimateInput").value),
          exchange_charges_estimate: Number(document.getElementById("exchangeChargesEstimateInput").value),
          use_cost_adjusted_pnl: parseBooleanSelect("useCostAdjustedPnlInput"),
          enable_confidence_filter: parseBooleanSelect("enableConfidenceFilterInput"),
          minimum_confidence_score: Number(document.getElementById("minimumConfidenceScoreInput").value),
          confidence_source: document.getElementById("confidenceSourceInput").value,
          allow_low_confidence_paper_trades_only: parseBooleanSelect("allowLowConfidencePaperOnlyInput"),
          block_live_trades_below_confidence_threshold: parseBooleanSelect("blockLiveTradesBelowConfidenceThresholdInput"),
        };
        const result = await apiSend("/configuration/execution-rules", "POST", payload);
        renderExecutionSettings(result);
        setInlineMessage("executionModeStatus", "Execution and risk rules saved. New signals and orders will use these values.", "success");
      } catch (error) {
        setInlineMessage("executionModeStatus", error.message, "error");
      }
    });

    document.getElementById("refreshExecutionRulesButton").addEventListener("click", async () => {
      try {
        const result = await loadExecutionSettings();
        if (result) {
          renderExecutionSettings(result);
        }
      } catch (error) {
        setInlineMessage("executionModeStatus", error.message, "error");
      }
    });

    document.getElementById("connectZerodhaButton").addEventListener("click", () => {
      window.location.href = "/api/zerodha/login";
    });

    document.getElementById("testZerodhaButton").addEventListener("click", async () => {
      try {
        const [readiness, zerodhaStatus] = await Promise.all([loadReadiness(), loadZerodhaConnectionStatus()]);
        renderReadiness(readiness, zerodhaStatus);
      } catch (error) {
        setBox("zerodhaConnectionStatus", error.message, "error");
      }
    });

    refreshAll().then(() => {
      applyZerodhaCallbackMessage();
    }).catch((error) => {
      setBox("zerodhaConnectionStatus", "Unable to determine Zerodha connection state.", "error");
      setInlineMessage("watchlistStatus", error.message, "error");
      setBox("readinessStatus", "Unable to initialize configuration workspace.", "error");
      setInlineMessage("validationStatus", "Configuration workspace failed to initialize.", "error");
      setInlineMessage("strategySettingsStatus", "Unable to load strategy tuning values.", "error");
    });
    """
    return render_app_shell(
        title="Qubitx Configuration",
        heading="Configuration",
        subtitle="Build the daily NSE and BSE watch universe, validate symbols against the Zerodha instrument master, and confirm the platform is ready for 3-minute market monitoring.",
        active_nav="configuration",
        body_html=body_html,
        script=script,
    )


@router.get("/configuration/watchlists")
def configuration_watchlists(db: Session = Depends(get_db)) -> list[dict]:
    return _watchlist_payload(db)


@router.get("/configuration/watchlists/{watchlist_id}")
def configuration_watchlist_detail(watchlist_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    return _watchlist_detail_payload(db, watchlist_id)


@router.post("/configuration/watchlists")
def create_watchlist(payload: WatchlistCreatePayload, db: Session = Depends(get_db)) -> dict:
    exchange = _normalize_exchange(payload.exchange)
    existing = db.scalar(select(Watchlist).where(Watchlist.name == payload.name.strip()).limit(1))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Watchlist name already exists")

    has_any_watchlist = db.scalar(select(func.count()).select_from(Watchlist)) or 0

    watchlist = Watchlist(
        id=uuid.uuid4(),
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        exchange=exchange,
        is_selected=has_any_watchlist == 0,
    )
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return {
        "id": str(watchlist.id),
        "name": watchlist.name,
        "description": watchlist.description,
        "exchange": watchlist.exchange,
        "is_selected": watchlist.is_selected,
    }


@router.post("/configuration/validate-symbols")
def validate_symbols(payload: SymbolValidationPayload, db: Session = Depends(get_db)) -> dict:
    exchange = _normalize_exchange(payload.exchange)
    parsed_symbols = _parse_symbols(payload.symbols_text)
    if not parsed_symbols:
        raise HTTPException(status_code=422, detail="Provide at least one symbol to validate")
    return _symbol_validation_result(db, exchange, parsed_symbols)


@router.post("/configuration/watchlists/{watchlist_id}/symbols")
def add_watchlist_symbols(
    watchlist_id: uuid.UUID,
    payload: WatchlistSymbolCreatePayload,
    db: Session = Depends(get_db),
) -> dict:
    watchlist = db.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    exchange = _normalize_exchange(payload.exchange)
    parsed_symbols = _parse_symbols(payload.symbols_text)
    if not parsed_symbols:
        raise HTTPException(status_code=422, detail="Provide at least one symbol to add")

    validation = _symbol_validation_result(db, exchange, parsed_symbols)
    valid_symbols = validation["valid_symbols"]
    if not valid_symbols:
        return {
            "watchlist_id": str(watchlist.id),
            "added_count": 0,
            "existing_count": 0,
            "invalid_count": validation["invalid_count"],
            "added_symbols": [],
            "existing_symbols": [],
            "validation": validation,
        }

    instrument_map = _upsert_validated_instruments(db, exchange, validation)
    existing_members = db.scalars(
        select(WatchlistSymbol).where(
            WatchlistSymbol.watchlist_id == watchlist.id,
            WatchlistSymbol.exchange == exchange,
            WatchlistSymbol.symbol.in_(valid_symbols),
        )
    ).all()
    existing_symbols = {member.symbol.upper() for member in existing_members}

    added_symbols: list[str] = []
    for symbol in valid_symbols:
        if symbol in existing_symbols:
            continue
        instrument = instrument_map[symbol]
        db.add(
            WatchlistSymbol(
                id=uuid.uuid4(),
                watchlist_id=watchlist.id,
                instrument_id=instrument.id,
                exchange=exchange,
                symbol=symbol,
                instrument_token=instrument.instrument_token,
                company_name=instrument.name,
                is_active=True,
            )
        )
        added_symbols.append(symbol)

    db.commit()
    return {
        "watchlist_id": str(watchlist.id),
        "added_count": len(added_symbols),
        "existing_count": len(existing_symbols),
        "invalid_count": validation["invalid_count"],
        "added_symbols": added_symbols,
        "existing_symbols": sorted(existing_symbols),
        "validation": validation,
    }


@router.post("/configuration/watchlists/{watchlist_id}/select")
def select_configuration_watchlist(watchlist_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    watchlist = db.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    selected = set_selected_watchlist(db, watchlist)
    return {
        "id": str(selected.id),
        "name": selected.name,
        "exchange": selected.exchange,
        "is_selected": selected.is_selected,
    }


@router.get("/configuration/readiness")
def configuration_readiness(db: Session = Depends(get_db)) -> dict:
    try:
        return _readiness_payload(db)
    except Exception:  # noqa: BLE001
        logger.exception("Configuration readiness payload failed")
        return _fallback_readiness_payload()


@router.get("/configuration/strategy-settings", response_model=StrategySettingsResponse)
def configuration_strategy_settings(db: Session = Depends(get_db)) -> StrategySettingsResponse:
    current = ensure_settings(db)
    return StrategySettingsResponse.model_validate(current, from_attributes=True)


@router.post("/configuration/strategy-settings", response_model=StrategySettingsResponse)
def save_configuration_strategy_settings(
    payload: StrategySettingsPayload,
    db: Session = Depends(get_db),
) -> StrategySettingsResponse:
    _validate_time_string(payload.daily_structure_rebuild_time, field_name="Daily structure rebuild time")
    current = update_strategy_settings(db, payload)
    return StrategySettingsResponse.model_validate(current, from_attributes=True)


@router.post("/configuration/market-structure/redraw-now")
def configuration_redraw_market_structure_now(db: Session = Depends(get_db)) -> dict:
    zerodha_auth = ZerodhaAuthService()
    if not zerodha_auth.has_credentials():
        raise HTTPException(status_code=503, detail="Configure Zerodha credentials before redrawing market structure")

    zerodha_session = get_current_zerodha_session(db)
    if zerodha_session is None:
        raise HTTPException(status_code=503, detail="Connect Zerodha before redrawing market structure")
    if zerodha_session.access_token_expires_at and zerodha_session.access_token_expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=503, detail="Zerodha session has expired. Reconnect Zerodha before redrawing market structure")

    current_access_token = get_current_zerodha_access_token(db)
    scanner = DailyMarketScanner(
        provider=HistoricalCandleProvider(
            client=ZerodhaApiClient(
                auth_service=zerodha_auth,
                access_token=current_access_token,
            )
        )
    )
    try:
        execution = scanner.run(db, scan_date=datetime.now(UTC).date(), dry_run=False)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Unable to redraw market structure: {exc}") from exc

    return {
        "execution_id": str(execution.id),
        "status": execution.status,
        "symbols_scanned": execution.symbols_scanned,
        "trigger_lines_created": execution.trigger_lines_created,
        "trigger_lines_updated": execution.trigger_lines_updated,
    }


@router.post("/configuration/market-structure/truncate")
def configuration_truncate_market_structure(db: Session = Depends(get_db)) -> dict:
    try:
        deleted_counts = _truncate_market_structure_tables(db)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Unable to truncate market structure tables")
        raise HTTPException(status_code=500, detail="Unable to truncate market structure tables") from exc

    return deleted_counts


@router.get("/configuration/execution-rules", response_model=ExecutionRulesResponse)
def configuration_execution_rules(db: Session = Depends(get_db)) -> ExecutionRulesResponse:
    try:
        return get_execution_rules_payload(db)
    except SQLAlchemyError:
        logger.exception("Execution rules could not be loaded")
        defaults = get_settings()
        return ExecutionRulesResponse(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            paper_trading_enabled=defaults.paper_trading_enabled,
            live_trading_enabled=defaults.zerodha_live_trading_enabled,
            require_candle_close_beyond_line=True,
            entry_buffer_ticks=defaults.entry_buffer_ticks,
            stop_loss_buffer_ticks=defaults.stop_buffer_ticks,
            target_mode="NEAREST_DAILY_SWING",
            fallback_risk_reward_ratio=2.0,
            use_nearest_daily_swing_target=True,
            minimum_reward_risk_ratio=1.0,
            order_type="LIMIT",
            product_type="MIS",
            reentry_cooldown_minutes=0,
            allow_repeat_entry_same_line=False,
            default_quantity_mode="RISK_BASED",
            fixed_quantity=None,
            capital_per_trade=25000.0,
            risk_per_trade=2500.0,
            max_quantity_per_order=None,
            buy_volume_multiplier=defaults.buy_volume_multiplier,
            sell_volume_multiplier=defaults.sell_volume_multiplier,
            skip_zero_previous_volume=True,
            minimum_price=None,
            maximum_price=None,
            allowed_exchanges=["NSE", "BSE"],
            max_trades_per_day=3,
            max_open_positions=3,
            max_daily_loss=5000.0,
            max_loss_per_symbol_per_day=2500.0,
            block_new_trades_after_max_daily_loss=True,
            no_trade_after_time="15:00",
            market_hours_guard=True,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            exchange_charges_estimate=0.0,
            use_cost_adjusted_pnl=True,
            enable_confidence_filter=False,
            minimum_confidence_score=0.6,
            confidence_source="RULES_ONLY",
            allow_low_confidence_paper_trades_only=True,
            block_live_trades_below_confidence_threshold=True,
        )


@router.post("/configuration/execution-rules", response_model=ExecutionRulesResponse)
def save_configuration_execution_rules(
    payload: ExecutionRulesPayload,
    db: Session = Depends(get_db),
) -> ExecutionRulesResponse:
    if payload.live_trading_enabled:
        zerodha_auth = ZerodhaAuthService()
        if not zerodha_auth.has_credentials():
            raise HTTPException(status_code=503, detail="Configure Zerodha credentials before enabling live trading")
        if get_current_zerodha_session(db) is None:
            raise HTTPException(status_code=503, detail="Connect Zerodha before enabling live trading")

    if not payload.allowed_exchanges:
        raise HTTPException(status_code=422, detail="Select at least one allowed exchange")

    if payload.minimum_price is not None and payload.maximum_price is not None and payload.minimum_price > payload.maximum_price:
        raise HTTPException(status_code=422, detail="Minimum price cannot exceed maximum price")

    try:
        current = update_execution_rules(db, payload)
        return ExecutionRulesResponse.model_validate(current, from_attributes=True)
    except SQLAlchemyError as exc:
        logger.exception("Execution rules could not be updated")
        raise HTTPException(
            status_code=503,
            detail="Execution rules are unavailable until the latest database migrations are applied",
        ) from exc


@router.get("/configuration/execution-settings", response_model=ExecutionModeResponse)
def configuration_execution_settings(db: Session = Depends(get_db)) -> ExecutionModeResponse:
    try:
        return get_execution_mode_payload(db)
    except SQLAlchemyError:
        logger.exception("Execution settings could not be loaded")
        zerodha_session = get_current_zerodha_session(db)
        return ExecutionModeResponse(
            paper_trading_enabled=settings.paper_trading_enabled,
            live_trading_enabled=settings.zerodha_live_trading_enabled,
            effective_mode="PAPER_ONLY",
            zerodha_credentials_configured=bool(
                settings.zerodha_api_key and settings.zerodha_api_secret and settings.zerodha_redirect_url
            ),
            zerodha_session_present=zerodha_session is not None,
            zerodha_access_token_expires_at=zerodha_session.access_token_expires_at if zerodha_session else None,
        )


@router.post("/configuration/execution-settings", response_model=ExecutionModeResponse)
def save_configuration_execution_settings(
    payload: ExecutionModePayload,
    db: Session = Depends(get_db),
) -> ExecutionModeResponse:
    if payload.live_trading_enabled:
        zerodha_auth = ZerodhaAuthService()
        if not zerodha_auth.has_credentials():
            raise HTTPException(status_code=503, detail="Configure Zerodha credentials before enabling live trading")
        if get_current_zerodha_session(db) is None:
            raise HTTPException(status_code=503, detail="Connect Zerodha before enabling live trading")

    try:
        update_live_trading_enabled(db, payload.live_trading_enabled)
        return get_execution_mode_payload(db)
    except SQLAlchemyError as exc:
        logger.exception("Execution settings could not be updated")
        raise HTTPException(
            status_code=503,
            detail="Live trading controls are unavailable until the latest database migrations are applied",
        ) from exc
