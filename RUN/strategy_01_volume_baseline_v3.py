# -*- coding: utf-8 -*-
"""Build S01 opening relative-volume baselines from preserved one-minute bars."""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


DATA = Path(r"C:\stock_bot\data")
OUTPUT = DATA / "s01_open_volume_baseline_v3.json"


def build(days: int = 20) -> dict:
    files = [p for p in sorted(DATA.glob("prices_1m_clean_*.csv"), reverse=True)
             if p.stat().st_size > 100_000][:days]
    observations: dict[tuple[str, int], list[float]] = defaultdict(list)
    for path in files:
        per_code: dict[str, float] = defaultdict(float)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                stamp = str(row.get("ts") or "")
                if len(stamp) < 12 or stamp[8:12] < "0900" or stamp[8:12] > "0919":
                    continue
                try:
                    minute = int(stamp[10:12])
                    volume = max(0.0, float(row.get("volume") or 0))
                except (TypeError, ValueError):
                    continue
                code = str(row.get("code") or "").zfill(6)
                per_code[code] += volume
                observations[(code, minute)].append(per_code[code])
    rows: dict[str, dict[str, float]] = defaultdict(dict)
    for (code, minute), values in observations.items():
        if values:
            rows[code][str(minute)] = round(statistics.median(values), 3)
    return {
        "schema": "s01_open_volume_baseline_v3",
        "source_files": [str(p) for p in files],
        "codes": rows,
    }


def main() -> int:
    payload = build()
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT)
    print(json.dumps({"output": str(OUTPUT), "files": len(payload["source_files"]),
                      "codes": len(payload["codes"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
