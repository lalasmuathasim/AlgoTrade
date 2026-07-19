# ruff: noqa: E402
from __future__ import annotations

import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import Watchlist
from backend.app.services.watchlists import set_selected_watchlist


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, watchlists):
        self.watchlists = watchlists
        self.committed = False
        self.refreshed = None

    def scalars(self, _query):
        return FakeScalarRows(self.watchlists)

    def commit(self):
        self.committed = True

    def refresh(self, watchlist):
        self.refreshed = watchlist


class WatchlistSelectionTests(unittest.TestCase):
    def test_set_selected_watchlist_marks_only_target_as_selected(self):
        first = Watchlist(id=uuid.uuid4(), name="Watchlist A", exchange="NSE", is_selected=True)
        second = Watchlist(id=uuid.uuid4(), name="Watchlist B", exchange="NSE", is_selected=False)
        session = FakeSession([first, second])

        selected = set_selected_watchlist(session, second)

        self.assertFalse(first.is_selected)
        self.assertTrue(second.is_selected)
        self.assertTrue(session.committed)
        self.assertIs(session.refreshed, second)
        self.assertIs(selected, second)


if __name__ == "__main__":
    unittest.main()
