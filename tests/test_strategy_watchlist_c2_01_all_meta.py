# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


WATCHLIST = Path(r"C:\stock_bot\RUN\strategy_watchlist.py")


class StrategyWatchlistC201AllMetaTests(unittest.TestCase):
    def test_all_meta_covers_top_pool_without_expanding_legacy_meta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eod = root / "eod.csv"
            output = root / "captain2.json"
            self._write_eod(eod)
            spec = importlib.util.spec_from_file_location("watchlist_c2_01", WATCHLIST)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            module.EOD = eod
            module.OUT = root / "strategy.json"
            module.VALLEY_OUT = root / "valley.json"
            module.CAPTAIN2_OUT = output
            module.STRATEGY01_OUT = root / "strategy01.json"
            module.LOG = root / "watchlist.log"
            module.TOPN = 2
            module.CAPTAIN2_TOPN = 2
            module._market_caps = lambda: {}
            module.main()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["codes"]), 2)
            self.assertEqual(len(payload["all_meta"]), 2)
            self.assertEqual(len(payload["qualified_codes"]), 1)
            self.assertEqual(set(payload["meta"]), set(payload["qualified_codes"]))
            self.assertTrue(all(
                row["prev_close"] >= 10000
                for row in payload["all_meta"].values()
            ))

    @staticmethod
    def _write_eod(path: Path) -> None:
        fields = ["date", "code", "market", "close", "high", "value", "name"]
        start = date(2026, 6, 29)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for index in range(21):
                day = (start + timedelta(days=index)).strftime("%Y%m%d")
                writer.writerow({
                    "date": day, "code": "111110", "market": "KOSDAQ",
                    "close": 10000 + index * 100, "high": 12000 + index * 100,
                    "value": 10000 if index == 20 else 1000, "name": "통과",
                })
                writer.writerow({
                    "date": day, "code": "222220", "market": "KOSDAQ",
                    "close": 20000, "high": 20100,
                    "value": 2000, "name": "미통과",
                })


if __name__ == "__main__":
    unittest.main()
