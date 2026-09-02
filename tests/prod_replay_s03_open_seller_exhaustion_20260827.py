# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo


ROOT = Path("C:/stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_03_rotation_engine_v1 as rotation  # noqa: E402
import s03_s06_crash_claim_v1 as crash_claim  # noqa: E402
from strategy_03_rotation_engine_v1 import (  # noqa: E402
    Strategy03HoldSellEngine,
    make_strategy03_signal_selector,
)
from strategy_06_crash_low_chase_v1 import ChaseState, Strategy06Engine  # noqa: E402
from strategy_common_hold_sell_v1 import (  # noqa: E402
    HoldSellObservation,
    HoldSellState,
    StrategyId,
)
from 골짜기_급반등 import MicroPoint, PriorProfile, RapidReboundMonitor  # noqa: E402


INPUT = ROOT / "tests" / "fixtures" / "s03_open_seller_exhaustion_20260827.json"
SNAPSHOT = ROOT / "tests" / "fixtures" / "s03_open_order_snapshot_20260827.json"
REPORT = ROOT / "reports" / "prod_replay_s03_open_seller_exhaustion_20260827.json"
SOURCES = (
    RUN / "골짜기_급반등.py",
    RUN / "strategy_03_flow_turn_fast_v1.py",
    RUN / "strategy_03_signal_contract_v1.py",
    RUN / "strategy_03_rotation_engine_v1.py",
    RUN / "strategy_06_crash_low_chase_v1.py",
    RUN / "s03_s06_crash_claim_v1.py",
    Path(__file__).resolve(),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    saved = json.loads(INPUT.read_text(encoding="utf-8"))
    start = datetime(2026, 8, 27, 9, 5, 0)
    profile = PriorProfile(previous_close=float(saved["previous_close"]))
    emitted = None
    selected = []
    s06_result = "NOT_RUN"
    s06_events = []
    claim_state = "FREE"
    exit_decision = None
    early_peak_arm_decision = None
    early_peak_hold_decision = None
    early_peak_watch_decision = None
    early_peak_decision = None
    original_drop_dir = rotation.DROP_LOG_DIR
    original_claim_dir = crash_claim.CLAIM_DIR
    original_claim_enabled = os.environ.get("S03_S06_CRASH_CLAIM_ENABLED")
    with tempfile.TemporaryDirectory(prefix="s03_open_replay_") as temp_dir:
        rotation.DROP_LOG_DIR = Path(temp_dir) / "drop"
        crash_claim.CLAIM_DIR = Path(temp_dir) / "claims"
        os.environ["S03_S06_CRASH_CLAIM_ENABLED"] = "YES"
        try:
            monitor = RapidReboundMonitor()
            last_point = None
            for raw in saved["points"]:
                point = MicroPoint(
                    ts=start + timedelta(seconds=int(raw["second"])),
                    price=float(raw["price"]),
                    minute_low=float(raw.get("minute_low") or 0),
                    open_price=float(saved["open_price"]),
                    buy_money_cum=float(raw["buy"]),
                    sell_money_cum=float(raw["sell"]),
                    buy_volume_cum=float(raw["buy"]),
                    sell_volume_cum=float(raw["sell"]),
                    best_ask_px=float(raw["price"]) + 10,
                    best_bid_px=float(raw["price"]),
                    best_ask_qty=float(raw.get("ask_qty") or 100),
                    best_bid_qty=1000,
                )
                last_point = point
                row, fired = monitor.process_point(
                    saved["code"], saved["name"], point, profile,
                    allow_signal=True,
                )
                if fired:
                    emitted = row
                    break
            if emitted is not None:
                payload = {
                    "schema": "strategy_03_valley_rapid_rebound_signal_v1",
                    "date": saved["date"],
                    "updated_at": emitted["ts"],
                    "mode": "SIGNAL_ONLY_ORDER_ZERO",
                    "signals": [emitted],
                }
                selector = make_strategy03_signal_selector(
                    SNAPSHOT,
                    snapshot_max_age_sec=4,
                    early_low_live_enabled=False,
                    flow_turn_live_enabled=False,
                    bottom_all_lanes_live_enabled=False,
                )
                selected = selector(
                    payload,
                    now=datetime.fromisoformat(emitted["ts"]) + timedelta(seconds=1),
                    max_age_sec=5,
                )
                decision_at = datetime.fromisoformat(emitted["ts"])
                s03_order = rotation.Strategy03Engine.__new__(
                    rotation.Strategy03Engine)
                s03_order.config = SimpleNamespace(
                    strategy_id=rotation.StrategyId.VALLEY_MORNING_CRASH,
                    order_lifecycle_root=Path(temp_dir) / "order_lifecycle",
                )
                s03_order.state = {"date": saved["date"]}
                s03_order.broker = SimpleNamespace(mode="PROD_REPLAY")
                s03_order._order_lifecycle_prod_sha = {}
                s03_order._order_lifecycle(
                    "BUY_PREPARED",
                    {
                        "code": saved["code"],
                        "name": saved["name"],
                        "phase": "BUY_PENDING",
                        "entry_lane": "OPEN_CRASH",
                        "last_price": float(last_point.price),
                        "pending": {"idempotency_key": "prod-replay-order-1"},
                    },
                    observed_at=decision_at,
                )
                claim_state = crash_claim.s03_claim_status(
                    saved["code"], decision_at)
                s06 = Strategy06Engine.__new__(Strategy06Engine)
                s06._event = lambda event, **kwargs: s06_events.append(
                    {"event": event, **kwargs})
                s06_result = s06._try_entry(
                    saved["code"], saved["name"],
                    {"price": float(last_point.price)},
                    ChaseState(low=float(emitted["anchor_low"])),
                    decision_at,
                )
                exit_case = saved["exit_case"]
                exit_engine = Strategy03HoldSellEngine()
                exit_engine.set_s03_entry_reference_low(emitted["anchor_low"])
                exit_entry_at = decision_at.replace(
                    tzinfo=ZoneInfo("Asia/Seoul")
                )
                exit_state = HoldSellState(
                    position_id="prod-replay-s03-low-break-v2",
                    strategy_id=StrategyId.VALLEY_MORNING_CRASH,
                    code=saved["code"],
                    quantity=1,
                    entry_price=Decimal(str(last_point.price)),
                    entry_at=exit_entry_at,
                    entry_lane="OPEN_CRASH",
                )
                exit_decision = exit_engine.evaluate(
                    exit_state,
                    HoldSellObservation(
                        observed_at=exit_entry_at + timedelta(
                            seconds=int(exit_case["seconds_after_entry"])
                        ),
                        price=Decimal(str(exit_case["price"])),
                        buy_money_per_sec_10s=Decimal(str(
                            exit_case["buy_money_per_sec_10s"]
                        )),
                        sell_money_per_sec_10s=Decimal(str(
                            exit_case["sell_money_per_sec_10s"]
                        )),
                        sell_money_per_sec_30s=Decimal(str(
                            exit_case["sell_money_per_sec_30s"]
                        )),
                    ),
                )
                early_peak_case = saved["early_peak_case"]
                early_peak_engine = Strategy03HoldSellEngine(
                    early_peak_live_enabled=True
                )
                early_peak_state = HoldSellState(
                    position_id="prod-replay-s03-early-peak-d",
                    strategy_id=StrategyId.VALLEY_MORNING_CRASH,
                    code=saved["code"],
                    quantity=1,
                    entry_price=Decimal(str(last_point.price)),
                    entry_at=exit_entry_at,
                    entry_lane="OPEN_CRASH",
                )
                early_peak_arm_decision = early_peak_engine.evaluate(
                    early_peak_state,
                    HoldSellObservation(
                        observed_at=exit_entry_at + timedelta(
                            seconds=int(early_peak_case["seconds_after_entry_arm"])
                        ),
                        price=Decimal(str(early_peak_case["arm_price"])),
                    ),
                )
                early_peak_hold_decision = early_peak_engine.evaluate(
                    early_peak_state,
                    HoldSellObservation(
                        observed_at=exit_entry_at + timedelta(
                            seconds=int(
                                early_peak_case["seconds_after_entry_hold"]
                            )
                        ),
                        price=Decimal(str(early_peak_case["hold_price"])),
                    ),
                )
                early_peak_watch_decision = early_peak_engine.evaluate(
                    early_peak_state,
                    HoldSellObservation(
                        observed_at=exit_entry_at + timedelta(
                            seconds=int(
                                early_peak_case["seconds_after_entry_retrace"]
                            )
                        ),
                        price=Decimal(str(early_peak_case["retrace_price"])),
                        buy_money_per_sec_10s=Decimal(str(
                            early_peak_case["buy_money_per_sec_10s"]
                        )),
                        sell_money_per_sec_10s=Decimal(str(
                            early_peak_case["sell_money_per_sec_10s"]
                        )),
                        buy_money_per_sec_30s=Decimal(str(
                            early_peak_case["buy_money_per_sec_30s"]
                        )),
                        sell_money_per_sec_30s=Decimal(str(
                            early_peak_case["sell_money_per_sec_30s"]
                        )),
                        buy_volume_per_sec_5s=Decimal(str(
                            early_peak_case["buy_volume_per_sec_5s"]
                        )),
                        sell_volume_per_sec_5s=Decimal(str(
                            early_peak_case["sell_volume_per_sec_5s"]
                        )),
                        sell_volume_per_sec_previous_10s=Decimal(str(
                            early_peak_case[
                                "sell_volume_per_sec_previous_10s"
                            ]
                        )),
                        che_str_change_5s=Decimal(str(
                            early_peak_case["che_str_change_5s"]
                        )),
                    ),
                )
                early_peak_decision = early_peak_engine.evaluate(
                    early_peak_state,
                    HoldSellObservation(
                        observed_at=exit_entry_at + timedelta(
                            seconds=int(
                                early_peak_case["seconds_after_entry_confirm"]
                            )
                        ),
                        price=Decimal(str(early_peak_case["confirm_price"])),
                        buy_money_per_sec_10s=Decimal(str(
                            early_peak_case["buy_money_per_sec_10s"]
                        )),
                        sell_money_per_sec_10s=Decimal(str(
                            early_peak_case["sell_money_per_sec_10s"]
                        )),
                        buy_money_per_sec_30s=Decimal(str(
                            early_peak_case["buy_money_per_sec_30s"]
                        )),
                        sell_money_per_sec_30s=Decimal(str(
                            early_peak_case["sell_money_per_sec_30s"]
                        )),
                        buy_volume_per_sec_5s=Decimal(str(
                            early_peak_case["buy_volume_per_sec_5s"]
                        )),
                        sell_volume_per_sec_5s=Decimal(str(
                            early_peak_case["sell_volume_per_sec_5s"]
                        )),
                        sell_volume_per_sec_previous_10s=Decimal(str(
                            early_peak_case[
                                "sell_volume_per_sec_previous_10s"
                            ]
                        )),
                        che_str_change_5s=Decimal(str(
                            early_peak_case["che_str_change_5s"]
                        )),
                    ),
                )
        finally:
            rotation.DROP_LOG_DIR = Path(temp_dir)
            rotation.DROP_LOG_DIR = original_drop_dir
            crash_claim.CLAIM_DIR = original_claim_dir
            if original_claim_enabled is None:
                os.environ.pop("S03_S06_CRASH_CLAIM_ENABLED", None)
            else:
                os.environ["S03_S06_CRASH_CLAIM_ENABLED"] = original_claim_enabled

    expected = saved["expected"]
    passed = bool(
        emitted
        and emitted.get("action") == expected["action"]
        and emitted.get("entry_lane") == expected["entry_lane"]
        and float(emitted.get("anchor_low") or 0) == float(expected["anchor_low"])
        and float(expected["rebound_min_pct"]) <= float(emitted.get("rebound_pct") or 0)
        <= float(expected["rebound_max_pct"])
        and len(selected) == 1
        and claim_state == "ORDERING"
        and s06_result == "RETRY"
        and any(
            str(row.get("reason") or "").endswith("_PREORDER")
            for row in s06_events
        )
        and exit_decision is not None
        and exit_decision.action.value == saved["exit_case"]["expected_action"]
        and exit_decision.reason == saved["exit_case"]["expected_reason"]
        and early_peak_arm_decision is not None
        and not early_peak_arm_decision.should_sell
        and early_peak_hold_decision is not None
        and not early_peak_hold_decision.should_sell
        and early_peak_watch_decision is not None
        and not early_peak_watch_decision.should_sell
        and early_peak_decision is not None
        and early_peak_decision.action.value
        == saved["early_peak_case"]["expected_action"]
        and early_peak_decision.reason
        == saved["early_peak_case"]["expected_reason"]
    )
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": saved["date"],
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_points": [
            "RUN/골짜기_급반등.py::RapidReboundMonitor.process_point",
            "RUN/strategy_03_signal_contract_v1.py::select_fresh_signals",
            "RUN/strategy_03_rotation_engine_v1.py::make_strategy03_signal_selector",
            "RUN/strategy_03_rotation_engine_v1.py::Strategy03Engine._order_lifecycle",
            "RUN/strategy_03_rotation_engine_v1.py::Strategy03HoldSellEngine.evaluate",
            "RUN/s03_s06_crash_claim_v1.py::try_claim_s03",
            "RUN/strategy_06_crash_low_chase_v1.py::Strategy06Engine._try_entry",
        ],
        "source_data": [str(INPUT), str(SNAPSHOT)],
        "sha256": {
            str(INPUT): sha256(INPUT),
            str(SNAPSHOT): sha256(SNAPSHOT),
            **{str(path): sha256(path) for path in SOURCES},
        },
        "non_decision_override": (
            "DROP_LOG_DIR and S03/S06 claim ledger redirected to one isolated "
            "temporary directory; claim feature enabled for replay"
        ),
        "command": "python -B -X utf8 tests/prod_replay_s03_open_seller_exhaustion_20260827.py",
        "raw_result": {
            "emitted_decision": ({
                "action": emitted.get("action"),
                "reason": emitted.get("reason"),
                "entry_lane": emitted.get("entry_lane"),
                "anchor_low": emitted.get("anchor_low"),
                "rebound_band_pass": bool(
                    float(expected["rebound_min_pct"])
                    <= float(emitted.get("rebound_pct") or 0)
                    <= float(expected["rebound_max_pct"])
                ),
            } if emitted else None),
            "selected_count": len(selected),
            "claim_state": claim_state,
            "s06_preorder_decision": s06_result,
            "s06_block_reason": (
                str(s06_events[-1].get("reason") or "") if s06_events else ""
            ),
            "expected_action": expected["action"],
            "expected_lane": expected["entry_lane"],
            "expected_anchor_low": expected["anchor_low"],
            "low_break_exit_decision": ({
                "action": exit_decision.action.value,
                "reason": exit_decision.reason,
            } if exit_decision else None),
            "early_peak_arm_decision": ({
                "action": early_peak_arm_decision.action.value,
                "reason": early_peak_arm_decision.reason,
            } if early_peak_arm_decision else None),
            "early_peak_hold_decision": ({
                "action": early_peak_hold_decision.action.value,
                "reason": early_peak_hold_decision.reason,
            } if early_peak_hold_decision else None),
            "early_peak_watch_decision": ({
                "action": early_peak_watch_decision.action.value,
                "reason": early_peak_watch_decision.reason,
            } if early_peak_watch_decision else None),
            "early_peak_exit_decision": ({
                "action": early_peak_decision.action.value,
                "reason": early_peak_decision.reason,
            } if early_peak_decision else None),
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
