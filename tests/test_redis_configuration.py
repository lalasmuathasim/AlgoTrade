# ruff: noqa: E402
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.queue import describe_redis_url, redis_diagnostics


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


if __name__ == "__main__":
    unittest.main()
