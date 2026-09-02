import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(r"C:\stock_bot")
PROD = ROOT / "RUN" / "eod_gap_live_executor_v1.py"
FIXTURE = ROOT / "reports" / "verified_replay" / "eod_gap_repair_20260827_inputs.json"
REPORT = ROOT / "reports" / "verified_replay" / "eod_gap_repair_20260827_report.json"
COMMAND = "python -B -X utf8 tests/prod_replay_eod_gap_repair_20260827.py"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prod():
    env = {
        "EOD_GAP_LIVE": "NO",
        "EOD_GAP_MAX_POS": "1",
        "EOD_GAP_QTY_ONE_ALL": "YES",
        "EOD_GAP_LOCKED_FIRST": "NO",
        "EOD_GAP_LOCKED_PRIORITY": "NO",
        "EOD_GAP_BOARD_CACHE_FALLBACK": "YES",
        "EOD_GAP_BOARD_MAX_AGE_SEC": "600",
        "SAFEPLUS_MIN_PRICE": "10000",
        "SAFEPLUS_MIN_MARKETCAP": "100000000000",
    }
    with patch.dict(os.environ, env, clear=False):
        spec = importlib.util.spec_from_file_location("eod_gap_live_executor_replay", PROD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def run_scenario(frozen, shares, expected_code):
    mod = load_prod()
    captured = datetime.fromisoformat(frozen["captured_at"])

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = captured + timedelta(seconds=599)
            return value if tz is None else value.astimezone(tz)

    with tempfile.TemporaryDirectory(prefix="eod_gap_repair_replay_") as td:
        tmp = Path(td)
        mod.POS = tmp / "positions.json"
        mod.POS.write_text("{}", encoding="utf-8")
        mod.LOG = tmp / "replay.log"
        mod.SUP_DIR = tmp / "supply"
        mod.LEAD_SHADOW = tmp / "leader.csv"
        mod.MICRO_WATCH_FILE = tmp / "micro_watch.json"
        mod.AUCTION_AUDIT_DIR = tmp / "auction"
        mod.LIVE_BOARD_CACHE = tmp / "board.json"
        mod.LIVE_BOARD_CACHE.write_text(json.dumps({
            "date": frozen["date"],
            "captured_at": frozen["captured_at"],
            "source": "opt10032",
            "rows": frozen["top"],
        }, ensure_ascii=False), encoding="utf-8")
        mod.datetime = FixedDateTime
        mod.LIVE = False
        mod.LOCKED_FIRST = False
        mod.LOCKED_PRIORITY = False
        mod.LIVE_BOARD_CACHE_FALLBACK = True
        mod.LIVE_BOARD_MAX_AGE_SEC = 600
        mod.QTY_ONE_ALL = True
        mod.MAX_POS = 1
        mod.MIN_SCORE = 70.0
        mod.SUPPLY_PRIORITY = False
        mod.UNIFIED_PICK = False
        mod.PORTFOLIO_V2 = False
        mod.LEADER_ONLY = False
        mod.SKIP_LOCKED = True
        mod.LIMITUP_ADD = True

        orders = []
        fake_modules = {
            "broker_client": types.SimpleNamespace(_load_shares_cache=lambda: shares),
            "trend_filter": types.SimpleNamespace(is_jeongbae=lambda *_: frozen["gate_inputs"]["trend_strict"]),
            "foreign_supply": types.SimpleNamespace(buy_gate=lambda *_args, **_kwargs: frozen["gate_inputs"]["foreign_buy_gate"]),
            "smart_money": types.SimpleNamespace(dumping=lambda *_: (frozen["gate_inputs"]["smart_money_dumping"], "fixture")),
        }
        with patch.dict(sys.modules, fake_modules), \
                patch.object(mod, "_broker", return_value=object()), \
                patch.object(mod, "_opt10032_top", return_value=[]), \
                patch.object(mod, "_limitup_extra", return_value=[]), \
                patch.object(mod.G, "_load_memb", return_value=frozen["memb"]), \
                patch.object(mod.G, "_load_block", return_value=set(frozen["block"])), \
                patch.object(mod.G, "_intraday", return_value=frozen["intra"]), \
                patch.object(mod.G, "_load_opt10032_aft", return_value=frozen["opt_aft"]), \
                patch.object(mod, "_prev_eod", return_value=frozen["prev"]), \
                patch.object(mod, "_unified_scores", return_value={}), \
                patch.object(mod, "_supply_net", return_value=(None, None)), \
                patch.object(mod, "_eod_micro_skip", return_value=False), \
                patch.object(mod, "_write_micro_watch"), \
                patch.object(mod, "_order", side_effect=lambda _bc, code, qty, side, tag: orders.append((code, qty, side, tag)) or True):
            mod.mode_pick()

        if not orders:
            raise AssertionError(f"no order decision for expected {expected_code}")
        if orders[0] != (expected_code, 1, "BUY", "PICK"):
            raise AssertionError(f"unexpected decision {orders[0]} expected {expected_code}/1")
        if any(code == "000003" for code, *_ in orders):
            raise AssertionError("locked candidate was selected despite LOCKED_FIRST/PRIORITY off")
        return {"selected_code": orders[0][0], "quantity": orders[0][1], "decision": "PASS"}


def main():
    frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))
    setup = run_scenario(frozen, frozen["shares_all"], "000002")
    fallback = run_scenario(frozen, frozen["shares_setup_unavailable"], "000001")
    report = {
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS",
        "date": "2026-08-27",
        "performance_scope": "DECISION_ONLY",
        "source_data": str(FIXTURE),
        "production_entry_point": str(PROD) + "::mode_pick",
        "production_code_changed": "CHANGED",
        "command": COMMAND,
        "source_sha256": sha256(FIXTURE),
        "replay_engine_sha256": sha256(PROD),
        "sha256": {"fixture": sha256(FIXTURE), "production": sha256(PROD)},
        "decisions": {
            "strategy_ab_own_gate": setup,
            "unorderable_setup_falls_back_to_general": fallback,
            "locked_priority": "BLOCKED",
            "fresh_same_day_cache_max_age_sec": 600
        },
        "notes": [
            "Synthetic order-zero decision fixture; this is not a qualifying production replay.",
            "No profit, loss, return, price, or fill result is reported."
        ]
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
