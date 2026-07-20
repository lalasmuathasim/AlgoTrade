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

from backend.app.config import get_settings
from backend.app.dependencies import require_admin_user, require_approved_user
from backend.app.database import get_db
from backend.app.models import BreakoutEvent, Instrument, PaperTrade, ScanExecution, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.paper_trading_service import ensure_settings
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.ui import render_app_shell


router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_approved_user)])
settings = get_settings()


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


def _resolve_instrument_token(db: Session, symbol: WatchlistSymbol) -> int | None:
    if symbol.instrument_token is not None:
        return symbol.instrument_token
    if symbol.instrument_id is None:
        return None
    instrument = db.get(Instrument, symbol.instrument_id)
    return instrument.instrument_token if instrument else None


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
        "required_volume_multiplier": event.required_volume_multiplier,
        "volume_ratio": event.volume_ratio,
        "volume_condition_required": event.volume_condition_required,
        "volume_condition_passed": event.volume_condition_passed,
        "entry_price": event.entry_price,
        "stop_loss": event.stop_loss,
        "target": event.target,
        "signal_generated": event.signal_generated,
        "status": event.status,
        "rejection_reason": event.rejection_reason,
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
    <section id="summaryCards" class="metric-strip"></section>
    <section class="layout-main-aside">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Market Support and Resistance</h2>
            <p class="panel-copy">Review the market structure table built from the last 100 daily candles. These reference lines represent projected support and resistance zones for normal market conditions and can be refreshed after market close or whenever you explicitly rescan.</p>
          </div>
        </div>
        <ul id="dashboardSummaryList" style="margin: 0; padding-left: 20px; color: var(--muted); font-size: 0.86rem; line-height: 1.55;">
          <li>Loading market structure summary...</li>
          <li>Loading active structure tuning values...</li>
        </ul>
      </div>
      <div class="rail-stack">
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2>Table Properties</h2>
              <p class="panel-copy">This view now focuses only on the line details needed to verify the daily structure logic.</p>
            </div>
          </div>
          <ul style="margin: 0; padding-left: 20px; color: var(--muted); font-size: 0.86rem; line-height: 1.55;">
            <li>One row is shown for each detected support or resistance line.</li>
            <li>Multiple lines for the same symbol remain in separate rows.</li>
            <li>Swing references stay visible for manual cross-checking.</li>
          </ul>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Market Structure Table</h2>
          <p class="panel-copy">Review the saved support and resistance rows for the selected watchlist, including the swing references, gap percentage, and nearest target used for validation.</p>
        </div>
      </div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p class="table-toolbar-copy">Preview mode keeps long market-structure lists compact. Expand when you want the full saved table.</p>
          <div class="table-toolbar-actions">
            <button id="refreshDailyReviewButton" class="secondary table-toggle" type="button">Update Table</button>
            <button id="dailyReviewToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
          </div>
        </div>
        <div id="dailyReviewFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 920px;">
          <table id="dailyReviewTable"></table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>3-Minute Breakout Review</h2>
          <p class="panel-copy">Review every saved breakout or breakdown attempt for the selected watchlist, including the previous candle volume, the required multiplier, and whether the event converted into a signal.</p>
        </div>
      </div>
      <div id="breakoutReviewSummary" class="table-toolbar-copy" style="margin-bottom: 14px;">Loading breakout review summary...</div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p class="table-toolbar-copy">This review stays collapsed by default so you can scan the latest breakout attempts without stretching the dashboard.</p>
          <div class="table-toolbar-actions">
            <button id="refreshBreakoutReviewButton" class="secondary table-toggle" type="button">Refresh Table</button>
            <button id="breakoutReviewToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
          </div>
        </div>
        <div id="breakoutReviewFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 1480px;">
          <table id="breakoutReviewTable"></table>
        </div>
      </div>
    </section>
    """
    script = """
    let latestOverview = null;
    const syncDailyReviewPreview = bindCollapsibleTable({
      buttonId: "dailyReviewToggle",
      frameId: "dailyReviewFrame",
      tableId: "dailyReviewTable",
      previewRows: 9,
    });
    const syncBreakoutReviewPreview = bindCollapsibleTable({
      buttonId: "breakoutReviewToggle",
      frameId: "breakoutReviewFrame",
      tableId: "breakoutReviewTable",
      previewRows: 8,
    });

    function renderCards(stats) {
      renderMetricStrip(document.getElementById("summaryCards"), [
        { label: "Watchlists", value: stats.watchlists, meta: "Saved watch universes" },
        { label: "In Use", value: stats.current_watchlist_name || "None", meta: "Runtime-selected market universe" },
        { label: "Watched Symbols", value: stats.configured_symbols, meta: "Daily draw and redraw candidates" },
        { label: "Drawn Symbols", value: stats.drawn_symbols, meta: "Symbols with stored line structures" },
        { label: "Active Trigger Lines", value: stats.active_trigger_lines, meta: "Open structure levels" },
      ]);
    }

    function renderDashboardSummary(overview, tuning = null, reviewSummary = null, message = null) {
      const list = document.getElementById("dashboardSummaryList");
      if (message) {
        list.innerHTML = message.map((item) => `<li>${item}</li>`).join("");
        return;
      }

      const items = [
        `${overview?.current_watchlist_name ? `Using ${overview.current_watchlist_name}. ` : ""}${overview?.active_trigger_lines ?? 0} active stored trigger lines are available across ${overview?.configured_symbols ?? 0} configured symbols.`,
        tuning
          ? `Current tuning: candle lookback ${tuning.daily_candle_lookback}, max gap ${tuning.max_gap_percent}%, swing window ${tuning.swing_window}, minimum swing distance ${tuning.min_swing_distance} candles.`
          : "Current tuning values will appear after the market structure table loads.",
        reviewSummary
          ? `${reviewSummary.total_candidate_rows} stored rows are available across ${reviewSummary.symbols_with_lines} symbols. Last scan: ${reviewSummary.last_scan_finished_at ? new Date(reviewSummary.last_scan_finished_at).toLocaleString() : "not run yet"}${reviewSummary.last_scan_status ? ` (${reviewSummary.last_scan_status})` : ""}.`
          : "Saved support and resistance rows load from the database and refresh only when the scheduled scan or manual update runs.",
      ];
      list.innerHTML = items.map((item) => `<li>${item}</li>`).join("");
    }

    async function loadDailyLineReview() {
      const review = await apiGet("/dashboard/reports/daily-line-review");
      renderDashboardSummary(latestOverview, review.summary.tuning, review.summary);
      renderTable(
        document.getElementById("dailyReviewTable"),
        ["Symbol", "Line Type", "Line Price", "Line Drawn Date", "Swing 1", "Swing 2", "Gap %", "Nearest Target"],
        review.rows.map((item) => [
          item.symbol,
          `<span class="badge">${item.line_type}</span>`,
          item.line_price ?? "N/A",
          item.line_drawn_date ?? "N/A",
          item.swing_1 ? `${item.swing_1.price} · ${item.swing_1.date}` : "N/A",
          item.swing_2 ? `${item.swing_2.price} · ${item.swing_2.date}` : "N/A",
          item.swing_gap_percent ?? "N/A",
          item.nearest_target ?? "N/A",
        ]),
      );
      syncDailyReviewPreview();
      return review;
    }

    function renderBreakoutReviewSummary(summary) {
      const element = document.getElementById("breakoutReviewSummary");
      if (!summary || !summary.selected_watchlist) {
        element.textContent = "No selected watchlist is available for breakout review yet.";
        element.className = "table-toolbar-copy";
        return;
      }
      element.textContent = `${summary.selected_watchlist.name} · ${summary.total_events} breakout attempts · ${summary.passed_events} volume-confirmed · ${summary.failed_events} rejected · latest event ${summary.latest_event_time ? new Date(summary.latest_event_time).toLocaleString() : "not recorded yet"}`;
      element.className = "table-toolbar-copy";
    }

    async function loadBreakoutReview() {
      const review = await apiGet("/dashboard/reports/breakout-review");
      renderBreakoutReviewSummary(review.summary);
      renderTable(
        document.getElementById("breakoutReviewTable"),
        ["Symbol", "Line Type", "Line Price", "Event", "Breakout Time", "Prev Volume", "Breakout Volume", "Required", "Ratio", "Passed", "Entry", "Stop Loss", "Target", "Signal", "Status"],
        review.rows.map((item) => [
          item.symbol,
          `<span class="badge">${item.line_type}</span>`,
          item.line_price ?? "N/A",
          item.event_type,
          item.event_time ? new Date(item.event_time).toLocaleString() : "N/A",
          item.previous_candle_volume ?? "N/A",
          item.breakout_candle_volume ?? "N/A",
          item.required_volume_multiplier ? `${item.required_volume_multiplier}x` : "N/A",
          item.volume_ratio ?? "N/A",
          item.volume_condition_passed ? '<span class="badge">YES</span>' : '<span class="badge warn">NO</span>',
          item.entry_price ?? "N/A",
          item.stop_loss ?? "N/A",
          item.target ?? "N/A",
          item.signal_generated ? '<span class="badge">CREATED</span>' : '<span class="badge warn">SKIPPED</span>',
          item.rejection_reason ? `${item.status} · ${item.rejection_reason}` : item.status,
        ]),
      );
      syncBreakoutReviewPreview();
      return review;
    }

    async function updateDailyReview() {
      renderDashboardSummary(
        latestOverview,
        null,
        null,
        [
          "Running the daily scan and updating stored market structure rows.",
          "The selected watchlist is being rescanned with the current tuning values.",
        ],
      );
      const result = await apiSend("/dashboard/reports/daily-line-review/refresh", "POST", {});
      renderDashboardSummary(
        latestOverview,
        null,
        null,
        [
          `Update complete with status ${result.status}.`,
          `${result.symbols_scanned} symbols scanned, ${result.trigger_lines_created} lines created, ${result.trigger_lines_updated} lines updated.`,
        ],
      );
      return result;
    }

    async function init() {
      const [overview] = await Promise.all([
        apiGet("/dashboard/reports/overview"),
      ]);
      latestOverview = overview;
      renderCards(overview);
      renderDashboardSummary(overview);
      try {
        await Promise.all([loadDailyLineReview(), loadBreakoutReview()]);
      } catch (error) {
        renderDashboardSummary(
          overview,
          null,
          null,
          [
            "Unable to load the saved market structure table.",
            error.message,
          ],
        );
      }
    }

    document.getElementById("refreshDailyReviewButton").addEventListener("click", async () => {
      try {
        await updateDailyReview();
        await loadDailyLineReview();
      } catch (error) {
        renderDashboardSummary(
          latestOverview,
          null,
          null,
          [
            "Unable to update the market structure table.",
            error.message,
          ],
        );
      }
    });

    document.getElementById("refreshBreakoutReviewButton").addEventListener("click", async () => {
      try {
        await loadBreakoutReview();
      } catch (error) {
        renderBreakoutReviewSummary(null);
        document.getElementById("breakoutReviewSummary").textContent = `Unable to load breakout review: ${error.message}`;
      }
    });

    init().catch((error) => {
      renderDashboardSummary(
        null,
        null,
        null,
        [
          "Unable to initialize the dashboard.",
          error.message,
        ],
      );
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


@router.get("/dashboard/reports/daily-line-review")
def dashboard_daily_line_review(db: Session = Depends(get_db)) -> dict:
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    if selected_watchlist is None or selected_watchlist_id is None:
        return {
            "selected_watchlist": None,
            "summary": {
                "total_symbols": 0,
                "unmapped_symbols": 0,
                "symbols_with_lines": 0,
                "total_candidate_rows": 0,
                "last_scan_status": None,
                "last_scan_finished_at": None,
            },
            "rows": [],
        }

    symbols = db.scalars(
        select(WatchlistSymbol)
        .where(
            WatchlistSymbol.watchlist_id == selected_watchlist_id,
            WatchlistSymbol.is_active.is_(True),
        )
        .order_by(WatchlistSymbol.symbol)
    ).all()
    lines = db.scalars(
        select(TriggerLine)
        .where(
            TriggerLine.watchlist_id == selected_watchlist_id,
            TriggerLine.line_status == "ACTIVE",
        )
        .order_by(TriggerLine.symbol, TriggerLine.line_type, desc(TriggerLine.line_drawn_date), desc(TriggerLine.updated_at))
    ).all()
    latest_scan = db.scalar(
        select(ScanExecution)
        .where(ScanExecution.scan_name == "daily_market_scan")
        .order_by(desc(ScanExecution.finished_at), desc(ScanExecution.created_at))
        .limit(1)
    )
    runtime_settings = ensure_settings(db)

    rows: list[dict] = []
    for line in lines:
        if line.line_type == "BUY":
            swing_1 = {
                "price": line.swing_high_1_price,
                "date": line.swing_high_1_date.isoformat() if line.swing_high_1_date else None,
            }
            swing_2 = {
                "price": line.swing_high_2_price,
                "date": line.swing_high_2_date.isoformat() if line.swing_high_2_date else None,
            }
            nearest_target = line.nearest_daily_swing_high_target
        else:
            swing_1 = {
                "price": line.swing_low_1_price,
                "date": line.swing_low_1_date.isoformat() if line.swing_low_1_date else None,
            }
            swing_2 = {
                "price": line.swing_low_2_price,
                "date": line.swing_low_2_date.isoformat() if line.swing_low_2_date else None,
            }
            nearest_target = line.nearest_daily_swing_low_target

        rows.append(
            {
                "exchange": line.exchange,
                "symbol": line.symbol,
                "line_type": line.line_type,
                "line_price": round(line.line_price, 2) if line.line_price is not None else None,
                "line_drawn_date": line.line_drawn_date.isoformat() if line.line_drawn_date else None,
                "swing_1": swing_1,
                "swing_2": swing_2,
                "swing_gap_percent": line.swing_gap_percent,
                "nearest_target": round(nearest_target, 2) if nearest_target is not None else None,
            }
        )

    return {
        "selected_watchlist": {
            "id": str(selected_watchlist.id),
            "name": selected_watchlist.name,
            "exchange": selected_watchlist.exchange,
        },
        "summary": {
            "total_symbols": len(symbols),
            "unmapped_symbols": sum(1 for symbol in symbols if _resolve_instrument_token(db, symbol) is None),
            "symbols_with_lines": len({(row["exchange"], row["symbol"]) for row in rows}),
            "total_candidate_rows": len(rows),
            "last_scan_status": latest_scan.status if latest_scan else None,
            "last_scan_finished_at": _serialize_datetime(latest_scan.finished_at) if latest_scan else None,
            "tuning": {
                "daily_candle_lookback": runtime_settings.daily_candle_lookback,
                "max_gap_percent": runtime_settings.max_gap_percent,
                "swing_window": runtime_settings.swing_window,
                "min_swing_distance": runtime_settings.min_swing_distance,
            },
        },
        "rows": rows,
    }


@router.get("/dashboard/reports/breakout-review")
def dashboard_breakout_review(db: Session = Depends(get_db)) -> dict:
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    if selected_watchlist is None or selected_watchlist_id is None:
        return {
            "selected_watchlist": None,
            "summary": {
                "selected_watchlist": None,
                "total_events": 0,
                "passed_events": 0,
                "failed_events": 0,
                "latest_event_time": None,
            },
            "rows": [],
        }

    lines = db.scalars(
        select(TriggerLine)
        .where(TriggerLine.watchlist_id == selected_watchlist_id)
        .order_by(TriggerLine.symbol, TriggerLine.line_type)
    ).all()
    line_map = {line.id: line for line in lines}
    events = db.scalars(select(BreakoutEvent).order_by(desc(BreakoutEvent.event_time), desc(BreakoutEvent.created_at))).all()

    rows: list[dict] = []
    for event in events:
        line = line_map.get(event.trigger_line_id) if event.trigger_line_id else None
        if line is None:
            continue
        rows.append(
            {
                "id": str(event.id),
                "symbol": event.symbol,
                "exchange": event.exchange,
                "line_type": line.line_type,
                "line_price": line.line_price,
                "event_type": event.event_type,
                "event_time": _serialize_datetime(event.event_time),
                "breakout_candle_volume": event.breakout_candle_volume,
                "previous_candle_volume": event.previous_candle_volume,
                "required_volume_multiplier": event.required_volume_multiplier,
                "volume_ratio": event.volume_ratio,
                "volume_condition_passed": event.volume_condition_passed,
                "entry_price": event.entry_price,
                "stop_loss": event.stop_loss,
                "target": event.target,
                "signal_generated": event.signal_generated,
                "status": event.status,
                "rejection_reason": event.rejection_reason,
            }
        )

    return {
        "selected_watchlist": {
            "id": str(selected_watchlist.id),
            "name": selected_watchlist.name,
            "exchange": selected_watchlist.exchange,
        },
        "summary": {
            "selected_watchlist": {
                "id": str(selected_watchlist.id),
                "name": selected_watchlist.name,
                "exchange": selected_watchlist.exchange,
            },
            "total_events": len(rows),
            "passed_events": sum(1 for row in rows if row["volume_condition_passed"]),
            "failed_events": sum(1 for row in rows if not row["volume_condition_passed"]),
            "latest_event_time": rows[0]["event_time"] if rows else None,
        },
        "rows": rows,
    }


@router.post("/dashboard/reports/daily-line-review/refresh", dependencies=[Depends(require_admin_user)])
def refresh_dashboard_daily_line_review(db: Session = Depends(get_db)) -> dict:
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    if selected_watchlist_id is None:
        raise HTTPException(status_code=404, detail="No watchlist is currently selected")

    scanner = DailyMarketScanner()
    execution = scanner.run(
        db,
        watchlist_id=selected_watchlist_id,
        scan_date=datetime.now(UTC).date(),
        dry_run=False,
    )
    return {
        "execution_id": str(execution.id),
        "status": execution.status,
        "symbols_scanned": execution.symbols_scanned,
        "trigger_lines_created": execution.trigger_lines_created,
        "trigger_lines_updated": execution.trigger_lines_updated,
    }


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
