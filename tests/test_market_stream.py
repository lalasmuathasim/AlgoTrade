# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import PaperTradingSetting, TriggerLine, TradingSignal
from backend.app.schemas import TickPayload
from backend.app.services.market_stream import CandleBuilder, MarketDataProcessor, SignalGenerator, VolumeValidator


class ScalarQueueSession:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, _obj):
        return None

    def flush(self):
        return None


class BreakoutAwareSession:
    def __init__(self, scalar_values, active_lines):
        self.scalar_values = list(scalar_values)
        self.active_lines = list(active_lines)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self.active_lines))

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class MarketStreamTests(unittest.TestCase):
    def test_candle_builder_aggregates_exchange_aligned_three_minute_candles(self):
        builder = CandleBuilder()
        ticks = [
            TickPayload(
                instrument_token=111,
                symbol="RELIANCE",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:15:10+05:30"),
                last_price=100.0,
                volume_traded=1000,
            ),
            TickPayload(
                instrument_token=111,
                symbol="RELIANCE",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:17:40+05:30"),
                last_price=103.0,
                volume_traded=1300,
            ),
            TickPayload(
                instrument_token=111,
                symbol="RELIANCE",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:18:05+05:30"),
                last_price=101.0,
                volume_traded=1500,
            ),
        ]

        finalized = []
        for tick in ticks:
            finalized.extend(builder.on_tick(tick))

        self.assertEqual(len(finalized), 1)
        candle = finalized[0]
        self.assertEqual(candle.open, 100.0)
        self.assertEqual(candle.high, 103.0)
        self.assertEqual(candle.low, 100.0)
        self.assertEqual(candle.close, 103.0)
        self.assertEqual(candle.volume, 300.0)

    def test_candle_builder_finalizes_due_candle_when_another_symbol_advances_clock(self):
        builder = CandleBuilder()
        initial_ticks = [
            TickPayload(
                instrument_token=111,
                symbol="ICICIBANK",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:15:10+05:30"),
                last_price=100.0,
                volume_traded=1000,
            ),
            TickPayload(
                instrument_token=111,
                symbol="ICICIBANK",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:17:40+05:30"),
                last_price=103.0,
                volume_traded=1300,
            ),
        ]

        for tick in initial_ticks:
            self.assertEqual(builder.on_tick(tick), [])

        finalized = builder.on_tick(
            TickPayload(
                instrument_token=222,
                symbol="SBIN",
                exchange="NSE",
                timestamp=datetime.fromisoformat("2026-07-18T09:18:05+05:30"),
                last_price=800.0,
                volume_traded=500,
            )
        )

        self.assertEqual(len(finalized), 1)
        candle = finalized[0]
        self.assertEqual(candle.symbol, "ICICIBANK")
        self.assertEqual(candle.candle_start.isoformat(), "2026-07-18T03:45:00+00:00")
        self.assertEqual(candle.candle_end.isoformat(), "2026-07-18T03:48:00+00:00")
        self.assertEqual(candle.close, 103.0)
        self.assertEqual(candle.volume, 300.0)

    def test_volume_validator_checks_buy_and_sell_thresholds(self):
        validator = VolumeValidator()

        buy_passed, buy_ratio, buy_required = validator.validate("BUY", current_volume=5000, previous_volume=900)
        sell_passed, sell_ratio, sell_required = validator.validate("SELL", current_volume=3100, previous_volume=1000)

        self.assertTrue(buy_passed)
        self.assertAlmostEqual(buy_ratio, 5.5556, places=4)
        self.assertEqual(buy_required, 5.0)
        self.assertTrue(sell_passed)
        self.assertAlmostEqual(sell_ratio, 3.1, places=1)
        self.assertEqual(sell_required, 3.0)

    def test_volume_validator_can_skip_volume_confirmation(self):
        validator = VolumeValidator()

        passed, ratio, required = validator.validate(
            "BUY",
            current_volume=1200,
            previous_volume=1000,
            require_confirmation=False,
        )

        self.assertTrue(passed)
        self.assertEqual(required, 5.0)
        self.assertAlmostEqual(ratio, 1.2, places=1)

    def test_market_data_processor_tracks_pending_breakout_attempt_from_live_tick(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="ICICIBANK",
            line_type="BUY",
            line_price=100.0,
            line_status="ACTIVE",
            nearest_daily_swing_high_target=110.0,
        )
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        db = BreakoutAwareSession([None], [line])
        processor = MarketDataProcessor()
        tick = TickPayload(
            instrument_token=111,
            symbol="ICICIBANK",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-18T09:15:10+05:30"),
            last_price=100.4,
            volume_traded=1000.0,
        )

        with patch("backend.app.services.market_stream.ensure_settings", return_value=settings):
            result = processor.process_ticks(db, [tick])

        pending = processor.snapshot_pending_breakout_attempts()
        self.assertEqual(result.finalized_candles_count, 0)
        self.assertEqual(result.breakout_events_count, 0)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["symbol"], "ICICIBANK")
        self.assertEqual(pending[0]["status"], "PENDING_CANDLE_CLOSE")
        self.assertEqual(pending[0]["event_time"], "2026-07-18T03:45:10+00:00")

    def test_signal_generator_rejects_breakout_attempt_without_close_confirmation(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="ICICIBANK",
            line_type="BUY",
            line_price=100.0,
            nearest_daily_swing_high_target=110.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "candle_start": datetime.fromisoformat("2026-07-18T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-18T03:48:00+00:00"),
                "open": 99.8,
                "high": 100.6,
                "low": 99.4,
                "close": 99.9,
                "volume": 6000.0,
            },
        )()
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
            require_candle_close_beyond_line=True,
        )
        generator = SignalGenerator()
        db = ScalarQueueSession([settings, SimpleNamespace(tick_size=0.05)])

        breakout, signal = generator.build(db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)

        self.assertIsNone(signal)
        self.assertEqual(breakout.rejection_reason, "CLOSE_CONFIRMATION_FAILED")

    def test_market_data_processor_uses_first_live_breach_timestamp_for_persisted_breakout_event(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="ICICIBANK",
            line_type="BUY",
            line_price=100.0,
            line_status="ACTIVE",
            nearest_daily_swing_high_target=110.0,
            is_untouched=True,
        )
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        breakout_payload = SimpleNamespace(
            breakout_or_breakdown_price=100.0,
            breakout_candle_high=100.6,
            breakout_candle_low=99.8,
            breakout_candle_volume=0.0,
            previous_candle_volume=None,
            required_volume_multiplier=5.0,
            volume_ratio=None,
            volume_condition_passed=False,
            entry_price=100.65,
            stop_loss=99.95,
            target=110.0,
            rejection_reason="NO_PREVIOUS_VOLUME",
        )
        db = BreakoutAwareSession([None, None, None, None], [line])
        processor = MarketDataProcessor()
        first_tick = TickPayload(
            instrument_token=111,
            symbol="ICICIBANK",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-18T09:15:10+05:30"),
            last_price=100.4,
            volume_traded=1000.0,
        )
        second_tick = TickPayload(
            instrument_token=111,
            symbol="ICICIBANK",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-18T09:18:05+05:30"),
            last_price=99.6,
            volume_traded=1100.0,
        )

        with (
            patch("backend.app.services.market_stream.ensure_settings", return_value=settings),
            patch.object(processor, "_persist_candle", return_value=SimpleNamespace(id=uuid.uuid4())),
            patch.object(processor.signal_generator, "build", return_value=(breakout_payload, None)),
        ):
            first_result = processor.process_ticks(db, [first_tick])
            second_result = processor.process_ticks(db, [second_tick])

        self.assertEqual(first_result.breakout_events_count, 0)
        self.assertEqual(len(processor.snapshot_pending_breakout_attempts()), 0)
        self.assertEqual(second_result.breakout_events_count, 1)
        self.assertEqual(second_result.breakout_events[0].event_time.isoformat(), "2026-07-18T03:45:10+00:00")

    def test_signal_generator_uses_breakout_candle_for_entry_and_trigger_line_for_stop(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=100.0,
            nearest_daily_swing_high_target=110.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "candle_start": datetime.fromisoformat("2026-07-18T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-18T03:48:00+00:00"),
                "open": 99.6,
                "high": 101.0,
                "low": 99.0,
                "close": 100.95,
                "volume": 6000.0,
            },
        )()
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        generator = SignalGenerator()

        first_db = ScalarQueueSession([settings, SimpleNamespace(tick_size=0.05), None, settings])
        breakout, signal = generator.build(first_db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)
        self.assertTrue(breakout.volume_condition_passed)
        self.assertEqual(breakout.required_volume_multiplier, 5.0)
        self.assertEqual(breakout.entry_price, 101.05)
        self.assertEqual(breakout.stop_loss, 99.95)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.entry_price, 101.05)
        self.assertEqual(signal.stop_loss, 99.95)
        self.assertEqual(signal.target, 110.0)

    def test_signal_generator_prevents_duplicates(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=100.0,
            nearest_daily_swing_high_target=110.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "candle_start": datetime.fromisoformat("2026-07-18T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-18T03:48:00+00:00"),
                "open": 99.6,
                "high": 101.0,
                "low": 99.0,
                "close": 100.95,
                "volume": 6000.0,
            },
        )()
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        generator = SignalGenerator()
        duplicate_db = ScalarQueueSession([
            settings,
            SimpleNamespace(tick_size=0.05),
            TradingSignal(id=uuid.uuid4(), exchange="NSE", symbol="RELIANCE", action="BUY"),
        ])
        breakout, duplicate_signal = generator.build(
            duplicate_db,
            line,
            candle,
            previous_candle_volume=1000.0,
            market_candle_id=None,
        )
        self.assertIsNone(duplicate_signal)
        self.assertEqual(breakout.rejection_reason, "DUPLICATE_SIGNAL")

    def test_signal_generator_records_volume_failure_without_signal(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="SBIN",
            line_type="SELL",
            line_price=600.0,
            nearest_daily_swing_low_target=580.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "candle_start": datetime.fromisoformat("2026-07-18T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-18T03:48:00+00:00"),
                "open": 601.5,
                "high": 602.0,
                "low": 595.0,
                "close": 595.2,
                "volume": 2500.0,
            },
        )()
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        generator = SignalGenerator()

        db = ScalarQueueSession([settings, SimpleNamespace(tick_size=0.05)])
        breakout, signal = generator.build(db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)

        self.assertIsNone(signal)
        self.assertFalse(breakout.volume_condition_passed)
        self.assertEqual(breakout.required_volume_multiplier, 3.0)
        self.assertEqual(breakout.entry_price, 594.95)
        self.assertEqual(breakout.stop_loss, 600.05)
        self.assertEqual(breakout.rejection_reason, "VOLUME_FAILED")

    def test_signal_generator_rejects_buy_order_when_breakout_quality_fails(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="INFY",
            line_type="BUY",
            line_price=1500.0,
            nearest_daily_swing_high_target=1540.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "candle_start": datetime.fromisoformat("2026-07-18T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-18T03:48:00+00:00"),
                "open": 1499.8,
                "high": 1502.0,
                "low": 1499.0,
                "close": 1500.9,
                "volume": 8000.0,
            },
        )()
        settings = PaperTradingSetting(
            id=uuid.uuid4(),
            starting_capital=200000.0,
            capital_per_trade=25000.0,
            fixed_quantity=None,
            risk_per_trade=2500.0,
            brokerage_estimate=20.0,
            slippage_estimate=0.2,
            max_trades_per_day=3,
            max_daily_loss=5000.0,
            default_quantity_mode="RISK_BASED",
            enable_breakout_quality=True,
            minimum_close_position_percent=80.0,
            minimum_candle_body_percent=60.0,
            maximum_rejection_wick_percent=20.0,
            minimum_close_beyond_level_ticks=2.0,
            require_volume_confirmation=True,
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
            daily_candle_lookback=100,
            swing_window=2,
            max_gap_percent=0.5,
            min_swing_distance=1,
        )
        generator = SignalGenerator()

        db = ScalarQueueSession([settings, SimpleNamespace(tick_size=0.05)])
        breakout, signal = generator.build(db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)

        self.assertIsNone(signal)
        self.assertEqual(breakout.rejection_reason, "CLOSE_POSITION_FAILED")

    def test_market_data_processor_skips_repeat_breakout_for_same_line_on_same_day(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=100.0,
        )
        candle = type(
            "Candle",
            (),
            {
                "instrument_token": 111,
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "timeframe": "3minute",
                "candle_start": datetime.fromisoformat("2026-07-22T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-22T03:48:00+00:00"),
                "open": 99.5,
                "high": 101.0,
                "low": 99.4,
                "close": 100.8,
                "volume": 6000.0,
            },
        )()
        previous_candle = SimpleNamespace(volume=1000.0)
        existing_event = SimpleNamespace(id=uuid.uuid4())
        db = BreakoutAwareSession([previous_candle, existing_event], [line])
        processor = MarketDataProcessor()

        with patch.object(processor, "_persist_candle", return_value=SimpleNamespace(id=uuid.uuid4())), \
             patch("backend.app.services.market_stream.ensure_settings", return_value=SimpleNamespace(require_candle_close_beyond_line=True)), \
             patch.object(processor.breakout_detector, "detect", return_value=[(line, "BREAKOUT")]), \
             patch.object(processor.signal_generator, "build") as mock_build:
            signals, breakout_events = processor._process_finalized_candle(db, candle)

        self.assertEqual(signals, [])
        self.assertEqual(breakout_events, [])
        mock_build.assert_not_called()
        self.assertEqual(db.added, [])

    def test_market_data_processor_archives_line_after_first_breakout_even_without_signal(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=100.0,
            line_status="ACTIVE",
            is_untouched=True,
        )
        candle = type(
            "Candle",
            (),
            {
                "instrument_token": 111,
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "timeframe": "3minute",
                "candle_start": datetime.fromisoformat("2026-07-22T03:45:00+00:00"),
                "candle_end": datetime.fromisoformat("2026-07-22T03:48:00+00:00"),
                "open": 99.5,
                "high": 101.0,
                "low": 99.4,
                "close": 100.8,
                "volume": 4200.0,
            },
        )()
        previous_candle = SimpleNamespace(volume=1000.0)
        db = BreakoutAwareSession([previous_candle, None], [line])
        processor = MarketDataProcessor()
        breakout_payload = SimpleNamespace(
            breakout_or_breakdown_price=100.0,
            breakout_candle_high=101.0,
            breakout_candle_low=99.4,
            breakout_candle_volume=4200.0,
            previous_candle_volume=1000.0,
            required_volume_multiplier=5.0,
            volume_ratio=4.2,
            volume_condition_passed=False,
            entry_price=101.05,
            stop_loss=99.95,
            target=110.0,
            rejection_reason="VOLUME_FAILED",
        )

        with patch.object(processor, "_persist_candle", return_value=SimpleNamespace(id=uuid.uuid4())), \
             patch("backend.app.services.market_stream.ensure_settings", return_value=SimpleNamespace(require_candle_close_beyond_line=True)), \
             patch.object(processor.breakout_detector, "detect", return_value=[(line, "BREAKOUT")]), \
             patch.object(processor.signal_generator, "build", return_value=(breakout_payload, None)):
            signals, breakout_events = processor._process_finalized_candle(db, candle)

        self.assertEqual(signals, [])
        self.assertEqual(len(breakout_events), 1)
        self.assertEqual(line.line_status, "ARCHIVED")
        self.assertFalse(line.is_untouched)
        self.assertEqual(line.archive_reason, "BUY_BREAKOUT_RECORDED")
        self.assertIsNotNone(line.archived_at)

    def test_market_data_processor_continues_after_finalized_candle_failure(self):
        tick = TickPayload(
            instrument_token=111,
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-22T03:45:10+00:00"),
            last_price=100.0,
            volume_traded=1000.0,
        )
        candle = SimpleNamespace(
            instrument_token=111,
            symbol="RELIANCE",
            exchange="NSE",
            timeframe="3minute",
            candle_start=datetime.fromisoformat("2026-07-22T03:45:00+00:00"),
            candle_end=datetime.fromisoformat("2026-07-22T03:48:00+00:00"),
            open=99.5,
            high=101.0,
            low=99.4,
            close=100.8,
            volume=4200.0,
        )
        db = BreakoutAwareSession([], [])
        processor = MarketDataProcessor()

        with patch("backend.app.services.market_stream.ensure_settings", return_value=SimpleNamespace(trading_timezone="Asia/Kolkata")), \
             patch.object(processor.candle_builder, "on_tick", return_value=[candle]), \
             patch.object(processor, "_process_finalized_candle", side_effect=ValueError("db failure")):
            result = processor.process_ticks(db, [tick])

        self.assertEqual(result.ticks_processed, 1)
        self.assertEqual(result.finalized_candles_count, 1)
        self.assertEqual(result.breakout_events_count, 0)
        self.assertEqual(result.signals_created_count, 0)
        self.assertEqual(db.rollbacks, 1)
        self.assertEqual(db.commits, 0)


if __name__ == "__main__":
    unittest.main()
