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

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self.active_lines))

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


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
                "high": 101.0,
                "low": 99.0,
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

        first_db = ScalarQueueSession([settings, None, settings])
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
                "high": 101.0,
                "low": 99.0,
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
                "high": 602.0,
                "low": 595.0,
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

        db = ScalarQueueSession([settings])
        breakout, signal = generator.build(db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)

        self.assertIsNone(signal)
        self.assertFalse(breakout.volume_condition_passed)
        self.assertEqual(breakout.required_volume_multiplier, 3.0)
        self.assertEqual(breakout.entry_price, 594.95)
        self.assertEqual(breakout.stop_loss, 600.05)
        self.assertEqual(breakout.rejection_reason, "VOLUME_FAILED")

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
            signals = processor._process_finalized_candle(db, candle)

        self.assertEqual(signals, [])
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


if __name__ == "__main__":
    unittest.main()
