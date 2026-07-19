# ruff: noqa: E402
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.support import configure_test_env

configure_test_env()

from backend.app.services.zerodha import ZerodhaApiClient


class ZerodhaInstrumentTests(unittest.TestCase):
    def test_fetch_exchange_instruments_parses_csv_dump(self):
        csv_payload = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
408065,1594,INFY,INFOSYS,0,,,0.05,1,EQ,NSE,NSE
738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,,0.05,1,EQ,NSE,NSE
"""

        with patch("backend.app.services.zerodha.httpx.get") as mock_get:
            mock_get.return_value = SimpleNamespace(
                text=csv_payload,
                raise_for_status=lambda: None,
            )

            instruments = ZerodhaApiClient().fetch_exchange_instruments("NSE")

        self.assertEqual(len(instruments), 2)
        self.assertEqual(instruments[0].tradingsymbol, "INFY")
        self.assertEqual(instruments[0].instrument_token, 408065)
        self.assertEqual(instruments[0].segment, "NSE")
        self.assertEqual(instruments[1].tradingsymbol, "RELIANCE")


if __name__ == "__main__":
    unittest.main()
