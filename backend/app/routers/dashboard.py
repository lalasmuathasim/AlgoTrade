import logging
import csv
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
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
from backend.app.models import BrokerOrder, BreakoutEvent, Instrument, MarketCandle, PaperTrade, ScanExecution, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.queue import get_live_engine_runtime
from backend.app.schemas import HistoricalCandlePayload
from backend.app.services.market_scanner import DailyMarketScanner
from backend.app.services.paper_trading_service import ensure_settings
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.services.zerodha import HistoricalCandleProvider, ZerodhaApiClient, ZerodhaAuthService
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token, get_current_zerodha_session
from backend.app.ui import render_app_shell


router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_approved_user)])
settings = get_settings()
logger = logging.getLogger(__name__)


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


def _build_manual_scan_scanner(db: Session) -> DailyMarketScanner:
    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    return DailyMarketScanner(
        provider=HistoricalCandleProvider(
            client=ZerodhaApiClient(
                auth_service=ZerodhaAuthService(),
                access_token=access_token,
            )
        )
    )


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


def _resolve_trigger_line_instrument_token(db: Session, line: TriggerLine) -> int | None:
    if line.instrument_id is not None:
        instrument = db.get(Instrument, line.instrument_id)
        if instrument and instrument.instrument_token is not None:
            return instrument.instrument_token

    membership = db.scalar(
        select(WatchlistSymbol)
        .where(
            WatchlistSymbol.watchlist_id == line.watchlist_id,
            WatchlistSymbol.exchange == line.exchange,
            WatchlistSymbol.symbol == line.symbol,
        )
        .limit(1)
    )
    if membership and membership.instrument_token is not None:
        return membership.instrument_token
    return None


def _build_potential_trigger_row(
    line: TriggerLine,
    candles: list[HistoricalCandlePayload],
    prediction_proximity_percent: float,
) -> dict | None:
    if len(candles) < 4:
        return None

    latest_close = float(candles[-1].close)
    if line.line_type == "BUY" and latest_close >= line.line_price:
        return None
    if line.line_type == "SELL" and latest_close <= line.line_price:
        return None

    distance_percent = round(abs(line.line_price - latest_close) / max(line.line_price, 1.0) * 100, 4)
    if distance_percent > prediction_proximity_percent:
        return None

    recent_closes = [float(candle.close) for candle in candles[-4:]]
    distance_series = [abs(line.line_price - close) for close in recent_closes]
    toward_moves = sum(
        1
        for previous_distance, current_distance in zip(distance_series[:-1], distance_series[1:])
        if current_distance < previous_distance
    )
    if toward_moves < 2:
        return None

    directional_moves = sum(
        1
        for previous_close, current_close in zip(recent_closes[:-1], recent_closes[1:])
        if (current_close > previous_close if line.line_type == "BUY" else current_close < previous_close)
    )
    nearest_target = (
        line.nearest_daily_swing_high_target
        if line.line_type == "BUY"
        else line.nearest_daily_swing_low_target
    )
    readiness_score = round(
        ((max(prediction_proximity_percent - distance_percent, 0.0) / prediction_proximity_percent) * 70.0)
        + ((toward_moves / 3.0) * 20.0)
        + ((directional_moves / 3.0) * 10.0),
        1,
    )
    return {
        "exchange": line.exchange,
        "symbol": line.symbol,
        "line_type": line.line_type,
        "line_price": round(line.line_price, 2),
        "last_close": round(latest_close, 2),
        "distance_percent": distance_percent,
        "toward_moves": toward_moves,
        "directional_moves": directional_moves,
        "nearest_target": round(nearest_target, 2) if nearest_target is not None else None,
        "line_drawn_date": _serialize_date(line.line_drawn_date),
        "last_daily_candle_date": candles[-1].timestamp.date().isoformat(),
        "readiness_score": readiness_score,
    }


def _load_recent_daily_candles_from_db(
    db: Session,
    *,
    exchange: str,
    symbol: str,
    lookback: int,
) -> list[HistoricalCandlePayload]:
    rows = db.scalars(
        select(MarketCandle)
        .where(
            MarketCandle.exchange == exchange,
            MarketCandle.symbol == symbol,
            MarketCandle.timeframe == "day",
        )
        .order_by(desc(MarketCandle.candle_start))
        .limit(lookback)
    ).all()
    ordered_rows = list(reversed(rows))
    return [
        HistoricalCandlePayload(
            timestamp=row.candle_start,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in ordered_rows
    ]


def _load_zerodha_ltp_map(db: Session, symbols: list[tuple[str, str]]) -> dict[str, float]:
    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    if not symbols or not access_token:
        return {}

    quote_keys = sorted({f"{exchange}:{symbol}" for exchange, symbol in symbols})
    try:
        return ZerodhaApiClient(
            auth_service=ZerodhaAuthService(),
            access_token=access_token,
        ).fetch_ltp_quotes(quote_keys)
    except Exception:  # noqa: BLE001
        logger.warning("Unable to fetch Zerodha LTP quotes for potential line hits", exc_info=True)
        return {}


def _load_runtime_live_price_map() -> dict[str, dict]:
    try:
        snapshot = get_live_engine_runtime()
    except Exception:  # noqa: BLE001
        logger.warning("Unable to load live engine runtime snapshot for potential line hits", exc_info=True)
        return {}
    if not snapshot:
        return {}
    latest_prices = snapshot.get("latest_prices")
    return latest_prices if isinstance(latest_prices, dict) else {}


def _load_recent_3minute_close_map(
    db: Session,
    symbols: list[tuple[str, str]],
) -> dict[str, dict]:
    if not symbols:
        return {}

    symbol_keys = {(exchange, symbol) for exchange, symbol in symbols}
    recent_threshold = datetime.now(UTC) - timedelta(days=2)
    rows = db.scalars(
        select(MarketCandle)
        .where(MarketCandle.timeframe == "3minute", MarketCandle.candle_end >= recent_threshold)
        .order_by(desc(MarketCandle.candle_end))
        .limit(max(len(symbol_keys) * 12, 200))
    ).all()
    latest_map: dict[str, dict] = {}
    for row in rows:
        key_tuple = (row.exchange, row.symbol)
        if key_tuple not in symbol_keys:
            continue
        key = f"{row.exchange}:{row.symbol}"
        if key in latest_map:
            continue
        latest_map[key] = {
            "price": round(float(row.close), 2),
            "timestamp": row.candle_end.astimezone(UTC).isoformat(),
            "source": "3minute_close",
        }
    return latest_map


def _resolve_live_price_payload(
    *,
    quote_key: str,
    runtime_price_map: dict[str, dict],
    ltp_map: dict[str, float],
    three_minute_close_map: dict[str, dict],
    daily_close: float | None,
) -> dict:
    runtime_entry = runtime_price_map.get(quote_key)
    if isinstance(runtime_entry, dict) and runtime_entry.get("price") is not None:
        price = round(float(runtime_entry["price"]), 2)
        timestamp = runtime_entry.get("timestamp")
        return {
            "value": price,
            "source": "tick",
            "label": f"{price} · Tick",
            "timestamp": timestamp,
        }

    ltp_value = ltp_map.get(quote_key)
    if ltp_value is not None:
        price = round(float(ltp_value), 2)
        return {
            "value": price,
            "source": "zerodha_ltp",
            "label": f"{price} · Zerodha LTP",
            "timestamp": None,
        }

    candle_entry = three_minute_close_map.get(quote_key)
    if isinstance(candle_entry, dict) and candle_entry.get("price") is not None:
        price = round(float(candle_entry["price"]), 2)
        return {
            "value": price,
            "source": "3minute_close",
            "label": f"{price} · 3-min close",
            "timestamp": candle_entry.get("timestamp"),
        }

    if daily_close is not None:
        price = round(float(daily_close), 2)
        return {
            "value": price,
            "source": "daily_close",
            "label": f"{price} · Daily close",
            "timestamp": None,
        }

    return {
        "value": None,
        "source": None,
        "label": "Unavailable",
        "timestamp": None,
    }


def _serialize_broker_order(order: BrokerOrder, signal: TradingSignal | None = None) -> dict:
    return {
        "id": str(order.id),
        "signal_id": str(order.signal_id) if order.signal_id else None,
        "exchange": order.exchange,
        "symbol": order.symbol,
        "action": order.action,
        "quantity": order.quantity,
        "average_price": order.average_price,
        "mode": order.mode,
        "status": order.status,
        "broker_order_id": order.broker_order_id,
        "trigger_price": signal.trigger_price if signal else None,
        "entry_price": signal.entry_price if signal else None,
        "stop_loss": signal.stop_loss if signal else None,
        "target": signal.target if signal else None,
        "volume_ratio": signal.volume_ratio if signal else None,
        "created_at": _serialize_datetime(order.created_at),
        "updated_at": _serialize_datetime(order.updated_at),
    }


def _trade_history_summary(rows: list[dict]) -> dict:
    paper_rows = [row for row in rows if row["trade_mode"] == "PAPER"]
    live_rows = [row for row in rows if row["trade_mode"] == "LIVE"]
    return {
        "total_rows": len(rows),
        "paper_rows": len(paper_rows),
        "live_rows": len(live_rows),
        "paper_open": sum(1 for row in paper_rows if row["status"] == "OPEN"),
        "paper_closed": sum(1 for row in paper_rows if row["status"] != "OPEN"),
        "live_placed": sum(1 for row in live_rows if row["status"] == "PLACED"),
        "live_skipped_or_rejected": sum(1 for row in live_rows if row["status"] != "PLACED"),
        "paper_total_pnl": round(sum(float(row.get("pnl") or 0.0) for row in paper_rows), 2),
        "latest_activity_at": next(
            (
                row.get("activity_time")
                for row in rows
                if row.get("activity_time") is not None
            ),
            None,
        ),
    }


def _dashboard_trade_history_payload(db: Session, mode: str = "combined") -> dict:
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    watchlist_symbols: set[tuple[str, str]] = set()
    if selected_watchlist_id:
        watchlist_symbols = {
            (item.exchange, item.symbol)
            for item in db.scalars(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == selected_watchlist_id)).all()
        }

    signals = db.scalars(select(TradingSignal).order_by(desc(TradingSignal.created_at))).all()
    signal_map = {signal.id: signal for signal in signals}

    rows: list[dict] = []

    if mode in {"combined", "paper"}:
        paper_trades = db.scalars(select(PaperTrade).order_by(desc(PaperTrade.entry_time), desc(PaperTrade.created_at))).all()
        for trade in paper_trades:
            if watchlist_symbols and (trade.exchange, trade.symbol) not in watchlist_symbols:
                continue
            rows.append(
                {
                    "trade_mode": "PAPER",
                    "record_id": str(trade.id),
                    "signal_id": str(trade.signal_id) if trade.signal_id else None,
                    "exchange": trade.exchange,
                    "symbol": trade.symbol,
                    "action": trade.action,
                    "quantity": trade.quantity,
                    "reference_price": trade.simulated_entry_price,
                    "trigger_price": signal_map.get(trade.signal_id).trigger_price if trade.signal_id in signal_map else None,
                    "stop_loss": trade.simulated_stop_loss,
                    "target": trade.simulated_target,
                    "volume_ratio": signal_map.get(trade.signal_id).volume_ratio if trade.signal_id in signal_map else None,
                    "status": trade.status,
                    "order_ref": None,
                    "capital_used": trade.capital_used,
                    "risk_amount": trade.risk_amount,
                    "pnl": trade.pnl,
                    "pnl_percent": trade.pnl_percent,
                    "activity_time": _serialize_datetime(trade.entry_time or trade.created_at),
                    "updated_time": _serialize_datetime(trade.exit_time or trade.created_at),
                }
            )

    if mode in {"combined", "live"}:
        broker_orders = db.scalars(select(BrokerOrder).order_by(desc(BrokerOrder.created_at))).all()
        for order in broker_orders:
            if order.mode != "LIVE":
                continue
            if watchlist_symbols and (order.exchange, order.symbol) not in watchlist_symbols:
                continue
            signal = signal_map.get(order.signal_id) if order.signal_id else None
            rows.append(
                {
                    "trade_mode": "LIVE",
                    "record_id": str(order.id),
                    "signal_id": str(order.signal_id) if order.signal_id else None,
                    "exchange": order.exchange,
                    "symbol": order.symbol,
                    "action": order.action,
                    "quantity": order.quantity,
                    "reference_price": order.average_price or (signal.entry_price if signal else None),
                    "trigger_price": signal.trigger_price if signal else None,
                    "stop_loss": signal.stop_loss if signal else None,
                    "target": signal.target if signal else None,
                    "volume_ratio": signal.volume_ratio if signal else None,
                    "status": order.status,
                    "order_ref": order.broker_order_id,
                    "capital_used": signal.capital_used if signal else None,
                    "risk_amount": signal.risk_amount if signal else None,
                    "pnl": None,
                    "pnl_percent": None,
                    "activity_time": _serialize_datetime(order.created_at),
                    "updated_time": _serialize_datetime(order.updated_at),
                }
            )

    rows.sort(key=lambda item: item.get("activity_time") or "", reverse=True)
    return {
        "selected_watchlist": {
            "id": str(selected_watchlist.id),
            "name": selected_watchlist.name,
            "exchange": selected_watchlist.exchange,
        }
        if selected_watchlist
        else None,
        "mode": mode,
        "summary": _trade_history_summary(rows),
        "rows": rows,
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
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Potential Line Hits</h2>
          <p class="panel-copy">This shortlist highlights active support and resistance lines that may be tested soon, using the latest daily close together with recent daily closing movement toward the line.</p>
        </div>
      </div>
      <div id="potentialLineHitSummary" class="table-toolbar-copy" style="margin-bottom: 14px;">Loading potential line-hit candidates...</div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p class="table-toolbar-copy">Rows appear only when an active line remains within the configured prediction threshold and the recent daily closes have been moving toward that level.</p>
          <div class="table-toolbar-actions">
            <button id="refreshPotentialLineHitsButton" class="secondary table-toggle" type="button">Refresh Table</button>
            <button id="potentialLineHitsToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
          </div>
        </div>
        <div id="potentialLineHitsFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 1320px;">
          <table id="potentialLineHitsTable"></table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Trade History</h2>
          <p class="panel-copy">Review simulated and live execution history from one place. Switch between paper results, live Zerodha orders, or a combined view for later analytics and model training.</p>
        </div>
      </div>
      <div id="tradeHistorySummary" class="table-toolbar-copy" style="margin-bottom: 14px;">Loading trade history...</div>
      <div class="table-shell">
        <div class="table-toolbar">
          <p class="table-toolbar-copy">Trade history stays collapsed by default so long lists remain readable while still supporting full horizontal inspection when expanded.</p>
          <div class="table-toolbar-actions">
            <button id="tradeHistoryCombinedButton" class="primary table-toggle" type="button">Combined</button>
            <button id="tradeHistoryPaperButton" class="secondary table-toggle" type="button">Paper</button>
            <button id="tradeHistoryLiveButton" class="secondary table-toggle" type="button">Live</button>
            <button id="refreshTradeHistoryButton" class="secondary table-toggle" type="button">Refresh Table</button>
            <button id="tradeHistoryToggle" class="secondary table-toggle hidden" type="button" aria-expanded="false">Expand table</button>
          </div>
        </div>
        <div id="tradeHistoryFrame" class="table-scroll-frame is-collapsed" style="--table-min-width: 1540px;">
          <table id="tradeHistoryTable"></table>
        </div>
      </div>
    </section>
    """
    script = """
    let latestOverview = null;
    let currentTradeHistoryMode = "combined";
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
    const syncPotentialLineHitPreview = bindCollapsibleTable({
      buttonId: "potentialLineHitsToggle",
      frameId: "potentialLineHitsFrame",
      tableId: "potentialLineHitsTable",
      previewRows: 8,
    });
    const syncTradeHistoryPreview = bindCollapsibleTable({
      buttonId: "tradeHistoryToggle",
      frameId: "tradeHistoryFrame",
      tableId: "tradeHistoryTable",
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
          ? `Current tuning: candle lookback ${tuning.daily_candle_lookback}, max gap ${tuning.max_gap_percent}%, swing window ${tuning.swing_window}, minimum swing distance ${tuning.min_swing_distance} candles, prediction threshold ${tuning.prediction_proximity_percent}%.`
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
        ["Symbol", "Line Type", "Breakout", "Line Drawn Date", "Swing 1", "Swing 2", "Gap %", "Nearest Target"],
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
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter daily structure symbols" } },
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
        ["Symbol", "Line Type", "Breakout", "Event", "Breakout Time", "Prev Volume", "Breakout Volume", "Required", "Ratio", "Passed", "Entry", "Stop Loss", "Target", "Signal", "Status"],
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
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter breakout symbols" } },
      );
      syncBreakoutReviewPreview();
      return review;
    }

    function renderPotentialLineHitSummary(payload) {
      const element = document.getElementById("potentialLineHitSummary");
      if (!payload || !payload.summary) {
        element.textContent = "No potential line-hit candidates are available yet.";
        element.className = "table-toolbar-copy";
        return;
      }
      if (payload.summary.error_message) {
        element.textContent = payload.summary.error_message;
        element.className = "table-toolbar-copy warn";
        return;
      }
      const watchlistLabel = payload.selected_watchlist ? `${payload.selected_watchlist.name} · ` : "";
      element.textContent = `${watchlistLabel}${payload.summary.total_candidates} candidate rows · threshold ${payload.summary.prediction_proximity_percent}% · ${payload.summary.symbols_covered} symbols covered · latest daily close ${payload.summary.latest_daily_candle_date || "not available"}`;
      element.className = "table-toolbar-copy";
    }

    async function loadPotentialLineHits() {
      const payload = await apiGet("/dashboard/reports/potential-line-hits");
      renderPotentialLineHitSummary(payload);
      renderTable(
        document.getElementById("potentialLineHitsTable"),
        ["Symbol", "Line Type", "Breakout", "Last Close", "Live Price", "Distance %", "Toward Moves", "Nearest Target", "Line Drawn", "Readiness"],
        payload.rows.map((item) => [
          `${item.exchange}:${item.symbol}`,
          `<span class="badge">${item.line_type}</span>`,
          item.line_price ?? "N/A",
          item.last_close ?? "N/A",
          item.current_realtime_label || "Unavailable",
          item.distance_percent ?? "N/A",
          item.toward_moves ?? "N/A",
          item.nearest_target ?? "N/A",
          item.line_drawn_date || "N/A",
          item.readiness_score ?? "N/A",
        ]),
        { symbolFilter: { enabled: true, columnIndex: 0, placeholder: "Filter potential-hit symbols" } },
      );
      syncPotentialLineHitPreview();
      return payload;
    }

    function renderTradeHistorySummary(payload) {
      const element = document.getElementById("tradeHistorySummary");
      if (!payload || !payload.summary) {
        element.textContent = "No trade history is available yet.";
        element.className = "table-toolbar-copy";
        return;
      }
      const watchlistLabel = payload.selected_watchlist ? `${payload.selected_watchlist.name} · ` : "";
      const modeLabel = payload.mode ? `${payload.mode.toUpperCase()} view · ` : "";
      element.textContent = `${watchlistLabel}${modeLabel}${payload.summary.total_rows} rows · ${payload.summary.paper_rows} paper · ${payload.summary.live_rows} live · paper PnL ${payload.summary.paper_total_pnl} · latest activity ${payload.summary.latest_activity_at ? new Date(payload.summary.latest_activity_at).toLocaleString() : "not recorded yet"}`;
      element.className = "table-toolbar-copy";
    }

    function setTradeHistoryMode(mode) {
      currentTradeHistoryMode = mode;
      const mapping = {
        combined: "tradeHistoryCombinedButton",
        paper: "tradeHistoryPaperButton",
        live: "tradeHistoryLiveButton",
      };
      Object.entries(mapping).forEach(([key, id]) => {
        const button = document.getElementById(id);
        button.className = `${key === mode ? "primary" : "secondary"} table-toggle`;
      });
    }

    async function loadTradeHistory(mode = currentTradeHistoryMode) {
      setTradeHistoryMode(mode);
      const payload = await apiGet(`/dashboard/reports/trade-history?mode=${encodeURIComponent(mode)}`);
      renderTradeHistorySummary(payload);
      renderTable(
        document.getElementById("tradeHistoryTable"),
        ["Mode", "Symbol", "Action", "Reference Price", "Trigger", "Stop Loss", "Target", "Qty", "Volume Ratio", "Status", "Capital Used", "Risk", "PnL", "Order Ref", "Activity Time"],
        payload.rows.map((item) => [
          `<span class="badge ${item.trade_mode === "LIVE" ? "warn" : ""}">${item.trade_mode}</span>`,
          `${item.exchange}:${item.symbol}`,
          item.action,
          item.reference_price ?? "N/A",
          item.trigger_price ?? "N/A",
          item.stop_loss ?? "N/A",
          item.target ?? "N/A",
          item.quantity ?? "N/A",
          item.volume_ratio ?? "N/A",
          item.status,
          item.capital_used ?? "N/A",
          item.risk_amount ?? "N/A",
          item.pnl ?? "N/A",
          item.order_ref ?? "N/A",
          item.activity_time ? new Date(item.activity_time).toLocaleString() : "N/A",
        ]),
        { symbolFilter: { enabled: true, columnIndex: 1, placeholder: "Filter trade symbols" } },
      );
      syncTradeHistoryPreview();
      return payload;
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
        await Promise.all([loadDailyLineReview(), loadBreakoutReview(), loadPotentialLineHits(), loadTradeHistory("combined")]);
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

    document.getElementById("refreshPotentialLineHitsButton").addEventListener("click", async () => {
      try {
        await loadPotentialLineHits();
      } catch (error) {
        document.getElementById("potentialLineHitSummary").textContent = `Unable to load potential line-hit review: ${error.message}`;
      }
    });

    document.getElementById("tradeHistoryCombinedButton").addEventListener("click", async () => {
      try {
        await loadTradeHistory("combined");
      } catch (error) {
        document.getElementById("tradeHistorySummary").textContent = `Unable to load combined trade history: ${error.message}`;
      }
    });

    document.getElementById("tradeHistoryPaperButton").addEventListener("click", async () => {
      try {
        await loadTradeHistory("paper");
      } catch (error) {
        document.getElementById("tradeHistorySummary").textContent = `Unable to load paper trade history: ${error.message}`;
      }
    });

    document.getElementById("tradeHistoryLiveButton").addEventListener("click", async () => {
      try {
        await loadTradeHistory("live");
      } catch (error) {
        document.getElementById("tradeHistorySummary").textContent = `Unable to load live trade history: ${error.message}`;
      }
    });

    document.getElementById("refreshTradeHistoryButton").addEventListener("click", async () => {
      try {
        await loadTradeHistory(currentTradeHistoryMode);
      } catch (error) {
        document.getElementById("tradeHistorySummary").textContent = `Unable to refresh trade history: ${error.message}`;
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
                "prediction_proximity_percent": runtime_settings.prediction_proximity_percent,
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
    auth = ZerodhaAuthService()
    access_token = get_current_zerodha_access_token(db) or settings.zerodha_access_token
    if not auth.has_credentials():
        raise HTTPException(status_code=503, detail="Configure Zerodha credentials before refreshing the market structure table")
    if not access_token:
        raise HTTPException(status_code=503, detail="Connect Zerodha before refreshing the market structure table")
    current_session = get_current_zerodha_session(db)
    if current_session is not None and current_session.access_token_expires_at and current_session.access_token_expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=503, detail="Zerodha session has expired. Reconnect Zerodha before refreshing the market structure table")

    scanner = _build_manual_scan_scanner(db)
    try:
        execution = scanner.run(
            db,
            watchlist_id=selected_watchlist_id,
            scan_date=datetime.now(UTC).date(),
            dry_run=False,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Unable to refresh the market structure table: {exc}") from exc
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


@router.get("/dashboard/reports/potential-line-hits")
def dashboard_potential_line_hits(db: Session = Depends(get_db)) -> dict:
    selected_watchlist, selected_watchlist_id = _selected_watchlist_filter(db)
    runtime_settings = ensure_settings(db)
    prediction_threshold = round(float(getattr(runtime_settings, "prediction_proximity_percent", 2.0)), 2)

    if selected_watchlist is None or selected_watchlist_id is None:
        return {
            "selected_watchlist": None,
            "summary": {
                "prediction_proximity_percent": prediction_threshold,
                "total_candidates": 0,
                "symbols_covered": 0,
                "latest_daily_candle_date": None,
                "error_message": None,
            },
            "rows": [],
        }

    active_lines = db.scalars(
        select(TriggerLine)
        .where(
            TriggerLine.watchlist_id == selected_watchlist_id,
            TriggerLine.line_status == "ACTIVE",
        )
        .order_by(TriggerLine.symbol, TriggerLine.line_type, desc(TriggerLine.updated_at))
    ).all()
    if not active_lines:
        return {
            "selected_watchlist": {
                "id": str(selected_watchlist.id),
                "name": selected_watchlist.name,
                "exchange": selected_watchlist.exchange,
            },
            "summary": {
                "prediction_proximity_percent": prediction_threshold,
                "total_candidates": 0,
                "symbols_covered": 0,
                "latest_daily_candle_date": None,
                "error_message": None,
            },
            "rows": [],
        }

    symbol_keys = [(line.exchange, line.symbol) for line in active_lines]
    runtime_price_map = _load_runtime_live_price_map()
    ltp_map = _load_zerodha_ltp_map(db, symbol_keys)
    three_minute_close_map = _load_recent_3minute_close_map(db, symbol_keys)
    candle_cache: dict[tuple[str, str], list[HistoricalCandlePayload]] = {}
    rows: list[dict] = []
    latest_daily_candle_date = None

    for line in active_lines:
        cache_key = (line.exchange, line.symbol)
        if cache_key not in candle_cache:
            candle_cache[cache_key] = _load_recent_daily_candles_from_db(
                db,
                exchange=line.exchange,
                symbol=line.symbol,
                lookback=max(6, min(runtime_settings.daily_candle_lookback, 12)),
            )
        candles = candle_cache[cache_key]
        row = _build_potential_trigger_row(line, candles, prediction_threshold)
        if row is None:
            continue
        quote_key = f"{line.exchange}:{line.symbol}"
        live_price_payload = _resolve_live_price_payload(
            quote_key=quote_key,
            runtime_price_map=runtime_price_map,
            ltp_map=ltp_map,
            three_minute_close_map=three_minute_close_map,
            daily_close=row.get("last_close"),
        )
        row["current_realtime_value"] = live_price_payload["value"]
        row["current_realtime_source"] = live_price_payload["source"]
        row["current_realtime_label"] = live_price_payload["label"]
        row["current_realtime_timestamp"] = live_price_payload["timestamp"]
        latest_daily_candle_date = row["last_daily_candle_date"] if latest_daily_candle_date is None else max(latest_daily_candle_date, row["last_daily_candle_date"])
        rows.append(row)

    if not rows and not any(candle_cache.values()):
        return {
            "selected_watchlist": {
                "id": str(selected_watchlist.id),
                "name": selected_watchlist.name,
                "exchange": selected_watchlist.exchange,
            },
            "summary": {
                "prediction_proximity_percent": prediction_threshold,
                "total_candidates": 0,
                "symbols_covered": 0,
                "latest_daily_candle_date": None,
                "error_message": "No stored daily candle history is available yet. Run the daily market scan once to populate the database, then refresh this table.",
            },
            "rows": [],
        }

    rows.sort(key=lambda item: (item["distance_percent"], -item["readiness_score"], item["symbol"], item["line_type"]))
    return {
        "selected_watchlist": {
            "id": str(selected_watchlist.id),
            "name": selected_watchlist.name,
            "exchange": selected_watchlist.exchange,
        },
        "summary": {
            "prediction_proximity_percent": prediction_threshold,
            "total_candidates": len(rows),
            "symbols_covered": len({(row["exchange"], row["symbol"]) for row in rows}),
            "latest_daily_candle_date": latest_daily_candle_date,
            "error_message": None,
        },
        "rows": rows,
    }


@router.get("/dashboard/reports/trade-history")
def dashboard_trade_history(
    mode: str = "combined",
    db: Session = Depends(get_db),
) -> dict:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"combined", "paper", "live"}:
        raise HTTPException(status_code=422, detail="Mode must be one of combined, paper, or live")
    return _dashboard_trade_history_payload(db, mode=normalized_mode)
