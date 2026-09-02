# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))
from s07_morning_live_orders_v1 import S07MLiveOrders


class FakeClient:
    def __init__(self):
        self.orders = []

    def account_info(self, tag):
        return {"status": "OK", "data": {"accounts": ["12345678"]}}

    def balance_tr(self, *args, **kwargs):
        return {"status": "OK", "data": {"records": []}}

    def send_order_real(self, **kwargs):
        self.orders.append(kwargs)
        return {"status": "OK"}


class S07MLiveOrderWiringTest(unittest.TestCase):
    def test_buy_is_one_share_best_price_with_fixed_key(self):
        fake = FakeClient()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            live = S07MLiveOrders("20260903", client=fake, account="12345678",
                                  audit_dir=root / "audit", state_path=root / "state.json",
                                  fills_dir=root / "fills", sleep_fn=lambda _: None)
            status = live._submit("006730", buy=True, hoga_gb="06", stage="ENTRY_06")
        self.assertEqual(status, "OK")
        self.assertEqual(fake.orders[0]["qty"], 1)
        self.assertEqual(fake.orders[0]["order_type"], 1)
        self.assertEqual(fake.orders[0]["hoga_gb"], "06")
        self.assertEqual(fake.orders[0]["idempotency_key"], "s07m_buy_20260903_006730")


if __name__ == "__main__":
    unittest.main()
