# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime
import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import PaperTradingSetting, TradingSignal
from backend.app.services.paper_trading_service import generate_paper_trade_from_signal


class FakeScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class FakeSession:
    def __init__(self, scalar_values, scalar_row_values):
        self.scalar_values = list(scalar_values)
        self.scalar_row_values = list(scalar_row_values)

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def scalars(self, _query):
        rows = self.scalar_row_values.pop(0) if self.scalar_row_values else []
        return FakeScalarRows(rows)

    def add(self, _obj):
        return None

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


class PaperExecutionTests(unittest.TestCase):
    def test_paper_trade_is_created_for_valid_signal(self):
        signal = TradingSignal(
            id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            action="BUY",
            trigger_line_id=uuid.uuid4(),
            entry_price=100.0,
            stop_loss=98.0,
            target=110.0,
            volume_ratio=6.0,
            created_at=datetime.now(UTC),
            raw_payload={},
        )
        settings = PaperTradingSetting(
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
            buy_volume_multiplier=5.0,
            sell_volume_multiplier=3.0,
            entry_buffer_ticks=0.05,
            stop_loss_buffer_ticks=0.05,
        )
        db = FakeSession([None, settings], [[]])

        trade = generate_paper_trade_from_signal(db, signal)

        self.assertIsNotNone(trade)
        self.assertEqual(trade.status, "OPEN")
        self.assertGreater(trade.quantity, 0)
        self.assertGreater(trade.capital_used, 0)


if __name__ == "__main__":
    unittest.main()
