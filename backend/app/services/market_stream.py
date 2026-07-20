import logging
import uuid
from dataclasses import dataclass
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import BreakoutEvent, MarketCandle, TradingSignal, TriggerLine
from backend.app.queue import enqueue_signal_dispatch
from backend.app.schemas import BreakoutCandidatePayload, CompletedCandlePayload, SignalDispatchJob, TickPayload
from backend.app.services.execution_runtime import RiskEngine
from backend.app.services.paper_trading_service import ensure_settings


logger = logging.getLogger(__name__)
settings = get_settings()
market_tz = ZoneInfo(settings.market_timezone)


def _coalesce(value, default):
    return default if value is None else value


@dataclass
class TickProcessingResult:
    ticks_processed: int
    finalized_candles: list[CompletedCandlePayload]
    signals: list[TradingSignal]

    @property
    def finalized_candles_count(self) -> int:
        return len(self.finalized_candles)

    @property
    def signals_created_count(self) -> int:
        return len(self.signals)


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
    def validate(
        self,
        action: str,
        current_volume: float,
        previous_volume: float | None,
        buy_volume_multiplier: float | None = None,
        sell_volume_multiplier: float | None = None,
        skip_zero_previous_volume: bool = True,
    ) -> tuple[bool, float | None, float]:
        required = (
            buy_volume_multiplier
            if action == "BUY" and buy_volume_multiplier is not None
            else sell_volume_multiplier
            if action == "SELL" and sell_volume_multiplier is not None
            else settings.buy_volume_multiplier
            if action == "BUY"
            else settings.sell_volume_multiplier
        )
        if not previous_volume or previous_volume <= 0:
            return (not skip_zero_previous_volume), None, required

        ratio = current_volume / previous_volume
        return ratio >= required, round(ratio, 4), required


class BreakoutDetector:
    def detect(
        self,
        candle: CompletedCandlePayload,
        active_lines: Sequence[TriggerLine],
        require_candle_close_beyond_line: bool = True,
    ) -> list[tuple[TriggerLine, str]]:
        events: list[tuple[TriggerLine, str]] = []
        for line in active_lines:
            if line.line_type == "BUY" and (
                (candle.close > line.line_price and candle.high >= line.line_price)
                if require_candle_close_beyond_line
                else candle.open < line.line_price <= candle.high
            ):
                events.append((line, "BREAKOUT"))
            elif line.line_type == "SELL" and (
                (candle.close < line.line_price and candle.low <= line.line_price)
                if require_candle_close_beyond_line
                else candle.open > line.line_price >= candle.low
            ):
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
        runtime_settings = ensure_settings(db)
        allowed_exchanges = list(_coalesce(getattr(runtime_settings, "allowed_exchanges", None), ["NSE", "BSE"]))
        if line.exchange not in allowed_exchanges:
            breakout_payload = BreakoutCandidatePayload(
                trigger_line_id=line.id,
                symbol=line.symbol,
                exchange=line.exchange,
                line_type=line.line_type,
                event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
                event_time=candle.candle_end,
                breakout_or_breakdown_price=line.line_price,
                breakout_candle_high=candle.high,
                breakout_candle_low=candle.low,
                breakout_candle_volume=candle.volume,
                previous_candle_volume=previous_candle_volume,
                required_volume_multiplier=runtime_settings.buy_volume_multiplier if action == "BUY" else runtime_settings.sell_volume_multiplier,
                volume_ratio=None,
                volume_condition_passed=False,
                entry_price=None,
                stop_loss=None,
                target=None,
                market_candle_id=market_candle_id,
                rejection_reason="EXCHANGE_BLOCKED",
            )
            return breakout_payload, None

        min_price = getattr(runtime_settings, "minimum_price", None)
        max_price = getattr(runtime_settings, "maximum_price", None)
        if min_price is not None and line.line_price < min_price:
            return BreakoutCandidatePayload(
                trigger_line_id=line.id,
                symbol=line.symbol,
                exchange=line.exchange,
                line_type=line.line_type,
                event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
                event_time=candle.candle_end,
                breakout_or_breakdown_price=line.line_price,
                breakout_candle_high=candle.high,
                breakout_candle_low=candle.low,
                breakout_candle_volume=candle.volume,
                previous_candle_volume=previous_candle_volume,
                required_volume_multiplier=runtime_settings.buy_volume_multiplier if action == "BUY" else runtime_settings.sell_volume_multiplier,
                volume_ratio=None,
                volume_condition_passed=False,
                entry_price=None,
                stop_loss=None,
                target=None,
                market_candle_id=market_candle_id,
                rejection_reason="PRICE_BELOW_MINIMUM",
            ), None
        if max_price is not None and line.line_price > max_price:
            return BreakoutCandidatePayload(
                trigger_line_id=line.id,
                symbol=line.symbol,
                exchange=line.exchange,
                line_type=line.line_type,
                event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
                event_time=candle.candle_end,
                breakout_or_breakdown_price=line.line_price,
                breakout_candle_high=candle.high,
                breakout_candle_low=candle.low,
                breakout_candle_volume=candle.volume,
                previous_candle_volume=previous_candle_volume,
                required_volume_multiplier=runtime_settings.buy_volume_multiplier if action == "BUY" else runtime_settings.sell_volume_multiplier,
                volume_ratio=None,
                volume_condition_passed=False,
                entry_price=None,
                stop_loss=None,
                target=None,
                market_candle_id=market_candle_id,
                rejection_reason="PRICE_ABOVE_MAXIMUM",
            ), None

        candle_local = candle.candle_end.astimezone(market_tz)
        if bool(getattr(runtime_settings, "market_hours_guard", True)):
            if candle_local.time() < time(9, 15) or candle_local.time() > time(15, 30):
                return BreakoutCandidatePayload(
                    trigger_line_id=line.id,
                    symbol=line.symbol,
                    exchange=line.exchange,
                    line_type=line.line_type,
                    event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
                    event_time=candle.candle_end,
                    breakout_or_breakdown_price=line.line_price,
                    breakout_candle_high=candle.high,
                    breakout_candle_low=candle.low,
                    breakout_candle_volume=candle.volume,
                    previous_candle_volume=previous_candle_volume,
                    required_volume_multiplier=runtime_settings.buy_volume_multiplier if action == "BUY" else runtime_settings.sell_volume_multiplier,
                    volume_ratio=None,
                    volume_condition_passed=False,
                    entry_price=None,
                    stop_loss=None,
                    target=None,
                    market_candle_id=market_candle_id,
                    rejection_reason="OUTSIDE_MARKET_HOURS",
                ), None

        no_trade_after_time = _coalesce(getattr(runtime_settings, "no_trade_after_time", None), None)
        if no_trade_after_time:
            try:
                cutoff = time.fromisoformat(no_trade_after_time)
                if candle_local.time() >= cutoff:
                    return BreakoutCandidatePayload(
                        trigger_line_id=line.id,
                        symbol=line.symbol,
                        exchange=line.exchange,
                        line_type=line.line_type,
                        event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
                        event_time=candle.candle_end,
                        breakout_or_breakdown_price=line.line_price,
                        breakout_candle_high=candle.high,
                        breakout_candle_low=candle.low,
                        breakout_candle_volume=candle.volume,
                        previous_candle_volume=previous_candle_volume,
                        required_volume_multiplier=runtime_settings.buy_volume_multiplier if action == "BUY" else runtime_settings.sell_volume_multiplier,
                        volume_ratio=None,
                        volume_condition_passed=False,
                        entry_price=None,
                        stop_loss=None,
                        target=None,
                        market_candle_id=market_candle_id,
                        rejection_reason="NO_TRADE_AFTER_CUTOFF",
                    ), None
            except ValueError:
                logger.warning("Invalid no_trade_after_time value in runtime settings: %s", no_trade_after_time)

        volume_passed, volume_ratio, required_volume_multiplier = self.volume_validator.validate(
            action,
            candle.volume,
            previous_candle_volume,
            buy_volume_multiplier=runtime_settings.buy_volume_multiplier,
            sell_volume_multiplier=runtime_settings.sell_volume_multiplier,
            skip_zero_previous_volume=bool(_coalesce(getattr(runtime_settings, "skip_zero_previous_volume", None), True)),
        )
        entry_price = (
            candle.high + runtime_settings.entry_buffer_ticks
            if action == "BUY"
            else candle.low - runtime_settings.entry_buffer_ticks
        )
        stop_loss = (
            line.line_price - runtime_settings.stop_loss_buffer_ticks
            if action == "BUY"
            else line.line_price + runtime_settings.stop_loss_buffer_ticks
        )

        line_target = (
            line.nearest_daily_swing_high_target
            if action == "BUY"
            else line.nearest_daily_swing_low_target
        )
        target = None
        target_mode = _coalesce(getattr(runtime_settings, "target_mode", None), "NEAREST_DAILY_SWING")
        use_swing_target = bool(_coalesce(getattr(runtime_settings, "use_nearest_daily_swing_target", None), True))
        if target_mode == "NEAREST_DAILY_SWING" and use_swing_target:
            target = line_target
        if target is None:
            reward = abs(entry_price - stop_loss) * float(_coalesce(getattr(runtime_settings, "fallback_risk_reward_ratio", None), 2.0))
            target = entry_price + reward if action == "BUY" else entry_price - reward

        reward_risk_ratio = 0.0
        if abs(entry_price - stop_loss) > 0:
            reward_risk_ratio = abs(target - entry_price) / abs(entry_price - stop_loss)

        breakout_payload = BreakoutCandidatePayload(
            trigger_line_id=line.id,
            symbol=line.symbol,
            exchange=line.exchange,
            line_type=line.line_type,
            event_type="BREAKOUT" if action == "BUY" else "BREAKDOWN",
            event_time=candle.candle_end,
            breakout_or_breakdown_price=line.line_price,
            breakout_candle_high=candle.high,
            breakout_candle_low=candle.low,
            breakout_candle_volume=candle.volume,
            previous_candle_volume=previous_candle_volume,
            required_volume_multiplier=required_volume_multiplier,
            volume_ratio=volume_ratio,
            volume_condition_passed=volume_passed,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            market_candle_id=market_candle_id,
            rejection_reason=None,
        )

        if not volume_passed:
            breakout_payload.rejection_reason = (
                "NO_PREVIOUS_VOLUME"
                if previous_candle_volume is None or previous_candle_volume <= 0
                else "VOLUME_FAILED"
            )
            return breakout_payload, None

        minimum_reward_risk_ratio = float(_coalesce(getattr(runtime_settings, "minimum_reward_risk_ratio", None), 1.0))
        if reward_risk_ratio < minimum_reward_risk_ratio:
            breakout_payload.rejection_reason = "REWARD_RISK_TOO_LOW"
            return breakout_payload, None

        if bool(_coalesce(getattr(runtime_settings, "allow_repeat_entry_same_line", None), False)):
            cooldown = int(_coalesce(getattr(runtime_settings, "reentry_cooldown_minutes", None), 0))
            if cooldown > 0:
                recent_signal = db.scalar(
                    select(TradingSignal)
                    .where(
                        TradingSignal.trigger_line_id == line.id,
                        TradingSignal.action == action,
                    )
                    .order_by(desc(TradingSignal.created_at))
                    .limit(1)
                )
                if recent_signal is not None and recent_signal.created_at is not None:
                    elapsed = candle.candle_end - recent_signal.created_at
                    if elapsed < timedelta(minutes=cooldown):
                        breakout_payload.rejection_reason = "REENTRY_COOLDOWN"
                        return breakout_payload, None

        dedupe_key = f"{line.id}:{action}:{candle.candle_start.isoformat()}"
        existing = db.scalar(select(TradingSignal).where(TradingSignal.dedupe_key == dedupe_key).limit(1))
        if existing is not None:
            breakout_payload.rejection_reason = "DUPLICATE_SIGNAL"
            return breakout_payload, None

        required_confidence = float(_coalesce(getattr(runtime_settings, "minimum_confidence_score", None), 0.6))
        volume_strength = min((volume_ratio or 0.0) / max(required_volume_multiplier, 1.0), 2.0) / 2.0
        reward_strength = min(reward_risk_ratio / max(minimum_reward_risk_ratio, 1.0), 2.0) / 2.0
        confidence_score = round((volume_strength * 0.6) + (reward_strength * 0.4), 4)
        if bool(_coalesce(getattr(runtime_settings, "enable_confidence_filter", None), False)) and confidence_score < required_confidence:
            if not bool(_coalesce(getattr(runtime_settings, "allow_low_confidence_paper_trades_only", None), True)):
                breakout_payload.rejection_reason = "CONFIDENCE_TOO_LOW"
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
                "reward_risk_ratio": reward_risk_ratio,
                "confidence_score": confidence_score,
                "confidence_source": _coalesce(getattr(runtime_settings, "confidence_source", None), "RULES_ONLY"),
            },
            status="PENDING_EXECUTION",
        )
        return breakout_payload, signal


class MarketDataProcessor:
    def __init__(self, candle_builder: CandleBuilder | None = None) -> None:
        self.candle_builder = candle_builder or CandleBuilder()
        self.breakout_detector = BreakoutDetector()
        self.signal_generator = SignalGenerator()

    def process_ticks(self, db: Session, ticks: list[TickPayload]) -> TickProcessingResult:
        signals: list[TradingSignal] = []
        finalized_candles: list[CompletedCandlePayload] = []
        for tick in ticks:
            tick_finalized_candles = self.candle_builder.on_tick(tick)
            finalized_candles.extend(tick_finalized_candles)
            for candle in tick_finalized_candles:
                signals.extend(self._process_finalized_candle(db, candle))
        db.commit()
        return TickProcessingResult(
            ticks_processed=len(ticks),
            finalized_candles=finalized_candles,
            signals=signals,
        )

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
        runtime_settings = ensure_settings(db)

        active_lines = db.scalars(
            select(TriggerLine).where(
                TriggerLine.symbol == candle.symbol,
                TriggerLine.exchange == candle.exchange,
                TriggerLine.line_status == "ACTIVE",
            )
        ).all()

        created_signals: list[TradingSignal] = []
        for line, event_type in self.breakout_detector.detect(
            candle,
            active_lines,
            require_candle_close_beyond_line=bool(getattr(runtime_settings, "require_candle_close_beyond_line", True)),
        ):
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
                required_volume_multiplier=breakout_payload.required_volume_multiplier,
                volume_ratio=breakout_payload.volume_ratio,
                volume_condition_passed=breakout_payload.volume_condition_passed,
                entry_price=breakout_payload.entry_price,
                stop_loss=breakout_payload.stop_loss,
                target=breakout_payload.target,
                signal_generated=signal is not None,
                status="PASSED" if signal is not None else (breakout_payload.rejection_reason or "IGNORED"),
                rejection_reason=breakout_payload.rejection_reason,
            )
            db.add(breakout_event)
            db.flush()

            if signal is None:
                continue

            signal.breakout_event_id = breakout_event.id
            db.add(signal)
            line.is_untouched = False
            line.triggered_at = datetime.now(UTC)
            if bool(_coalesce(getattr(runtime_settings, "allow_repeat_entry_same_line", None), False)):
                line.line_status = "ACTIVE"
            else:
                line.line_status = "TRIGGERED"
            db.flush()
            enqueue_signal_dispatch(SignalDispatchJob(signal_id=signal.id))
            created_signals.append(signal)

        return created_signals
