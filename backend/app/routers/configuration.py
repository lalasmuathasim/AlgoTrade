import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db, verify_database_connectivity
from backend.app.dependencies import require_admin_user
from backend.app.models import Instrument, MarketCandle, Watchlist, WatchlistSymbol
from backend.app.queue import check_redis_connectivity
from backend.app.schemas import (
    InstrumentPayload,
    StrategySettingsPayload,
    StrategySettingsResponse,
    SymbolValidationPayload,
    WatchlistCreatePayload,
    WatchlistSymbolCreatePayload,
)
from backend.app.services.paper_trading_service import ensure_settings, update_strategy_settings
from backend.app.services.watchlists import ensure_selected_watchlist, set_selected_watchlist
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token, get_current_zerodha_session
from backend.app.services.zerodha import InstrumentMasterSyncService, SubscriptionManager, ZerodhaApiClient, ZerodhaAuthService
from backend.app.ui import render_app_shell


router = APIRouter(tags=["configuration"], dependencies=[Depends(require_admin_user)])
settings = get_settings()
logger = logging.getLogger(__name__)


def _normalize_exchange(exchange: str) -> str:
    value = exchange.strip().upper()
    if value not in {"NSE", "BSE"}:
        raise HTTPException(status_code=422, detail="Exchange must be NSE or BSE")
    return value


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
        "symbol_activity": symbol_activity,
    }


@router.get("/configuration", response_class=HTMLResponse)
def configuration_page() -> str:
    body_html = """
    <section id="configSummary" class="metric-strip"></section>
    <section class="layout-main-aside">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Configured Watchlists</h2>
            <p class="panel-copy">Open a list to inspect it, or switch the runtime focus with a single action.</p>
          </div>
        </div>
        <table id="watchlistsTable"></table>
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
          <div id="readinessPills" class="inline"></div>
          <div class="inline" style="margin-top: 12px;">
            <button id="connectZerodhaButton" class="primary" type="button">Connect Zerodha</button>
            <button id="testZerodhaButton" class="secondary" type="button">Test Connection</button>
            <button id="syncInstrumentsButton" class="secondary" type="button">Sync Instruments From Zerodha</button>
            <button id="refreshReadinessButton" class="secondary" type="button">Refresh Readiness</button>
          </div>
        </div>
      </div>
    </section>
    <section class="layout-main-aside">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Validate Symbols</h2>
            <p class="panel-copy">Paste one symbol per line or comma-separated values, validate against Zerodha, then add only the clean set.</p>
          </div>
        </div>
        <div id="validationStatus" class="status-box">Paste one symbol per line or comma-separated values, then validate before saving.</div>
        <div class="field">
          <label for="targetWatchlist">Target watchlist</label>
          <select id="targetWatchlist"></select>
        </div>
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
      </div>
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Validation Result</h2>
            <p class="panel-copy">Review the matched company name and instrument token before committing symbols into the active data model.</p>
          </div>
        </div>
        <div id="validationBreakdown" class="status-box">No validation run yet.</div>
        <table id="validationTable"></table>
      </div>
    </section>
    <section class="layout-halves">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Strategy Tuning</h2>
            <p class="panel-copy">Control how daily support and resistance lines are discovered, plus the breakout confirmation thresholds that the live engine and paper flow use.</p>
          </div>
          <div class="badge">Runtime</div>
        </div>
        <div id="strategySettingsStatus" class="status-box">Loading strategy tuning values from the runtime settings store...</div>
        <div class="field">
          <label for="dailyCandleLookbackInput">Daily candle lookback</label>
          <input id="dailyCandleLookbackInput" type="number" min="20" max="300" step="1" />
          <div class="field-help">How many completed daily candles the scanner should review when searching for swing highs and swing lows.</div>
        </div>
        <div class="field">
          <label for="swingWindowInput">Swing window</label>
          <input id="swingWindowInput" type="number" min="1" max="10" step="1" />
          <div class="field-help">How many candles on each side must be lower or higher before a candle qualifies as a swing point. Pine usually uses `1` here.</div>
        </div>
        <div class="field">
          <label for="maxGapPercentInput">Max gap percent</label>
          <input id="maxGapPercentInput" type="number" min="0.1" max="10" step="0.1" />
          <div class="field-help">Maximum allowed percentage gap between the two chosen swings before the candidate line is rejected as too wide.</div>
        </div>
        <div class="field">
          <label for="minSwingDistanceInput">Min swing distance</label>
          <input id="minSwingDistanceInput" type="number" min="1" max="50" step="1" />
          <div class="field-help">Minimum number of candles that must separate the two selected swings so very tight structures are ignored.</div>
        </div>
        <div class="field">
          <label for="buyVolumeMultiplierInput">Buy volume multiplier</label>
          <input id="buyVolumeMultiplierInput" type="number" min="0.1" max="20" step="0.1" />
          <div class="field-help">Required breakout candle volume multiple versus the previous 3-minute candle for BUY signals.</div>
        </div>
        <div class="field">
          <label for="sellVolumeMultiplierInput">Sell volume multiplier</label>
          <input id="sellVolumeMultiplierInput" type="number" min="0.1" max="20" step="0.1" />
          <div class="field-help">Required breakdown candle volume multiple versus the previous 3-minute candle for SELL signals.</div>
        </div>
        <div class="field">
          <label for="entryBufferTicksInput">Entry buffer ticks</label>
          <input id="entryBufferTicksInput" type="number" min="0.01" max="10" step="0.01" />
          <div class="field-help">Extra ticks added above a BUY breakout or below a SELL breakdown before generating the entry trigger.</div>
        </div>
        <div class="field">
          <label for="stopLossBufferTicksInput">Stop-loss buffer ticks</label>
          <input id="stopLossBufferTicksInput" type="number" min="0.01" max="10" step="0.01" />
          <div class="field-help">Extra ticks added beyond the trigger line when placing the protective stop loss.</div>
        </div>
        <div class="inline">
          <button id="saveStrategySettingsButton" class="primary" type="button">Save Strategy Tuning</button>
          <button id="refreshStrategySettingsButton" class="secondary" type="button">Reload Values</button>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Tuning Guide</h2>
            <p class="panel-copy">These values directly affect which lines appear in Daily Line Review and which 3-minute breakouts become valid signals.</p>
          </div>
        </div>
        <ul class="list">
          <li class="pill">Smaller swing window: more swing points and more candidate lines</li>
          <li class="pill">Larger max gap percent: more tolerant matching between two swing levels</li>
          <li class="pill">Larger minimum swing distance: filters out crowded nearby swing pairs</li>
          <li class="pill">Higher volume multipliers: fewer but stronger breakout confirmations</li>
          <li class="pill">Entry and stop buffers help avoid exact-line fills when price is noisy</li>
        </ul>
      </div>
    </section>
    <section class="layout-main-aside">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Watchlist Control</h2>
            <p class="panel-copy">Create and switch the runtime universe that the daily scan and live 3-minute monitor should care about.</p>
          </div>
          <div class="badge">Control</div>
        </div>
        <div id="watchlistStatus" class="status-box">Create a watchlist first, then validate and add NSE or BSE symbols.</div>
        <div id="selectedWatchlistBox" class="status-box" style="margin-top: 12px;">No watchlist is currently selected.</div>
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
        <button id="createWatchlistButton" class="primary" type="button">Create Watchlist</button>
      </div>
      <div class="panel">
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
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Watchlist Detail</h2>
          <p class="panel-copy">Inspect the selected or opened watchlist with mapped symbols, companies, and latest available market price reference.</p>
        </div>
      </div>
      <div id="watchlistDetailStatus" class="status-box">Select a watchlist to inspect its tracked symbols and current prices.</div>
      <table id="watchlistDetailTable"></table>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>3-Minute Coverage Snapshot</h2>
          <p class="panel-copy">Recent candle visibility for the currently watched symbols. This is the fastest way to confirm that monitoring is producing fresh market data.</p>
        </div>
      </div>
      <table id="symbolActivityTable"></table>
    </section>
    """
    script = """
    let cachedValidation = null;
    let cachedWatchlists = [];
    let currentWatchlistDetailId = null;
    let latestReadiness = null;
    let latestZerodhaStatus = null;
    let latestStrategySettings = null;
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
      document.getElementById("buyVolumeMultiplierInput").value = settingsPayload.buy_volume_multiplier;
      document.getElementById("sellVolumeMultiplierInput").value = settingsPayload.sell_volume_multiplier;
      document.getElementById("entryBufferTicksInput").value = settingsPayload.entry_buffer_ticks;
      document.getElementById("stopLossBufferTicksInput").value = settingsPayload.stop_loss_buffer_ticks;
      setBox(
        "strategySettingsStatus",
        `Daily scan uses ${settingsPayload.daily_candle_lookback} candles with swing window ${settingsPayload.swing_window}. Gap filter ${settingsPayload.max_gap_percent}% · min swing distance ${settingsPayload.min_swing_distance} candles · BUY volume ${settingsPayload.buy_volume_multiplier}x · SELL volume ${settingsPayload.sell_volume_multiplier}x.`,
        "success",
      );
    }

    function renderWatchlists(watchlists) {
      cachedWatchlists = watchlists;
      document.getElementById("targetWatchlist").innerHTML = watchlists.length
        ? optionMarkup(watchlists)
        : '<option value="">Create a watchlist first</option>';
      const selected = watchlists.find((item) => item.is_selected);
      setBox(
        "selectedWatchlistBox",
        selected
          ? `Currently using ${selected.name} (${selected.exchange}) for scans, subscriptions, and 3-minute monitoring.`
          : "No watchlist is currently selected.",
        selected ? "success" : "warn",
      );
      renderTable(
        document.getElementById("watchlistsTable"),
        ["Name", "In Use", "Exchange", "Symbols", "Mapped", "Actions", "Preview"],
        watchlists.map((item) => [
          `<button class="secondary" type="button" onclick="openWatchlistDetail('${item.id}')">${item.name}</button>`,
          item.is_selected ? '<span class="badge">IN USE</span>' : '<span class="badge warn">STANDBY</span>',
          item.exchange,
          item.symbol_count,
          item.mapped_symbol_count,
          `<div class="inline">
            <button class="secondary" type="button" onclick="openWatchlistDetail('${item.id}')">View</button>
            ${item.is_selected
              ? '<span class="badge">Current</span>'
              : `<button class="secondary" type="button" onclick="selectWatchlist('${item.id}')">Use This Watchlist</button>`
            }
          </div>`,
          item.symbols.slice(0, 6).map((symbol) => symbol.symbol).join(", ") || "No symbols yet",
        ]),
      );
      if (selected) {
        document.getElementById("targetWatchlist").value = selected.id;
      }
    }

    function renderWatchlistDetail(payload) {
      currentWatchlistDetailId = payload.watchlist.id;
      const watchlist = payload.watchlist;
      const statusMessage = `${watchlist.name} · ${watchlist.exchange} · ${watchlist.symbol_count} symbols · ${watchlist.mapped_symbol_count} mapped${watchlist.description ? ` · ${watchlist.description}` : ""}`;
      setBox("watchlistDetailStatus", statusMessage, watchlist.is_selected ? "success" : "");
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
      );
    }

    function renderReadiness(readiness, zerodhaStatus) {
      latestReadiness = readiness;
      latestZerodhaStatus = zerodhaStatus;
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
        `${readiness.selected_watchlist ? `Using ${readiness.selected_watchlist.name} · ` : ""}DB ${readiness.database_connected ? "connected" : "down"} · Redis ${readiness.redis_connected ? "connected" : "down"} · ${zerodhaSummary} · ${readiness.symbols_with_recent_3minute_data}/${readiness.watched_symbol_count} watched symbols have recent 3-minute candle data.`,
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
        <button class="pill-button" type="button" data-readiness-action="${key}">
          <span class="badge ${ok ? "" : "warn"}">${ok ? "READY" : "CHECK"}</span>${label}
        </button>
      `).join("");
      document.querySelectorAll("[data-readiness-action]").forEach((element) => {
        element.addEventListener("click", handleReadinessAction);
      });
      renderTable(
        document.getElementById("symbolActivityTable"),
        ["Symbol", "Token", "Latest 3-Min Candle", "Volume"],
        readiness.symbol_activity.map((row) => [
          `${row.exchange}:${row.symbol}`,
          row.instrument_token ?? "Unmapped",
          row.latest_3minute_candle_at ? new Date(row.latest_3minute_candle_at).toLocaleString() : "No recent candle",
          row.latest_3minute_volume ?? "N/A",
        ]),
      );
    }

    async function handleReadinessAction(event) {
      const action = event.currentTarget.dataset.readinessAction;
      if (!latestReadiness) {
        return;
      }

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
        setBox(
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
            : "Live engine is waiting for both a Zerodha token and fully mapped watchlist symbols.",
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
      setBox(
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
      );
    }

    async function loadWatchlists() {
      const watchlists = await apiGet("/configuration/watchlists");
      renderWatchlists(watchlists);
      return watchlists;
    }

    async function selectWatchlist(id) {
      try {
        const result = await apiSend(`/configuration/watchlists/${id}/select`, "POST");
        setBox("watchlistStatus", `Now using ${result.name} for scans and live monitoring.`, "success");
        await refreshAll(id);
      } catch (error) {
        setBox("watchlistStatus", error.message, "error");
      }
    }
    window.selectWatchlist = selectWatchlist;

    async function openWatchlistDetail(id) {
      try {
        const detail = await apiGet(`/configuration/watchlists/${id}`);
        renderWatchlistDetail(detail);
      } catch (error) {
        setBox("watchlistDetailStatus", error.message, "error");
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

    async function loadZerodhaConnectionStatus() {
      const result = await apiGet("/api/zerodha/test");
      renderZerodhaConnectionStatus(result);
      return result;
    }

    async function refreshAll(preferredWatchlistId = null) {
      const [readiness, watchlists, zerodhaStatus, strategySettings] = await Promise.all([
        loadReadiness(),
        loadWatchlists(),
        loadZerodhaConnectionStatus(),
        loadStrategySettings(),
      ]);
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
        setBox("watchlistDetailStatus", "Create a watchlist to inspect its symbols and current prices.", "warn");
        renderTable(document.getElementById("watchlistDetailTable"), ["Symbol", "Company", "Instrument Token", "Current Price", "Price Source", "Active"], []);
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
        setBox("watchlistStatus", `Created watchlist ${created.name}.`, "success");
        await refreshAll();
      } catch (error) {
        setBox("watchlistStatus", error.message, "error");
      }
    });

    document.getElementById("validateSymbolsButton").addEventListener("click", async () => {
      try {
        const result = await apiSend("/configuration/validate-symbols", "POST", {
          exchange: document.getElementById("symbolsExchange").value,
          symbols_text: document.getElementById("symbolsInput").value,
        });
        renderValidation(result);
        setBox("validationStatus", "Validation complete. Review the list before saving.", result.invalid_count ? "warn" : "success");
      } catch (error) {
        setBox("validationStatus", error.message, "error");
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
        setBox(
          "validationStatus",
          `Added ${result.added_count} symbols. ${result.existing_count} already existed. ${result.invalid_count} invalid.`,
          result.invalid_count ? "warn" : "success",
        );
        if (cachedValidation) {
          renderValidation(result.validation);
        }
        await refreshAll();
      } catch (error) {
        setBox("validationStatus", error.message, "error");
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
          buy_volume_multiplier: Number(document.getElementById("buyVolumeMultiplierInput").value),
          sell_volume_multiplier: Number(document.getElementById("sellVolumeMultiplierInput").value),
          entry_buffer_ticks: Number(document.getElementById("entryBufferTicksInput").value),
          stop_loss_buffer_ticks: Number(document.getElementById("stopLossBufferTicksInput").value),
        };
        const result = await apiSend("/configuration/strategy-settings", "POST", payload);
        renderStrategySettings(result);
        setBox("strategySettingsStatus", "Strategy tuning saved. Daily scans, line review, and breakout checks will use these values.", "success");
      } catch (error) {
        setBox("strategySettingsStatus", error.message, "error");
      }
    });

    document.getElementById("refreshStrategySettingsButton").addEventListener("click", async () => {
      try {
        const result = await loadStrategySettings();
        renderStrategySettings(result);
      } catch (error) {
        setBox("strategySettingsStatus", error.message, "error");
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
      setBox("watchlistStatus", error.message, "error");
      setBox("readinessStatus", "Unable to initialize configuration workspace.", "error");
      setBox("validationStatus", "Configuration workspace failed to initialize.", "error");
      setBox("strategySettingsStatus", "Unable to load strategy tuning values.", "error");
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
    return _readiness_payload(db)


@router.get("/configuration/strategy-settings", response_model=StrategySettingsResponse)
def configuration_strategy_settings(db: Session = Depends(get_db)) -> StrategySettingsResponse:
    current = ensure_settings(db)
    return StrategySettingsResponse.model_validate(current, from_attributes=True)


@router.post("/configuration/strategy-settings", response_model=StrategySettingsResponse)
def save_configuration_strategy_settings(
    payload: StrategySettingsPayload,
    db: Session = Depends(get_db),
) -> StrategySettingsResponse:
    current = update_strategy_settings(db, payload)
    return StrategySettingsResponse.model_validate(current, from_attributes=True)
