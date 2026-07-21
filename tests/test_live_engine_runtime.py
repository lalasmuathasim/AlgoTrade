# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.services.live_engine_runtime import build_live_engine_runtime_snapshot
from backend.app.services.zerodha import SubscriptionManager


class _DummyScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DummyDb:
    def __init__(self, scalars_values):
        self.scalars_values = list(scalars_values)

    def scalars(self, _query):
        return _DummyScalarResult(self.scalars_values.pop(0))


class LiveEngineRuntimeTests(unittest.TestCase):
    def test_build_live_engine_runtime_snapshot_includes_subscription_context(self):
        watchlist = SimpleNamespace(id=uuid.uuid4(), name="NSE Core", exchange="NSE")

        payload = build_live_engine_runtime_snapshot(
            status="SUBSCRIPTION_PLAN_READY",
            message="Prepared 2 instrument subscriptions.",
            selected_watchlist=watchlist,
            subscriptions=[
                {"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"},
                {"instrument_token": 222, "exchange": "NSE", "symbol": "INFY", "source": "TRIGGER_LINE"},
            ],
            credentials_configured=True,
            access_token_configured=True,
        )

        self.assertEqual(payload["status"], "SUBSCRIPTION_PLAN_READY")
        self.assertEqual(payload["subscription_count"], 2)
        self.assertEqual(payload["selected_watchlist"]["name"], "NSE Core")
        self.assertTrue(payload["credentials_configured"])
        self.assertTrue(payload["access_token_configured"])
        self.assertEqual(payload["finalized_candles_count"], 0)
        self.assertEqual(payload["signals_created_count"], 0)

    def test_subscription_manager_describes_selected_watchlist_scope_without_duplicates(self):
        selected_watchlist = SimpleNamespace(id=uuid.uuid4(), name="Selected", exchange="NSE")
        instrument = SimpleNamespace(id=uuid.uuid4(), instrument_token=111, is_active=True)
        trigger_line = SimpleNamespace(
            watchlist_id=selected_watchlist.id,
            instrument_id=instrument.id,
            exchange="NSE",
            symbol="RELIANCE",
            line_status="ACTIVE",
        )
        db = _DummyDb([[instrument], [trigger_line]])

        with patch("backend.app.services.zerodha.get_selected_watchlist", return_value=selected_watchlist):
            subscriptions = SubscriptionManager().describe_active_subscriptions(db)

        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions[0]["instrument_token"], 111)
        self.assertEqual(subscriptions[0]["symbol"], "RELIANCE")
        self.assertEqual(subscriptions[0]["source"], "TRIGGER_LINE")


if __name__ == "__main__":
    unittest.main()
