import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Instrument, ScanExecution, TriggerLine, WatchlistSymbol
from backend.app.schemas import HistoricalCandlePayload, SwingPointPayload, TriggerLineCandidatePayload
from backend.app.services.watchlists import get_selected_watchlist
from backend.app.services.zerodha import HistoricalCandleProvider


logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class TriggerLineUpsertSummary:
    created: int = 0
    updated: int = 0


class SwingDetector:
    def __init__(self, window: int | None = None) -> None:
        self.window = window or settings.swing_window

    def detect(self, candles: list[HistoricalCandlePayload]) -> tuple[list[SwingPointPayload], list[SwingPointPayload]]:
        swing_highs: list[SwingPointPayload] = []
        swing_lows: list[SwingPointPayload] = []
        for index in range(self.window, len(candles) - self.window):
            current = candles[index]
            previous = candles[index - self.window : index]
            following = candles[index + 1 : index + 1 + self.window]

            if previous and following and all(current.high > candle.high for candle in previous + following):
                swing_highs.append(
                    SwingPointPayload(
                        kind="HIGH",
                        index=index,
                        price=current.high,
                        candle_date=current.timestamp.date(),
                    )
                )
            if previous and following and all(current.low < candle.low for candle in previous + following):
                swing_lows.append(
                    SwingPointPayload(
                        kind="LOW",
                        index=index,
                        price=current.low,
                        candle_date=current.timestamp.date(),
                    )
                )
        return swing_highs, swing_lows


class TargetResolver:
    def resolve_buy_target(self, line_price: float, swing_highs: list[SwingPointPayload], candles: list[HistoricalCandlePayload]) -> float:
        higher = [point.price for point in swing_highs if point.price > line_price]
        return min(higher) if higher else max(candle.high for candle in candles)

    def resolve_sell_target(self, line_price: float, swing_lows: list[SwingPointPayload], candles: list[HistoricalCandlePayload]) -> float:
        lower = [point.price for point in swing_lows if point.price < line_price]
        return max(lower) if lower else min(candle.low for candle in candles)


class UntouchedLevelValidator:
    def __init__(self, target_resolver: TargetResolver | None = None) -> None:
        self.target_resolver = target_resolver or TargetResolver()

    def build_candidates(
        self,
        symbol: str,
        exchange: str,
        candles: list[HistoricalCandlePayload],
        swing_highs: list[SwingPointPayload],
        swing_lows: list[SwingPointPayload],
    ) -> list[TriggerLineCandidatePayload]:
        candidates: list[TriggerLineCandidatePayload] = []
        candidates.extend(self._build_buy_candidates(symbol, exchange, candles, swing_highs))
        candidates.extend(self._build_sell_candidates(symbol, exchange, candles, swing_lows))
        return candidates

    def _gap_percent(self, first_price: float, second_price: float) -> float:
        anchor = max(first_price, second_price, 1.0)
        return round(abs(first_price - second_price) / anchor * 100, 4)

    def _build_buy_candidates(
        self,
        symbol: str,
        exchange: str,
        candles: list[HistoricalCandlePayload],
        swing_highs: list[SwingPointPayload],
    ) -> list[TriggerLineCandidatePayload]:
        candidates: list[TriggerLineCandidatePayload] = []
        for first, second in zip(swing_highs, swing_highs[1:]):
            gap_percent = self._gap_percent(first.price, second.price)
            distance = second.index - first.index
            line_price = max(first.price, second.price)
            later_candles = candles[second.index + 1 :]
            untouched = all(candle.high < line_price for candle in later_candles)
            if gap_percent > settings.max_gap_percent or distance < settings.min_swing_distance or not untouched:
                continue

            candidates.append(
                TriggerLineCandidatePayload(
                    symbol=symbol,
                    exchange=exchange,
                    line_type="BUY",
                    line_price=line_price,
                    level_key=f"{exchange}:{symbol}:BUY:{line_price:.4f}:{second.candle_date.isoformat()}",
                    line_drawn_date=second.candle_date,
                    lookback_candles=settings.daily_candle_lookback,
                    max_gap_percent_used=settings.max_gap_percent,
                    min_swing_distance_used=settings.min_swing_distance,
                    swing_gap_percent=gap_percent,
                    swing_high_1_price=first.price,
                    swing_high_1_date=first.candle_date,
                    swing_high_2_price=second.price,
                    swing_high_2_date=second.candle_date,
                    higher_swing_high_price=max(first.price, second.price),
                    lower_swing_high_price=min(first.price, second.price),
                    nearest_daily_swing_high_target=self.target_resolver.resolve_buy_target(
                        line_price,
                        swing_highs,
                        candles,
                    ),
                )
            )
        return candidates

    def _build_sell_candidates(
        self,
        symbol: str,
        exchange: str,
        candles: list[HistoricalCandlePayload],
        swing_lows: list[SwingPointPayload],
    ) -> list[TriggerLineCandidatePayload]:
        candidates: list[TriggerLineCandidatePayload] = []
        for first, second in zip(swing_lows, swing_lows[1:]):
            gap_percent = self._gap_percent(first.price, second.price)
            distance = second.index - first.index
            line_price = min(first.price, second.price)
            later_candles = candles[second.index + 1 :]
            untouched = all(candle.low > line_price for candle in later_candles)
            if gap_percent > settings.max_gap_percent or distance < settings.min_swing_distance or not untouched:
                continue

            candidates.append(
                TriggerLineCandidatePayload(
                    symbol=symbol,
                    exchange=exchange,
                    line_type="SELL",
                    line_price=line_price,
                    level_key=f"{exchange}:{symbol}:SELL:{line_price:.4f}:{second.candle_date.isoformat()}",
                    line_drawn_date=second.candle_date,
                    lookback_candles=settings.daily_candle_lookback,
                    max_gap_percent_used=settings.max_gap_percent,
                    min_swing_distance_used=settings.min_swing_distance,
                    swing_gap_percent=gap_percent,
                    swing_low_1_price=first.price,
                    swing_low_1_date=first.candle_date,
                    swing_low_2_price=second.price,
                    swing_low_2_date=second.candle_date,
                    lower_swing_low_price=min(first.price, second.price),
                    higher_swing_low_price=max(first.price, second.price),
                    nearest_daily_swing_low_target=self.target_resolver.resolve_sell_target(
                        line_price,
                        swing_lows,
                        candles,
                    ),
                )
            )
        return candidates


class TriggerLineManager:
    def upsert_candidates(
        self,
        db: Session,
        candidates: Iterable[TriggerLineCandidatePayload],
        watchlist_symbol: WatchlistSymbol,
        scan_execution_id,
        dry_run: bool = False,
    ) -> TriggerLineUpsertSummary:
        now = datetime.now(UTC)
        rows = list(candidates)
        summary = TriggerLineUpsertSummary()
        candidate_keys = {row.level_key for row in rows}

        existing_lines = db.scalars(
            select(TriggerLine).where(
                TriggerLine.symbol == watchlist_symbol.symbol,
                TriggerLine.exchange == watchlist_symbol.exchange,
                TriggerLine.source == "ZERODHA",
            )
        ).all()
        existing_by_key = {line.level_key: line for line in existing_lines if line.level_key}

        for row in rows:
            line = existing_by_key.get(row.level_key)
            if line is None:
                line = TriggerLine(
                    watchlist_id=watchlist_symbol.watchlist_id,
                    instrument_id=watchlist_symbol.instrument_id,
                    scan_execution_id=scan_execution_id,
                    exchange=row.exchange,
                    symbol=row.symbol,
                    source="ZERODHA",
                    line_type=row.line_type,
                    line_price=row.line_price,
                    level_key=row.level_key,
                    line_drawn_date=row.line_drawn_date,
                    source_timeframe="Daily",
                )
                summary.created += 1
                if not dry_run:
                    db.add(line)
            else:
                summary.updated += 1

            line.watchlist_id = watchlist_symbol.watchlist_id
            line.instrument_id = watchlist_symbol.instrument_id
            line.scan_execution_id = scan_execution_id
            line.line_status = "ACTIVE"
            line.is_untouched = True
            line.line_price = row.line_price
            line.line_drawn_date = row.line_drawn_date
            line.lookback_candles = row.lookback_candles
            line.max_gap_percent_used = row.max_gap_percent_used
            line.min_swing_distance_used = row.min_swing_distance_used
            line.swing_gap_percent = row.swing_gap_percent
            line.swing_high_1_price = row.swing_high_1_price
            line.swing_high_1_date = row.swing_high_1_date
            line.swing_high_2_price = row.swing_high_2_price
            line.swing_high_2_date = row.swing_high_2_date
            line.higher_swing_high_price = row.higher_swing_high_price
            line.lower_swing_high_price = row.lower_swing_high_price
            line.swing_low_1_price = row.swing_low_1_price
            line.swing_low_1_date = row.swing_low_1_date
            line.swing_low_2_price = row.swing_low_2_price
            line.swing_low_2_date = row.swing_low_2_date
            line.lower_swing_low_price = row.lower_swing_low_price
            line.higher_swing_low_price = row.higher_swing_low_price
            line.nearest_daily_swing_high_target = row.nearest_daily_swing_high_target
            line.nearest_daily_swing_low_target = row.nearest_daily_swing_low_target
            line.last_validated_at = now
            line.invalidated_at = None
            line.notes = row.notes

        for line in existing_lines:
            if line.line_status == "ACTIVE" and line.level_key not in candidate_keys:
                line.line_status = "EXPIRED"
                line.is_untouched = False
                line.invalidated_at = now

        if not dry_run:
            db.flush()
        return summary


class DailyMarketScanner:
    def __init__(
        self,
        provider: HistoricalCandleProvider | None = None,
        swing_detector: SwingDetector | None = None,
        validator: UntouchedLevelValidator | None = None,
        trigger_line_manager: TriggerLineManager | None = None,
    ) -> None:
        self.provider = provider or HistoricalCandleProvider()
        self.swing_detector = swing_detector or SwingDetector()
        self.validator = validator or UntouchedLevelValidator()
        self.trigger_line_manager = trigger_line_manager or TriggerLineManager()

    def run(self, db: Session, watchlist_id=None, scan_date: date | None = None, dry_run: bool = False) -> ScanExecution:
        if watchlist_id is None:
            selected_watchlist = get_selected_watchlist(db)
            watchlist_id = selected_watchlist.id if selected_watchlist is not None else None

        execution = ScanExecution(
            id=uuid.uuid4(),
            scan_name="daily_market_scan",
            scan_date=scan_date or datetime.now(UTC).date(),
            status="RUNNING",
            symbols_scanned=0,
            trigger_lines_created=0,
            trigger_lines_updated=0,
            started_at=datetime.now(UTC),
        )
        if not dry_run:
            db.add(execution)
            db.flush()

        query = select(WatchlistSymbol).where(WatchlistSymbol.is_active.is_(True))
        if watchlist_id is not None:
            query = query.where(WatchlistSymbol.watchlist_id == watchlist_id)
        symbols = db.scalars(query.order_by(WatchlistSymbol.symbol)).all()
        execution.symbols_scanned = len(symbols)

        try:
            for symbol in symbols:
                instrument_token = symbol.instrument_token
                if instrument_token is None and symbol.instrument_id is not None:
                    instrument = db.get(Instrument, symbol.instrument_id)
                    instrument_token = instrument.instrument_token if instrument else None
                if instrument_token is None:
                    logger.warning("Skipping %s because no instrument token is linked", symbol.symbol)
                    continue

                candles = self.provider.fetch_last_n_completed_daily_candles(
                    symbol.symbol,
                    instrument_token,
                    settings.daily_candle_lookback,
                )
                if len(candles) < (settings.swing_window * 2) + 1:
                    logger.info("Skipping %s because only %s candles are available", symbol.symbol, len(candles))
                    continue

                swing_highs, swing_lows = self.swing_detector.detect(candles)
                candidates = self.validator.build_candidates(
                    symbol.symbol,
                    symbol.exchange,
                    candles,
                    swing_highs,
                    swing_lows,
                )
                summary = self.trigger_line_manager.upsert_candidates(
                    db,
                    candidates,
                    symbol,
                    execution.id,
                    dry_run=dry_run,
                )
                execution.trigger_lines_created += summary.created
                execution.trigger_lines_updated += summary.updated

            execution.status = "COMPLETED"
            execution.finished_at = datetime.now(UTC)
            if not dry_run:
                db.commit()
            return execution
        except Exception as exc:  # noqa: BLE001
            execution.status = "FAILED"
            execution.error_message = str(exc)[:1000]
            execution.finished_at = datetime.now(UTC)
            if not dry_run:
                db.commit()
            raise
