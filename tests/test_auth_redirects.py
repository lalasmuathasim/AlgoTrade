# ruff: noqa: E402
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.main import app


class DummyDb:
    pass


class AuthRedirectTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_db] = lambda: DummyDb()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_browser_dashboard_request_redirects_to_home_when_auth_is_missing(self):
        with (
            patch("backend.app.main.initialize_runtime_state", return_value=None),
            TestClient(app) as client,
        ):
            response = client.get(
                "/dashboard",
                headers={"accept": "text/html"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/?auth_status=auth_required")

    def test_browser_dashboard_request_redirects_to_home_when_session_is_invalid(self):
        with (
            patch("backend.app.main.initialize_runtime_state", return_value=None),
            TestClient(app) as client,
        ):
            response = client.get(
                "/dashboard",
                headers={"accept": "text/html"},
                cookies={"trading_session": "invalid-session-token"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/?auth_status=session_expired")

    def test_api_request_still_returns_json_for_auth_failure(self):
        with (
            patch("backend.app.main.initialize_runtime_state", return_value=None),
            TestClient(app) as client,
        ):
            response = client.get(
                "/configuration/readiness",
                headers={"accept": "application/json"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication required"})


if __name__ == "__main__":
    unittest.main()
