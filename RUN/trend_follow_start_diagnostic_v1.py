# -*- coding: utf-8 -*-
"""Order-zero TREND_START funnel and frozen-definition comparison."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import trend_follow_board_v1 as prod


SOURCE = ROOT / "data" / "eod_daily_bars.csv"
REPORT = ROOT / "reports" / "trend_follow_start_diagnostic_20260902.json"
HORIZONS = (1, 3, 5)
SIGNAL_DAYS = 25


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def conditions(entry: dict, index: int) -> dict | None:
    closes, highs, values = entry["closes"], entry["highs"], entry["values"]
    if index + 1 < prod.MIN_BARS:
        return None
    if prod.is_preferred_name(entry["name"]):
        return None
    value20 = sum(values[index - 19:index + 1]) / 20
    close = closes[index]
    if value20 < prod.MIN_VALUE_20D_MKRW or close <= prod.MIN_PRICE:
        return None
    ma = {period: prod.sma(closes, index, period)
          for period in (5, 10, 20, 60, 120, 200)}
    ma20_prev = prod.sma(closes, index - 5, 20)
    ma60_prev = prod.sma(closes, index - 5, 60)
    comp_now = prod.compression_at(closes, index)
    if ma[20] is None or ma[60] is None or ma20_prev is None or comp_now is None:
        return None
    past_tight = 0
    for back in range(prod.PAST_WINDOW[1], prod.PAST_WINDOW[0] + 1):
        past = prod.compression_at(closes, index - back)
        if past is not None and past <= prod.COMPRESSION_PAST_PCT:
            past_tight += 1
    had_compression = past_tight >= prod.PAST_MIN_DAYS
    box_high20 = max(highs[index - 20:index])
    aligned = close > ma[5] > ma[10] > ma[20]
    ma20_non_down = ma[20] >= ma20_prev
    breakout_current = close >= box_high20 * 0.99
    breakout_alt_a = close >= box_high20 * 0.97
    value_explosion_alt_a = values[index] >= value20 * 1.5
    stretch_now = (close / ma[20] - 1) * 100
    ret20 = (close / closes[index - 20] - 1) * 100
    bear = close < ma[20] < ma[60] and not (ma[20] > ma20_prev)
    overheated = stretch_now > 30 or ret20 > 60
    return {
        "close": close,
        "had_compression": had_compression,
        "aligned": aligned,
        "ma20_non_down": ma20_non_down,
        "breakout_current": breakout_current,
        "breakout_alt_a": breakout_alt_a,
        "value_explosion_alt_a": value_explosion_alt_a,
        "bear": bear,
        "overheated": overheated,
    }


def signal(flags: dict, definition: str) -> bool:
    common = (flags["had_compression"] and flags["aligned"]
              and flags["ma20_non_down"])
    if definition == "CURRENT":
        raw = common and flags["breakout_current"]
    elif definition == "ALT_A_097_VALUE_1P5":
        raw = (common and flags["breakout_alt_a"]
               and flags["value_explosion_alt_a"])
    elif definition == "ALT_B_NO_BREAKOUT":
        raw = common
    else:
        raise ValueError(definition)
    return bool(raw and not flags["bear"] and not flags["overheated"])


def outcome_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "win_rate_pct": None, "median_pct": None,
                "worst_pct": None}
    return {
        "n": len(values),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 6),
        "median_pct": round(statistics.median(values), 6),
        "worst_pct": round(min(values), 6),
    }


def main() -> int:
    series = prod.load_series()
    all_dates = sorted({date for entry in series.values() for date in entry["dates"]})
    if len(all_dates) < SIGNAL_DAYS + max(HORIZONS):
        raise RuntimeError("not enough trading dates")
    signal_dates = all_dates[-(SIGNAL_DAYS + max(HORIZONS)):-max(HORIZONS)]
    global_date_index = {date: index for index, date in enumerate(all_dates)}
    definitions = ("CURRENT", "ALT_A_097_VALUE_1P5", "ALT_B_NO_BREAKOUT")
    returns = {definition: {horizon: [] for horizon in HORIZONS}
               for definition in definitions}
    signal_rows = {definition: [] for definition in definitions}
    funnels = []
    current_reproduction_mismatches = []

    for date in signal_dates:
        counts = {
            "date": date, "n_eligible": 0, "n_had_compression": 0,
            "n_aligned": 0, "n_ma20_non_down": 0, "n_breakout_current": 0,
            "n_had_aligned": 0, "n_had_aligned_ma20": 0, "n_all4": 0,
            "n_bear_stolen": 0, "n_overheat_stolen": 0,
            "n_trend_start_current": 0,
        }
        for code, entry in series.items():
            try:
                index = entry["dates"].index(date)
            except ValueError:
                continue
            flags = conditions(entry, index)
            if flags is None:
                continue
            counts["n_eligible"] += 1
            for key, count_key in (
                ("had_compression", "n_had_compression"),
                ("aligned", "n_aligned"),
                ("ma20_non_down", "n_ma20_non_down"),
                ("breakout_current", "n_breakout_current"),
            ):
                counts[count_key] += int(flags[key])
            had_aligned = flags["had_compression"] and flags["aligned"]
            had_aligned_ma20 = had_aligned and flags["ma20_non_down"]
            all4 = had_aligned_ma20 and flags["breakout_current"]
            counts["n_had_aligned"] += int(had_aligned)
            counts["n_had_aligned_ma20"] += int(had_aligned_ma20)
            counts["n_all4"] += int(all4)
            counts["n_bear_stolen"] += int(all4 and flags["bear"])
            counts["n_overheat_stolen"] += int(all4 and flags["overheated"])

            current_signal = signal(flags, "CURRENT")
            counts["n_trend_start_current"] += int(current_signal)
            prefix = {key: (value[:index + 1] if isinstance(value, list) else value)
                      for key, value in entry.items()}
            prefix["_code"] = code
            verdict = prod.judge(prefix, date)
            production_signal = bool(verdict and verdict.get("state") == "TREND_START")
            if current_signal != production_signal:
                current_reproduction_mismatches.append({
                    "date": date, "code": code,
                    "replicated": current_signal, "production": production_signal,
                })

            for definition in definitions:
                if not signal(flags, definition):
                    continue
                signal_rows[definition].append({"date": date, "code": code})
                date_pos = global_date_index[date]
                signal_close = flags["close"]
                close_by_date = dict(zip(entry["dates"], entry["closes"]))
                for horizon in HORIZONS:
                    future_date = all_dates[date_pos + horizon]
                    future_close = close_by_date.get(future_date)
                    if future_close:
                        returns[definition][horizon].append(
                            (future_close / signal_close - 1) * 100
                        )
        funnels.append(counts)

    comparison = {}
    for definition in definitions:
        comparison[definition] = {
            "signal_count": len(signal_rows[definition]),
            "outcomes": {f"D+{horizon}": outcome_stats(returns[definition][horizon])
                         for horizon in HORIZONS},
        }
    insufficient = {
        definition: data["signal_count"] < 20
        for definition, data in comparison.items()
    }
    report = {
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS" if not current_reproduction_mismatches else "FAIL",
        "analysis_scope": "ORDER_ZERO_DAILY_CLOSE_RESEARCH_NOT_PRODUCTION_ENTRY_EXIT",
        "source_data": str(SOURCE),
        "source_sha256": sha256(SOURCE),
        "production_entry_point": str(ROOT / "RUN" / "trend_follow_board_v1.py") + "::judge",
        "production_sha256": sha256(ROOT / "RUN" / "trend_follow_board_v1.py"),
        "command": "py -3 -B -X utf8 RUN/trend_follow_start_diagnostic_v1.py",
        "signal_dates": signal_dates,
        "horizons": list(HORIZONS),
        "return_definition": "signal close to D+N close, gross, no fees or slippage",
        "funnel_by_date": funnels,
        "funnel_totals": {
            key: sum(row[key] for row in funnels)
            for key in funnels[0] if key != "date"
        },
        "definitions": {
            "CURRENT": "had_compression AND aligned AND ma20_non_down AND close>=box_high20*0.99",
            "ALT_A_097_VALUE_1P5": "CURRENT with breakout*0.97 AND current_value>=value20*1.5",
            "ALT_B_NO_BREAKOUT": "had_compression AND aligned AND ma20_non_down",
            "preemption_all": "BEAR then OVERHEATED, identical to production order",
        },
        "comparison": comparison,
        "sample_gate_lt_20": insufficient,
        "recommendation": (
            "INSUFFICIENT_SAMPLE_NO_RECOMMENDATION"
            if any(insufficient.values()) else "REVIEW_REQUIRED_NO_AUTO_WINNER"
        ),
        "current_definition_reproduction_mismatches": current_reproduction_mismatches,
        "source_notes": {
            "past_window_runtime": list(prod.PAST_WINDOW),
            "past_window_comment_claim": "25~3 days",
            "past_window_mismatch": list(prod.PAST_WINDOW) != [25, 3],
            "html_writers": [
                "RUN/trend_follow_board_v1.py",
                "RUN/flow_trend_intraday_refresh_v1.py",
            ],
            "html_writer_resolution": (
                "Both call trend_follow_board_v1.build_html; intraday refresher writes until 15:20, "
                "scheduled trend board is the later daily writer."
            ),
        },
        "files_changed_in_production": [],
        "orders_sent": 0,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "report": str(REPORT),
        "signal_counts": {key: value["signal_count"] for key, value in comparison.items()},
        "recommendation": report["recommendation"],
        "mismatches": len(current_reproduction_mismatches),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
