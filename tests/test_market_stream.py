# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import PaperTradingSetting, TriggerLine, TradingSignal
from backend.app.schemas import TickPayload
from backend.app.services.market_stream import CandleBuilder, SignalGenerator, VolumeValidator


class ScalarQueueSession:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, _obj):
        return None

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

        buy_passed, buy_ratio = validator.validate("BUY", current_volume=5000, previous_volume=900)
        sell_passed, sell_ratio = validator.validate("SELL", current_volume=3100, previous_volume=1000)

        self.assertTrue(buy_passed)
        self.assertAlmostEqual(buy_ratio, 5.5556, places=4)
        self.assertTrue(sell_passed)
        self.assertAlmostEqual(sell_ratio, 3.1, places=1)

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

        first_db = ScalarQueueSession([settings, None, settings])
        breakout, signal = generator.build(first_db, line, candle, previous_candle_volume=1000.0, market_candle_id=None)
        self.assertTrue(breakout.volume_condition_passed)
        self.assertIsNotNone(signal)

        duplicate_db = ScalarQueueSession([
            settings,
            TradingSignal(id=uuid.uuid4(), exchange="NSE", symbol="RELIANCE", action="BUY"),
        ])
        _, duplicate_signal = generator.build(
            duplicate_db,
            line,
            candle,
            previous_candle_volume=1000.0,
            market_candle_id=None,
        )
        self.assertIsNone(duplicate_signal)


if __name__ == "__main__":
    unittest.main()
