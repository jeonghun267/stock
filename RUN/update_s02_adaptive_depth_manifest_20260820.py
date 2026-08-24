# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


EXPECTED_SHA = "b0cb65f905093e7744b78637f7efc2a7faaab616dcb8b52e0bb8bd64e946d2d0"
ENGINE_PATH = "RUN/strategy_02_low_buy_signal_v1.py"
ENGINE_SHA = "29f9f6c8c8202bb71e6bc69a7ccd3d36959cbc76ee8df1acb95b8b46cd11c224"
SIGNAL_LAUNCHER_PATH = "RUN/hidden/SAFEPLUS_STRATEGY02_SIGNAL.cmd"
SIGNAL_LAUNCHER_SHA = "23bdaab756f965452a1000e503341a09e6105dfb8d44ccc9a08fbbd88101bbc8"


def mutate(data):
    entries = data["strategies"]["S02"]
    by_path = {entry["path"]: entry for entry in entries}
    by_path[ENGINE_PATH]["sha256"] = ENGINE_SHA
    by_path[SIGNAL_LAUNCHER_PATH]["sha256"] = SIGNAL_LAUNCHER_SHA
    scope = (
        " (29) 2026-08-20 owner-approved permanent S02 adaptive-depth change: "
        "when S02_ADAPTIVE_BOTTOM_ENABLED=YES, the legacy morning -3% and "
        "intraday -5% thresholds no longer block anchor-low tracking. The existing "
        "FAST/RETEST regime, flow, order-book, distance, one-share sizing, hard stop, "
        "force exit, and other strategies remain unchanged. Current-path exact-input "
        "PROD_REPLAY passed after the production change."
    )
    if "(29) 2026-08-20 owner-approved permanent S02 adaptive-depth change" not in data["approval_scope"]:
        data["approval_scope"] += scope
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s02_adaptive_depth_20260820",
        expect_sha=EXPECTED_SHA,
    ))
