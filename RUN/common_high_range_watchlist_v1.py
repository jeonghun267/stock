# -*- coding: utf-8 -*-
"""주식공통 고저폭 TOP30 선별기.

전날까지 확정된 EOD만 읽어 공통 관찰 후보와 실시간 구독 파일을 만든다.
주문 경로를 호출하지 않으며 매수·매도 판단도 수행하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


DEFAULT_BASE = Path(r"C:\stock_bot")
RANGE_MIN_PCT = 10.0
DAILY_VALUE_MIN_EOK = 100.0
PRICE_MIN_KRW = 10_000.0
CORE_AVG_5D_VALUE_EOK = 500.0
CORE_PRIORITY_MIN_5D_RANGE_PCT = 12.0
TOP_N = 30


def _atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding=encoding)
    os.replace(temp, path)


def _load_bars(eod_path: Path) -> pd.DataFrame:
    bars = pd.read_csv(eod_path, dtype={"code": str})
    required = {"date", "code", "name", "high", "low", "close", "value"}
    missing = sorted(required.difference(bars.columns))
    if missing:
        raise ValueError(f"EOD missing columns: {missing}")
    bars["date"] = bars["date"].astype(str)
    bars["code"] = bars["code"].str.zfill(6)
    numeric = ["high", "low", "close", "value"]
    bars[numeric] = bars[numeric].apply(pd.to_numeric, errors="coerce")
    bars = bars.dropna(subset=["date", "code", "high", "low", "close", "value"])
    bars = bars.sort_values(["code", "date"]).copy()
    duplicates = int(bars.duplicated(["date", "code"]).sum())
    if duplicates:
        raise ValueError(f"EOD duplicate date-code keys: {duplicates}")
    return bars


def _add_metrics(bars: pd.DataFrame) -> pd.DataFrame:
    bars["range_pct"] = (bars["high"] / bars["low"] - 1.0) * 100.0
    bars["value_eok"] = bars["value"] / 100.0
    bars["qualified_day"] = (
        (bars["range_pct"] >= RANGE_MIN_PCT)
        & (bars["value_eok"] >= DAILY_VALUE_MIN_EOK)
    )
    grouped = bars.groupby("code", group_keys=False)
    bars["streak"] = (
        grouped["qualified_day"]
        .transform(lambda s: s.groupby((~s).cumsum()).cumsum())
        .astype(int)
    )
    bars["avg_5d_range_pct"] = grouped["range_pct"].transform(
        lambda s: s.rolling(5, min_periods=5).mean()
    )
    bars["min_5d_range_pct"] = grouped["range_pct"].transform(
        lambda s: s.rolling(5, min_periods=5).min()
    )
    bars["avg_5d_value_eok"] = grouped["value_eok"].transform(
        lambda s: s.rolling(5, min_periods=5).mean()
    )
    return bars


def _stage_rows(rows: pd.DataFrame) -> pd.DataFrame:
    core = (rows["streak"] >= 5) & (
        rows["avg_5d_value_eok"] >= CORE_AVG_5D_VALUE_EOK
    )
    confirmed = rows["streak"] >= 5
    early = rows["streak"].between(3, 4)
    rows["stage"] = "신규대"
    rows.loc[early, "stage"] = "선발대"
    rows.loc[confirmed, "stage"] = "확인대"
    rows.loc[core, "stage"] = "핵심확인대"
    rows["crown"] = core
    rows["stage_order"] = rows["stage"].map(
        {"핵심확인대": 1, "확인대": 2, "선발대": 3, "신규대": 4}
    )
    return rows


def _load_holidays(base: Path) -> set[str]:
    # 휴장일 파일 없음/깨짐 = 주말만 제외 (s05_signal_guard_v1 과 동일한 fail-open)
    try:
        return {
            line.strip()
            for line in (base / "config" / "krx_holidays.txt")
            .read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError:
        return set()


def _prev_trading_day(now: datetime, holidays: set[str]) -> str:
    day = now.date() - timedelta(days=1)
    while day.weekday() >= 5 or day.strftime("%Y%m%d") in holidays:
        day -= timedelta(days=1)
    return day.strftime("%Y%m%d")


def _round_or_none(value, digits: int = 2):
    # ★[2026-07-30 친구님 승인 "NaN 결측도 고쳐줘"] 상장 5일 미만 종목은 5일 지표가 없어
    #   NaN 이 JSON 에 그대로 실렸다(표준 위반 — 엄격한 파서는 파일 전체를 못 읽음.
    #   1년 재현 84/247일 발생). null 로 바꾼다. 정렬은 종전 그대로(결측은 그룹 꼬리) —
    #   등수 로직 무변경. 롤백: backup\common_high_range_watchlist_v1_20260730_nanfix.py
    number = float(value)
    if math.isnan(number):
        return None
    return round(number, digits)


def select_candidates(eod_path: Path) -> tuple[str, list[dict]]:
    bars = _add_metrics(_load_bars(eod_path))
    source_date = str(bars["date"].max())
    latest = bars[
        (bars["date"] == source_date)
        & bars["qualified_day"]
        & (bars["close"] >= PRICE_MIN_KRW)
    ].copy()
    latest = _stage_rows(latest)
    latest = latest.sort_values(
        [
            "stage_order",
            "streak",
            "avg_5d_range_pct",
            "min_5d_range_pct",
            "avg_5d_value_eok",
        ],
        ascending=[True, False, False, False, False],
    ).head(TOP_N)

    records: list[dict] = []
    for rank, row in enumerate(latest.itertuples(index=False), start=1):
        records.append(
            {
                "rank": rank,
                "stage": str(row.stage),
                "crown": bool(row.crown),
                "code": str(row.code).zfill(6),
                "name": str(row.name),
                "prev_close": float(row.close),
                "streak": int(row.streak),
                "prev_range_pct": round(float(row.range_pct), 2),
                "avg_5d_range_pct": _round_or_none(row.avg_5d_range_pct),
                "min_5d_range_pct": _round_or_none(row.min_5d_range_pct),
                "prev_value_eok": round(float(row.value_eok), 2),
                "avg_5d_value_eok": _round_or_none(row.avg_5d_value_eok),
            }
        )
    return source_date, records


def _csv_frame(source_date: str, records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        rows.append(
            {
                "순위": record["rank"],
                "왕관": "👑고저폭" if record["crown"] else "",
                "단계": record["stage"],
                "기준일": source_date,
                "종목명": record["name"],
                "회사번호(종목코드)": record["code"],
                "전일종가": record["prev_close"],
                "연속발생일": record["streak"],
                "전일고저폭_pct": record["prev_range_pct"],
                "최근5일평균고저폭_pct": "신규" if record["avg_5d_range_pct"] is None
                else record["avg_5d_range_pct"],
                "최근5일최소고저폭_pct": "신규" if record["min_5d_range_pct"] is None
                else record["min_5d_range_pct"],
                "전일거래대금_억원": record["prev_value_eok"],
                "최근5일평균거래대금_억원": "신규" if record["avg_5d_value_eok"] is None
                else record["avg_5d_value_eok"],
            }
        )
    return pd.DataFrame(rows)


def build_and_publish(
    base: Path = DEFAULT_BASE,
    eod_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now()
    eod_path = eod_path or base / "data" / "eod_daily_bars.csv"
    source_date, records = select_candidates(eod_path)
    # ★[2026-07-30 친구님 승인 "⑤도 해줘"] 일봉 신선도 검증 — 기준일이 직전 거래일보다
    #   오래됐으면(전날 16:05 수집 실패 등) 낡음 깃발을 싣는다. 생성은 막지 않는다
    #   (관찰·그림자까지 죽는 것 방지) — 실황판이 이 깃발로 빨간 경고를 띄운다.
    #   저녁 재생성처럼 기준일이 더 최신인 경우는 낡음이 아니다(source >= 직전거래일).
    #   롤백: backup\common_high_range_watchlist_v1_20260730_stalecheck.py
    expected_source = _prev_trading_day(now, _load_holidays(base))
    source_stale = source_date < expected_source
    payload = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "for_date": now.strftime("%Y%m%d"),
        "source_date": source_date,
        "expected_source_date": expected_source,
        "source_stale": source_stale,
        "candidate_count": len(records),
        "crown_count": sum(1 for row in records if row["crown"]),
        "filters": {
            "price_min_krw": PRICE_MIN_KRW,
            "daily_range_min_pct": RANGE_MIN_PCT,
            "daily_value_min_eok": DAILY_VALUE_MIN_EOK,
            "core_streak_min_days": 5,
            "core_avg_5d_value_min_eok": CORE_AVG_5D_VALUE_EOK,
            "core_priority_min_5d_range_pct": CORE_PRIORITY_MIN_5D_RANGE_PCT,
            "max_candidates": TOP_N,
        },
        "candidates": records,
    }
    data_dir = base / "data"
    ipc_dir = base / "IPC"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    _atomic_write(data_dir / "common_high_range_top30.json", json_text)
    frame = _csv_frame(source_date, records)
    _atomic_write(
        data_dir / "common_high_range_top30.csv",
        frame.to_csv(index=False),
        encoding="utf-8-sig",
    )
    watch = {
        "codes": [row["code"] for row in records],
        "crown_codes": [row["code"] for row in records if row["crown"]],
        "crown_priority_codes": [
            row["code"] for row in records
            if row["crown"]
            and row["min_5d_range_pct"] is not None
            and row["min_5d_range_pct"] >= CORE_PRIORITY_MIN_5D_RANGE_PCT
        ],
        "ts": now.isoformat(),
        "for_date": now.strftime("%Y%m%d"),
        "source_date": source_date,
        "source_stale": source_stale,
        "src": "common_high_range_top30",
    }
    _atomic_write(
        ipc_dir / "micro_watch_high_range.json",
        json.dumps(watch, ensure_ascii=False),
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--eod", type=Path)
    args = parser.parse_args()
    payload = build_and_publish(args.base, args.eod)
    print(
        f"HIGH_RANGE_TOP30 source={payload['source_date']} "
        f"count={payload['candidate_count']} crown={payload['crown_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
