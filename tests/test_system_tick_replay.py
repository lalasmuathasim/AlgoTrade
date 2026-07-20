# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.dependencies import require_admin_user
from backend.app.models import TradingSignal
from backend.app.routers.system import router


class _DummyDb:
    pass


class SystemTickReplayTests(unittest.TestCase):
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

    def test_tick_replay_returns_processing_summary(self):
        client = TestClient(self.app)
        signal = TradingSignal(id=uuid.uuid4(), exchange="NSE", symbol="RELIANCE", action="BUY")
        finalized_candle = SimpleNamespace(
            symbol="RELIANCE",
            exchange="NSE",
            candle_start=datetime.fromisoformat("2026-07-20T03:45:00+00:00"),
            candle_end=datetime.fromisoformat("2026-07-20T03:48:00+00:00"),
            open=100.0,
            high=103.0,
            low=99.5,
            close=102.0,
            volume=3000.0,
        )
        fake_result = SimpleNamespace(
            ticks_processed=4,
            finalized_candles_count=1,
            signals_created_count=1,
            finalized_candles=[finalized_candle],
            signals=[signal],
        )

        from unittest.mock import patch

        with patch("backend.app.routers.system.MarketDataProcessor.process_ticks", return_value=fake_result):
            response = client.post(
                "/system/ticks/replay",
                json={
                    "ticks": [
                        {
                            "instrument_token": 111,
                            "symbol": "RELIANCE",
                            "exchange": "NSE",
                            "timestamp": "2026-07-20T09:15:00+05:30",
                            "last_price": 100.0,
                            "volume_traded": 1000,
                        }
                    ]
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["ticks_processed"], 4)
        self.assertEqual(payload["finalized_candles_count"], 1)
        self.assertEqual(payload["signals_created"], 1)
        self.assertEqual(payload["signal_ids"], [str(signal.id)])
        self.assertEqual(payload["last_finalized_candle"]["symbol"], "RELIANCE")
        client.close()


if __name__ == "__main__":
    unittest.main()
