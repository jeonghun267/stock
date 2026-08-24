# -*- coding: utf-8 -*-
"""Owner-approved, fail-closed S06 automatic release contract."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(r"C:\stock_bot")
MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"
REPORT_PATH = (
    ROOT / "reports" / "verified_replay" / "s06_current_buy_latest.json"
)
FEATURE = "S06_CURRENT_BUY"
CONDITION_ID = (
    "S06_CURRENT_DIRECT_REBOUND_DROP_8P0_REBOUND_1P5_"
    "FLOOR_1P0_CHASE_2P0_EARLY_1P8_QTY_1"
)
QUANTITY = 1
DURATION = "PERMANENT"

EXPECTED_CONFIG = {
    "quantity": 1,
    "max_slots": 6,
    "max_daily_codes": 20,
    "max_entries_per_code": 2,
    "capital_krw": 1000000,
    "max_price_krw": 300000,
    "drop_pct": 8.0,
    "rebound_pct": 1.5,
    "entry_floor_pct": 1.0,
    "chase_cap_pct": 2.0,
    "early_entry_cap_pct": 1.8,
    "pullback_min_pct": 0.4,
    "higher_low_buffer_pct": 0.3,
    "second_rebound_pct": 0.5,
    "flow_accel_window_sec": 10.0,
    "observe_sec": 60.0,
    "observe_max_sec": 720.0,
    "rearm_deeper_pct": 1.0,
}
EXPECTED_RUNTIME_FLAGS = {"LOW_REBOUND_DIRECT": "YES"}

PRODUCTION_FILES = {
    "RUN/run_strategy_06_crash_low_chase.cmd": (
        ROOT / "RUN" / "run_strategy_06_crash_low_chase.cmd"
    ),
    "RUN/strategy_06_crash_low_chase_v1.py": (
        ROOT / "RUN" / "strategy_06_crash_low_chase_v1.py"
    ),
}

EVIDENCE_FILES = {
    "RUN/s06_release_contract_v1.py": ROOT / "RUN" / "s06_release_contract_v1.py",
    "RUN/strategy_06_exact_input_recorder_v1.py": (
        ROOT / "RUN" / "strategy_06_exact_input_recorder_v1.py"
    ),
    "RUN/s06_capture_only_runner_v1.py": ROOT / "RUN" / "s06_capture_only_runner_v1.py",
    "RUN/s06_exact_replay_v1.py": ROOT / "RUN" / "s06_exact_replay_v1.py",
    "RUN/s06_auto_replay_report_v1.py": ROOT / "RUN" / "s06_auto_replay_report_v1.py",
    "RUN/s06_atomic_promote_v1.py": ROOT / "RUN" / "s06_atomic_promote_v1.py",
    "RUN/hidden/SAFEPLUS_S06_CAPTURE_ONLY.cmd": (
        ROOT / "RUN" / "hidden" / "SAFEPLUS_S06_CAPTURE_ONLY.cmd"
    ),
    "RUN/hidden/SAFEPLUS_S06_AUTO_PROMOTE.cmd": (
        ROOT / "RUN" / "hidden" / "SAFEPLUS_S06_AUTO_PROMOTE.cmd"
    ),
    "RUN/low_rebound_common_v1.py": ROOT / "RUN" / "low_rebound_common_v1.py",
    "RUN/strategy_common_order_v1.py": ROOT / "RUN" / "strategy_common_order_v1.py",
    "RUN/strategy_06_exit_policy_v2.py": ROOT / "RUN" / "strategy_06_exit_policy_v2.py",
}
