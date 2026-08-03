# -*- coding: utf-8 -*-
"""실시간 시세 지연 판독기 - 계측 ①② 의 CSV 를 한 장 보고로 (읽기 전용).

★[2026-08-01 친구님 지시 "월요일 저녁에 장끝나고 보고해줘"]
계측기가 쌓은 원자료를 사람이 읽을 숫자로 바꾼다. 아무것도 고치지 않는다.

읽는 것
  data\latency_probe\snapshot_lag_YYYYMMDD.csv   ② 우리 집 안 지연(스냅샷→전략)
  data\latency_probe\real_latency_YYYYMMDD.csv   ① 키움서버→우리 PC 지연

사용
  python latency_probe_report_v1.py            (오늘)
  python latency_probe_report_v1.py 20260803   (날짜 지정)
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

PROBE_DIR = Path(r"C:\stock_bot") / "data" / "latency_probe"
SNAPSHOT_MAX_AGE_SEC = 4.0   # 전략의 신선도 허용치(S01_SNAPSHOT_MAX_AGE_SEC 기본값)

# 콘솔 기본이 cp949 라 한글 보고가 깨져서 읽을 수가 없다(em dash 는 아예 죽는다).
# 출력만 UTF-8 로 고정한다 — 파일도 파이프도 그대로 읽힌다.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _nums(rows, key) -> list:
    out = []
    for row in rows:
        raw = (row.get(key) or "").strip()
        if not raw:
            continue
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _stat(values: list) -> str:
    if not values:
        return "표본 없음"
    values = sorted(values)
    n = len(values)
    p50 = values[n // 2]
    p90 = values[min(n - 1, int(n * 0.9))]
    return (f"{n}건 · 중앙 {p50:.2f}초 · p90 {p90:.2f}초 · "
            f"최대 {values[-1]:.2f}초 · 평균 {sum(values)/n:.2f}초")


def _hour(row) -> str:
    return (row.get("ts_local") or "")[11:13]


def report_snapshot(day: str) -> None:
    path = PROBE_DIR / f"snapshot_lag_{day}.csv"
    rows = _rows(path)
    print("\n" + "=" * 62)
    print("② 우리 집 안 지연 - 스냅샷에 값이 나타나고 전략이 보기까지")
    print("=" * 62)
    if not rows:
        print(f"  자료 없음: {path}")
        print("  → 태스크 LATENCY_SNAPSHOT_LAG 가 돌았는지, LOG\\sched_LATENCY_SNAPSHOT_LAG.log 확인")
        return

    first, last = rows[0].get("ts_local", ""), rows[-1].get("ts_local", "")
    print(f"  관측 {len(rows)}행 · {first[11:19]} ~ {last[11:19]}")

    live = [r for r in rows if (r.get("upd_n") or "0") not in ("", "0")]
    print(f"  값이 실제로 변한 관측이 있던 행: {len(live)}/{len(rows)}")

    print("\n  [핵심] 값이 변한 종목 기준 지연")
    print("    전체     :", _stat(_nums(live, "upd_p50")))
    print("    p90 계열 :", _stat(_nums(live, "upd_p90")))
    print("    고저폭30 :", _stat(_nums(live, "hr_p50")))

    print("\n  [파일 자체] broker flush 가 1초 주기를 지켰나")
    print("    file_lag :", _stat(_nums(rows, "file_lag_sec")))

    stale4 = _nums(rows, "stale_over4s")
    ncodes = _nums(rows, "n_codes")
    if stale4 and ncodes:
        avg_stale = sum(stale4) / len(stale4)
        avg_codes = sum(ncodes) / len(ncodes)
        share = (avg_stale / avg_codes * 100) if avg_codes else 0
        print(f"\n  [신선도 {SNAPSHOT_MAX_AGE_SEC:.0f}초 초과] 평균 {avg_stale:.0f}종목 "
              f"/ {avg_codes:.0f}종목 ({share:.1f}%)")
        print("    ※ 거래가 뜸한 종목이 섞이므로 이 값만으로 '지연'이라 부르면 안 된다")

    print("\n  [시간대별 중앙 지연(upd_p50)]")
    by_hour = {}
    for row in live:
        raw = (row.get("upd_p50") or "").strip()
        if raw:
            try:
                by_hour.setdefault(_hour(row), []).append(float(raw))
            except ValueError:
                pass
    for hour in sorted(by_hour):
        vals = sorted(by_hour[hour])
        mid = vals[len(vals) // 2]
        worst = vals[-1]
        print(f"    {hour}시  중앙 {mid:5.2f}초   최대 {worst:6.2f}초   ({len(vals)}행)")


def report_real(day: str) -> None:
    path = PROBE_DIR / f"real_latency_{day}.csv"
    rows = _rows(path)
    print("\n" + "=" * 62)
    print("① 키움서버 → 우리 PC 지연 (해상도 1초 - 밀리초는 키움이 안 준다)")
    print("=" * 62)
    if not rows:
        print(f"  자료 없음: {path}")
        print("  → 브로커가 이 코드로 재기동됐는지, REAL_LAT_PROBE=OFF 아닌지 확인")
        return

    print(f"  표본 {len(rows)}건 · {rows[0].get('ts_local','')[11:19]} ~ {rows[-1].get('ts_local','')[11:19]}")

    has20 = sum(1 for r in rows if (r.get("fid20") or "").strip())
    has908 = sum(1 for r in rows if (r.get("fid908") or "").strip())
    print(f"\n  [어느 FID 가 체결시각을 주나]  FID20 {has20}건 · FID908 {has908}건")
    if not has20 and not has908:
        print("    ★둘 다 빈 값 = SetRealReg 등록(MICRO_FIDS)에 없어서 안 오는 것.")
        print("     → MICRO_FIDS 에 20 추가가 필요하다(구독 문자열 변경이라 승인 사항).")
        return

    print("\n  [지연]")
    print("    FID20  :", _stat(_nums(rows, "lag20_sec")))
    print("    FID908 :", _stat(_nums(rows, "lag908_sec")))

    lags = _nums(rows, "lag20_sec") or _nums(rows, "lag908_sec")
    if lags:
        over1 = sum(1 for v in lags if v >= 1.0)
        over2 = sum(1 for v in lags if v >= 2.0)
        print(f"\n  [판정] 1초 이상 밀린 표본 {over1}/{len(lags)} ({over1/len(lags)*100:.1f}%)"
              f" · 2초 이상 {over2} ({over2/len(lags)*100:.1f}%)")
        print("    ※ 체결시각이 초 단위라 ±1초 오차가 깔려 있다. 0~1초는 '밀리지 않음'으로 읽을 것")


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else f"{datetime.now():%Y%m%d}"
    print(f"\n실시간 시세 지연 판독 - {day}")
    report_snapshot(day)
    report_real(day)
    print("\n" + "=" * 62)
    print("이 숫자를 본 뒤에 판단할 것: flush 1000ms→500ms · 신선도 4초→2초")
    print("=" * 62 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
