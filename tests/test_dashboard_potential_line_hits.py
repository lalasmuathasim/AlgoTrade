# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import TriggerLine
from backend.app.routers.dashboard import _build_potential_trigger_row
from backend.app.schemas import HistoricalCandlePayload


class DashboardPotentialLineHitTests(unittest.TestCase):
    def test_buy_line_candidate_is_detected_when_close_is_near_and_moving_up(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=1000.0,
            nearest_daily_swing_high_target=1045.0,
        )
        candles = [
            HistoricalCandlePayload(
                timestamp=datetime.fromisoformat(timestamp),
                open=close - 2,
                high=close + 3,
                low=close - 4,
                close=close,
                volume=1000.0,
            )
            for timestamp, close in [
                ("2026-07-14T00:00:00+00:00", 970.0),
                ("2026-07-15T00:00:00+00:00", 978.0),
                ("2026-07-16T00:00:00+00:00", 987.0),
                ("2026-07-17T00:00:00+00:00", 994.0),
            ]
        ]

        row = _build_potential_trigger_row(line, candles, prediction_proximity_percent=2.0)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["symbol"], "RELIANCE")
        self.assertEqual(row["line_type"], "BUY")
        self.assertEqual(row["toward_moves"], 3)
        self.assertLessEqual(row["distance_percent"], 2.0)

    def test_sell_line_candidate_is_filtered_when_recent_closes_move_away(self):
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="SBIN",
            line_type="SELL",
            line_price=800.0,
            nearest_daily_swing_low_target=760.0,
        )
        candles = [
            HistoricalCandlePayload(
                timestamp=datetime.fromisoformat(timestamp),
                open=close + 2,
                high=close + 4,
                low=close - 3,
                close=close,
                volume=1000.0,
            )
            for timestamp, close in [
                ("2026-07-14T00:00:00+00:00", 809.0),
                ("2026-07-15T00:00:00+00:00", 810.0),
                ("2026-07-16T00:00:00+00:00", 812.0),
                ("2026-07-17T00:00:00+00:00", 813.0),
            ]
        ]

        row = _build_potential_trigger_row(line, candles, prediction_proximity_percent=2.0)

        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
