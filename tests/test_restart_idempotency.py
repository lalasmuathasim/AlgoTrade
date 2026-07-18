# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest

from tests.support import configure_test_env

configure_test_env()

from backend.app.schemas import TickPayload
from backend.app.services.market_stream import CandleBuilder


class RestartIdempotencyTests(unittest.TestCase):
    def test_candle_builder_state_can_be_restored_without_losing_open_candle(self):
        builder = CandleBuilder()
        tick = TickPayload(
            instrument_token=321,
            symbol="INFY",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-18T09:15:20+05:30"),
            last_price=1500.0,
            volume_traded=10000,
        )

        builder.on_tick(tick)
        state = builder.export_state()

        rebuilt = CandleBuilder()
        rebuilt.restore_state(state)
        next_tick = TickPayload(
            instrument_token=321,
            symbol="INFY",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2026-07-18T09:16:20+05:30"),
            last_price=1502.0,
            volume_traded=10300,
        )

        finalized = rebuilt.on_tick(next_tick)

        self.assertEqual(finalized, [])
        restored_state = rebuilt.export_state()
        self.assertIn("NSE:INFY", restored_state["candles"])
        self.assertEqual(restored_state["candles"]["NSE:INFY"]["close"], 1502.0)


if __name__ == "__main__":
    unittest.main()
