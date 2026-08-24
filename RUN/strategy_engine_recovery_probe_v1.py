# -*- coding: utf-8 -*-
"""Fail-closed probe for S05/S06 exit-only crash recovery."""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ACTIVE_PHASES = {"BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"}


@dataclass(frozen=True)
class RecoveryTarget:
    state_path: Path
    lock_path: Path
    schema: str


TARGETS = {
    "S05": RecoveryTarget(
        Path(r"C:\stock_bot\data\strategy_05_rotation_state_v1.json"),
        Path(r"C:\stock_bot\data\strategy_05_rotation_v1.lock"),
        "strategy_05_rotation_engine_v1",
    ),
    "S06": RecoveryTarget(
        Path(r"C:\stock_bot\data\strategy_06_crash_low_chase_state_v1.json"),
        Path(r"C:\stock_bot\data\strategy_06_crash_low_chase.lock"),
        "strategy_06_crash_low_chase_v1",
    ),
}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows의 os.kill(pid, 0)은 POSIX식 생존 확인이 아니라
        # TerminateProcess로 이어질 수 있다. 읽기 전용 핸들로만 확인한다.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _engine_alive(lock_path: Path) -> bool:
    try:
        pid = int(lock_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def _read_stable_json(path: Path) -> Mapping[str, Any] | None:
    try:
        first = path.read_bytes()
        time.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return None
        payload = json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _active_real_codes(payload: Mapping[str, Any]) -> list[str]:
    positions = payload.get("positions")
    if not isinstance(positions, Mapping):
        return []
    codes = []
    for key, position in positions.items():
        if not isinstance(position, Mapping):
            continue
        if position.get("real") is not True:
            continue
        if str(position.get("phase") or "") not in ACTIVE_PHASES:
            continue
        codes.append(str(position.get("code") or key))
    return sorted(set(codes))


def probe(strategy: str) -> int:
    target = TARGETS[strategy]
    if _engine_alive(target.lock_path):
        print(f"RECOVERY_SKIP_RUNNING strategy={strategy}")
        return 10
    payload = _read_stable_json(target.state_path)
    if payload is None or str(payload.get("schema") or "") != target.schema:
        print(f"RECOVERY_BLOCK_INVALID_STATE strategy={strategy} path={target.state_path}")
        return 12
    codes = _active_real_codes(payload)
    if not codes:
        print(f"RECOVERY_SKIP_NO_REAL_POSITION strategy={strategy}")
        return 11
    print(f"RECOVERY_START_EXIT_ONLY strategy={strategy} codes={','.join(codes)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(TARGETS), required=True)
    args = parser.parse_args()
    return probe(args.strategy)


if __name__ == "__main__":
    raise SystemExit(main())
