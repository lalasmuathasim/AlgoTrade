# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from tests.support import configure_test_env

configure_test_env()

from backend.app.queue import _is_runtime_snapshot_stale


class QueueRuntimeTests(unittest.TestCase):
    def test_runtime_snapshot_with_fresh_published_at_is_not_stale(self):
        now = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
        payload = {
            "status": "STREAMING",
            "published_at": (now - timedelta(seconds=30)).isoformat(),
        }

        self.assertFalse(_is_runtime_snapshot_stale(payload, now=now))

    def test_runtime_snapshot_with_old_published_at_is_stale(self):
        now = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
        payload = {
            "status": "CLOSED",
            "published_at": (now - timedelta(minutes=10)).isoformat(),
        }

        self.assertTrue(_is_runtime_snapshot_stale(payload, now=now))

    def test_runtime_snapshot_without_published_at_uses_fallback_updated_at(self):
        now = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
        payload = {
            "status": "STREAMING",
        }

        self.assertTrue(
            _is_runtime_snapshot_stale(
                payload,
                fallback_updated_at=now - timedelta(minutes=10),
                now=now,
            )
        )
        self.assertFalse(
            _is_runtime_snapshot_stale(
                payload,
                fallback_updated_at=now - timedelta(seconds=20),
                now=now,
            )
        )


if __name__ == "__main__":
    unittest.main()
