# -*- coding: utf-8 -*-
"""Seal approved S03 low-break V2 and early-peak D after PROD_REPLAY."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from approval_manifest_writer_v1 import read_content_sha, update_manifest
from trading_report_truth_gate_v1 import validate


PRODUCTION = ROOT / "RUN" / "strategy_03_rotation_engine_v1.py"
REPORT = ROOT / "reports" / "prod_replay_s03_open_seller_exhaustion_20260827.json"
RELATIVE = "RUN/strategy_03_rotation_engine_v1.py"
REASON = "S03_REFERENCE_LOW_BREAK_SELL_REACCEL"
EARLY_PEAK_REASON = "S03_EARLY_PEAK"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk_entries(node):
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        else:
            for value in node.values():
                yield from walk_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_entries(value)


report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
quotable, reason = validate(report)
if not quotable:
    raise SystemExit(f"truth gate failed: {reason}")
current_hash = sha256(PRODUCTION)
if report.get("sha256", {}).get(str(PRODUCTION)) != current_hash:
    raise SystemExit("production hash differs from passing replay")
exit_decision = (report.get("raw_result") or {}).get("low_break_exit_decision") or {}
if exit_decision != {"action": "SELL", "reason": REASON}:
    raise SystemExit(f"unexpected replay exit decision: {exit_decision!r}")
early_peak_decision = (
    (report.get("raw_result") or {}).get("early_peak_exit_decision") or {}
)
if early_peak_decision != {"action": "SELL", "reason": EARLY_PEAK_REASON}:
    raise SystemExit(
        f"unexpected replay early-peak decision: {early_peak_decision!r}"
    )


def mutate(data):
    updated = False
    for entry in walk_entries(data):
        if entry.get("path") == RELATIVE:
            entry["sha256"] = current_hash
            updated = True
    if not updated:
        raise SystemExit(f"manifest entry missing: {RELATIVE}")
    data.setdefault("live_features", {})["S03_EARLY_PEAK"] = True
    numbers = [
        int(value)
        for value in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))
    ]
    nxt = max(numbers, default=0) + 1
    note = (
        "2026-08-30 owner-approved permanent S03 exits: OPEN_CRASH low-break V2 "
        "full exit plus all-lane S03_EARLY_PEAK D full exit armed at +1.0pct "
        "and triggered by 0.6pct drop from peak only when shared flow-break "
        "score>=2, no rising-hold condition is active, the setup persists for "
        "3 seconds, and observed price remains at least entry+0.25pct; "
        "price<=entry_reference_low*0.997 and complete 10s/30s sell-flow evidence "
        "shows sell10>buy10 and sell10>sell30*1.2; missing/stale data does not fire; "
        "time exit and hard stop keep priority; each re-entry refreshes reference low; "
        "time exit, hard stop, and common exits keep priority; PROD_REPLAY and "
        "truth gate PASS."
    )
    data["approval_scope"] = str(data.get("approval_scope") or "") + f" ({nxt}) {note}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s03_early_peak_d06_20260830",
        expect_sha=read_content_sha(),
    ))
