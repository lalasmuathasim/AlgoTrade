# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.routers.configuration import _readiness_payload


class _FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self):
        self.scalar_values = iter([0, 0, None])
        self.scalar_row_values = iter([[], []])

    def scalar(self, _query):
        return next(self.scalar_values)

    def scalars(self, _query):
        return _FakeScalarRows(next(self.scalar_row_values))


class ConfigurationReadinessTests(unittest.TestCase):
    def test_readiness_payload_uses_published_live_engine_runtime(self):
        session = _FakeSession()
        published_watchlist_id = str(uuid.uuid4())

        with (
            patch("backend.app.routers.configuration.verify_database_connectivity"),
            patch("backend.app.routers.configuration.check_redis_connectivity", return_value=True),
            patch("backend.app.routers.configuration.get_current_zerodha_session", return_value=None),
            patch("backend.app.routers.configuration.ensure_selected_watchlist", return_value=None),
            patch("backend.app.routers.configuration.SubscriptionManager.get_active_subscriptions", return_value=[]),
            patch("backend.app.routers.configuration.get_live_engine_runtime", return_value={
                "status": "STREAMING",
                "message": "Ticks are flowing.",
                "transport": "kite_ticker",
                "selected_watchlist": {"id": published_watchlist_id, "name": "Runtime Selected", "exchange": "NSE"},
                "subscription_count": 3,
                "subscriptions": [],
                "credentials_configured": True,
                "access_token_configured": True,
                "last_tick_at": "2026-07-20T09:18:00+00:00",
                "last_tick_symbol": "NSE:RELIANCE",
                "finalized_candles_count": 4,
                "signals_created_count": 2,
                "last_finalized_candle": {"symbol": "RELIANCE", "exchange": "NSE"},
                "last_signal_id": str(uuid.uuid4()),
                "last_signal_symbol": "RELIANCE",
                "published_at": "2026-07-20T09:18:02+00:00",
            }),
        ):
            payload = _readiness_payload(session)

        self.assertTrue(payload["database_connected"])
        self.assertEqual(payload["live_engine_runtime"]["status"], "STREAMING")
        self.assertEqual(payload["live_engine_runtime"]["subscription_count"], 3)
        self.assertEqual(payload["live_engine_runtime"]["signals_created_count"], 2)
        self.assertEqual(payload["live_engine_runtime"]["selected_watchlist"]["name"], "Runtime Selected")

    def test_readiness_payload_builds_fallback_live_engine_runtime(self):
        session = _FakeSession()
        selected_watchlist = SimpleNamespace(id=uuid.uuid4(), name="Fallback Watchlist", exchange="NSE")

        with (
            patch("backend.app.routers.configuration.verify_database_connectivity"),
            patch("backend.app.routers.configuration.check_redis_connectivity", return_value=False),
            patch("backend.app.routers.configuration.get_current_zerodha_session", return_value=None),
            patch("backend.app.routers.configuration.ensure_selected_watchlist", return_value=selected_watchlist),
            patch("backend.app.routers.configuration.SubscriptionManager.get_active_subscriptions", return_value=[]),
            patch(
                "backend.app.routers.configuration.SubscriptionManager.describe_active_subscriptions",
                return_value=[{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
            ),
            patch("backend.app.routers.configuration.get_live_engine_runtime", return_value=None),
            patch("backend.app.routers.configuration.ZerodhaAuthService.has_credentials", return_value=True),
        ):
            payload = _readiness_payload(session)

        self.assertFalse(payload["redis_connected"])
        self.assertEqual(payload["live_engine_runtime"]["status"], "NOT_PUBLISHED")
        self.assertEqual(payload["live_engine_runtime"]["subscription_count"], 1)
        self.assertEqual(payload["live_engine_runtime"]["selected_watchlist"]["name"], "Fallback Watchlist")
        self.assertIsNone(payload["live_engine_runtime"]["published_at"])


if __name__ == "__main__":
    unittest.main()
