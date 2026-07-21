# ruff: noqa: E402
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.queue import describe_redis_url, get_live_engine_runtime, publish_live_engine_runtime, redis_diagnostics


class RedisConfigurationTests(unittest.TestCase):
    def test_describe_redis_url_returns_sanitized_host_port_and_db(self):
        details = describe_redis_url("redis://:super-secret@host.docker.internal:6379/2")

        self.assertEqual(details["scheme"], "redis")
        self.assertEqual(details["host"], "host.docker.internal")
        self.assertEqual(details["port"], 6379)
        self.assertEqual(details["db"], 2)
        self.assertNotIn("super-secret", str(details))

    def test_redis_diagnostics_reports_connectivity_without_credentials(self):
        fake_client = type("FakeClient", (), {"ping": lambda self: True})()

        with (
            patch("backend.app.queue.settings.redis_url", "redis://:super-secret@host.docker.internal:6379/2"),
            patch("backend.app.queue.get_redis_client", return_value=fake_client),
        ):
            diagnostics = redis_diagnostics()

        self.assertTrue(diagnostics["connected"])
        self.assertEqual(diagnostics["host"], "host.docker.internal")
        self.assertEqual(diagnostics["port"], 6379)
        self.assertEqual(diagnostics["db"], 2)
        self.assertNotIn("super-secret", str(diagnostics))

    def test_publish_live_engine_runtime_does_not_raise_when_redis_is_unavailable(self):
        fake_client = type("FakeClient", (), {"set": lambda self, *args, **kwargs: (_ for _ in ()).throw(ConnectionError("down"))})()

        with (
            patch("backend.app.queue.settings.redis_url", "redis://:super-secret@host.docker.internal:6379/12"),
            patch("backend.app.queue.get_redis_client", return_value=fake_client),
        ):
            payload = publish_live_engine_runtime({"status": "STREAMING"})

        self.assertEqual(payload["status"], "STREAMING")
        self.assertIn("published_at", payload)

    def test_get_live_engine_runtime_returns_none_when_redis_is_unavailable(self):
        fake_client = type("FakeClient", (), {"get": lambda self, *args, **kwargs: (_ for _ in ()).throw(ConnectionError("down"))})()

        with (
            patch("backend.app.queue.settings.redis_url", "redis://:super-secret@host.docker.internal:6379/12"),
            patch("backend.app.queue.get_redis_client", return_value=fake_client),
        ):
            payload = get_live_engine_runtime()

        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
