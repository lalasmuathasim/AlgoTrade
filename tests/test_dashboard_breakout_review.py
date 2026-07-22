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
from backend.app.models import BreakoutEvent, TriggerLine, Watchlist
from backend.app.routers.dashboard import router


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


class DashboardBreakoutReviewTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.selected_watchlist = Watchlist(
            id=uuid.uuid4(),
            name="Selected Watchlist",
            exchange="NSE",
            is_selected=True,
        )
        self.app.dependency_overrides[require_approved_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_breakout_review_returns_selected_watchlist_events_with_volume_context(self):
        trigger_line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=self.selected_watchlist.id,
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=1520.0,
        )
        ignored_other_watchlist_line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="SBIN",
            line_type="SELL",
            line_price=600.0,
        )
        breakout_event = BreakoutEvent(
            id=uuid.uuid4(),
            trigger_line_id=trigger_line.id,
            exchange="NSE",
            symbol="RELIANCE",
            event_type="BREAKOUT",
            event_time=datetime.fromisoformat("2026-07-20T10:03:00+05:30"),
            breakout_candle_volume=6200.0,
            previous_candle_volume=1000.0,
            required_volume_multiplier=5.0,
            volume_ratio=6.2,
            volume_condition_passed=True,
            entry_price=1525.05,
            stop_loss=1519.95,
            target=1560.0,
            signal_generated=True,
            status="PASSED",
        )
        ignored_event = BreakoutEvent(
            id=uuid.uuid4(),
            trigger_line_id=ignored_other_watchlist_line.id,
            exchange="NSE",
            symbol="SBIN",
            event_type="BREAKDOWN",
            event_time=datetime.fromisoformat("2026-07-20T10:06:00+05:30"),
            breakout_candle_volume=4000.0,
            previous_candle_volume=2000.0,
            required_volume_multiplier=3.0,
            volume_ratio=2.0,
            volume_condition_passed=False,
            entry_price=598.95,
            stop_loss=600.05,
            target=580.0,
            signal_generated=False,
            status="VOLUME_FAILED",
            rejection_reason="VOLUME_FAILED",
        )
        self.app.dependency_overrides[get_db] = lambda: DummyDb([[trigger_line], [ignored_event, breakout_event]])
        client = TestClient(self.app)

        with patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist):
            response = client.get("/dashboard/reports/breakout-review?trade_date=2026-07-20")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["report_date"], "2026-07-20")
        self.assertEqual(payload["summary"]["total_events"], 1)
        self.assertEqual(payload["summary"]["passed_events"], 1)
        self.assertEqual(payload["summary"]["failed_events"], 0)
        self.assertEqual(payload["rows"][0]["symbol"], "RELIANCE")
        self.assertEqual(payload["rows"][0]["line_type"], "BUY")
        self.assertEqual(payload["rows"][0]["required_volume_multiplier"], 5.0)
        self.assertTrue(payload["rows"][0]["volume_condition_passed"])
        self.assertTrue(payload["rows"][0]["signal_generated"])
        client.close()


if __name__ == "__main__":
    unittest.main()
