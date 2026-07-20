# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.dependencies import require_admin_user
from backend.app.routers.system import router


class _DummyDb:
    pass


class SystemLiveEngineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )
        self.app.dependency_overrides[get_db] = lambda: _DummyDb()

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_live_engine_runtime_returns_published_snapshot(self):
        client = TestClient(self.app)

        with patch(
            "backend.app.routers.system.get_live_engine_runtime",
            return_value={
                "status": "SUBSCRIPTION_PLAN_READY",
                "message": "Prepared 4 instrument subscriptions for the selected watchlist.",
                "transport": "placeholder",
                "selected_watchlist": {"id": str(uuid.uuid4()), "name": "Selected", "exchange": "NSE"},
                "subscription_count": 4,
                "subscriptions": [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                "credentials_configured": True,
                "access_token_configured": True,
                "last_tick_at": None,
                "last_tick_symbol": None,
                "published_at": "2026-07-20T12:00:00+00:00",
            },
        ):
            response = client.get("/system/live-engine/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "SUBSCRIPTION_PLAN_READY")
        self.assertEqual(payload["subscription_count"], 4)
        self.assertEqual(payload["selected_watchlist"]["name"], "Selected")
        client.close()

    def test_live_engine_runtime_builds_fallback_when_no_snapshot_is_published(self):
        selected_watchlist = SimpleNamespace(id=uuid.uuid4(), name="Fallback", exchange="NSE")
        client = TestClient(self.app)

        with (
            patch("backend.app.routers.system.get_live_engine_runtime", return_value=None),
            patch("backend.app.routers.system.get_selected_watchlist", return_value=selected_watchlist),
            patch(
                "backend.app.routers.system.SubscriptionManager.describe_active_subscriptions",
                return_value=[{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
            ),
            patch("backend.app.routers.system.get_current_zerodha_access_token", return_value="token"),
        ):
            response = client.get("/system/live-engine/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "NOT_PUBLISHED")
        self.assertEqual(payload["subscription_count"], 1)
        self.assertEqual(payload["selected_watchlist"]["name"], "Fallback")
        self.assertTrue(payload["access_token_configured"])
        client.close()


if __name__ == "__main__":
    unittest.main()
