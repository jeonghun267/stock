# -*- coding: utf-8 -*-
"""Strategy 05 fail-closed preflight and date-bound owner approval."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_04_preflight_v1 as shared
from strategy_05_base_breakout_signal_v1 import SIGNAL_MODE, SIGNAL_SCHEMA


ROOT = Path(r"C:\stock_bot")


def configure() -> None:
    shared.LABEL = "STRATEGY05"
    shared.ROOT = ROOT
    shared.WATCH = ROOT / "IPC" / "micro_watch_strategy05.json"
    shared.SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"
    shared.MINUTE = ROOT / "data" / "돈맥_1분봉.json"
    shared.MARKET = ROOT / "data" / "kosdaq_index.json"
    shared.SIGNAL = ROOT / "data" / "strategy_05_base_breakout_signal_v1.json"
    shared.STATE = ROOT / "data" / "strategy_05_rotation_state_v1.json"
    shared.AUDIT = ROOT / "data" / "strategy_05_preflight_v1.json"
    shared.APPROVAL = ROOT / "config" / "strategy_05_live_approved.flag"
    shared.OFF = ROOT / "config" / "strategy_05_off.flag"
    shared.MANUAL_BLOCK = ROOT / "config" / "manual_buy_block.flag"
    shared.SIGNAL_SCHEMA = SIGNAL_SCHEMA
    shared.SIGNAL_MODE = SIGNAL_MODE
    shared.REQUIRED_TASKS = (
        "SAFEPLUS_WATCHDOG_BROKER",
        "SAFEPLUS_STRATEGY_WATCHLIST",
        "SAFEPLUS_KOSDAQ_IDX_REFRESH",
        "SAFEPLUS_STRATEGY05_SIGNAL",
        "SAFEPLUS_STRATEGY05_LIVE",
        "SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED",
    )


def main() -> int:
    configure()
    return shared.main()


if __name__ == "__main__":
    raise SystemExit(main())
