import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "RUN"))
import bollinger_high_range30_shadow_v1 as shadow


def _state(prices):
    rows = [[f"2026081409{i:02d}", price] for i, price in enumerate(prices)]
    return {"codes": {"123456": {"status": "LIVE", "current": prices[-1],
                                   "minute_closes": rows}}}


def test_squeeze_breakout_and_exit_are_order_zero(tmp_path):
    payload = {"candidates": [{"code": "123456", "name": "TEST"}]}
    flat = [99.9, 100.1] * 15 + [100.0]
    shadow.run_once(tmp_path, payload, _state(flat), datetime(2026, 8, 14, 9, 31))
    breakout = flat[:-1] + [102.0]
    shadow.run_once(tmp_path, payload, _state(breakout), datetime(2026, 8, 14, 9, 32))
    falling = breakout[:-1] + [99.0]
    shadow.run_once(tmp_path, payload, _state(falling), datetime(2026, 8, 14, 9, 33))

    path = tmp_path / "data" / "shadow" / "bollinger_high_range30_20260814.csv"
    with path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["event"] for row in rows] == ["SHADOW_ENTRY", "SHADOW_EXIT"]
    assert all(row["requested_quantity"] == "0" for row in rows)
    assert all(row["provenance"] == "HYPOTHETICAL" for row in rows)
