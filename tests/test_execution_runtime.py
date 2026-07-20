# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import PaperTradingSetting, TradingSignal
from backend.app.services.execution_runtime import LiveExecutionService


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


def build_runtime_settings(*, live_trading_enabled: bool) -> PaperTradingSetting:
    return PaperTradingSetting(
        id=uuid.uuid4(),
        starting_capital=200000.0,
        capital_per_trade=25000.0,
        fixed_quantity=None,
        risk_per_trade=2500.0,
        brokerage_estimate=20.0,
        slippage_estimate=0.2,
        max_trades_per_day=3,
        max_daily_loss=5000.0,
        default_quantity_mode="RISK_BASED",
        live_trading_enabled=live_trading_enabled,
        buy_volume_multiplier=5.0,
        sell_volume_multiplier=3.0,
        entry_buffer_ticks=0.05,
        stop_loss_buffer_ticks=0.05,
        daily_candle_lookback=100,
        swing_window=2,
        max_gap_percent=0.5,
        min_swing_distance=1,
    )


class ExecutionRuntimeTests(unittest.TestCase):
    def test_live_execution_skips_when_runtime_live_toggle_is_disabled(self):
        signal = TradingSignal(
            id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            action="BUY",
            quantity=10,
            entry_price=100.5,
            stop_loss=99.5,
            target=108.0,
            raw_payload={},
        )
        db = FakeSession()

        with patch(
            "backend.app.services.execution_runtime.ensure_settings",
            return_value=build_runtime_settings(live_trading_enabled=False),
        ):
            order = LiveExecutionService().execute(db, signal)

        self.assertEqual(order.mode, "PAPER")
        self.assertEqual(order.status, "SKIPPED")
        self.assertEqual(order.response_payload["detail"], "Live Zerodha execution is disabled in configuration")

    def test_live_execution_places_zerodha_order_when_runtime_toggle_is_enabled(self):
        signal = TradingSignal(
            id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            action="BUY",
            quantity=10,
            entry_price=100.5,
            stop_loss=99.5,
            target=108.0,
            trigger_price=100.0,
            raw_payload={},
        )
        db = FakeSession()

        with (
            patch(
                "backend.app.services.execution_runtime.ensure_settings",
                return_value=build_runtime_settings(live_trading_enabled=True),
            ),
            patch("backend.app.services.execution_runtime.get_current_zerodha_access_token", return_value="access-token"),
            patch(
                "backend.app.services.execution_runtime.ZerodhaApiClient.place_regular_order",
                return_value={"order_id": "order-123"},
            ) as mock_place_order,
        ):
            order = LiveExecutionService().execute(db, signal)

        self.assertEqual(order.mode, "LIVE")
        self.assertEqual(order.status, "PLACED")
        self.assertEqual(order.broker_order_id, "order-123")
        self.assertEqual(order.request_payload["order_type"], "LIMIT")
        self.assertEqual(order.request_payload["product"], "MIS")
        mock_place_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
