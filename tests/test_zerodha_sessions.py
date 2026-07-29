# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import ZerodhaSession
from backend.app.services.zerodha_sessions import get_usable_zerodha_access_token, is_zerodha_session_expired


class _SessionDb:
    def __init__(self, session: ZerodhaSession | None):
        self._session = session

    def scalar(self, _query):
        return self._session


class ZerodhaSessionHelpersTests(unittest.TestCase):
    def test_expired_session_is_detected(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="expired-token",
            access_token_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        self.assertTrue(is_zerodha_session_expired(session))

    def test_usable_access_token_prefers_active_database_session(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="fresh-db-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=8),
        )

        token = get_usable_zerodha_access_token(
            _SessionDb(session),
            fallback_token="env-fallback-token",
        )

        self.assertEqual(token, "fresh-db-token")

    def test_usable_access_token_returns_none_when_database_session_is_expired(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="expired-db-token",
            access_token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        token = get_usable_zerodha_access_token(
            _SessionDb(session),
            fallback_token="env-fallback-token",
        )

        self.assertIsNone(token)

    def test_usable_access_token_returns_none_when_no_active_token_exists(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="expired-db-token",
            access_token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        token = get_usable_zerodha_access_token(_SessionDb(session))

        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
