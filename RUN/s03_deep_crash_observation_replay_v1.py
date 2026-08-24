# -*- coding: utf-8 -*-
"""고저폭 생산판에서 S03 깊은 급락 가격경로를 재생한다.

주문/체결 성과가 아니라, 09:15 이전 전일종가 대비 -10%에 도달한 종목의
관측 최저가와 그 저점 뒤 관측 최고가를 현재 생산판 `_pct`로 다시 계산한다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from high_range_live_board_v1 import _pct  # noqa: E402


DATES = ("20260818", "20260821")
DEEP_DEADLINE = time(9, 15)
REPORT = ROOT / "data" / "replay_cache" / "s03_deep_crash_observation_replay_20260821.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def replay_day(day: str) -> dict:
    source = ROOT / "data" / f"high_range_shadow_{day}.csv"
    grouped: dict[str, list[dict]] = defaultdict(list)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            try:
                ts = datetime.fromisoformat(str(raw.get("ts") or ""))
            except ValueError:
                continue
            raw["_ts"] = ts
            grouped[str(raw.get("code") or "").zfill(6)].append(raw)

    observations = []
    for code, rows in grouped.items():
        rows.sort(key=lambda row: row["_ts"])
        prev_close = number(rows[0].get("prev_close"))
        if prev_close <= 0:
            continue
        reached = next((
            row for row in rows
            if row["_ts"].time() <= DEEP_DEADLINE
            and (_pct(number(row.get("low")), prev_close) or 0.0) <= -10.0
        ), None)
        if reached is None:
            continue

        final_low_row = min(
            (row for row in rows if number(row.get("low")) > 0),
            key=lambda row: number(row.get("low")),
        )
        low_price = number(final_low_row.get("low"))
        low_time_text = str(final_low_row.get("low_time") or "")
        try:
            low_time = datetime.strptime(low_time_text, "%H:%M:%S").time()
        except ValueError:
            low_time = final_low_row["_ts"].time()
        after_low = [
            row for row in rows
            if row["_ts"].time() >= low_time and number(row.get("current")) > 0
        ]
        peak_row = max(after_low, key=lambda row: number(row.get("current")))
        peak_price = number(peak_row.get("current"))
        observations.append({
            "code": code,
            "name": str(rows[-1].get("name") or rows[0].get("name") or code),
            "first_deep_ts": reached["_ts"].isoformat(timespec="seconds"),
            "previous_close": prev_close,
            "observed_low": low_price,
            "observed_low_time": low_time_text,
            "max_drop_pct": _pct(low_price, prev_close),
            "post_low_peak": peak_price,
            "post_low_peak_ts": peak_row["_ts"].isoformat(timespec="seconds"),
            "post_low_rise_pct": _pct(peak_price, low_price),
        })
    observations.sort(key=lambda row: row["max_drop_pct"])
    return {
        "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "source": str(source),
        "source_sha256": sha256(source),
        "source_last_ts": max(
            (row["_ts"] for rows in grouped.values() for row in rows),
            default=None,
        ).isoformat(timespec="seconds"),
        "observations": observations,
    }


def main() -> int:
    engine = RUN / "high_range_live_board_v1.py"
    days = [replay_day(day) for day in DATES]
    report = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS",
        "date": ",".join(day["date"] for day in days),
        "source_data": [day["source"] for day in days],
        "production_entry_point": "RUN/high_range_live_board_v1.py::_pct",
        "production_code_changed": "CHANGED",
        "performance_scope": "PRICE_PATH_OBSERVATION_NOT_TRADE",
        "command": r"C:\python310\python.exe -B RUN\s03_deep_crash_observation_replay_v1.py",
        "sha256": {
            str(engine): sha256(engine),
            **{day["source"]: day["source_sha256"] for day in days},
        },
        "definition": (
            "09:15 이전 누적 관측저가가 전일종가 대비 -10% 이하인 고저폭판 종목. "
            "max_drop_pct=전일종가→관측최저가, post_low_rise_pct=그 저점→이후 관측최고가. "
            "체결·매수·수익률이 아닌 생산판 가격경로 관측이다."
        ),
        "days": days,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(str(REPORT))
    for day in days:
        print(day["date"], day["source_last_ts"], len(day["observations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
