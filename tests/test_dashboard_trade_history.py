# ruff: noqa: E402
from __future__ import annotations

from datetime import date, datetime
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
from backend.app.models import PaperTrade
from backend.app.routers.dashboard import router


class _DummyScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DummyDb:
    def __init__(self, scalars_values):
        self.scalars_values = list(scalars_values)

    def scalars(self, _query):
        return _DummyScalarRows(self.scalars_values.pop(0))


class DashboardTradeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[require_approved_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_trade_history_defaults_to_current_trading_day_when_no_range_is_supplied(self):
        current_day_trade = PaperTrade(
            id=uuid.uuid4(),
            exchange="NSE",
            symbol="ICICIBANK",
            action="BUY",
            simulated_entry_price=1400.0,
            simulated_stop_loss=1395.0,
            simulated_target=1425.0,
            quantity=1,
            capital_used=1400.0,
            risk_amount=5.0,
            status="OPEN",
            entry_time=datetime.fromisoformat("2026-08-17T09:30:00+05:30"),
            created_at=datetime.fromisoformat("2026-08-17T09:30:00+05:30"),
        )
        previous_day_trade = PaperTrade(
            id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            action="BUY",
            simulated_entry_price=3000.0,
            simulated_stop_loss=2985.0,
            simulated_target=3055.0,
            quantity=1,
            capital_used=3000.0,
            risk_amount=15.0,
            status="OPEN",
            entry_time=datetime.fromisoformat("2026-08-16T09:30:00+05:30"),
            created_at=datetime.fromisoformat("2026-08-16T09:30:00+05:30"),
        )
        self.app.dependency_overrides[get_db] = lambda: _DummyDb([
            [],
            [current_day_trade, previous_day_trade],
            [],
        ])
        client = TestClient(self.app)

        with (
            patch("backend.app.routers.dashboard._selected_watchlist_filter", return_value=(None, None)),
            patch(
                "backend.app.routers.dashboard.ensure_settings",
                return_value=SimpleNamespace(trading_timezone="Asia/Kolkata"),
            ),
            patch("backend.app.routers.dashboard.current_trading_date", return_value=date(2026, 8, 17)),
        ):
            response = client.get("/dashboard/reports/trade-history?mode=combined")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["date_from"], "2026-08-17")
        self.assertEqual(payload["summary"]["date_to"], "2026-08-17")
        self.assertEqual(payload["summary"]["total_rows"], 1)
        self.assertEqual(payload["rows"][0]["symbol"], "ICICIBANK")
        client.close()

    def test_dashboard_runtime_snapshot_includes_trading_day_timezone_and_trade_activity_fields(self):
        client = TestClient(self.app)

        with (
            patch(
                "backend.app.routers.dashboard.ensure_settings",
                return_value=SimpleNamespace(trading_timezone="Asia/Kolkata"),
            ),
            patch("backend.app.routers.dashboard.current_trading_date", return_value=date(2026, 8, 17)),
            patch(
                "backend.app.routers.dashboard.get_live_engine_runtime",
                return_value={
                    "status": "RUNNING",
                    "message": "Runtime published.",
                    "latest_prices": {"NSE:ICICIBANK": {"price": 1402.5, "source": "tick"}},
                    "finalized_candles_count": 8,
                    "breakout_events_count": 2,
                    "last_breakout_event_id": str(uuid.uuid4()),
                    "last_breakout_event_symbol": "ICICIBANK",
                    "last_signal_id": str(uuid.uuid4()),
                    "pending_breakout_attempts": [],
                    "pending_breakout_revision": None,
                    "last_trade_activity_revision": "signal-1:2026-08-17T04:05:00+00:00",
                    "last_trade_activity_at": "2026-08-17T04:05:00+00:00",
                    "last_trade_signal_id": str(uuid.uuid4()),
                    "last_trade_symbol": "ICICIBANK",
                    "last_trade_mode": "PAPER",
                    "published_at": "2026-08-17T04:05:01+00:00",
                },
            ),
        ):
            response = client.get("/dashboard/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["current_trading_date"], "2026-08-17")
        self.assertEqual(payload["trading_timezone"], "Asia/Kolkata")
        self.assertEqual(payload["last_trade_activity_revision"], "signal-1:2026-08-17T04:05:00+00:00")
        self.assertEqual(payload["last_trade_symbol"], "ICICIBANK")
        self.assertEqual(payload["last_trade_mode"], "PAPER")
        client.close()


if __name__ == "__main__":
    unittest.main()
