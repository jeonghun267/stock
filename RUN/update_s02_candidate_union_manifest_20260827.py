# -*- coding: utf-8 -*-
"""S02 고저폭·돈흐름 합집합 후보선별 상시 승인 해시 재봉인."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest


ROOT = Path(r"C:\stock_bot")
RELATIVE_PATH = "RUN/strategy_02_low_buy_signal_v1.py"
ENGINE = ROOT / RELATIVE_PATH
REPORT = (
    ROOT / "data" / "s02_candidate_replay" / "20260827_1305"
    / "prod_replay_s02_candidate_union_20260827.json"
)
EXPECTED_OLD_SHA = "298c85cf9f64440368e4e3eadda0eb2796ed46bcb57d23ece1713d050b2d8f59"
NEW_SHA = hashlib.sha256(ENGINE.read_bytes()).hexdigest()
REPORT_SHA = hashlib.sha256(REPORT.read_bytes()).hexdigest()
REPLAY = json.loads(REPORT.read_text(encoding="utf-8-sig"))

if REPLAY.get("provenance") != "[PROD_REPLAY]" or REPLAY.get("status") != "PASS":
    raise SystemExit("candidate replay did not pass")
if REPLAY.get("sha256", {}).get(str(ENGINE)) != NEW_SHA:
    raise SystemExit("candidate replay engine hash mismatch")

NOTE = (
    "2026-08-27 owner-approved permanent S02 candidate selection: observe at most 50 "
    "codes from the UNION of the high-range board and money-flow selector, prioritize "
    "codes present in both, then high-range rank and positive institution/foreign/program "
    "flow. Existing entry gates, quantity, slots, sell rules, hard stop, and forced exit "
    "are unchanged. Current-path [PROD_REPLAY] PASS report_sha256=" + REPORT_SHA + "."
)


def _walk_entries(node):
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        else:
            for value in node.values():
                yield from _walk_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_entries(value)


def mutate(data):
    matches = [entry for entry in _walk_entries(data) if entry["path"] == RELATIVE_PATH]
    if len(matches) != 1:
        raise SystemExit(f"manifest entry count unexpected: {len(matches)}")
    if matches[0]["sha256"] != EXPECTED_OLD_SHA:
        raise SystemExit(f"unexpected current hash: {matches[0]['sha256']}")
    matches[0]["sha256"] = NEW_SHA
    numbers = [int(n) for n in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))]
    nxt = (max(numbers) + 1) if numbers else 1
    data["approval_scope"] += f" ({nxt}) {NOTE}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s02_candidate_union_20260827",
        expect_sha=read_content_sha(),
    ))
