# -*- coding: utf-8 -*-
"""Build the durable opening MA3 seed from the completed 1-minute archive.

This module never sends orders or broker requests.  It converts the latest
regular session in prices_1m.csv into the payload format already consumed by
deep_bottom_signal_recorder.py and ma3_common_v1.py.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple


DEFAULT_PRICES_PATH = Path(r"C:\stock_bot\data\prices_1m.csv")
DEFAULT_SEED_PATH = Path(r"C:\stock_bot\data\돈맥_1분봉_seed.json")
KEEP_MINUTES = 70
MIN_3M_BLOCKS = 21


def _number(value) -> float:
    try:
        return abs(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(value: str) -> Optional[datetime]:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 12:
        return None
    try:
        return datetime.strptime(digits[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _regular_session(ts: datetime) -> bool:
    minute = ts.hour * 60 + ts.minute
    return 9 * 60 <= minute <= 15 * 60 + 30


def build_opening_seed(
    prices_path: Path = DEFAULT_PRICES_PATH,
    seed_path: Path = DEFAULT_SEED_PATH,
    max_session_date: Optional[str] = None,
) -> Dict[str, object]:
    """Write a broad, atomic opening seed and return coverage statistics.

    Only the latest session found at or before ``max_session_date`` is used.
    A code is emitted only when its retained rows form at least 21 distinct
    three-minute blocks.  That is the exact minimum for MA20 and its previous
    value; raw row counts alone are not trusted.
    """
    limit = str(max_session_date or "99999999").replace("-", "")[:8]
    latest_date = ""
    rows: Dict[str, Deque[Tuple[datetime, list, float]]] = defaultdict(
        lambda: deque(maxlen=KEEP_MINUTES)
    )

    with Path(prices_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"code", "ts", "open", "high", "low", "close"}
        if not required.issubset(set(reader.fieldnames or [])):
            missing = ",".join(sorted(required - set(reader.fieldnames or [])))
            raise ValueError(f"prices_1m schema missing: {missing}")

        for raw in reader:
            ts = _parse_ts(raw.get("ts", ""))
            if ts is None or not _regular_session(ts):
                continue
            day = ts.strftime("%Y%m%d")
            if day > limit or day < latest_date:
                continue
            if day > latest_date:
                latest_date = day
                rows.clear()

            code = str(raw.get("code") or "").strip().zfill(6)
            if len(code) != 6 or not code.isdigit():
                continue
            bar = [_number(raw.get(key)) for key in ("open", "high", "low", "close")]
            if min(bar) <= 0 or bar[1] < bar[2]:
                continue
            volume = _number(raw.get("volume"))
            rows[code].append((ts, bar, volume))

    payload = {
        "ts": (
            datetime.strptime(latest_date, "%Y%m%d").replace(
                hour=15, minute=30
            ).isoformat(sep=" ", timespec="seconds")
            if latest_date else ""
        ),
        "hm": "1530",
        "source": "prices_1m_eod",
        "m": {},
    }
    skipped = 0
    for code, code_rows in rows.items():
        ordered = sorted(code_rows, key=lambda item: item[0])[-KEEP_MINUTES:]
        blocks = {int(item[0].timestamp()) // 180 for item in ordered}
        if len(blocks) < MIN_3M_BLOCKS:
            skipped += 1
            continue
        payload["m"][code] = {
            "prev": [item[1] for item in ordered],
            "pv": [item[2] for item in ordered],
            "pm": [item[0].strftime("%Y%m%d%H%M") for item in ordered],
            "c": ordered[-1][1][3],
        }

    if not latest_date or not payload["m"]:
        raise ValueError("no MA3-ready regular-session rows in prices_1m")

    target = Path(seed_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return {
        "session_date": latest_date,
        "ready_codes": len(payload["m"]),
        "skipped_codes": skipped,
        "path": str(target),
    }


if __name__ == "__main__":
    print(json.dumps(build_opening_seed(), ensure_ascii=False))
