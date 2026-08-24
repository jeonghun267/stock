# -*- coding: utf-8 -*-
"""Decision-only S02 production order-path replay from preserved 2026-08-20 inputs."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_02_rotation_engine_v1 import Strategy02Engine, build_config  # noqa: E402
from strategy_02_signal_contract_v1 import (  # noqa: E402
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)


DAY = "20260820"
KST = ZoneInfo("Asia/Seoul")
INPUTS = ROOT / "data" / "s02_exact_replay" / f"s02_exact_inputs_{DAY}.csv"
EVENTS = (
    ROOT / "data" / "s02_exact_replay_runtime" / "events"
    / f"strategy_02_signals_{DAY}.csv"
)
OUT = (
    ROOT / "data" / "s02_exact_replay"
    / f"prod_replay_s02_order_path_{DAY}.json"
)
PRODUCTION_FILES = {
    "engine": RUN / "strategy_02_rotation_engine_v1.py",
    "shared_rotation_engine": RUN / "strategy_01_rotation_engine_v2.py",
    "signal_contract": RUN / "strategy_02_signal_contract_v1.py",
    "signal_source": RUN / "strategy_02_low_buy_signal_v1.py",
    "order_adapter": RUN / "strategy_common_order_v1.py",
}


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_hash_valid(record: dict[str, Any]) -> bool:
    payload = dict(record)
    stored = str(payload.pop("record_sha256", ""))
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    )
    return stored == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _matching_input(
    event: dict[str, str],
    inputs: list[dict[str, str]],
) -> dict[str, str]:
    code = str(event.get("code") or "").zfill(6)
    second = str(event.get("ts") or "")
    matches = [
        row for row in inputs
        if str(row.get("code") or "").zfill(6) == code
        and str(row.get("ts") or "").startswith(second)
    ]
    if not matches:
        raise RuntimeError(f"EXACT_INPUT_NOT_FOUND:{code}:{second}")
    return matches[-1]


def _snapshot_row(raw: dict[str, str]) -> dict[str, Any]:
    return {
        "ts": raw["ts"],
        "ob_ts": raw["ts"],
        "cur": _num(raw.get("price")),
        "op": _num(raw.get("open_price")),
        "hi": _num(raw.get("broker_day_high")),
        "lo": _num(raw.get("broker_day_low")),
        "cum_vol": _num(raw.get("cum_vol")),
        "che_str": _num(raw.get("che_str")),
        "ask_tot": _num(raw.get("ask_tot")),
        "bid_tot": _num(raw.get("bid_tot")),
        "buy_money_cum": _num(raw.get("buy_money_cum")),
        "sell_money_cum": _num(raw.get("sell_money_cum")),
        "buy_vol_cum": _num(raw.get("buy_vol_cum"), -1.0),
        "sell_vol_cum": _num(raw.get("sell_vol_cum"), -1.0),
        "best_ask_px": _num(raw.get("best_ask_px")),
        "best_bid_px": _num(raw.get("best_bid_px")),
        "best_ask_qty": _num(raw.get("best_ask_qty")),
        "best_bid_qty": _num(raw.get("best_bid_qty")),
    }


def _replay_one(event: dict[str, str], raw: dict[str, str]) -> dict[str, Any]:
    code = str(event.get("code") or "").zfill(6)
    now = datetime.fromisoformat(event["ts"]).replace(tzinfo=KST)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        signal_path = root / "signal.json"
        snapshot_path = root / "snapshot.json"
        board_path = root / "board.json"
        bars_path = root / "bars.json"
        names_path = root / "names.json"
        signal_path.write_text(json.dumps({
            "schema": SIGNAL_SCHEMA,
            "date": DAY,
            "updated_at": event["ts"],
            "mode": SIGNAL_MODE,
            "signals": [event],
        }, ensure_ascii=False), encoding="utf-8")
        snapshot_path.write_text(json.dumps({
            "ts": raw["ts"],
            "codes": {code: _snapshot_row(raw)},
        }, ensure_ascii=False), encoding="utf-8")
        board_path.write_text(json.dumps({
            "ts": raw["ts"], "all_items": [],
        }), encoding="utf-8")
        bars_path.write_text("{}", encoding="utf-8")
        names_path.write_text("{}", encoding="utf-8")

        config = replace(
            build_config(),
            signal_path=signal_path,
            snapshot_path=snapshot_path,
            board_path=board_path,
            bars_path=bars_path,
            names_path=names_path,
            state_path=root / "state.json",
            fills_dir=root / "fills",
            event_dir=root / "events",
            log_path=root / "engine.log",
            audit_root=root / "audit",
            order_lifecycle_root=root / "order_lifecycle",
            approval_path=root / "approved.flag",
            off_flag_path=root / "off.flag",
            manual_buy_block_path=root / "manual.flag",
            lock_path=root / "engine.lock",
            live_requested=False,
            audit_enabled=False,
            loss_reentry_gate_mode="OFF",
            reentry_peer_state_paths=(),
            reentry_audit_root=root / "reentry_audit",
            open_priority_mode="OFF",
            open_priority_state_path=root / "priority.json",
        )
        engine = Strategy02Engine(
            config,
            signal_selector=select_fresh_signals,
        )
        # Historical replay must use the preserved trade date, not today's
        # wall-clock date chosen by the production startup state loader.
        engine.state = engine._blank_state(DAY)
        engine.tick(now)
        position = engine._active_positions().get(code) or {}
        lifecycle_path = (
            config.order_lifecycle_root / DAY / "s02_order_lifecycle.jsonl"
        )
        lifecycle = [
            json.loads(line)
            for line in lifecycle_path.read_text(encoding="utf-8").splitlines()
        ] if lifecycle_path.exists() else []
        expected_events = [
            "BUY_PREPARED", "BUY_SUBMIT_RESULT", "BUY_FILL_CONFIRMED",
        ]
        production_hashes = {
            name: _sha256(path) for name, path in PRODUCTION_FILES.items()
        }
        checks = {
            "position_hold": position.get("phase") == "HOLD",
            "position_order_zero": position.get("real") is False,
            "quantity_one": int(position.get("qty") or 0) == 1,
            "event_sequence": [row.get("event") for row in lifecycle] == expected_events,
            "schema_valid": bool(lifecycle) and all(
                row.get("schema") == "s02_order_lifecycle_v1" for row in lifecycle
            ),
            "record_hashes_valid": bool(lifecycle) and all(
                _record_hash_valid(row) for row in lifecycle
            ),
            "production_hashes_valid": bool(lifecycle) and all(
                row.get("production_files") == production_hashes for row in lifecycle
            ),
            "fill_source_order_zero": bool(lifecycle) and lifecycle[-1].get("fill_source") == "ORDER_ZERO",
            "arrival_collar_valid": bool(lifecycle) and _num(lifecycle[-1].get("arrival_chase_bps"), 999.0) <= 25.0,
            "fill_slippage_zero": bool(lifecycle) and _num(lifecycle[-1].get("fill_slippage_bps"), 999.0) == 0.0,
        }
        passed = all(checks.values())
        result = {
            "code": code,
            "signal_ts": event["ts"],
            "decision": "BUY_ORDER_ZERO_CONFIRMED" if passed else "FAIL",
            "lifecycle_events": [row.get("event") for row in lifecycle],
            "record_hashes_valid": bool(lifecycle) and all(
                _record_hash_valid(row) for row in lifecycle
            ),
            "production_hashes_valid": bool(lifecycle) and all(
                row.get("production_files") == production_hashes
                for row in lifecycle
            ),
            "arrival_chase_bps": (
                lifecycle[-1].get("arrival_chase_bps") if lifecycle else None
            ),
            "fill_slippage_bps": (
                lifecycle[-1].get("fill_slippage_bps") if lifecycle else None
            ),
            "checks": checks,
            "passed": passed,
        }
        for handler in list(engine.log.handlers):
            handler.close()
            engine.log.removeHandler(handler)
        return result


def main() -> int:
    with INPUTS.open(encoding="utf-8-sig", newline="") as handle:
        inputs = list(csv.DictReader(handle))
    with EVENTS.open(encoding="utf-8-sig", newline="") as handle:
        events = list(csv.DictReader(handle))
    scenarios = [
        _replay_one(event, _matching_input(event, inputs))
        for event in events
    ]
    passed = bool(scenarios) and all(row["passed"] for row in scenarios)
    report = {
        "schema": "prod_replay_s02_order_path_v1",
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "performance_scope": "DECISION_ONLY_SIGNAL_TO_ORDER_ZERO",
        "date": DAY,
        "production_code_changed": "CHANGED",
        "production_entry_point": (
            "RUN/strategy_02_rotation_engine_v1.py::"
            "Strategy02Engine.tick"
        ),
        "source_data": [str(INPUTS), str(EVENTS)],
        "source_sha256": {
            str(INPUTS): _sha256(INPUTS),
            str(EVENTS): _sha256(EVENTS),
        },
        "replay_engine_sha256": _sha256(Path(__file__)),
        "production_sha256": {
            name: _sha256(path) for name, path in PRODUCTION_FILES.items()
        },
        "command": (
            r"C:\python310\python.exe -B -X utf8 "
            r"tests\prod_replay_s02_order_path_20260820.py"
        ),
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "provenance": report["provenance"],
        "status": report["status"],
        "performance_scope": report["performance_scope"],
        "scenario_count": len(scenarios),
    }, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())