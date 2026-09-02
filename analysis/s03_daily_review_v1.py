"""S03 daily read-only review; imports no RUN module and writes no data."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOW_BREAK = "S03_REFERENCE_LOW_BREAK_SELL_REACCEL"


def csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def json_obj(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def jsonl_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict):
                    result.append(row)
        except OSError:
            continue
    return result


def dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def signal_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("signal_id") or ""),
        str(row.get("ts") or row.get("signal_ts") or ""),
        str(row.get("code") or "").zfill(6),
        str(row.get("signal_sequence") or ""),
    )


def ordering_after_cutoff(day: str) -> list[str]:
    rows = jsonl_rows([DATA / f"s03_s06_crash_claim_audit_{day}.jsonl"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("owner") == "S03":
            grouped[str(row.get("code") or "").zfill(6)].append(row)
    stale: set[str] = set()
    for code, events in grouped.items():
        events.sort(key=lambda row: str(row.get("ts") or ""))
        ordering = False
        for row in events:
            observed = dt(row.get("ts"))
            state = row.get("state")
            if state == "ORDERING":
                ordering = True
            elif ordering:
                if observed is None or observed.time() > time(9, 20):
                    stale.add(code)
                ordering = False
        if ordering:
            stale.add(code)
    claims = json_obj(DATA / f"s03_s06_crash_claim_{day}.json").get("claims")
    if isinstance(claims, dict):
        for code, row in claims.items():
            if isinstance(row, dict) and row.get("state") == "ORDERING":
                stale.add(str(code).zfill(6))
    return sorted(stale)


def final_candidates(day: str) -> tuple[list[dict[str, Any]], bool]:
    payload = json_obj(DATA / "strategy_03_골짜기_급반등_signal_v1.json")
    if str(payload.get("date") or "") != day:
        return [], False
    rows = payload.get("candidates")
    return ([row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list) else []), True


def low_breaks(day: str) -> list[dict[str, Any]]:
    folder = DATA / "audit" / "hold_sell" / day / "VALLEY_MORNING_CRASH"
    rows = jsonl_rows(folder.glob("*.jsonl") if folder.exists() else [])
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        decision = row.get("decision")
        if not isinstance(decision, dict) or decision.get("reason") != LOW_BREAK:
            continue
        state = row.get("state_after")
        state = state if isinstance(state, dict) else {}
        key = str(state.get("position_id") or decision.get("order_key") or len(unique))
        unique.setdefault(key, row)
    return list(unique.values())


def sell_reason(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith(LOW_BREAK):
        return LOW_BREAK
    match = re.match(r"([A-Z][A-Z0-9_]+)", text)
    return match.group(1) if match else (text.split()[0] if text else "(EMPTY)")


def table(headers: list[str], rows: list[list[Any]]) -> None:
    rows = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print(" | ".join(value.ljust(widths[i]) for i, value in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def review(day: str) -> int:
    s06_file = DATA / "strategy_06_crash_low_chase" / f"strategy_06_events_{day}.csv"
    s03_file = DATA / "strategy_03_rotation_v1" / f"strategy_03_events_{day}.csv"
    signal_file = (DATA / "strategy_03_골짜기_급반등_v1"
                   / f"strategy_03_signals_{day}.csv")
    s06 = csv_rows(s06_file)
    s03 = csv_rows(s03_file)
    signals = csv_rows(signal_file)
    candidates, has_snapshot = final_candidates(day)

    errors = sum("S03_OPEN_CRASH_CLAIM_ERROR" in str(row.get("reason") or "")
                 for row in s06)
    stale = ordering_after_cutoff(day)
    not_held = sum(row.get("reason") == "S03_CRASH_CLAIM_NOT_HELD"
                   for row in candidates)
    open_missing = sum(row.get("reason") == "OPEN_PRICE_MISSING"
                       for row in candidates)

    early: dict[tuple[str, ...], dict[str, Any]] = {}
    deep: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in signals:
        observed = dt(row.get("ts"))
        if observed and time(9, 0) <= observed.time() < time(9, 3):
            early[signal_key(row)] = row
        drop = number(row.get("drop_from_open_pct"))
        if drop is not None and drop <= -8.0:
            deep[signal_key(row)] = row
    deep_codes = {str(row.get("code") or "").zfill(6) for row in deep.values()}
    deep_buys = [row for row in s03
                 if row.get("event") == "BUY_CONFIRMED"
                 and str(row.get("code") or "").zfill(6) in deep_codes]

    breaks = low_breaks(day)
    zero_buy10 = 0
    for row in breaks:
        decision = row.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        meta = decision.get("metadata")
        meta = meta if isinstance(meta, dict) else {}
        obs = row.get("observation")
        obs = obs if isinstance(obs, dict) else {}
        ready = meta.get("s03_low_break_flow_data_ready",
                         obs.get("s03_low_break_flow_data_ready"))
        buy10 = obs.get("buy_money_per_sec_10s",
                        meta.get("buy_money_per_sec_10s"))
        if truth(ready) and number(buy10) == 0.0:
            zero_buy10 += 1

    snapshot = lambda value: value if has_snapshot else "N/A"
    rows = [
        [1, "S03_OPEN_CRASH_CLAIM_ERROR", errors,
         str(s06_file.relative_to(ROOT)) if s06_file.exists() else "source missing"],
        [2, "ORDERING remaining after 09:20", len(stale), ",".join(stale) or "-"],
        [3, "S03_CRASH_CLAIM_NOT_HELD", snapshot(not_held),
         "final snapshot minimum" if has_snapshot else "daily snapshot missing"],
        [4, "09:00-09:02 signals / OPEN_PRICE_MISSING",
         f"{len(early)} / {snapshot(open_missing)}",
         "daily CSV / final snapshot minimum"],
        [5, "open <= -8% signals / buys", f"{len(deep)} / {len(deep_buys)}",
         "[UNVERIFIED] buy engine event; no broker match"],
        [6, LOW_BREAK, len(breaks), "hold_sell daily audit"],
        [7, "row 6: flow_ready=True & buy10=0", zero_buy10,
         "hold_sell daily audit"],
    ]
    print(f"S03 DAILY REVIEW {day} (READ ONLY)")
    table(["#", "check", "result", "source/note"], rows)

    counts = Counter(sell_reason(row.get("reason")) for row in s03
                     if row.get("event") == "SELL_CONFIRMED")
    perf = [[reason, count, "N/A", "N/A"]
            for reason, count in sorted(counts.items())]
    print("\n8. sell reason summary")
    table(["sell reason", "engine events", "MFE avg", "realized avg"],
          perf or [["(none)", 0, "N/A", "N/A"]])
    print("Performance averages N/A: no truth-gated FULL_ENTRY_EXIT report was read.")
    print("WARNING: row 3 and OPEN_PRICE_MISSING are final-snapshot minimums; zero is not conclusive.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only S03 daily review")
    parser.add_argument("date", help="YYYYMMDD")
    args = parser.parse_args()
    try:
        datetime.strptime(args.date, "%Y%m%d")
    except ValueError:
        parser.error("date must be YYYYMMDD")
    return review(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
