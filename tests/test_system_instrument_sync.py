# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from tests.support import configure_test_env

configure_test_env()

from backend.app.routers.system import _resolve_instrument_sync_scope, sync_instruments
from backend.app.schemas import InstrumentSyncRequest


class _DummyScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DummyDb:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, _query):
        return _DummyScalarResult(self._rows)


class SystemInstrumentSyncTests(unittest.TestCase):
    def test_resolve_instrument_sync_scope_groups_symbols_by_exchange(self):
        rows = [
            SimpleNamespace(symbol="reliance", exchange="NSE"),
            SimpleNamespace(symbol="INFY", exchange="NSE"),
            SimpleNamespace(symbol="tatamotors", exchange="BSE"),
        ]
        db = _DummyDb(rows)

        with patch("backend.app.routers.system.get_selected_watchlist", return_value=None):
            scope = _resolve_instrument_sync_scope(db)

        self.assertEqual(scope, {"NSE": {"RELIANCE", "INFY"}, "BSE": {"TATAMOTORS"}})

    def test_sync_instruments_uses_scoped_sync_by_default(self):
        db = _DummyDb([])
        watchlist_id = uuid.uuid4()

        with (
            patch("backend.app.routers.system.get_current_zerodha_access_token", return_value="token"),
            patch("backend.app.routers.system._resolve_instrument_sync_scope", return_value={"NSE": {"RELIANCE"}}) as scope_mock,
            patch("backend.app.routers.system.InstrumentMasterSyncService.sync_watchlist_scope", return_value=1) as sync_scope_mock,
        ):
            response = sync_instruments(InstrumentSyncRequest(watchlist_id=watchlist_id), db=db)

        scope_mock.assert_called_once_with(db, watchlist_id=watchlist_id)
        sync_scope_mock.assert_called_once()
        self.assertEqual(response.synced, 1)

    def test_sync_instruments_returns_503_for_runtime_error(self):
        db = _DummyDb([])

        with (
            patch("backend.app.routers.system.get_current_zerodha_access_token", return_value="token"),
            patch("backend.app.routers.system._resolve_instrument_sync_scope", return_value={"NSE": {"RELIANCE"}}),
            patch(
                "backend.app.routers.system.InstrumentMasterSyncService.sync_watchlist_scope",
                side_effect=RuntimeError("Zerodha API key or access token is not configured"),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                sync_instruments(InstrumentSyncRequest(), db=db)

        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, "Zerodha API key or access token is not configured")


if __name__ == "__main__":
    unittest.main()
