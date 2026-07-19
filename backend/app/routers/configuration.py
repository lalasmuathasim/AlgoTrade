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
from backend.app.schemas import SymbolValidationPayload, WatchlistCreatePayload, WatchlistSymbolCreatePayload
from backend.app.services.watchlists import ensure_selected_watchlist, set_selected_watchlist
from backend.app.services.zerodha_sessions import get_current_zerodha_session
from backend.app.services.zerodha import SubscriptionManager, ZerodhaAuthService
from backend.app.ui import render_app_shell


router = APIRouter(tags=["configuration"], dependencies=[Depends(require_admin_user)])
settings = get_settings()


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

    instruments = db.scalars(
        select(Instrument)
        .where(
            Instrument.exchange == exchange,
            Instrument.is_active.is_(True),
            Instrument.tradingsymbol.in_(parsed_symbols),
        )
        .order_by(Instrument.tradingsymbol)
    ).all()
    instrument_map = {instrument.tradingsymbol.upper(): instrument for instrument in instruments}

    valid_symbols = [symbol for symbol in parsed_symbols if symbol in instrument_map]
    invalid_symbols = [symbol for symbol in parsed_symbols if symbol not in instrument_map]
    matches = [
        {
            "symbol": symbol,
            "instrument_token": instrument_map[symbol].instrument_token,
            "company_name": instrument_map[symbol].name,
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
    }


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


def _readiness_payload(db: Session) -> dict:
    database_ok = False
    try:
        verify_database_connectivity()
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    zerodha_auth = ZerodhaAuthService()
    zerodha_session = get_current_zerodha_session(db)
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
        "zerodha_access_token_configured": bool(zerodha_session or zerodha_auth.has_access_token()),
        "zerodha_login_url": zerodha_auth.build_login_url(),
        "instrument_master_ready": active_instruments_count > 0,
        "instrument_count": int(instruments_count),
        "active_instrument_count": int(active_instruments_count),
        "last_instrument_sync_at": last_instrument_sync.isoformat() if last_instrument_sync else None,
        "watched_symbol_count": watched_symbol_count,
        "mapped_symbol_count": mapped_symbol_count,
        "unmapped_symbol_count": watched_symbol_count - mapped_symbol_count,
        "unmapped_symbols": unmapped_symbols[:20],
        "active_subscription_count": len(subscriptions),
        "live_engine_ready": zerodha_auth.has_access_token() and mapped_symbol_count > 0,
        "three_minute_volume_ready": symbols_with_recent_candles > 0,
        "symbols_with_recent_3minute_data": symbols_with_recent_candles,
        "latest_3minute_candle_at": latest_three_minute_candle.isoformat() if latest_three_minute_candle else None,
        "symbol_activity": symbol_activity,
    }


@router.get("/configuration", response_class=HTMLResponse)
def configuration_page() -> str:
    body_html = """
    <section class="grid" id="configSummary"></section>
    <section class="two-col">
      <div class="panel">
        <h2>Watchlist Setup</h2>
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
        <h2>External Readiness</h2>
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
    </section>
    <section class="two-col" style="margin-top: 18px;">
      <div class="panel">
        <h2>Validate Symbols</h2>
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
        <h2>Validation Result</h2>
        <div id="validationBreakdown" class="status-box">No validation run yet.</div>
        <table id="validationTable"></table>
      </div>
    </section>
    <section class="split">
      <div class="panel">
        <h2>Configured Watchlists</h2>
        <table id="watchlistsTable"></table>
      </div>
      <div class="panel">
        <h2>3-Minute Coverage Snapshot</h2>
        <table id="symbolActivityTable"></table>
      </div>
    </section>
    """
    script = """
    let cachedValidation = null;
    let cachedWatchlists = [];
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
        Expired: "warn",
        "Invalid Token": "error",
        "Not Configured": "warn",
      };
      const badgeClassMap = {
        Connected: "badge",
        Expired: "badge warn",
        "Invalid Token": "badge danger",
        "Not Configured": "badge warn",
      };
      const tone = toneMap[result.status] || "";
      const detail = result.connected
        ? `${result.profile_user_name || result.profile_user_id || "Connected"} · token expires ${result.access_token_expires_at ? new Date(result.access_token_expires_at).toLocaleString() : "unknown"}`
        : `${result.status}${result.access_token_expires_at ? ` · token expiry ${new Date(result.access_token_expires_at).toLocaleString()}` : ""}`;
      setBox("zerodhaConnectionStatus", detail, tone);
      document.getElementById("zerodhaConnectionBadge").innerHTML = `<span class="${badgeClassMap[result.status] || "badge warn"}">${result.status}</span>`;
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

    function renderConfigCards(readiness, watchlists) {
      const totalSymbols = watchlists.reduce((sum, item) => sum + item.symbol_count, 0);
      const mappedSymbols = watchlists.reduce((sum, item) => sum + item.mapped_symbol_count, 0);
      const selected = watchlists.find((item) => item.is_selected);
      const cards = [
        ["Watchlists", watchlists.length, "Configured draw/redraw groups"],
        ["In Use", selected ? selected.name : "None", "The only watchlist used for scan and live monitoring"],
        ["Watched Symbols", totalSymbols, "Symbols queued for daily structure scanning"],
        ["Mapped Symbols", mappedSymbols, "Symbols linked to Zerodha instrument tokens"],
        ["3-Minute Coverage", readiness.symbols_with_recent_3minute_data, "Watched symbols with recent candle volume"],
      ];
      document.getElementById("configSummary").innerHTML = cards.map(([label, value, subvalue]) => `
        <article class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
          <div class="subvalue">${subvalue}</div>
        </article>
      `).join("");
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
        ["Name", "In Use", "Exchange", "Symbols", "Mapped", "Action", "Preview"],
        watchlists.map((item) => [
          item.name,
          item.is_selected ? '<span class="badge">IN USE</span>' : '<span class="badge warn">STANDBY</span>',
          item.exchange,
          item.symbol_count,
          item.mapped_symbol_count,
          item.is_selected
            ? "Current"
            : `<button class="secondary" type="button" onclick="selectWatchlist('${item.id}')">Use This Watchlist</button>`,
          item.symbols.slice(0, 6).map((symbol) => symbol.symbol).join(", ") || "No symbols yet",
        ]),
      );
    }

    function renderReadiness(readiness) {
      const tone = readiness.database_connected && readiness.redis_connected && readiness.live_engine_ready
        ? "success"
        : readiness.database_connected && readiness.redis_connected
          ? "warn"
          : "error";
      setBox(
        "readinessStatus",
        `${readiness.selected_watchlist ? `Using ${readiness.selected_watchlist.name} · ` : ""}DB ${readiness.database_connected ? "connected" : "down"} · Redis ${readiness.redis_connected ? "connected" : "down"} · Zerodha token ${readiness.zerodha_access_token_configured ? "present" : "missing"} · ${readiness.symbols_with_recent_3minute_data}/${readiness.watched_symbol_count} watched symbols have recent 3-minute candle data.`,
        tone,
      );
      const pillData = [
        ["Instrument sync", readiness.instrument_master_ready],
        ["Token ready", readiness.zerodha_access_token_configured],
        ["Mapped watchlist", readiness.mapped_symbol_count > 0 && readiness.unmapped_symbol_count === 0],
        ["Live-engine ready", readiness.live_engine_ready],
        ["3-minute volume", readiness.three_minute_volume_ready],
      ];
      document.getElementById("readinessPills").innerHTML = pillData.map(([label, ok]) => `
        <span class="pill"><span class="badge ${ok ? "" : "warn"}">${ok ? "READY" : "CHECK"}</span>${label}</span>
      `).join("");
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
        await refreshAll();
      } catch (error) {
        setBox("watchlistStatus", error.message, "error");
      }
    }
    window.selectWatchlist = selectWatchlist;

    async function loadReadiness() {
      const readiness = await apiGet("/configuration/readiness");
      renderReadiness(readiness);
      return readiness;
    }

    async function loadZerodhaConnectionStatus() {
      const result = await apiGet("/api/zerodha/test");
      renderZerodhaConnectionStatus(result);
      return result;
    }

    async function refreshAll() {
      const [readiness, watchlists] = await Promise.all([loadReadiness(), loadWatchlists()]);
      renderConfigCards(readiness, watchlists);
      await loadZerodhaConnectionStatus();
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

    document.getElementById("connectZerodhaButton").addEventListener("click", () => {
      window.location.href = "/api/zerodha/login";
    });

    document.getElementById("testZerodhaButton").addEventListener("click", async () => {
      try {
        await loadZerodhaConnectionStatus();
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

    instruments = db.scalars(
        select(Instrument).where(
            Instrument.exchange == exchange,
            Instrument.is_active.is_(True),
            Instrument.tradingsymbol.in_(valid_symbols),
        )
    ).all()
    instrument_map = {instrument.tradingsymbol.upper(): instrument for instrument in instruments}
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
