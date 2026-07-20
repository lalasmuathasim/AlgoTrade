# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import Instrument, TriggerLine
from backend.app.services.zerodha import SubscriptionManager


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, rows_per_call):
        self.rows_per_call = list(rows_per_call)

    def scalars(self, _query):
        rows = self.rows_per_call.pop(0) if self.rows_per_call else []
        return FakeScalarRows(rows)


class SubscriptionManagerTests(unittest.TestCase):
    def test_describe_active_subscriptions_uses_active_trigger_lines_only(self):
        selected_watchlist = SimpleNamespace(id=uuid.uuid4())
        instrument = Instrument(
            id=uuid.uuid4(),
            instrument_token=738561,
            tradingsymbol="RELIANCE",
            exchange="NSE",
            is_active=True,
        )
        line = TriggerLine(
            id=uuid.uuid4(),
            watchlist_id=selected_watchlist.id,
            instrument_id=instrument.id,
            exchange="NSE",
            symbol="RELIANCE",
            line_status="ACTIVE",
            line_type="BUY",
            line_price=100.0,
        )
        db = FakeSession([[instrument], [line]])

        with patch("backend.app.services.zerodha.get_selected_watchlist", return_value=selected_watchlist):
            subscriptions = SubscriptionManager().describe_active_subscriptions(db)

        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions[0]["instrument_token"], 738561)
        self.assertEqual(subscriptions[0]["symbol"], "RELIANCE")
        self.assertEqual(subscriptions[0]["source"], "TRIGGER_LINE")


if __name__ == "__main__":
    unittest.main()
