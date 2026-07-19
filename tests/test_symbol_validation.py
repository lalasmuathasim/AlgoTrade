# ruff: noqa: E402
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from tests.support import configure_test_env

configure_test_env()

from backend.app.routers.configuration import _symbol_validation_result
from backend.app.schemas import InstrumentPayload


class SymbolValidationTests(unittest.TestCase):
    def test_symbol_validation_uses_zerodha_instruments_instead_of_local_db(self):
        instruments = [
            InstrumentPayload(
                instrument_token=738561,
                tradingsymbol="RELIANCE",
                exchange="NSE",
                name="RELIANCE INDUSTRIES",
                segment="NSE",
                instrument_type="EQ",
            ),
            InstrumentPayload(
                instrument_token=779521,
                tradingsymbol="AXISBANK",
                exchange="NSE",
                name="AXIS BANK",
                segment="NSE",
                instrument_type="EQ",
            ),
        ]

        with patch(
            "backend.app.routers.configuration.ZerodhaApiClient.fetch_exchange_instruments",
            return_value=instruments,
        ):
            result = _symbol_validation_result(db=None, exchange="NSE", parsed_symbols=["RELIANCE", "INVALID", "AXISBANK"])

        self.assertEqual(result["source"], "zerodha")
        self.assertEqual(result["valid_symbols"], ["RELIANCE", "AXISBANK"])
        self.assertEqual(result["invalid_symbols"], ["INVALID"])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["invalid_count"], 1)
        self.assertEqual(result["instrument_matches"][0]["instrument_token"], 738561)

    def test_symbol_validation_requires_zerodha_configuration(self):
        with patch(
            "backend.app.routers.configuration.ZerodhaAuthService.has_credentials",
            return_value=False,
        ):
            with self.assertRaises(HTTPException) as context:
                _symbol_validation_result(db=None, exchange="NSE", parsed_symbols=["RELIANCE"])

        self.assertEqual(context.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
