# -*- coding: utf-8 -*-
"""Refresh the order-zero FLOW_TREND section from existing intraday sources."""
from __future__ import annotations

import argparse
import json
import sys
import time as time_module
from datetime import datetime, time as dt_time
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN_DIR = str(ROOT / "RUN")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from flow_trend_selector_v1 import build_flow_trend
from trend_follow_board_v1 import build_html

TREND_JSON = ROOT / "data" / "trend_follow_board_v1.json"
FLOW_JSON = ROOT / "data" / "돈흐름_선별판.json"
MICRO_JSON = ROOT / "IPC" / "live_micro_snapshot.json"
OUT_JSON = ROOT / "data" / "flow_trend_intraday_board_v1.json"
STATE_JSON = ROOT / "data" / "flow_trend_intraday_state_v1.json"
OUT_HTML = Path(r"C:\Users\UserK\Desktop\추세추종판.html")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    temporary.replace(path)


def refresh_once() -> int:
    trend = read_json(TREND_JSON)
    flow = read_json(FLOW_JSON)
    micro = read_json(MICRO_JSON)
    if not trend or not flow or not micro:
        print(json.dumps({
            "status": "DATA_WAIT", "trend": bool(trend),
            "flow": bool(flow), "micro": bool(micro),
        }, ensure_ascii=False))
        return 0
    result, state = build_flow_trend(
        trend, flow, read_json(STATE_JSON), micro,
    )
    atomic_json(OUT_JSON, result)
    atomic_json(STATE_JSON, state)
    trend["flow_trend"] = result
    atomic_json(TREND_JSON, trend)
    OUT_HTML.write_text(
        build_html(trend, trend.get("candidates") or [], result),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result.get("status"),
        "dynamic_universe": result.get("dynamic_universe", 0),
        "ready": len(result.get("candidates") or []),
        "discovery": len(result.get("discoveries") or []),
        "display": len(result.get("display") or []),
        "mode": result.get("mode"),
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop-sec", type=float, default=0.0)
    parser.add_argument("--until", default="15:20")
    args = parser.parse_args()
    if args.loop_sec <= 0:
        return refresh_once()

    end_clock = dt_time.fromisoformat(args.until)
    while True:
        now = datetime.now()
        end_at = datetime.combine(now.date(), end_clock)
        if now >= end_at:
            return 0
        refresh_once()
        remaining = (end_at - datetime.now()).total_seconds()
        if remaining <= 0:
            return 0
        time_module.sleep(min(args.loop_sec, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
