from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd


RUN = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(RUN))

from s01_trend_priority_board_v1 import build  # noqa: E402
import strategy_01_signal_contract_v2 as signal_contract  # noqa: E402
from strategy_01_signal_contract_v2 import (  # noqa: E402
    order_signals,
    order_selected_signals,
    select_fresh_signals,
)
from s01_open_priority_prod_replay_v1 import replay  # noqa: E402


def test_board_tiers_and_live_order() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "eod.csv"
        rows = []
        for day in range(1, 66):
            rows.extend([
                {"date": 20260100 + day, "code": "000001", "close": 100 + day},
                {"date": 20260100 + day, "code": "000002", "close": 100 + day * 0.3},
                {"date": 20260100 + day, "code": "000003", "close": 200 - day},
            ])
        pd.DataFrame(rows).to_csv(path, index=False)
        payload = build(path, datetime(2026, 8, 19, 8, 30))
        assert payload["codes"]["000001"]["s01_trend_tier"] == "A"
        assert payload["codes"]["000002"]["s01_trend_tier"] in {"A", "B"}
        assert payload["codes"]["000003"]["s01_trend_tier"] == "C"

    signals = [
        {"signal_id": "c", "code": "000003", "s01_trend_tier": "C", "money_speed_5s": 999},
        {"signal_id": "a", "code": "000001", "s01_trend_tier": "A", "money_speed_5s": 1},
        {"signal_id": "b", "code": "000002", "s01_trend_tier": "B", "money_speed_5s": 10},
    ]
    assert [r["code"] for r in order_signals(signals, "SHADOW")] == ["000003", "000002", "000001"]
    assert [r["code"] for r in order_signals(signals, "LIVE")] == ["000001", "000002", "000003"]

    v3 = [
        {"code": "000001", "score": 10, "s01_trend_tier": "A"},
        {"code": "000003", "score": 90, "s01_trend_tier": "C"},
    ]
    ranked = order_selected_signals(v3, entry_v3_mode="LIVE", trend_mode="LIVE")
    assert [row["code"] for row in ranked] == ["000003", "000001"]
    assert all(row["s01_entry_v3_order"] == "V3_SCORE_ONLY" for row in ranked)


def test_saved_sequence_replays_live_order_and_three_seconds() -> None:
    now = datetime(2026, 8, 19, 9, 0, 0)
    payload = {
        "schema": "strategy_01_open_surge_signal_v2",
        "mode": "SIGNAL_ONLY_ORDER_ZERO",
        "date": "20260819",
        "updated_at": now.isoformat(),
        "signals": [
            {
                "ts": now.isoformat(), "signal_sequence": 1,
                "action": "BUY_READY", "mode": "SIGNAL_ONLY_ORDER_ZERO",
                "code": "000003", "s01_trend_tier": "C",
                "money_speed_5s": 999,
            },
            {
                "ts": now.isoformat(), "signal_sequence": 1,
                "action": "BUY_READY", "mode": "SIGNAL_ONLY_ORDER_ZERO",
                "code": "000001", "s01_trend_tier": "A",
                "money_speed_5s": 1,
            },
        ],
    }
    signal_contract.OPEN_PRIORITY_CAPTURE = False
    rows = select_fresh_signals(payload, now=now, max_age_sec=5)
    files = [
        RUN / "strategy_01_rotation_engine_v2.py",
        RUN / "strategy_01_signal_contract_v2.py",
        RUN / "strategy_open_priority_v1.py",
        RUN / "strategy_01_open_surge_signal_v2.py",
    ]
    hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    base = {
        "schema": "s01_open_priority_replay_input_v1",
        "production_files": hashes,
        "config": {"signal_max_age_sec": 5},
        "consumed_signals": [],
        "signal_payload": payload,
        "selected_rows": rows,
        "decision": {},
    }
    with tempfile.TemporaryDirectory() as raw:
        signal_contract.OPEN_PRIORITY_AUDIT_ROOT = Path(raw) / "capture"
        signal_contract.OPEN_PRIORITY_CAPTURE = True
        select_fresh_signals(payload, now=now, max_age_sec=5)
        assert (signal_contract.OPEN_PRIORITY_AUDIT_ROOT / "20260819.jsonl").exists()
        audit = Path(raw) / "audit.jsonl"
        records = []
        for offset in (0.0, 3.1):
            row = dict(base)
            row["captured_at"] = now.replace(
                microsecond=int((offset % 1) * 1_000_000)
            ).isoformat()
            if offset >= 1:
                row["captured_at"] = "2026-08-19T09:00:03.100000"
            records.append(row)
        audit.write_text(
            "".join(json.dumps(row) + "\n" for row in records),
            encoding="utf-8",
        )
        result = replay(audit)
        assert result["status"] == "PASS", result
