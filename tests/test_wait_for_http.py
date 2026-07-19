# ruff: noqa: E402
from __future__ import annotations

import unittest
from urllib.error import URLError

from scripts.wait_for_http import wait_for_url


class WaitForHttpTests(unittest.TestCase):
    def test_wait_for_url_retries_until_success(self):
        attempts = {"count": 0}

        def fetcher(_url: str) -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise URLError("connection reset")
            return '{"status":"ok"}'

        body = wait_for_url(
            "http://127.0.0.1:8095/health",
            timeout_seconds=1.0,
            interval_seconds=0.0,
            fetcher=fetcher,
        )

        self.assertEqual(body, '{"status":"ok"}')
        self.assertEqual(attempts["count"], 3)

    def test_wait_for_url_times_out_after_retries(self):
        def fetcher(_url: str) -> str:
            raise URLError("still booting")

        with self.assertRaises(TimeoutError):
            wait_for_url(
                "http://127.0.0.1:8095/health",
                timeout_seconds=0.01,
                interval_seconds=0.0,
                fetcher=fetcher,
            )


if __name__ == "__main__":
    unittest.main()
