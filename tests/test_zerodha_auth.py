# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import configure_test_env

configure_test_env()

from backend.app.database import get_db
from backend.app.dependencies import require_admin_user
from backend.app.models import ZerodhaSession
from backend.app.routers.zerodha import router
from backend.app.services.zerodha import ZerodhaAuthService


class DummyDb:
    pass


class ZerodhaAuthTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_db] = lambda: DummyDb()
        self.app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(),
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.client.close()

    def test_exchange_request_token_posts_expected_checksum_payload(self):
        auth = ZerodhaAuthService()
        request_token = "request-token-123"

        with patch("backend.app.services.zerodha.httpx.post") as mock_post:
            mock_post.return_value = SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "status": "success",
                    "data": {
                        "access_token": "access-token-abc",
                        "login_time": "2026-07-19 09:15:00",
                        "user_id": "AB1234",
                    },
                },
            )

            payload = auth.exchange_request_token(request_token)

        self.assertEqual(payload["access_token"], "access-token-abc")
        _, kwargs = mock_post.call_args
        self.assertEqual(mock_post.call_args.args[0], "https://api.kite.trade/session/token")
        self.assertEqual(kwargs["headers"], {"X-Kite-Version": "3"})
        self.assertEqual(kwargs["data"]["api_key"], "test-api-key")
        self.assertEqual(kwargs["data"]["request_token"], request_token)
        self.assertEqual(kwargs["data"]["checksum"], auth.build_session_checksum(request_token))

    def test_callback_exchanges_request_token_and_redirects_to_configuration(self):
        current_user_id = uuid.uuid4()
        self.app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
            id=current_user_id,
            role="ADMIN",
            approval_status="APPROVED",
            is_active=True,
        )

        with (
            patch(
                "backend.app.routers.zerodha.ZerodhaAuthService.exchange_request_token",
                return_value={
                    "access_token": "stored-access-token",
                    "login_time": "2026-07-19 09:15:00",
                    "user_id": "AB1234",
                    "user_name": "Admin User",
                    "email": "admin@example.com",
                },
            ) as mock_exchange,
            patch("backend.app.routers.zerodha.upsert_zerodha_session") as mock_upsert,
        ):
            response = self.client.get(
                "/api/zerodha/callback?request_token=request-token-123&status=success",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/configuration?zerodha_status=connected")
        mock_exchange.assert_called_once_with("request-token-123")
        self.assertEqual(mock_upsert.call_count, 1)
        self.assertEqual(mock_upsert.call_args.kwargs["access_token"], "stored-access-token")
        self.assertEqual(mock_upsert.call_args.kwargs["connected_by_user_id"], current_user_id)
        self.assertEqual(mock_upsert.call_args.kwargs["profile_user_id"], "AB1234")

    def test_connection_test_returns_connected_when_profile_is_valid(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="stored-access-token",
            status="CONNECTED",
            login_time=datetime.now(UTC) - timedelta(hours=1),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=8),
            profile_user_id="AB1234",
            profile_user_name="Admin User",
            profile_email="admin@example.com",
        )

        with (
            patch("backend.app.routers.zerodha.get_current_zerodha_session", return_value=session),
            patch(
                "backend.app.routers.zerodha.ZerodhaAuthService.fetch_user_profile",
                return_value={
                    "user_id": "AB1234",
                    "user_name": "Admin User",
                    "email": "admin@example.com",
                },
            ) as mock_profile,
            patch("backend.app.routers.zerodha.mark_zerodha_session_status") as mock_mark,
        ):
            response = self.client.get("/api/zerodha/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Connected")
        self.assertTrue(response.json()["connected"])
        self.assertTrue(response.json()["credentials_configured"])
        self.assertTrue(response.json()["can_connect"])
        self.assertTrue(response.json()["can_test_connection"])
        mock_profile.assert_called_once_with("stored-access-token")
        mock_mark.assert_called_once()

    def test_connection_test_returns_ready_to_connect_when_credentials_exist_but_no_session(self):
        with (
            patch("backend.app.routers.zerodha.get_current_zerodha_session", return_value=None),
            patch("backend.app.routers.zerodha.ZerodhaAuthService.resolve_access_token", return_value=None),
        ):
            response = self.client.get("/api/zerodha/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Ready To Connect")
        self.assertFalse(response.json()["connected"])
        self.assertTrue(response.json()["credentials_configured"])
        self.assertTrue(response.json()["can_connect"])
        self.assertFalse(response.json()["can_test_connection"])

    def test_connection_test_returns_expired_when_stored_token_is_past_expiry(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="stored-access-token",
            status="CONNECTED",
            login_time=datetime.now(UTC) - timedelta(days=1),
            access_token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        with (
            patch("backend.app.routers.zerodha.get_current_zerodha_session", return_value=session),
            patch("backend.app.routers.zerodha.mark_zerodha_session_status") as mock_mark,
        ):
            response = self.client.get("/api/zerodha/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Expired")
        self.assertFalse(response.json()["connected"])
        mock_mark.assert_called_once_with(unittest.mock.ANY, session, status="EXPIRED")

    def test_connection_test_returns_invalid_token_on_unauthorized_profile_check(self):
        session = ZerodhaSession(
            id=uuid.uuid4(),
            access_token="stored-access-token",
            status="CONNECTED",
            login_time=datetime.now(UTC) - timedelta(hours=1),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=8),
        )
        request = httpx.Request("GET", "https://api.kite.trade/user/profile")
        response = httpx.Response(403, request=request)
        error = httpx.HTTPStatusError("Forbidden", request=request, response=response)

        with (
            patch("backend.app.routers.zerodha.get_current_zerodha_session", return_value=session),
            patch(
                "backend.app.routers.zerodha.ZerodhaAuthService.fetch_user_profile",
                side_effect=error,
            ),
            patch("backend.app.routers.zerodha.mark_zerodha_session_status") as mock_mark,
        ):
            result = self.client.get("/api/zerodha/test")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "Invalid Token")
        self.assertFalse(result.json()["connected"])
        mock_mark.assert_called_once_with(unittest.mock.ANY, session, status="INVALID_TOKEN")


if __name__ == "__main__":
    unittest.main()
