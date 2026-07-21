# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.dependencies import require_approved_user
from backend.app.models import TriggerLine
from backend.app.models import Watchlist
from backend.app.routers.dashboard import _build_potential_trigger_row, router
from backend.app.schemas import HistoricalCandlePayload


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class DummyDb:
    def __init__(self, scalars_values):
        self.scalars_values = list(scalars_values)

    def scalars(self, _query):
        return FakeScalarRows(self.scalars_values.pop(0))


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

    def test_route_returns_runtime_tick_price_with_fallback_metadata(self):
        app = FastAPI()
        app.include_router(router)
        selected_watchlist = Watchlist(
            id=uuid.uuid4(),
            name="Selected Watchlist",
            exchange="NSE",
            is_selected=True,
        )
        trigger_line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=selected_watchlist.id,
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=1000.0,
            line_status="ACTIVE",
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
        app.dependency_overrides[get_db] = lambda: DummyDb([[trigger_line]])
        app.dependency_overrides[require_approved_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )
        client = TestClient(app)

        with (
            patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=selected_watchlist),
            patch(
                "backend.app.routers.dashboard.ensure_settings",
                return_value=SimpleNamespace(daily_candle_lookback=100, prediction_proximity_percent=2.0),
            ),
            patch("backend.app.routers.dashboard._load_recent_daily_candles_from_db", return_value=candles),
            patch(
                "backend.app.routers.dashboard._load_runtime_live_price_map",
                return_value={"NSE:RELIANCE": {"price": 997.1, "timestamp": "2026-07-21T03:45:00+00:00", "source": "tick"}},
            ),
            patch("backend.app.routers.dashboard._load_zerodha_ltp_map", return_value={"NSE:RELIANCE": 996.45}),
            patch("backend.app.routers.dashboard._load_recent_3minute_close_map", return_value={"NSE:RELIANCE": {"price": 995.25, "timestamp": "2026-07-21T03:42:00+00:00", "source": "3minute_close"}}),
        ):
            response = client.get("/dashboard/reports/potential-line-hits")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["current_realtime_value"], 997.1)
        self.assertEqual(payload["rows"][0]["current_realtime_source"], "tick")
        self.assertEqual(payload["rows"][0]["current_realtime_label"], "997.1 · Tick")
        self.assertNotIn("pattern", payload["rows"][0])
        client.close()
        app.dependency_overrides.clear()

    def test_dashboard_runtime_snapshot_returns_unpublished_fallback(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_approved_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )
        client = TestClient(app)

        with patch("backend.app.routers.dashboard.get_live_engine_runtime", return_value=None):
            response = client.get("/dashboard/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "NOT_PUBLISHED")
        self.assertEqual(payload["latest_prices"], {})
        self.assertEqual(payload["finalized_candles_count"], 0)
        self.assertIsNone(payload["published_at"])
        client.close()
        app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
