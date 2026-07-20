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
from backend.app.routers.configuration import router
from backend.app.schemas import ExecutionModeResponse


class DummyDb:
    pass


class ConfigurationExecutionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )
        self.app.dependency_overrides[get_db] = lambda: DummyDb()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.client.close()

    def test_get_execution_settings_returns_runtime_mode(self):
        payload = ExecutionModeResponse(
            paper_trading_enabled=True,
            live_trading_enabled=False,
            effective_mode="PAPER_ONLY",
            zerodha_credentials_configured=True,
            zerodha_session_present=True,
            zerodha_access_token_expires_at=None,
        )

        with patch("backend.app.routers.configuration.get_execution_mode_payload", return_value=payload):
            response = self.client.get("/configuration/execution-settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["effective_mode"], "PAPER_ONLY")

    def test_enable_live_trading_requires_zerodha_session(self):
        with (
            patch("backend.app.routers.configuration.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.routers.configuration.get_current_zerodha_session", return_value=None),
        ):
            response = self.client.post("/configuration/execution-settings", json={"live_trading_enabled": True})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Connect Zerodha before enabling live trading")


if __name__ == "__main__":
    unittest.main()
