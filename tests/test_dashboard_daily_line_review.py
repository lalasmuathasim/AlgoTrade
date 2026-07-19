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
from backend.app.dependencies import require_admin_user, require_approved_user
from backend.app.models import ScanExecution, TriggerLine, Watchlist, WatchlistSymbol
from backend.app.routers.dashboard import router


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class DummyDb:
    def __init__(self, scalar_values, scalars_values):
        self.scalar_values = list(scalar_values)
        self.scalars_values = list(scalars_values)

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def scalars(self, _query):
        return FakeScalarRows(self.scalars_values.pop(0))

    def get(self, _model, _identifier):
        return None


class DashboardDailyLineReviewTests(unittest.TestCase):
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
        self.app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_daily_line_review_returns_stored_trigger_lines_for_selected_watchlist(self):
        symbol = WatchlistSymbol(
            id=uuid.uuid4(),
            watchlist_id=self.selected_watchlist.id,
            exchange="NSE",
            symbol="RELIANCE",
            company_name="Reliance Industries",
            instrument_token=12345,
            is_active=True,
        )
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=self.selected_watchlist.id,
            exchange="NSE",
            symbol="RELIANCE",
            line_type="BUY",
            line_price=1520.0,
            line_status="ACTIVE",
            line_drawn_date=datetime.fromisoformat("2026-07-18T00:00:00+00:00").date(),
            swing_gap_percent=0.59,
            swing_high_1_price=1518.0,
            swing_high_1_date=datetime.fromisoformat("2026-07-01T00:00:00+00:00").date(),
            swing_high_2_price=1509.0,
            swing_high_2_date=datetime.fromisoformat("2026-07-08T00:00:00+00:00").date(),
            nearest_daily_swing_high_target=1560.0,
        )
        latest_scan = ScanExecution(
            id=uuid.uuid4(),
            scan_name="daily_market_scan",
            scan_date=datetime.fromisoformat("2026-07-19T00:00:00+00:00").date(),
            status="COMPLETED",
            finished_at=datetime.fromisoformat("2026-07-19T10:30:00+00:00"),
        )
        self.app.dependency_overrides[get_db] = lambda: DummyDb([latest_scan], [[symbol], [line]])
        client = TestClient(self.app)

        with patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist):
            response = client.get("/dashboard/reports/daily-line-review")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["total_symbols"], 1)
        self.assertEqual(payload["summary"]["symbols_with_lines"], 1)
        self.assertEqual(payload["summary"]["total_candidate_rows"], len(payload["rows"]))
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["symbol"], "RELIANCE")
        self.assertEqual(payload["rows"][0]["line_type"], "BUY")
        self.assertEqual(payload["rows"][0]["line_price"], 1520.0)
        self.assertEqual(payload["rows"][0]["line_drawn_date"], "2026-07-18")
        self.assertEqual(payload["rows"][0]["nearest_target"], 1560.0)
        self.assertEqual(payload["summary"]["last_scan_status"], "COMPLETED")
        client.close()

    def test_daily_line_review_reports_unmapped_symbols_and_empty_rows(self):
        symbol = WatchlistSymbol(
            id=uuid.uuid4(),
            watchlist_id=self.selected_watchlist.id,
            exchange="NSE",
            symbol="SBIN",
            company_name="State Bank of India",
            instrument_token=None,
            instrument_id=None,
            is_active=True,
        )
        self.app.dependency_overrides[get_db] = lambda: DummyDb([None], [[symbol], []])
        client = TestClient(self.app)

        with patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist):
            response = client.get("/dashboard/reports/daily-line-review")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["unmapped_symbols"], 1)
        self.assertEqual(payload["summary"]["total_candidate_rows"], 0)
        self.assertEqual(payload["rows"], [])
        client.close()

    def test_daily_line_review_refresh_runs_scanner_explicitly(self):
        self.app.dependency_overrides[get_db] = lambda: DummyDb([], [])
        client = TestClient(self.app)
        execution = ScanExecution(
            id=uuid.uuid4(),
            scan_name="daily_market_scan",
            scan_date=datetime.fromisoformat("2026-07-19T00:00:00+00:00").date(),
            status="COMPLETED",
            symbols_scanned=8,
            trigger_lines_created=3,
            trigger_lines_updated=5,
        )

        with (
            patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist),
            patch("backend.app.routers.dashboard.DailyMarketScanner.run", return_value=execution),
        ):
            response = client.post("/dashboard/reports/daily-line-review/refresh")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["symbols_scanned"], 8)
        self.assertEqual(payload["trigger_lines_created"], 3)
        self.assertEqual(payload["trigger_lines_updated"], 5)
        client.close()


if __name__ == "__main__":
    unittest.main()
