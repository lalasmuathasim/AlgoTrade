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
from backend.app.models import Watchlist, WatchlistSymbol
from backend.app.routers.dashboard import router


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class DummyDb:
    def __init__(self, symbols):
        self.symbols = symbols

    def scalars(self, _query):
        return FakeScalarRows(self.symbols)

    def get(self, _model, _identifier):
        return None


def build_daily_fixture():
    rows = [
        ("2026-07-01T00:00:00+00:00", 95, 100, 90, 96, 1000),
        ("2026-07-02T00:00:00+00:00", 96, 108, 94, 105, 1100),
        ("2026-07-03T00:00:00+00:00", 105, 102, 96, 98, 1050),
        ("2026-07-04T00:00:00+00:00", 98, 103, 95, 101, 1025),
        ("2026-07-05T00:00:00+00:00", 101, 107, 97, 104, 1150),
        ("2026-07-06T00:00:00+00:00", 104, 103, 92, 94, 1500),
        ("2026-07-07T00:00:00+00:00", 94, 99, 89, 92, 1250),
        ("2026-07-08T00:00:00+00:00", 92, 107.2, 92, 104, 1600),
        ("2026-07-09T00:00:00+00:00", 104, 104.4, 89.2, 95, 1400),
        ("2026-07-10T00:00:00+00:00", 95, 101, 91, 99, 1300),
    ]
    from backend.app.schemas import HistoricalCandlePayload

    return [
        HistoricalCandlePayload(
            timestamp=datetime.fromisoformat(timestamp),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for timestamp, open_, high, low, close, volume in rows
    ]


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

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_daily_line_review_returns_history_and_candidates_for_selected_watchlist(self):
        symbol = WatchlistSymbol(
            id=uuid.uuid4(),
            watchlist_id=self.selected_watchlist.id,
            exchange="NSE",
            symbol="RELIANCE",
            company_name="Reliance Industries",
            instrument_token=12345,
            is_active=True,
        )
        self.app.dependency_overrides[get_db] = lambda: DummyDb([symbol])
        client = TestClient(self.app)

        with (
            patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist),
            patch("backend.app.routers.dashboard.get_current_zerodha_access_token", return_value="stored-token"),
            patch(
                "backend.app.routers.dashboard.HistoricalCandleProvider.fetch_last_n_completed_daily_candles",
                return_value=build_daily_fixture(),
            ),
        ):
            response = client.get("/dashboard/reports/daily-line-review")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["total_symbols"], 1)
        self.assertEqual(payload["summary"]["history_ready"], 1)
        self.assertGreaterEqual(
            payload["summary"]["total_buy_candidates"] + payload["summary"]["total_sell_candidates"],
            1,
        )
        self.assertEqual(payload["rows"][0]["symbol"], "RELIANCE")
        self.assertEqual(payload["rows"][0]["fetch_status"], "READY")
        self.assertTrue(
            payload["rows"][0]["primary_buy_line"] is not None
            or payload["rows"][0]["primary_sell_line"] is not None
        )
        client.close()

    def test_daily_line_review_marks_unmapped_symbols_without_fetching_history(self):
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
        self.app.dependency_overrides[get_db] = lambda: DummyDb([symbol])
        client = TestClient(self.app)

        with (
            patch("backend.app.routers.dashboard.get_selected_watchlist", return_value=self.selected_watchlist),
            patch("backend.app.routers.dashboard.get_current_zerodha_access_token", return_value="stored-token"),
        ):
            response = client.get("/dashboard/reports/daily-line-review")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"]["unmapped_symbols"], 1)
        self.assertEqual(payload["rows"][0]["fetch_status"], "UNMAPPED")
        self.assertEqual(payload["rows"][0]["candle_count"], 0)
        client.close()


if __name__ == "__main__":
    unittest.main()
