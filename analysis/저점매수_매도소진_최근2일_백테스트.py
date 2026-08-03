# -*- coding: utf-8 -*-
"""저점매수 매도소진 최근 2거래일 저점 포착 비교.

매도·손익·수익률은 계산하지 않는다. 미래 데이터는 신호 생성에 사용하지 않고,
각 에피소드가 끝난 뒤 정답 최저가를 채점하는 데만 사용한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable, Optional


ROOT = Path(r"C:\stock_bot")
RUN_DIR = ROOT / "RUN"
sys.path.insert(0, str(RUN_DIR))

from 저점매수_매도소진 import (  # noqa: E402
    BottomSignal,
    MarketPoint,
    detect_flow_book_exhaustion,
    detect_hybrid_exhaustion_pull,
    detect_legacy_pull,
    detect_sell_exhaustion,
)


DEFAULT_DAYS = ("20260723", "20260724")
RAW_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
REPLAY_DIR = ROOT / "data" / "shadow" / "captain2_replay"
OUT_CSV = ROOT / "analysis" / "저점매수_매도소진_최근2일_비교.csv"
OUT_JSON = ROOT / "analysis" / "저점매수_매도소진_최근2일_요약.json"


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _raw_files(day: str) -> list[Path]:
    path = RAW_DIR / f"mf_1s_{day}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return [path]


def _name_map(days: Iterable[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for day in days:
        paths = sorted(REPLAY_DIR.glob(f"captain2_1s_{day}*.csv"))
        for path in paths:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    code = str(row.get("code", "")).zfill(6)
                    name = str(row.get("name", "")).strip()
                    if code and name:
                        names[code] = name
    return names


def _evaluate(
    day: str,
    code: str,
    name: str,
    points: list[MarketPoint],
    signal: Optional[BottomSignal],
    algorithm: str,
) -> dict:
    true_low_idx = min(range(len(points)), key=lambda idx: points[idx].price)
    true_low = points[true_low_idx]
    peak = max(point.price for point in points)
    depth_pct = (peak / true_low.price - 1.0) * 100.0
    row = {
        "일자": day,
        "종목코드": code,
        "종목명": name,
        "알고리즘": algorithm,
        "에피소드시작": points[0].ts.isoformat(timespec="milliseconds"),
        "관측초": round((points[-1].ts - points[0].ts).total_seconds(), 1),
        "관측개수": len(points),
        "고점": round(peak, 2),
        "정답저점": round(true_low.price, 2),
        "정답저점시각": true_low.ts.isoformat(timespec="milliseconds"),
        "고점저점깊이_pct": round(depth_pct, 4),
        "신호": "YES" if signal else "NO",
        "신호시각": "",
        "신호가격": "",
        "탐지저점": "",
        "탐지저점시각": "",
        "저점파동수": "",
        "탐지저점오차_pct": "",
        "매수가저점오차_pct": "",
        "정답저점후신호": "",
        "신호후신저점붕괴": "",
        "저점매수가능": "",
        "사유": "",
    }
    if signal is None:
        return row
    anchor_error = (signal.anchor_low_price / true_low.price - 1.0) * 100.0
    entry_error = (signal.signal_price / true_low.price - 1.0) * 100.0
    signal_idx = next(
        idx for idx, point in enumerate(points) if point.ts >= signal.signal_ts
    )
    future_low = min(point.price for point in points[signal_idx:])
    broke = future_low < signal.anchor_low_price
    after_true_low = signal.signal_ts >= true_low.ts
    low_buy_possible = after_true_low and not broke and entry_error <= 1.50
    row.update(
        {
            "신호시각": signal.signal_ts.isoformat(timespec="milliseconds"),
            "신호가격": round(signal.signal_price, 2),
            "탐지저점": round(signal.anchor_low_price, 2),
            "탐지저점시각": signal.anchor_low_ts.isoformat(timespec="milliseconds"),
            "저점파동수": signal.wave_count,
            "탐지저점오차_pct": round(anchor_error, 4),
            "매수가저점오차_pct": round(entry_error, 4),
            "정답저점후신호": "YES" if after_true_low else "NO",
            "신호후신저점붕괴": "YES" if broke else "NO",
            "저점매수가능": "YES" if low_buy_possible else "NO",
            "사유": signal.reason,
        }
    )
    return row


def _eligible(points: list[MarketPoint]) -> bool:
    if len(points) < 20 or points[0].price < 10_000:
        return False
    duration = (points[-1].ts - points[0].ts).total_seconds()
    if duration < 20:
        return False
    peak = max(point.price for point in points)
    low = min(point.price for point in points)
    return low > 0 and (peak / low - 1.0) * 100.0 >= 2.0


def _score_episode(
    day: str,
    code: str,
    name: str,
    points: list[MarketPoint],
) -> list[dict]:
    by_ts: dict[datetime, MarketPoint] = {point.ts: point for point in points}
    ordered = [by_ts[ts] for ts in sorted(by_ts)]
    if not _eligible(ordered):
        return []
    old_signal = detect_legacy_pull(ordered)
    new_signal = detect_sell_exhaustion(ordered)
    pro_signal = detect_flow_book_exhaustion(ordered)
    hybrid_signal = detect_hybrid_exhaustion_pull(ordered)
    return [
        _evaluate(day, code, name, ordered, old_signal, "OLD_CAPTAIN2_PULL"),
        _evaluate(day, code, name, ordered, new_signal, "NEW_SELL_EXHAUSTION"),
        _evaluate(
            day,
            code,
            name,
            ordered,
            pro_signal,
            "PRO_FLOW_BOOK_EXHAUSTION",
        ),
        _evaluate(
            day,
            code,
            name,
            ordered,
            hybrid_signal,
            "HYBRID_EXHAUSTION_PULL",
        ),
    ]


def _scan_day(day: str, names: dict[str, str]) -> tuple[list[dict], dict]:
    active: dict[str, tuple[str, list[MarketPoint]]] = {}
    results: list[dict] = []
    stats = defaultdict(int)

    def flush(code: str) -> None:
        item = active.pop(code, None)
        if not item:
            return
        _, points = item
        scored = _score_episode(day, code, names.get(code, code), points)
        if scored:
            results.extend(scored)
            stats["eligible_episodes"] += 1
        else:
            stats["excluded_episodes"] += 1

    for path in _raw_files(day):
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            header = handle.readline().rstrip("\r\n").split(",")
            index = {name: header.index(name) for name in (
                "ts",
                "code",
                "current_price",
                "cum_vol",
                "che_str",
                "ask_tot",
                "bid_tot",
                "buy_money_cum",
                "sell_money_cum",
                "flow_detect_ts",
            )}
            max_index = max(index.values())
            for line in handle:
                stats["raw_rows"] += 1
                parts = line.rstrip("\r\n").split(",", max_index + 1)
                if len(parts) <= max_index:
                    stats["malformed_rows"] += 1
                    continue
                flow_ts = parts[index["flow_detect_ts"]].strip()
                if not flow_ts:
                    continue
                code = parts[index["code"]].strip().zfill(6)
                if len(code) != 6 or not code.isdigit():
                    stats["non_stock_rows"] += 1
                    continue
                price = _float(parts[index["current_price"]])
                if price <= 0:
                    continue
                if code in active and active[code][0] != flow_ts:
                    flush(code)
                if code not in active:
                    active[code] = (flow_ts, [])
                try:
                    ts = datetime.fromisoformat(parts[index["ts"]])
                except ValueError:
                    stats["malformed_rows"] += 1
                    continue
                active[code][1].append(
                    MarketPoint(
                        ts=ts,
                        price=price,
                        cum_vol=_float(parts[index["cum_vol"]]),
                        che_str=_float(parts[index["che_str"]]),
                        ask_tot=_float(parts[index["ask_tot"]]),
                        bid_tot=_float(parts[index["bid_tot"]]),
                        buy_money_cum=_float(parts[index["buy_money_cum"]]),
                        sell_money_cum=_float(parts[index["sell_money_cum"]]),
                    )
                )
                stats["active_rows"] += 1
    for code in list(active):
        flush(code)
    return results, dict(stats)


def _algorithm_summary(rows: list[dict], algorithm: str) -> dict:
    selected = [row for row in rows if row["알고리즘"] == algorithm]
    signals = [row for row in selected if row["신호"] == "YES"]
    possible = [row for row in signals if row["저점매수가능"] == "YES"]
    broken = [row for row in signals if row["신호후신저점붕괴"] == "YES"]
    anchor_errors = [float(row["탐지저점오차_pct"]) for row in signals]
    entry_errors = [float(row["매수가저점오차_pct"]) for row in signals]
    total = len(selected)
    return {
        "평가에피소드": total,
        "신호수": len(signals),
        "신호포착률_pct": round(len(signals) / total * 100.0, 2) if total else 0.0,
        "저점매수가능수": len(possible),
        "저점매수정확률_pct": (
            round(len(possible) / len(signals) * 100.0, 2) if signals else 0.0
        ),
        "전체저점포착률_pct": (
            round(len(possible) / total * 100.0, 2) if total else 0.0
        ),
        "신호후신저점붕괴율_pct": (
            round(len(broken) / len(signals) * 100.0, 2) if signals else 0.0
        ),
        "탐지저점오차중앙값_pct": round(median(anchor_errors), 4)
        if anchor_errors
        else None,
        "매수가저점오차중앙값_pct": round(median(entry_errors), 4)
        if entry_errors
        else None,
    }


def run(days: tuple[str, ...], out_csv: Path, out_json: Path) -> dict:
    names = _name_map(days)
    all_rows: list[dict] = []
    scan_stats: dict[str, dict] = {}
    for day in days:
        rows, stats = _scan_day(day, names)
        all_rows.extend(rows)
        scan_stats[day] = stats
        print(
            f"[{day}] 원본 {stats.get('raw_rows', 0):,}행 · "
            f"활성 {stats.get('active_rows', 0):,}행 · "
            f"평가 {stats.get('eligible_episodes', 0):,}에피소드"
        )
    if not all_rows:
        raise RuntimeError("평가 가능한 저점 에피소드가 없습니다.")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    summary = {
        "목적": "매도·손익 없이 저점매수 가능성만 비교",
        "자료": [str(path) for day in days for path in _raw_files(day)],
        "기간": list(days),
        "시간대": "Asia/Seoul",
        "정답저점": "각 돈유입 에피소드 안의 사후 최저가(평가에만 사용)",
        "저점매수가능": "정답저점 이후 신호 + 신호후 저점 미붕괴 + 매수가 오차 1.5% 이내",
        "공통필터": "가격 1만원 이상·에피소드 20초/20관측 이상·고점저점 깊이 2% 이상",
        "스캔통계": scan_stats,
        "알고리즘": {
            "OLD_CAPTAIN2_PULL": _algorithm_summary(all_rows, "OLD_CAPTAIN2_PULL"),
            "NEW_SELL_EXHAUSTION": _algorithm_summary(
                all_rows, "NEW_SELL_EXHAUSTION"
            ),
            "PRO_FLOW_BOOK_EXHAUSTION": _algorithm_summary(
                all_rows, "PRO_FLOW_BOOK_EXHAUSTION"
            ),
            "HYBRID_EXHAUSTION_PULL": _algorithm_summary(
                all_rows, "HYBRID_EXHAUSTION_PULL"
            ),
        },
        "출력CSV": str(out_csv),
    }
    out_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary["알고리즘"], ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", nargs="+", default=list(DEFAULT_DAYS))
    parser.add_argument("--out-csv", type=Path, default=OUT_CSV)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = parser.parse_args()
    run(tuple(args.days), args.out_csv, args.out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
