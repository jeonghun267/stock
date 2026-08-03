# -*- coding: utf-8 -*-
"""Reset S01-S03 daily gate flags so the morning ALL_PREFLIGHT can start clean.

Why this exists
---------------
strategy_all_auto_live_preflight_v1.activate_all_flags() requires, for every
strategy, that the OFF flag EXISTS and the approval flag DOES NOT exist before
activation. On a successful day the preflight itself creates the approvals and
removes the OFF flags. Nothing ever puts them back, so the next morning the
precondition is violated and the whole preflight aborts with
"<S>_FLAG_STATE_CHANGED_BEFORE_ACTIVATION" -> zero new buys for the day.

This job restores the clean pre-open state. It is idempotent and never touches
S04/S05 (they gate on the date written inside their own approval file) nor
manual_buy_block.flag (that is the owner's emergency switch).

Selling is unaffected: StrategyBroker.real_session also accepts
force_exit_only, so held positions can still be exited after a reset.

Read/writes only these files:
    config/strategy_0{1,2,3}_off.flag           (create if missing)
    config/strategy_0{1,2,3}_live_approved.flag (delete if present, after backup)
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, time
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
CONFIG = ROOT / "config"
BACKUP_DIR = CONFIG / "flag_reset_backup"
LOG_PATH = ROOT / "data" / "LOG" / "strategy_flag_daily_reset.log"

STRATEGIES = ("01", "02", "03")

# Never run while the live session is arming or trading. The morning gate is
# SAFEPLUS_STRATEGY_ALL_PREFLIGHT at 08:59:35; locking after that point would
# silently disable a session that is already approved.
BLOCK_START = time(8, 59)
BLOCK_END = time(16, 0)


def _log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def reset_flags(now: datetime | None = None) -> int:
    now = now or datetime.now()
    if BLOCK_START <= now.time() < BLOCK_END:
        _log(f"SKIP in-session window {BLOCK_START}-{BLOCK_END}; no change")
        return 3

    deleted: list[str] = []
    created: list[str] = []
    for num in STRATEGIES:
        approval = CONFIG / f"strategy_{num}_live_approved.flag"
        off = CONFIG / f"strategy_{num}_off.flag"

        if approval.exists():
            try:
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                stamp = now.strftime("%Y%m%d_%H%M%S")
                shutil.copy2(approval, BACKUP_DIR / f"{approval.name}.{stamp}")
            except OSError as exc:
                _log(f"FAIL backup {approval.name}: {exc}")
                return 1
            try:
                approval.unlink()
            except OSError as exc:
                _log(f"FAIL delete {approval.name}: {exc}")
                return 1
            deleted.append(approval.name)

        if not off.exists():
            try:
                off.write_text("OFF\n", encoding="ascii")
            except OSError as exc:
                _log(f"FAIL create {off.name}: {exc}")
                return 1
            created.append(off.name)

    for num in STRATEGIES:
        approval = CONFIG / f"strategy_{num}_live_approved.flag"
        off = CONFIG / f"strategy_{num}_off.flag"
        if approval.exists() or not off.exists():
            _log(f"FAIL postcheck S{num}: approval={approval.exists()} off={off.exists()}")
            return 1

    _log(
        "OK approvals_removed=%d off_created=%d %s"
        % (
            len(deleted),
            len(created),
            (",".join(deleted + created) or "already_clean"),
        )
    )
    return 0


def main() -> int:
    return reset_flags()


if __name__ == "__main__":
    sys.exit(main())
