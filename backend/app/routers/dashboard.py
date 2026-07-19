import csv
from collections import defaultdict
from datetime import UTC, date, datetime
from io import StringIO
from statistics import mean
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.dependencies import require_approved_user
from backend.app.database import get_db
from backend.app.models import BreakoutEvent, PaperTrade, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.ui import render_app_shell


router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_approved_user)])


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _paper_trade_summary(trades: list[PaperTrade]) -> dict:
    total_trades = len(trades)
    open_trades = sum(1 for trade in trades if trade.status == "OPEN")
    closed_trades_list = [trade for trade in trades if trade.status != "OPEN"]
    closed_trades = len(closed_trades_list)
    winners = [trade for trade in closed_trades_list if (trade.pnl or 0.0) > 0]
    losers = [trade for trade in closed_trades_list if (trade.pnl or 0.0) < 0]
    total_pnl = round(sum(trade.pnl or 0.0 for trade in trades), 2)
    average_profit = round(mean([trade.pnl for trade in winners]), 2) if winners else 0.0
    average_loss = round(mean([trade.pnl for trade in losers]), 2) if losers else 0.0
    gross_profit = sum(trade.pnl or 0.0 for trade in winners)
    gross_loss = abs(sum(trade.pnl or 0.0 for trade in losers))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None
    win_rate = round((len(winners) / closed_trades) * 100, 2) if closed_trades else 0.0

    return {
        "total_trades": total_trades,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_profit": average_profit,
        "average_loss": average_loss,
        "profit_factor": profit_factor,
    }


def _selected_watchlist_filter(db: Session) -> tuple[Watchlist | None, UUID | None]:
    selected = get_selected_watchlist(db)
    return selected, selected.id if selected else None


def _serialize_trigger_line(line: TriggerLine) -> dict:
    return {
        "id": str(line.id),
        "watchlist_id": str(line.watchlist_id) if line.watchlist_id else None,
        "exchange": line.exchange,
        "symbol": line.symbol,
        "line_type": line.line_type,
        "line_price": line.line_price,
        "line_status": line.line_status,
        "line_drawn_date": _serialize_date(line.line_drawn_date),
        "source_timeframe": line.source_timeframe,
        "lookback_candles": line.lookback_candles,
        "max_gap_percent_used": line.max_gap_percent_used,
        "min_swing_distance_used": line.min_swing_distance_used,
        "swing_high_1_price": line.swing_high_1_price,
        "swing_high_1_date": _serialize_date(line.swing_high_1_date),
        "swing_high_2_price": line.swing_high_2_price,
        "swing_high_2_date": _serialize_date(line.swing_high_2_date),
        "higher_swing_high_price": line.higher_swing_high_price,
        "lower_swing_high_price": line.lower_swing_high_price,
        "swing_low_1_price": line.swing_low_1_price,
        "swing_low_1_date": _serialize_date(line.swing_low_1_date),
        "swing_low_2_price": line.swing_low_2_price,
        "swing_low_2_date": _serialize_date(line.swing_low_2_date),
        "lower_swing_low_price": line.lower_swing_low_price,
        "higher_swing_low_price": line.higher_swing_low_price,
        "swing_gap_percent": line.swing_gap_percent,
        "nearest_daily_swing_high_target": line.nearest_daily_swing_high_target,
        "nearest_daily_swing_low_target": line.nearest_daily_swing_low_target,
        "created_at": _serialize_datetime(line.created_at),
        "updated_at": _serialize_datetime(line.updated_at),
    }


def _serialize_breakout_event(event: BreakoutEvent) -> dict:
    return {
        "id": str(event.id),
        "trigger_line_id": str(event.trigger_line_id) if event.trigger_line_id else None,
        "exchange": event.exchange,
        "symbol": event.symbol,
        "event_type": event.event_type,
        "event_time": _serialize_datetime(event.event_time),
        "breakout_or_breakdown_price": event.breakout_or_breakdown_price,
        "breakout_candle_high": event.breakout_candle_high,
        "breakout_candle_low": event.breakout_candle_low,
        "breakout_candle_volume": event.breakout_candle_volume,
        "previous_candle_volume": event.previous_candle_volume,
        "volume_ratio": event.volume_ratio,
        "volume_condition_required": event.volume_condition_required,
        "volume_condition_passed": event.volume_condition_passed,
        "entry_price": event.entry_price,
        "stop_loss": event.stop_loss,
        "target": event.target,
        "status": event.status,
        "created_at": _serialize_datetime(event.created_at),
    }


def _serialize_signal(signal: TradingSignal) -> dict:
    return {
        "id": str(signal.id),
        "exchange": signal.exchange,
        "symbol": signal.symbol,
        "action": signal.action,
        "source": signal.source,
        "watchlist_id": str(signal.watchlist_id) if signal.watchlist_id else None,
        "trigger_line_id": str(signal.trigger_line_id) if signal.trigger_line_id else None,
        "breakout_event_id": str(signal.breakout_event_id) if signal.breakout_event_id else None,
        "scan_execution_id": str(signal.scan_execution_id) if signal.scan_execution_id else None,
        "trigger_price": signal.trigger_price,
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "target": signal.target,
        "quantity": signal.quantity,
        "capital_used": signal.capital_used,
        "risk_amount": signal.risk_amount,
        "volume_ratio": signal.volume_ratio,
        "timeframe": signal.timeframe,
        "strategy": signal.strategy,
        "dedupe_key": signal.dedupe_key,
        "status": signal.status,
        "notification_status": signal.notification_status,
        "processed_at": _serialize_datetime(signal.processed_at),
        "created_at": _serialize_datetime(signal.created_at),
    }


def _serialize_paper_trade(trade: PaperTrade) -> dict:
    return {
        "id": str(trade.id),
        "signal_id": str(trade.signal_id) if trade.signal_id else None,
        "trigger_line_id": str(trade.trigger_line_id) if trade.trigger_line_id else None,
        "exchange": trade.exchange,
        "symbol": trade.symbol,
        "action": trade.action,
        "simulated_entry_price": trade.simulated_entry_price,
        "simulated_stop_loss": trade.simulated_stop_loss,
        "simulated_target": trade.simulated_target,
        "quantity": trade.quantity,
        "capital_used": trade.capital_used,
        "risk_amount": trade.risk_amount,
        "status": trade.status,
        "simulated_exit_price": trade.simulated_exit_price,
        "pnl": trade.pnl,
        "pnl_percent": trade.pnl_percent,
        "entry_time": _serialize_datetime(trade.entry_time),
        "exit_time": _serialize_datetime(trade.exit_time),
        "created_at": _serialize_datetime(trade.created_at),
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_home() -> str:
    body_html = """
    <section class="grid" id="summaryCards"></section>
    <section class="two-col">
      <div class="panel">
        <h2>Report Exports</h2>
        <div id="dashboardStatus" class="status-box">Loading report summaries and exports...</div>
        <div class="stack">
          <div class="inline">
            <a class="button secondary" href="/dashboard/reports/watched-symbols.csv">Export Watched Symbols CSV</a>
            <a class="button secondary" href="/dashboard/reports/active-trigger-lines.csv">Export Active Lines CSV</a>
          </div>
          <div class="inline">
            <a class="button secondary" href="/dashboard/watchlists">Watchlist Summary API</a>
            <a class="button secondary" href="/dashboard/trigger-lines">Trigger Lines API</a>
            <a class="button secondary" href="/dashboard/breakout-events">Breakout Events API</a>
          </div>
        </div>
      </div>
      <div class="panel">
        <h2>Report Scope</h2>
        <ul class="list">
          <li class="pill">Configured watchlists and watched symbols</li>
          <li class="pill">Already-drawn symbols and active trigger lines</li>
          <li class="pill">Breakout activity and recent paper-trading outcomes</li>
          <li class="pill">Export-ready reports for reviews and handoffs</li>
        </ul>
      </div>
    </section>
    <section class="split">
      <div class="panel">
        <h2>Watched Symbols Report</h2>
        <table id="watchedSymbolsTable"></table>
      </div>
      <div class="panel">
        <h2>Paper Trading Summary</h2>
        <table id="paperTable"></table>
      </div>
    </section>
    <section class="panel" style="margin-top: 18px;">
      <h2>Active Trigger Lines</h2>
      <table id="linesTable"></table>
    </section>
    <section class="panel" style="margin-top: 18px;">
      <h2>Recent Breakout Events</h2>
      <table id="breakoutsTable"></table>
    </section>
    """
    script = """
    function renderCards(stats) {
      const cards = [
        ["Watchlists", stats.watchlists, "Saved watch universes"],
        ["In Use", stats.current_watchlist_name || "None", "The watchlist currently used by scan and live monitoring"],
        ["Watched Symbols", stats.configured_symbols, "Symbols scheduled for daily draw/redraw"],
        ["Drawn Symbols", stats.drawn_symbols, "Symbols with at least one trigger line"],
        ["Active Trigger Lines", stats.active_trigger_lines, "Current breakout / breakdown levels"],
      ];
      document.getElementById("summaryCards").innerHTML = cards.map(([label, value, subvalue]) => `
        <article class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
          <div class="subvalue">${subvalue}</div>
        </article>
      `).join("");
    }

    async function init() {
      const [overview, watchedSymbols, paper, lines, breakouts] = await Promise.all([
        apiGet("/dashboard/reports/overview"),
        apiGet("/dashboard/reports/watched-symbols"),
        apiGet("/dashboard/paper-trades"),
        apiGet("/dashboard/trigger-lines?line_status=ACTIVE"),
        apiGet("/dashboard/breakout-events"),
      ]);
      renderCards(overview);
      setBox(
        "dashboardStatus",
        `${overview.current_watchlist_name ? `Using ${overview.current_watchlist_name} for runtime monitoring. ` : ""}${overview.drawn_symbols} watched symbols already have drawn trigger structures. ${overview.configured_symbols} symbols are in the daily draw/redraw universe.`,
        "success",
      );
      renderTable(
        document.getElementById("watchedSymbolsTable"),
        ["Symbol", "Watchlists", "Mapped", "Active Lines", "Latest Line Status"],
        watchedSymbols.map((item) => [
          `${item.exchange}:${item.symbol}`,
          item.watchlists.join(", "),
          item.instrument_token ?? "Unmapped",
          item.active_line_count,
          item.latest_line_status ?? "No lines yet",
        ]),
      );
      renderTable(
        document.getElementById("paperTable"),
        ["Total", "Open", "Closed", "Win Rate", "PnL", "Profit Factor"],
        [[
          paper.summary.total_trades,
          paper.summary.open_trades,
          paper.summary.closed_trades,
          `${paper.summary.win_rate}%`,
          paper.summary.total_pnl.toFixed(2),
          paper.summary.profit_factor ?? "N/A",
        ]],
      );
      renderTable(
        document.getElementById("linesTable"),
        ["Symbol", "Type", "Price", "Status", "Gap %", "Target", "Drawn Date"],
        lines.map((item) => [
          `${item.exchange}:${item.symbol}`,
          `<span class="badge">${item.line_type}</span>`,
          item.line_price,
          item.line_status,
          item.swing_gap_percent ?? "N/A",
          item.nearest_daily_swing_high_target ?? item.nearest_daily_swing_low_target ?? "N/A",
          item.line_drawn_date ?? "N/A",
        ]),
      );
      renderTable(
        document.getElementById("breakoutsTable"),
        ["Symbol", "Event", "Time", "Volume Ratio", "Status"],
        breakouts.slice(0, 12).map((item) => [
          `${item.exchange}:${item.symbol}`,
          item.event_type,
          new Date(item.event_time).toLocaleString(),
          item.volume_ratio ?? "N/A",
          item.status,
        ]),
      );
    }

    init().catch((error) => {
      setBox("dashboardStatus", error.message, "error");
    });
    """
    return render_app_shell(
        title="Qubitx Dashboard",
        heading="Dashboard",
        subtitle="Review watch coverage, already-drawn trigger structures, recent breakout activity, and export-ready reports built on the Zerodha-native data path.",
        active_nav="dashboard",
        body_html=body_html,
        script=script,
    )


@router.get("/dashboard/reports/overview")
def dashboard_report_overview(db: Session = Depends(get_db)) -> dict:
    watchlists = db.scalars(select(Watchlist)).all()
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    watchlist_symbols_query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
    trigger_lines_query = select(TriggerLine)
    if selected_watchlist_id is not None:
        watchlist_symbols_query = watchlist_symbols_query.where(WatchlistSymbol.watchlist_id == selected_watchlist_id)
        trigger_lines_query = trigger_lines_query.where(TriggerLine.watchlist_id == selected_watchlist_id)
    watchlist_symbols = db.scalars(watchlist_symbols_query).all()
    trigger_lines = db.scalars(trigger_lines_query).all()

    configured_symbol_keys = {(symbol.exchange, symbol.symbol) for symbol in watchlist_symbols}
    drawn_symbol_keys = {(line.exchange, line.symbol) for line in trigger_lines}

    return {
        "watchlists": len(watchlists),
        "current_watchlist_id": str(selected_watchlist.id) if selected_watchlist else None,
        "current_watchlist_name": selected_watchlist.name if selected_watchlist else None,
        "configured_symbols": len(configured_symbol_keys),
        "drawn_symbols": len(drawn_symbol_keys),
        "active_trigger_lines": sum(1 for line in trigger_lines if line.line_status == "ACTIVE"),
        "triggered_lines": sum(1 for line in trigger_lines if line.line_status == "TRIGGERED"),
    }


@router.get("/dashboard/reports/watched-symbols")
def dashboard_watched_symbols_report(db: Session = Depends(get_db)) -> list[dict]:
    watchlists = {watchlist.id: watchlist for watchlist in db.scalars(select(Watchlist)).all()}
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    symbols_query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
    lines_query = select(TriggerLine)
    if selected_watchlist_id is not None:
        symbols_query = symbols_query.where(WatchlistSymbol.watchlist_id == selected_watchlist_id)
        lines_query = lines_query.where(TriggerLine.watchlist_id == selected_watchlist_id)
    symbols = db.scalars(
        symbols_query.order_by(WatchlistSymbol.exchange, WatchlistSymbol.symbol)
    ).all()
    lines = db.scalars(
        lines_query.order_by(desc(TriggerLine.updated_at), desc(TriggerLine.created_at))
    ).all()

    lines_by_symbol: dict[tuple[str, str], list[TriggerLine]] = defaultdict(list)
    for line in lines:
        lines_by_symbol[(line.exchange, line.symbol)].append(line)

    grouped_symbols: dict[tuple[str, str], dict] = {}
    for symbol in symbols:
        key = (symbol.exchange, symbol.symbol)
        grouped = grouped_symbols.setdefault(
            key,
            {
                "exchange": symbol.exchange,
                "symbol": symbol.symbol,
                "company_name": symbol.company_name,
                "instrument_token": symbol.instrument_token,
                "watchlists": [],
            },
        )
        watchlist_name = watchlists[symbol.watchlist_id].name if symbol.watchlist_id in watchlists else "Unknown"
        if watchlist_name not in grouped["watchlists"]:
            grouped["watchlists"].append(watchlist_name)

    payload: list[dict] = []
    for key, grouped in sorted(grouped_symbols.items()):
        symbol_lines = lines_by_symbol.get(key, [])
        payload.append(
            {
                "exchange": grouped["exchange"],
                "symbol": grouped["symbol"],
                "company_name": grouped["company_name"],
                "instrument_token": grouped["instrument_token"],
                "watchlists": sorted(grouped["watchlists"]),
                "active_line_count": sum(1 for line in symbol_lines if line.line_status == "ACTIVE"),
                "historical_line_count": len(symbol_lines),
                "latest_line_status": symbol_lines[0].line_status if symbol_lines else None,
                "selected_watchlist_name": selected_watchlist.name if selected_watchlist else None,
            }
        )
    return payload


@router.get("/dashboard/reports/watched-symbols.csv")
def dashboard_watched_symbols_export(db: Session = Depends(get_db)) -> StreamingResponse:
    rows = dashboard_watched_symbols_report(db)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "exchange",
            "symbol",
            "company_name",
            "instrument_token",
            "watchlists",
            "active_line_count",
            "historical_line_count",
            "latest_line_status",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["exchange"],
                row["symbol"],
                row["company_name"] or "",
                row["instrument_token"] or "",
                ", ".join(row["watchlists"]),
                row["active_line_count"],
                row["historical_line_count"],
                row["latest_line_status"] or "",
            ]
        )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="watched-symbols-report.csv"'},
    )


@router.get("/dashboard/reports/active-trigger-lines.csv")
def dashboard_active_trigger_lines_export(db: Session = Depends(get_db)) -> StreamingResponse:
    _, selected_watchlist_id = _selected_watchlist_filter(db)
    query = select(TriggerLine).where(TriggerLine.line_status == "ACTIVE")
    if selected_watchlist_id is not None:
        query = query.where(TriggerLine.watchlist_id == selected_watchlist_id)
    lines = db.scalars(
        query.order_by(TriggerLine.exchange, TriggerLine.symbol, TriggerLine.line_type)
    ).all()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "exchange",
            "symbol",
            "line_type",
            "line_price",
            "line_status",
            "line_drawn_date",
            "swing_gap_percent",
            "nearest_target",
        ]
    )
    for line in lines:
        writer.writerow(
            [
                line.exchange,
                line.symbol,
                line.line_type,
                line.line_price,
                line.line_status,
                _serialize_date(line.line_drawn_date) or "",
                line.swing_gap_percent or "",
                line.nearest_daily_swing_high_target or line.nearest_daily_swing_low_target or "",
            ]
        )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="active-trigger-lines.csv"'},
    )


@router.get("/dashboard/watchlists")
def get_watchlist_summary(db: Session = Depends(get_db)) -> list[dict]:
    watchlists = db.scalars(select(Watchlist).order_by(Watchlist.name)).all()
    symbols = db.scalars(select(WatchlistSymbol)).all()
    lines = db.scalars(select(TriggerLine)).all()
    trades = db.scalars(select(PaperTrade)).all()

    symbols_by_watchlist: dict[UUID, list[WatchlistSymbol]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_watchlist[symbol.watchlist_id].append(symbol)

    lines_by_watchlist: dict[UUID, list[TriggerLine]] = defaultdict(list)
    for line in lines:
        if line.watchlist_id:
            lines_by_watchlist[line.watchlist_id].append(line)

    response = []
    for watchlist in watchlists:
        watchlist_symbols = symbols_by_watchlist.get(watchlist.id, [])
        watchlist_symbol_keys = {(item.exchange, item.symbol) for item in watchlist_symbols}
        watchlist_lines = lines_by_watchlist.get(watchlist.id, [])
        watchlist_trades = [trade for trade in trades if (trade.exchange, trade.symbol) in watchlist_symbol_keys]

        active_buy_symbols = {
            line.symbol for line in watchlist_lines if line.line_status == "ACTIVE" and line.line_type == "BUY"
        }
        active_sell_symbols = {
            line.symbol for line in watchlist_lines if line.line_status == "ACTIVE" and line.line_type == "SELL"
        }

        response.append(
            {
                "id": str(watchlist.id),
                "name": watchlist.name,
                "description": watchlist.description,
                "exchange": watchlist.exchange,
                "is_selected": watchlist.is_selected,
                "symbol_count": len(watchlist_symbols),
                "symbols_with_active_buy_lines": len(active_buy_symbols),
                "symbols_with_active_sell_lines": len(active_sell_symbols),
                "active_trigger_lines": sum(1 for line in watchlist_lines if line.line_status == "ACTIVE"),
                "triggered_lines": sum(1 for line in watchlist_lines if line.line_status == "TRIGGERED"),
                "paper_trades": len(watchlist_trades),
                "total_paper_pnl": round(sum(trade.pnl or 0.0 for trade in watchlist_trades), 2),
            }
        )
    return response


@router.get("/dashboard/watchlists/{watchlist_id}")
def get_watchlist_detail(watchlist_id: UUID, db: Session = Depends(get_db)) -> dict:
    watchlist = db.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = db.scalars(
        select(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == watchlist_id).order_by(WatchlistSymbol.symbol)
    ).all()
    lines = db.scalars(select(TriggerLine).where(TriggerLine.watchlist_id == watchlist_id)).all()
    signals = db.scalars(
        select(TradingSignal)
        .where(TradingSignal.watchlist_id == watchlist_id)
        .order_by(desc(TradingSignal.created_at))
    ).all()
    symbol_keys = {(item.exchange, item.symbol) for item in symbols}
    trades = [
        trade
        for trade in db.scalars(select(PaperTrade).order_by(desc(PaperTrade.created_at))).all()
        if (trade.exchange, trade.symbol) in symbol_keys
    ]

    latest_signal_by_symbol: dict[tuple[str, str], TradingSignal] = {}
    for signal in signals:
        latest_signal_by_symbol.setdefault((signal.exchange, signal.symbol), signal)

    symbol_payload = []
    for symbol in symbols:
        symbol_lines = [line for line in lines if line.symbol == symbol.symbol and line.exchange == symbol.exchange]
        symbol_trades = [trade for trade in trades if trade.symbol == symbol.symbol and trade.exchange == symbol.exchange]
        symbol_payload.append(
            {
                "id": str(symbol.id),
                "exchange": symbol.exchange,
                "symbol": symbol.symbol,
                "company_name": symbol.company_name,
                "is_active": symbol.is_active,
                "active_buy_lines": [_serialize_trigger_line(line) for line in symbol_lines if line.line_status == "ACTIVE" and line.line_type == "BUY"],
                "active_sell_lines": [_serialize_trigger_line(line) for line in symbol_lines if line.line_status == "ACTIVE" and line.line_type == "SELL"],
                "latest_signal": _serialize_signal(latest_signal_by_symbol[(symbol.exchange, symbol.symbol)]) if (symbol.exchange, symbol.symbol) in latest_signal_by_symbol else None,
                "paper_trade_summary": _paper_trade_summary(symbol_trades),
            }
        )

    return {
        "watchlist": {
            "id": str(watchlist.id),
            "name": watchlist.name,
            "description": watchlist.description,
            "exchange": watchlist.exchange,
            "is_selected": watchlist.is_selected,
            "created_at": _serialize_datetime(watchlist.created_at),
            "updated_at": _serialize_datetime(watchlist.updated_at),
        },
        "symbols": symbol_payload,
    }


@router.get("/dashboard/symbols/{exchange}/{symbol}")
def get_symbol_dashboard(exchange: str, symbol: str, db: Session = Depends(get_db)) -> dict:
    memberships = db.scalars(
        select(WatchlistSymbol).where(WatchlistSymbol.exchange == exchange, WatchlistSymbol.symbol == symbol)
    ).all()
    lines = db.scalars(
        select(TriggerLine)
        .where(TriggerLine.exchange == exchange, TriggerLine.symbol == symbol)
        .order_by(desc(TriggerLine.created_at))
    ).all()
    breakouts = db.scalars(
        select(BreakoutEvent)
        .where(BreakoutEvent.exchange == exchange, BreakoutEvent.symbol == symbol)
        .order_by(desc(BreakoutEvent.event_time))
    ).all()
    signals = db.scalars(
        select(TradingSignal)
        .where(TradingSignal.exchange == exchange, TradingSignal.symbol == symbol)
        .order_by(desc(TradingSignal.created_at))
    ).all()
    trades = db.scalars(
        select(PaperTrade)
        .where(PaperTrade.exchange == exchange, PaperTrade.symbol == symbol)
        .order_by(desc(PaperTrade.created_at))
    ).all()

    if not memberships and not lines and not breakouts and not signals and not trades:
        raise HTTPException(status_code=404, detail="Symbol not found")

    active_lines = [line for line in lines if line.line_status == "ACTIVE"]
    historical_lines = [line for line in lines if line.line_status != "ACTIVE"]
    return {
        "exchange": exchange,
        "symbol": symbol,
        "watchlists": [
            {
                "watchlist_id": str(membership.watchlist_id),
                "exchange": membership.exchange,
                "symbol": membership.symbol,
                "company_name": membership.company_name,
            }
            for membership in memberships
        ],
        "active_trigger_lines": [_serialize_trigger_line(line) for line in active_lines],
        "historical_trigger_lines": [_serialize_trigger_line(line) for line in historical_lines],
        "latest_signals": [_serialize_signal(signal) for signal in signals[:10]],
        "breakout_history": [_serialize_breakout_event(event) for event in breakouts],
        "paper_trades": [_serialize_paper_trade(trade) for trade in trades],
        "paper_trade_summary": _paper_trade_summary(trades),
    }


@router.get("/dashboard/trigger-lines")
def get_trigger_lines(
    watchlist_id: UUID | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    line_type: str | None = None,
    line_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    lines = db.scalars(select(TriggerLine).order_by(desc(TriggerLine.created_at))).all()
    filtered = []
    for line in lines:
        if watchlist_id and line.watchlist_id != watchlist_id:
            continue
        if exchange and line.exchange != exchange:
            continue
        if symbol and line.symbol != symbol:
            continue
        if line_type and line.line_type != line_type:
            continue
        if line_status and line.line_status != line_status:
            continue
        if date_from and line.line_drawn_date and line.line_drawn_date < date_from:
            continue
        if date_to and line.line_drawn_date and line.line_drawn_date > date_to:
            continue
        filtered.append(_serialize_trigger_line(line))
    return filtered


@router.get("/dashboard/breakout-events")
def get_breakout_events(
    exchange: str | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    volume_condition_passed: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    events = db.scalars(select(BreakoutEvent).order_by(desc(BreakoutEvent.event_time))).all()
    filtered = []
    for event in events:
        event_date = event.event_time.astimezone(UTC).date()
        if exchange and event.exchange != exchange:
            continue
        if symbol and event.symbol != symbol:
            continue
        if event_type and event.event_type != event_type:
            continue
        if volume_condition_passed is not None and event.volume_condition_passed != volume_condition_passed:
            continue
        if date_from and event_date < date_from:
            continue
        if date_to and event_date > date_to:
            continue
        filtered.append(_serialize_breakout_event(event))
    return filtered


@router.get("/dashboard/paper-trades")
def get_paper_trades(
    watchlist_id: UUID | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    trades = db.scalars(select(PaperTrade).order_by(desc(PaperTrade.created_at))).all()
    watchlist_symbols: set[tuple[str, str]] = set()
    if watchlist_id:
        watchlist_symbols = {
            (item.exchange, item.symbol)
            for item in db.scalars(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == watchlist_id)).all()
        }

    filtered = []
    for trade in trades:
        trade_date = (trade.entry_time or trade.created_at).astimezone(UTC).date()
        if watchlist_id and (trade.exchange, trade.symbol) not in watchlist_symbols:
            continue
        if exchange and trade.exchange != exchange:
            continue
        if symbol and trade.symbol != symbol:
            continue
        if status and trade.status != status:
            continue
        if date_from and trade_date < date_from:
            continue
        if date_to and trade_date > date_to:
            continue
        filtered.append(trade)

    return {
        "summary": _paper_trade_summary(filtered),
        "trades": [_serialize_paper_trade(trade) for trade in filtered],
    }
