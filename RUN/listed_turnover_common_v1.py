"""Shared listed-share turnover metrics for live candidate ranking."""
from __future__ import annotations

import csv
from pathlib import Path


DEFAULT_SHARES_PATH = Path(r"C:\stock_bot\data\shares_outstanding.csv")
_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS = -1
_CACHE: dict[str, float] = {}


def _load_shares(path: Path) -> dict[str, float]:
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE
    try:
        mtime_ns = path.stat().st_mtime_ns
        if path == _CACHE_PATH and mtime_ns == _CACHE_MTIME_NS:
            return _CACHE
        rows: dict[str, float] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = str(row.get("code") or "").zfill(6)
                try:
                    shares = float(row.get("shares") or 0)
                except (TypeError, ValueError):
                    shares = 0.0
                if len(code) == 6 and code.isdigit() and shares > 0:
                    rows[code] = shares
        _CACHE_PATH, _CACHE_MTIME_NS, _CACHE = path, mtime_ns, rows
    except OSError:
        _CACHE_PATH, _CACHE_MTIME_NS, _CACHE = path, -1, {}
    return _CACHE


def turnover_bonus(turnover_pct: float) -> int:
    """0:<2%, 1:2-5%, 2:5-10%, 3:>=10%."""
    if turnover_pct >= 10.0:
        return 3
    if turnover_pct >= 5.0:
        return 2
    if turnover_pct >= 2.0:
        return 1
    return 0


def listed_turnover_metrics(
    code: str,
    cumulative_volume: float,
    *,
    shares_path: Path = DEFAULT_SHARES_PATH,
) -> dict[str, float | int]:
    shares = _load_shares(Path(shares_path)).get(str(code).zfill(6), 0.0)
    volume = max(0.0, float(cumulative_volume or 0.0))
    pct = volume / shares * 100.0 if shares > 0 else 0.0
    return {
        "listed_turnover_pct": round(pct, 6),
        "listed_turnover_bonus": turnover_bonus(pct),
    }
