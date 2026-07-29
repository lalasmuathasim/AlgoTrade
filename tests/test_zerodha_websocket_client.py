# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.schemas import TickPayload
from backend.app.services.zerodha import ZerodhaWebSocketClient


class _FakeKiteTicker:
    MODE_FULL = "full"

    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.subscribed = []
        self.mode_calls = []
        self.on_connect = None
        self.on_ticks = None
        self.on_error = None
        self.on_close = None
        self.on_reconnect = None
        self.on_noreconnect = None

    def subscribe(self, instrument_tokens):
        self.subscribed.append(list(instrument_tokens))

    def set_mode(self, mode, instrument_tokens):
        self.mode_calls.append((mode, list(instrument_tokens)))

    def connect(self, threaded=False):
        if self.on_connect:
            self.on_connect(self, {"status": "connected"})
        if self.on_ticks:
            self.on_ticks(
                self,
                [
                    {
                        "instrument_token": 111,
                        "last_price": 1525.5,
                        "volume_traded": 6200,
                        "exchange_timestamp": datetime.fromisoformat("2026-07-20T10:03:00+05:30"),
                    }
                ],
            )
        if self.on_close:
            self.on_close(self, 1000, "closed")


class _FakeKiteModule:
    KiteTicker = _FakeKiteTicker


class _FakeNaiveTickKiteTicker(_FakeKiteTicker):
    def connect(self, threaded=False):
        if self.on_connect:
            self.on_connect(self, {"status": "connected"})
        if self.on_ticks:
            self.on_ticks(
                self,
                [
                    {
                        "instrument_token": 111,
                        "last_price": 1525.5,
                        "volume_traded": 6200,
                        "exchange_timestamp": datetime(2026, 7, 20, 10, 3, 0),
                    }
                ],
            )
        if self.on_close:
            self.on_close(self, 1000, "closed")


class _FakeNaiveTickKiteModule:
    KiteTicker = _FakeNaiveTickKiteTicker


class _FakeAuthFailureKiteTicker(_FakeKiteTicker):
    def __init__(self, api_key, access_token):
        super().__init__(api_key, access_token)
        self.stop_called = False
        self.stop_retry_called = False

    def stop(self):
        self.stop_called = True

    def stop_retry(self):
        self.stop_retry_called = True

    def connect(self, threaded=False):
        if self.on_error:
            self.on_error(self, 1006, "connection was closed uncleanly (WebSocket connection upgrade failed (403 - Forbidden))")
        if self.on_close:
            self.on_close(self, 1006, "connection was closed uncleanly (WebSocket connection upgrade failed (403 - Forbidden))")
        if self.on_noreconnect:
            self.on_noreconnect(self)


class _FakeAuthFailureKiteModule:
    KiteTicker = _FakeAuthFailureKiteTicker


class ZerodhaWebSocketClientTests(unittest.TestCase):
    def test_connect_forever_returns_idle_when_no_subscriptions(self):
        client = ZerodhaWebSocketClient()

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
        ):
            result = client.connect_forever([], lambda ticks: None)

        self.assertEqual(result["status"], "IDLE_NO_SUBSCRIPTIONS")

    def test_connect_forever_returns_dependency_missing_when_kiteconnect_is_unavailable(self):
        client = ZerodhaWebSocketClient()

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
            patch("backend.app.services.zerodha.import_module", side_effect=ModuleNotFoundError("kiteconnect")),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda ticks: None,
            )

        self.assertEqual(result["status"], "IDLE_DEPENDENCY_MISSING")

    def test_connect_forever_uses_kiteticker_and_normalizes_ticks(self):
        client = ZerodhaWebSocketClient()
        captured_ticks: list[list[TickPayload]] = []
        state_updates: list[dict] = []

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.resolve_access_token", return_value="token"),
            patch("backend.app.services.zerodha.settings.zerodha_api_key", "api-key"),
            patch("backend.app.services.zerodha.import_module", return_value=_FakeKiteModule()),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda ticks: captured_ticks.append(ticks),
                on_state_change=lambda state: state_updates.append(state),
            )

        self.assertEqual(state_updates[0]["status"], "CONNECTING")
        self.assertTrue(any(state["status"] == "CONNECTED_SUBSCRIBED" for state in state_updates))
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(len(captured_ticks), 1)
        self.assertEqual(captured_ticks[0][0].symbol, "RELIANCE")
        self.assertEqual(captured_ticks[0][0].exchange, "NSE")
        self.assertEqual(captured_ticks[0][0].last_price, 1525.5)
        self.assertEqual(captured_ticks[0][0].volume_traded, 6200.0)

    def test_connect_forever_accepts_explicit_access_token_when_env_token_is_absent(self):
        client = ZerodhaWebSocketClient()
        captured_ticks: list[list[TickPayload]] = []

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", side_effect=lambda token=None: bool(token)),
            patch("backend.app.services.zerodha.ZerodhaAuthService.resolve_access_token", side_effect=lambda token=None: token),
            patch("backend.app.services.zerodha.settings.zerodha_api_key", "api-key"),
            patch("backend.app.services.zerodha.import_module", return_value=_FakeKiteModule()),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda ticks: captured_ticks.append(ticks),
                access_token="db-session-token",
            )

        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(len(captured_ticks), 1)

    def test_connect_forever_normalizes_naive_tick_timestamp_using_trading_timezone(self):
        client = ZerodhaWebSocketClient()
        captured_ticks: list[list[TickPayload]] = []

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.resolve_access_token", return_value="token"),
            patch("backend.app.services.zerodha.settings.zerodha_api_key", "api-key"),
            patch("backend.app.services.zerodha.import_module", return_value=_FakeNaiveTickKiteModule()),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda ticks: captured_ticks.append(ticks),
            )

        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(len(captured_ticks), 1)
        self.assertEqual(captured_ticks[0][0].timestamp.tzinfo, UTC)
        self.assertEqual(captured_ticks[0][0].timestamp.isoformat(), "2026-07-20T04:33:00+00:00")

    def test_connect_forever_continues_when_tick_handler_raises(self):
        client = ZerodhaWebSocketClient()
        state_updates: list[dict] = []

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.resolve_access_token", return_value="token"),
            patch("backend.app.services.zerodha.settings.zerodha_api_key", "api-key"),
            patch("backend.app.services.zerodha.import_module", return_value=_FakeKiteModule()),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda _ticks: (_ for _ in ()).throw(RuntimeError("boom")),
                on_state_change=lambda state: state_updates.append(state),
            )

        self.assertTrue(any(state["status"] == "TICK_PROCESSING_ERROR" for state in state_updates))
        self.assertEqual(result["status"], "CLOSED")

    def test_connect_forever_marks_auth_failed_and_stops_retries_on_403(self):
        client = ZerodhaWebSocketClient()
        state_updates: list[dict] = []

        with (
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_credentials", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.has_access_token", return_value=True),
            patch("backend.app.services.zerodha.ZerodhaAuthService.resolve_access_token", return_value="token"),
            patch("backend.app.services.zerodha.settings.zerodha_api_key", "api-key"),
            patch("backend.app.services.zerodha.import_module", return_value=_FakeAuthFailureKiteModule()),
        ):
            result = client.connect_forever(
                [{"instrument_token": 111, "exchange": "NSE", "symbol": "RELIANCE", "source": "WATCHLIST"}],
                lambda _ticks: None,
                on_state_change=lambda state: state_updates.append(state),
            )

        self.assertEqual(result["status"], "AUTH_FAILED")
        self.assertTrue(any(state["status"] == "AUTH_FAILED" for state in state_updates))


if __name__ == "__main__":
    unittest.main()
