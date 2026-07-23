# ruff: noqa: E402
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import ScanExecution
from backend.app.scheduler import _run_due_scan, _scheduled_scan_time, _should_run


class FakeSchedulerDb:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)
        self.added = []
        self.commit_count = 0

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1


class SchedulerTests(unittest.TestCase):
    def test_scheduler_uses_runtime_rebuild_time(self):
        runtime_settings = SimpleNamespace(daily_structure_rebuild_time="15:52")
        now_local = datetime.fromisoformat("2026-07-19T15:53:00+05:30")

        self.assertEqual(_scheduled_scan_time(runtime_settings), "15:52")
        self.assertTrue(_should_run(now_local, _scheduled_scan_time(runtime_settings)))

    def test_scheduler_skips_and_records_scan_when_credentials_are_missing(self):
        db = FakeSchedulerDb([None, None])
        scanner = SimpleNamespace(run=lambda *args, **kwargs: self.fail("scanner.run should not be called"))
        now_local = datetime.fromisoformat("2026-07-19T15:46:00+05:30")

        from unittest.mock import patch

        with (
            patch("backend.app.scheduler.settings.zerodha_api_key", None),
            patch("backend.app.scheduler.get_current_zerodha_session", return_value=None),
            patch("backend.app.scheduler.get_current_zerodha_access_token", return_value=None),
        ):
            result = _run_due_scan(db, now_local, scanner)

        self.assertEqual(result, "skipped")
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], ScanExecution)
        self.assertEqual(db.added[0].status, "SKIPPED")
        self.assertIn("ZERODHA_API_KEY", db.added[0].error_message or "")
        self.assertEqual(db.commit_count, 1)

    def test_scheduler_skips_and_records_scan_when_token_is_expired(self):
        db = FakeSchedulerDb([None, None])
        scanner = SimpleNamespace(run=lambda *args, **kwargs: self.fail("scanner.run should not be called"))
        now_local = datetime.fromisoformat("2026-07-19T15:46:00+05:30")
        expired_session = SimpleNamespace(
            access_token="expired-token",
            access_token_expires_at=now_local.astimezone(UTC) - timedelta(minutes=5),
        )

        from unittest.mock import patch

        with (
            patch("backend.app.scheduler.settings.zerodha_api_key", "kite-key"),
            patch("backend.app.scheduler.get_current_zerodha_session", return_value=expired_session),
            patch("backend.app.scheduler.get_current_zerodha_access_token", return_value="expired-token"),
        ):
            result = _run_due_scan(db, now_local, scanner)

        self.assertEqual(result, "skipped")
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].status, "SKIPPED")
        self.assertIn("expired", (db.added[0].error_message or "").lower())
        self.assertEqual(db.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
