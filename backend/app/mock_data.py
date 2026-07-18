import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import (
    BreakoutEvent,
    PaperTrade,
    PaperTradingSetting,
    TradingSignal,
    TriggerLine,
    Watchlist,
    WatchlistSymbol,
)


logger = logging.getLogger(__name__)
settings = get_settings()
MOCK_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "mock_data"


def _read_json(filename: str) -> dict[str, Any]:
    with (MOCK_DATA_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(value)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _merge_watchlists(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            Watchlist(
                id=_parse_uuid(row["id"]),
                name=row["name"],
                description=row.get("description"),
                exchange=row.get("exchange", "NSE"),
                created_at=_parse_datetime(row.get("created_at")),
                updated_at=_parse_datetime(row.get("updated_at")),
            )
        )


def _merge_watchlist_symbols(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            WatchlistSymbol(
                id=_parse_uuid(row["id"]),
                watchlist_id=_parse_uuid(row["watchlist_id"]),
                exchange=row.get("exchange", "NSE"),
                symbol=row["symbol"],
                company_name=row.get("company_name"),
                price_filter_min=row.get("price_filter_min"),
                price_filter_max=row.get("price_filter_max"),
                is_active=row.get("is_active", True),
                instrument_token=row.get("instrument_token"),
                created_at=_parse_datetime(row.get("created_at")),
            )
        )


def _merge_trigger_lines(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            TriggerLine(
                id=_parse_uuid(row["id"]),
                watchlist_id=_parse_uuid(row.get("watchlist_id")),
                exchange=row.get("exchange", "NSE"),
                symbol=row["symbol"],
                source=row.get("source", "ZERODHA"),
                line_type=row["line_type"],
                line_price=row["line_price"],
                level_key=row.get("level_key"),
                line_status=row.get("line_status", "ACTIVE"),
                is_untouched=row.get("is_untouched", True),
                line_drawn_date=_parse_date(row.get("line_drawn_date")),
                source_timeframe=row.get("source_timeframe", "Daily"),
                lookback_candles=row.get("lookback_candles"),
                max_gap_percent_used=row.get("max_gap_percent_used"),
                min_swing_distance_used=row.get("min_swing_distance_used"),
                swing_high_1_price=row.get("swing_high_1_price"),
                swing_high_1_date=_parse_date(row.get("swing_high_1_date")),
                swing_high_2_price=row.get("swing_high_2_price"),
                swing_high_2_date=_parse_date(row.get("swing_high_2_date")),
                higher_swing_high_price=row.get("higher_swing_high_price"),
                lower_swing_high_price=row.get("lower_swing_high_price"),
                swing_low_1_price=row.get("swing_low_1_price"),
                swing_low_1_date=_parse_date(row.get("swing_low_1_date")),
                swing_low_2_price=row.get("swing_low_2_price"),
                swing_low_2_date=_parse_date(row.get("swing_low_2_date")),
                lower_swing_low_price=row.get("lower_swing_low_price"),
                higher_swing_low_price=row.get("higher_swing_low_price"),
                swing_gap_percent=row.get("swing_gap_percent"),
                nearest_daily_swing_high_target=row.get("nearest_daily_swing_high_target"),
                nearest_daily_swing_low_target=row.get("nearest_daily_swing_low_target"),
                last_validated_at=_parse_datetime(row.get("last_validated_at")),
                invalidated_at=_parse_datetime(row.get("invalidated_at")),
                triggered_at=_parse_datetime(row.get("triggered_at")),
                notes=row.get("notes"),
                created_at=_parse_datetime(row.get("created_at")),
                updated_at=_parse_datetime(row.get("updated_at")),
            )
        )


def _merge_breakout_events(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            BreakoutEvent(
                id=_parse_uuid(row["id"]),
                trigger_line_id=_parse_uuid(row.get("trigger_line_id")),
                market_candle_id=_parse_uuid(row.get("market_candle_id")),
                exchange=row.get("exchange", "NSE"),
                symbol=row["symbol"],
                event_type=row["event_type"],
                event_time=_parse_datetime(row["event_time"]),
                breakout_or_breakdown_price=row.get("breakout_or_breakdown_price"),
                breakout_candle_high=row.get("breakout_candle_high"),
                breakout_candle_low=row.get("breakout_candle_low"),
                breakout_candle_volume=row.get("breakout_candle_volume"),
                previous_candle_volume=row.get("previous_candle_volume"),
                volume_ratio=row.get("volume_ratio"),
                volume_condition_required=row.get("volume_condition_required", True),
                volume_condition_passed=row.get("volume_condition_passed", False),
                entry_price=row.get("entry_price"),
                stop_loss=row.get("stop_loss"),
                target=row.get("target"),
                signal_generated=row.get("signal_generated", False),
                status=row.get("status", "PASSED"),
                created_at=_parse_datetime(row.get("created_at")),
            )
        )


def _merge_signals(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            TradingSignal(
                id=_parse_uuid(row["id"]),
                exchange=row.get("exchange", "NSE"),
                symbol=row["symbol"],
                action=row["action"],
                source=row.get("source", "ZERODHA"),
                watchlist_id=_parse_uuid(row.get("watchlist_id")),
                trigger_line_id=_parse_uuid(row.get("trigger_line_id")),
                breakout_event_id=_parse_uuid(row.get("breakout_event_id")),
                scan_execution_id=_parse_uuid(row.get("scan_execution_id")),
                trigger_price=row.get("trigger_price"),
                entry_price=row.get("entry_price"),
                stop_loss=row.get("stop_loss"),
                target=row.get("target"),
                quantity=row.get("quantity"),
                capital_used=row.get("capital_used"),
                risk_amount=row.get("risk_amount"),
                volume_ratio=row.get("volume_ratio"),
                timeframe=row.get("timeframe"),
                strategy=row.get("strategy"),
                dedupe_key=row.get("dedupe_key"),
                raw_payload=row.get("raw_payload", {}),
                status=row.get("status", "PROCESSED"),
                processed_at=_parse_datetime(row.get("processed_at")),
                notification_status=row.get("notification_status", "SKIPPED"),
                error_message=row.get("error_message"),
                created_at=_parse_datetime(row.get("created_at")),
            )
        )


def _merge_paper_settings(db: Session, row: dict[str, Any]) -> None:
    db.merge(
        PaperTradingSetting(
            id=_parse_uuid(row["id"]),
            starting_capital=row["starting_capital"],
            capital_per_trade=row["capital_per_trade"],
            fixed_quantity=row.get("fixed_quantity"),
            risk_per_trade=row["risk_per_trade"],
            brokerage_estimate=row["brokerage_estimate"],
            slippage_estimate=row["slippage_estimate"],
            max_trades_per_day=row["max_trades_per_day"],
            max_daily_loss=row["max_daily_loss"],
            default_quantity_mode=row.get("default_quantity_mode", "RISK_BASED"),
            buy_volume_multiplier=row["buy_volume_multiplier"],
            sell_volume_multiplier=row["sell_volume_multiplier"],
            entry_buffer_ticks=row["entry_buffer_ticks"],
            stop_loss_buffer_ticks=row["stop_loss_buffer_ticks"],
            created_at=_parse_datetime(row.get("created_at")),
            updated_at=_parse_datetime(row.get("updated_at")),
        )
    )


def _merge_paper_trades(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.merge(
            PaperTrade(
                id=_parse_uuid(row["id"]),
                signal_id=_parse_uuid(row.get("signal_id")),
                trigger_line_id=_parse_uuid(row.get("trigger_line_id")),
                exchange=row.get("exchange", "NSE"),
                symbol=row["symbol"],
                action=row["action"],
                simulated_entry_price=row.get("simulated_entry_price"),
                simulated_stop_loss=row.get("simulated_stop_loss"),
                simulated_target=row.get("simulated_target"),
                quantity=row.get("quantity", 0),
                capital_used=row.get("capital_used", 0.0),
                risk_amount=row.get("risk_amount", 0.0),
                execution_mode=row.get("execution_mode", "PAPER"),
                status=row.get("status", "OPEN"),
                simulated_exit_price=row.get("simulated_exit_price"),
                pnl=row.get("pnl"),
                pnl_percent=row.get("pnl_percent"),
                entry_time=_parse_datetime(row.get("entry_time")),
                exit_time=_parse_datetime(row.get("exit_time")),
                created_at=_parse_datetime(row.get("created_at")),
            )
        )


def seed_mock_data_if_enabled() -> None:
    if not settings.mock_data:
        return

    if not MOCK_DATA_DIR.exists():
        logger.warning("MOCK_DATA is enabled but %s does not exist", MOCK_DATA_DIR)
        return

    logger.info("MOCK_DATA enabled; seeding dashboard data from JSON files")
    dashboard_seed = _read_json("dashboard_seed.json")
    signal_seed = _read_json("trading_signals_seed.json")

    with SessionLocal() as db:
        _merge_watchlists(db, dashboard_seed.get("watchlists", []))
        db.commit()
        _merge_watchlist_symbols(db, dashboard_seed.get("watchlist_symbols", []))
        db.commit()
        _merge_trigger_lines(db, dashboard_seed.get("trigger_lines", []))
        db.commit()
        _merge_breakout_events(db, dashboard_seed.get("breakout_events", []))
        db.commit()
        _merge_paper_settings(db, dashboard_seed["paper_trading_settings"])
        db.commit()
        _merge_signals(db, signal_seed.get("trading_signals", []))
        db.commit()
        _merge_paper_trades(db, dashboard_seed.get("paper_trades", []))
        db.commit()
