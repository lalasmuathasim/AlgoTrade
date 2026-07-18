import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import BreakoutEvent, MarketCandle, TradingSignal, TriggerLine
from backend.app.queue import enqueue_signal_dispatch
from backend.app.schemas import BreakoutCandidatePayload, CompletedCandlePayload, SignalDispatchJob, TickPayload
from backend.app.services.execution_runtime import RiskEngine


logger = logging.getLogger(__name__)
settings = get_settings()
market_tz = ZoneInfo(settings.market_timezone)


class CandleBuilder:
    def __init__(self) -> None:
        self._candles: dict[str, CompletedCandlePayload] = {}
        self._last_cumulative_volume: dict[str, float | None] = {}

    def _bucket_start(self, timestamp: datetime) -> datetime:
        localized = timestamp.astimezone(market_tz)
        minute = localized.minute - (localized.minute % 3)
        aligned = localized.replace(minute=minute, second=0, microsecond=0)
        return aligned.astimezone(UTC)

    def on_tick(self, tick: TickPayload) -> list[CompletedCandlePayload]:
        key = f"{tick.exchange}:{tick.symbol}"
        bucket_start = self._bucket_start(tick.timestamp)
        bucket_end = bucket_start + timedelta(minutes=3)
        finalized: list[CompletedCandlePayload] = []

        previous_cumulative = self._last_cumulative_volume.get(key)
        volume_delta = 0.0
        if tick.volume_traded is not None:
            if previous_cumulative is None:
                volume_delta = 0.0
            else:
                volume_delta = max(tick.volume_traded - previous_cumulative, 0.0)
            self._last_cumulative_volume[key] = tick.volume_traded

        current = self._candles.get(key)
        if current is None or current.candle_start != bucket_start:
            if current is not None:
                finalized.append(current)
            current = CompletedCandlePayload(
                instrument_token=tick.instrument_token,
                symbol=tick.symbol,
                exchange=tick.exchange,
                candle_start=bucket_start,
                candle_end=bucket_end,
                open=tick.last_price,
                high=tick.last_price,
                low=tick.last_price,
                close=tick.last_price,
                volume=volume_delta,
            )
            self._candles[key] = current
            return finalized

        current.high = max(current.high, tick.last_price)
        current.low = min(current.low, tick.last_price)
        current.close = tick.last_price
        current.volume += volume_delta
        return finalized

    def export_state(self) -> dict:
        return {
            "candles": {key: value.model_dump(mode="json") for key, value in self._candles.items()},
            "last_cumulative_volume": self._last_cumulative_volume,
        }

    def restore_state(self, state: dict) -> None:
        self._candles = {
            key: CompletedCandlePayload.model_validate(value)
            for key, value in state.get("candles", {}).items()
        }
        self._last_cumulative_volume = state.get("last_cumulative_volume", {})


class VolumeValidator:
    def validate(self, action: str, current_volume: float, previous_volume: float | None) -> tuple[bool, float | None]:
        if not previous_volume or previous_volume <= 0:
            return False, None

        ratio = current_volume / previous_volume
        required = settings.buy_volume_multiplier if action == "BUY" else settings.sell_volume_multiplier
        return ratio >= required, round(ratio, 4)


class BreakoutDetector:
    def detect(self, candle: CompletedCandlePayload, active_lines: Sequence[TriggerLine]) -> list[tuple[TriggerLine, str]]:
        events: list[tuple[TriggerLine, str]] = []
        for line in active_lines:
            if line.line_type == "BUY" and candle.open < line.line_price <= candle.high:
                events.append((line, "BREAKOUT"))
            elif line.line_type == "SELL" and candle.open > line.line_price >= candle.low:
                events.append((line, "BREAKDOWN"))
        return events


class SignalGenerator:
    def __init__(self, risk_engine: RiskEngine | None = None) -> None:
        self.volume_validator = VolumeValidator()
        self.risk_engine = risk_engine or RiskEngine()

    def build(
        self,
        db: Session,
        line: TriggerLine,
        candle: CompletedCandlePayload,
        previous_candle_volume: float | None,
        market_candle_id,
    ) -> tuple[BreakoutCandidatePayload, TradingSignal | None]:
        action = "BUY" if line.line_type == "BUY" else "SELL"
        volume_passed, volume_ratio = self.volume_validator.validate(action, candle.volume, previous_candle_volume)
        entry_price = line.line_price + settings.entry_buffer_ticks if action == "BUY" else line.line_price - settings.entry_buffer_ticks
        stop_loss = candle.low - settings.stop_buffer_ticks if action == "BUY" else candle.high + settings.stop_buffer_ticks

        target = (
            line.nearest_daily_swing_high_target
            if action == "BUY"
            else line.nearest_daily_swing_low_target
        )
        if target is None:
            reward = abs(entry_price - stop_loss) * 2
            target = entry_price + reward if action == "BUY" else entry_price - reward

        breakout_payload = BreakoutCandidatePayload(
            trigger_line_id=line.id,
            symbol=line.symbol,
            exchange=line.exchange,
            event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
            event_time=candle.candle_end,
            breakout_or_breakdown_price=line.line_price,
            breakout_candle_high=candle.high,
            breakout_candle_low=candle.low,
            breakout_candle_volume=candle.volume,
            previous_candle_volume=previous_candle_volume,
            volume_ratio=volume_ratio,
            volume_condition_passed=volume_passed,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            market_candle_id=market_candle_id,
        )

        if not volume_passed:
            return breakout_payload, None

        dedupe_key = f"{line.id}:{action}:{candle.candle_start.isoformat()}"
        existing = db.scalar(select(TradingSignal).where(TradingSignal.dedupe_key == dedupe_key).limit(1))
        if existing is not None:
            return breakout_payload, None

        quantity, capital_used, risk_amount = self.risk_engine.compute(db, action, entry_price, stop_loss)
        signal = TradingSignal(
            id=uuid.uuid4(),
            exchange=line.exchange,
            symbol=line.symbol,
            action=action,
            source="ZERODHA",
            watchlist_id=line.watchlist_id,
            trigger_line_id=line.id,
            trigger_price=line.line_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            quantity=quantity,
            capital_used=capital_used,
            risk_amount=risk_amount,
            volume_ratio=volume_ratio,
            timeframe="3minute",
            strategy="zerodha_daily_structure",
            dedupe_key=dedupe_key,
            raw_payload={
                "line_id": str(line.id),
                "candle_start": candle.candle_start.isoformat(),
                "candle_end": candle.candle_end.isoformat(),
                "volume": candle.volume,
            },
            status="PENDING_EXECUTION",
        )
        return breakout_payload, signal


class MarketDataProcessor:
    def __init__(self, candle_builder: CandleBuilder | None = None) -> None:
        self.candle_builder = candle_builder or CandleBuilder()
        self.breakout_detector = BreakoutDetector()
        self.signal_generator = SignalGenerator()

    def process_ticks(self, db: Session, ticks: list[TickPayload]) -> list[TradingSignal]:
        signals: list[TradingSignal] = []
        for tick in ticks:
            finalized_candles = self.candle_builder.on_tick(tick)
            for candle in finalized_candles:
                signals.extend(self._process_finalized_candle(db, candle))
        db.commit()
        return signals

    def _persist_candle(self, db: Session, candle: CompletedCandlePayload) -> MarketCandle:
        existing = db.scalar(
            select(MarketCandle).where(
                MarketCandle.symbol == candle.symbol,
                MarketCandle.exchange == candle.exchange,
                MarketCandle.timeframe == candle.timeframe,
                MarketCandle.candle_start == candle.candle_start,
            )
        )
        if existing is None:
            existing = MarketCandle(
                instrument_token=candle.instrument_token,
                symbol=candle.symbol,
                exchange=candle.exchange,
                timeframe=candle.timeframe,
                candle_start=candle.candle_start,
                candle_end=candle.candle_end,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                is_final=True,
                source="ZERODHA",
            )
            db.add(existing)
        else:
            existing.open = candle.open
            existing.high = candle.high
            existing.low = candle.low
            existing.close = candle.close
            existing.volume = candle.volume
            existing.candle_end = candle.candle_end
            existing.is_final = True
        db.flush()
        return existing

    def _process_finalized_candle(self, db: Session, candle: CompletedCandlePayload) -> list[TradingSignal]:
        persisted_candle = self._persist_candle(db, candle)
        previous_candle = db.scalar(
            select(MarketCandle)
            .where(
                MarketCandle.symbol == candle.symbol,
                MarketCandle.exchange == candle.exchange,
                MarketCandle.timeframe == candle.timeframe,
                MarketCandle.candle_start < candle.candle_start,
            )
            .order_by(desc(MarketCandle.candle_start))
            .limit(1)
        )
        previous_volume = previous_candle.volume if previous_candle else None

        active_lines = db.scalars(
            select(TriggerLine).where(
                TriggerLine.symbol == candle.symbol,
                TriggerLine.exchange == candle.exchange,
                TriggerLine.line_status == "ACTIVE",
            )
        ).all()

        created_signals: list[TradingSignal] = []
        for line, event_type in self.breakout_detector.detect(candle, active_lines):
            breakout_payload, signal = self.signal_generator.build(
                db,
                line,
                candle,
                previous_volume,
                persisted_candle.id,
            )

            breakout_event = BreakoutEvent(
                trigger_line_id=line.id,
                market_candle_id=persisted_candle.id,
                exchange=line.exchange,
                symbol=line.symbol,
                event_type=event_type,
                event_time=candle.candle_end,
                breakout_or_breakdown_price=breakout_payload.breakout_or_breakdown_price,
                breakout_candle_high=breakout_payload.breakout_candle_high,
                breakout_candle_low=breakout_payload.breakout_candle_low,
                breakout_candle_volume=breakout_payload.breakout_candle_volume,
                previous_candle_volume=breakout_payload.previous_candle_volume,
                volume_ratio=breakout_payload.volume_ratio,
                volume_condition_passed=breakout_payload.volume_condition_passed,
                entry_price=breakout_payload.entry_price,
                stop_loss=breakout_payload.stop_loss,
                target=breakout_payload.target,
                signal_generated=signal is not None,
                status="PASSED" if signal is not None else "IGNORED",
            )
            db.add(breakout_event)
            db.flush()

            if signal is None:
                continue

            signal.breakout_event_id = breakout_event.id
            db.add(signal)
            line.line_status = "TRIGGERED"
            line.is_untouched = False
            line.triggered_at = datetime.now(UTC)
            db.flush()
            enqueue_signal_dispatch(SignalDispatchJob(signal_id=signal.id))
            created_signals.append(signal)

        return created_signals
