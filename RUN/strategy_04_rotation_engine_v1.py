# -*- coding: utf-8 -*-
"""Strategy 04 rotation: S04 entry, shared hold/sell/order/recovery."""
from __future__ import annotations

import argparse
import os
from datetime import time as day_time
from pathlib import Path

from strategy_01_rotation_engine_v2 import Config, ProcessLock, Strategy01Engine
from strategy_04_signal_contract_v1 import select_fresh_signals
from strategy_common_hold_sell_v1 import StrategyId


def build_config() -> Config:
    return Config(
        signal_path=Path(r"C:\stock_bot\data\strategy_04_pullback_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(r"C:\stock_bot\data\strategy_04_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_04_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_04_rotation_v1.log"),
        approval_path=Path(r"C:\stock_bot\config\strategy_04_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_04_off.flag"),
        manual_buy_block_path=Path(r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_04_rotation_v1.lock"),
        live_requested=os.environ.get("S04_LIVE", "NO").strip().upper() == "YES",
        quantity=int(os.environ.get("S04_QTY", "1")),
        max_slots=int(os.environ.get("S04_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S04_MAX_DAILY_CODES", "6")),
        max_cycles_per_code=int(os.environ.get("S04_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=int(os.environ.get(
            "S04_ROTATION_CAPITAL_KRW", "2000000")),
        max_sell_retries=int(os.environ.get("S04_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get(
            "S04_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get(
            "S04_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get(
            "S04_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S04_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S04_LOOP_SEC", "1")),
        entry_start=day_time(10, 0),
        entry_end=day_time(14, 30),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_04_rotation_engine_v1",
        strategy_id=StrategyId.S04_PULLBACK,
        strategy_slug="strategy04",
        strategy_label="Strategy 04 Pullback",
        slot_owner="STRATEGY04",
        broker_order_prefix="STRATEGY04",
        event_prefix="strategy_04",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 04 is already running.", flush=True)
        return 0
    try:
        return Strategy01Engine(
            config,
            signal_selector=select_fresh_signals,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
