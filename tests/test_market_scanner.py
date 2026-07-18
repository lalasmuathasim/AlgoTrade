# ruff: noqa: E402
from __future__ import annotations

from datetime import datetime
import unittest
import uuid

from tests.support import configure_test_env

configure_test_env()

from backend.app.models import TriggerLine, WatchlistSymbol
from backend.app.schemas import HistoricalCandlePayload
from backend.app.services.market_scanner import DailyMarketScanner, SwingDetector, UntouchedLevelValidator


class FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, scalars_queue):
        self.scalars_queue = list(scalars_queue)
        self.added = []
        self.committed = False
        self.flushed = False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed = True

    def commit(self):
        self.committed = True

    def scalars(self, _query):
        return FakeScalarRows(self.scalars_queue.pop(0))


def build_daily_fixture() -> list[HistoricalCandlePayload]:
    rows = [
        ("2026-07-01T00:00:00+00:00", 95, 100, 90, 96, 1000),
        ("2026-07-02T00:00:00+00:00", 96, 108, 94, 105, 1100),
        ("2026-07-03T00:00:00+00:00", 105, 102, 96, 98, 1050),
        ("2026-07-04T00:00:00+00:00", 98, 103, 95, 101, 1025),
        ("2026-07-05T00:00:00+00:00", 101, 107, 97, 104, 1150),
        ("2026-07-06T00:00:00+00:00", 104, 103, 92, 94, 1500),
        ("2026-07-07T00:00:00+00:00", 94, 99, 89, 92, 1250),
        ("2026-07-08T00:00:00+00:00", 92, 107.2, 92, 104, 1600),
        ("2026-07-09T00:00:00+00:00", 104, 104.4, 89.2, 95, 1400),
        ("2026-07-10T00:00:00+00:00", 95, 101, 91, 99, 1300),
    ]
    return [
        HistoricalCandlePayload(
            timestamp=datetime.fromisoformat(timestamp),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for timestamp, open_, high, low, close, volume in rows
    ]


class MarketScannerTests(unittest.TestCase):
    def test_swing_detector_finds_highs_and_lows(self):
        candles = build_daily_fixture()
        detector = SwingDetector(window=1)
        highs, lows = detector.detect(candles)

        self.assertGreaterEqual(len(highs), 2)
        self.assertGreaterEqual(len(lows), 2)
        self.assertEqual(highs[0].kind, "HIGH")
        self.assertEqual(lows[0].kind, "LOW")

    def test_untouched_level_validator_builds_buy_and_sell_candidates(self):
        candles = build_daily_fixture()
        detector = SwingDetector(window=1)
        highs, lows = detector.detect(candles)
        validator = UntouchedLevelValidator()

        candidates = validator.build_candidates("RELIANCE", "NSE", candles, highs, lows)
        line_types = {candidate.line_type for candidate in candidates}

        self.assertIn("BUY", line_types)
        self.assertIn("SELL", line_types)
        self.assertTrue(all(candidate.level_key for candidate in candidates))

    def test_daily_scanner_uses_mocked_historical_provider(self):
        candles = build_daily_fixture()

        class Provider:
            def fetch_last_n_completed_daily_candles(self, symbol, instrument_token, count):
                self.request = (symbol, instrument_token, count)
                return candles

        provider = Provider()
        scanner = DailyMarketScanner(provider=provider)
        symbol = WatchlistSymbol(
            id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            exchange="NSE",
            symbol="RELIANCE",
            instrument_token=12345,
            is_active=True,
        )
        db = FakeSession([[symbol], []])

        execution = scanner.run(db, dry_run=False)

        created_lines = [row for row in db.added if isinstance(row, TriggerLine)]
        self.assertEqual(execution.status, "COMPLETED")
        self.assertEqual(provider.request, ("RELIANCE", 12345, 100))
        self.assertTrue(db.committed)
        self.assertGreaterEqual(len(created_lines), 1)


if __name__ == "__main__":
    unittest.main()
