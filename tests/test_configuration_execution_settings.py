# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.dependencies import require_admin_user
from backend.app.routers.configuration import router
from backend.app.schemas import ExecutionModeResponse, ExecutionRulesResponse


class DummyDb:
    pass


def build_execution_rules_payload() -> dict:
    return {
        "paper_trading_enabled": True,
        "live_trading_enabled": False,
        "require_candle_close_beyond_line": True,
        "entry_buffer_ticks": 0.05,
        "stop_loss_buffer_ticks": 0.05,
        "target_mode": "NEAREST_DAILY_SWING",
        "fallback_risk_reward_ratio": 2.0,
        "use_nearest_daily_swing_target": True,
        "minimum_reward_risk_ratio": 1.0,
        "order_type": "LIMIT",
        "product_type": "MIS",
        "reentry_cooldown_minutes": 0,
        "allow_repeat_entry_same_line": False,
        "default_quantity_mode": "RISK_BASED",
        "fixed_quantity": None,
        "capital_per_trade": 25000.0,
        "risk_per_trade": 2500.0,
        "max_quantity_per_order": None,
        "buy_volume_multiplier": 5.0,
        "sell_volume_multiplier": 3.0,
        "skip_zero_previous_volume": True,
        "minimum_price": None,
        "maximum_price": None,
        "allowed_exchanges": ["NSE", "BSE"],
        "max_trades_per_day": 3,
        "max_open_positions": 3,
        "max_daily_loss": 5000.0,
        "max_loss_per_symbol_per_day": 2500.0,
        "block_new_trades_after_max_daily_loss": True,
        "no_trade_after_time": "15:00",
        "market_hours_guard": True,
        "brokerage_estimate": 20.0,
        "slippage_estimate": 0.2,
        "exchange_charges_estimate": 0.0,
        "use_cost_adjusted_pnl": True,
        "enable_confidence_filter": False,
        "minimum_confidence_score": 0.6,
        "confidence_source": "RULES_ONLY",
        "allow_low_confidence_paper_trades_only": True,
        "block_live_trades_below_confidence_threshold": True,
    }


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

    def test_get_execution_settings_returns_fallback_when_runtime_settings_fail(self):
        with (
            patch(
                "backend.app.routers.configuration.get_execution_mode_payload",
                side_effect=SQLAlchemyError("column missing"),
            ),
            patch("backend.app.routers.configuration.get_current_zerodha_session", return_value=None),
        ):
            response = self.client.get("/configuration/execution-settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["effective_mode"], "PAPER_ONLY")

    def test_get_execution_rules_returns_runtime_payload(self):
        payload = ExecutionRulesResponse(
            id=uuid.uuid4(),
            created_at="2026-07-20T10:00:00Z",
            updated_at="2026-07-20T10:05:00Z",
            **build_execution_rules_payload(),
        )

        with patch("backend.app.routers.configuration.get_execution_rules_payload", return_value=payload):
            response = self.client.get("/configuration/execution-rules")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["target_mode"], "NEAREST_DAILY_SWING")
        self.assertEqual(response.json()["order_type"], "LIMIT")

    def test_get_execution_rules_returns_fallback_when_runtime_settings_fail(self):
        with patch(
            "backend.app.routers.configuration.get_execution_rules_payload",
            side_effect=SQLAlchemyError("column missing"),
        ):
            response = self.client.get("/configuration/execution-rules")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["target_mode"], "NEAREST_DAILY_SWING")
        self.assertEqual(response.json()["allowed_exchanges"], ["NSE", "BSE"])

    def test_save_execution_rules_rejects_empty_allowed_exchanges(self):
        payload = build_execution_rules_payload()
        payload["allowed_exchanges"] = []

        response = self.client.post("/configuration/execution-rules", json=payload)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Select at least one allowed exchange")


if __name__ == "__main__":
    unittest.main()
