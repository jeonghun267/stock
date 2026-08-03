# -*- coding: utf-8 -*-
"""Start missed Strategy 01 prerequisites after a weekday Windows logon."""
from __future__ import annotations

import subprocess
from datetime import datetime, time
from pathlib import Path


LOG = Path(r"C:\stock_bot\data\LOG\strategy_01_bootstrap.log")
TASKS = (
    "SAFEPLUS_WATCHDOG_BROKER",
    "SAFEPLUS_STRATEGY_WATCHLIST",
    "SAFEPLUS_MICRO_RANK_SHADOW",
    "SAFEPLUS_MONEYFLOW_WATCH",
    "SAFEPLUS_STRATEGY01_SIGNAL",
)


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")


def main() -> int:
    now = datetime.now()
    if now.weekday() >= 5:
        log("SKIP weekend")
        return 0
    if not time(8, 15) <= now.time() < time(9, 20):
        log(f"SKIP outside bootstrap window {now:%H:%M:%S}")
        return 0
    for task in TASKS:
        completed = subprocess.run(
            ["schtasks.exe", "/Run", "/TN", task],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        log(f"{task} rc={completed.returncode} {completed.stdout.strip()} "
            f"{completed.stderr.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
