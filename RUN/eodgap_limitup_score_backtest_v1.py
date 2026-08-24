# -*- coding: utf-8 -*-
"""종가매수 상한가(LOCKED) 점수 문턱 백테 — 2026-08-14 친구님 지시 "백테 돌려".

묻는 것 하나:
    "상한가는 점수와 무관하게 좋은가?"
    = 점수 하위 상한가도 익일 시가매도로 돈이 되는가.
    (되면 LOCKED 전용 문턱을 낮출 근거가 된다. 안 되면 지금 문턱이 옳다.)

배경:
    실전 LOCKED-FIRST 경로는 `_passes_final_score`(MIN_SCORE 70~75)를 공유한다.
    그런데 상한가는 거래가 잠겨 거래대금 점수를 못 받아 최대 28점 근처다
    (8/14 실측: 28.2 / 22.5 / 21.1 / 19.8 / 18.9). 그래서 이 경로는 한 번도
    발동한 적이 없고, 종가매수는 7/28 이후 정상 왕복 0건이다.

이 프로젝트가 실사고로 배운 규칙 — 코드로 강제한다:
  🚨 승자 vs 패자 비교 금지. **진입 시점 전수**만 본다.
     "많이 오른 상한가만 골라 보기"는 결과를 알고 뒤돌아보는 것이다.
  🚨 후보 수가 날마다 다르면 전수 평균이 실전을 대표 못 한다.
     → 실전 제약(하루 MAX_POS 개, 점수 상위부터)을 넣은 **슬롯 시뮬**을 함께 낸다.
  🚨 왕복비용을 반드시 뺀다(0.38%p). 안 빼면 엣지의 70%가 착시다.

매매 가정 (실전과 동일 프레임):
    D일 종가에 매수 → D+1 시가에 매도. 비용 0.38%p 차감.
    상한가 판정: daily_return >= LIMITUP_MIN (기본 0.28 = +28%).
    점수: 실전 점수식을 그대로 못 쓰므로 **대용 점수**를 쓴다 —
          실전에서 상한가 점수를 좌우하는 것은 거래대금이므로 거래대금(억)으로
          분위를 나눈다. 즉 "거래대금이 적어 점수가 낮은 상한가"가 나쁜지 본다.

사용:
    C:\python310\python.exe -X utf8 RUN\eodgap_limitup_score_backtest_v1.py
    ... --months 12 --maxpos 1
"""
import argparse
import csv
import os
import shutil
import statistics
import sys
import tempfile
from collections import defaultdict

BASE = r"C:\stock_bot"
EOD = os.path.join(BASE, "data", "eod_daily_bars.csv")
COST_PCT = 0.38          # 왕복비용 %p
LIMITUP_MIN = 0.28       # 상한가 판정 (일일수익률)


def load_rows(months):
    """복사본으로 읽는다(원본을 붙잡으면 엔진 저장이 죽는다 — 8/10 사고)."""
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    shutil.copy2(EOD, tmp)
    by_code = defaultdict(dict)     # code -> {date: row}
    dates = set()
    try:
        with open(tmp, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                d = (r.get("date") or "").strip()
                c = (r.get("code") or "").strip()
                if not (d.isdigit() and len(d) == 8 and c):
                    continue
                try:
                    row = {
                        "open": float(r.get("open") or 0),
                        "close": float(r.get("close") or 0),
                        "volume": float(r.get("volume") or 0),
                        "value": float(r.get("value") or 0),
                        "ret": float(r.get("daily_return") or 0),
                        "name": (r.get("name") or "").strip(),
                    }
                except ValueError:
                    continue
                # 빈 껍데기 행 차단 (장 전 수집분: 거래량 0)
                if row["volume"] <= 0 or row["close"] <= 0:
                    continue
                by_code[c][d] = row
                dates.add(d)
    finally:
        os.unlink(tmp)
    ds = sorted(dates)
    if months:
        keep = ds[-(months * 21):] if len(ds) > months * 21 else ds
        ds = keep
    return by_code, ds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--maxpos", type=int, default=1)
    args = ap.parse_args()

    by_code, dates = load_rows(args.months)
    if len(dates) < 2:
        print("자료 부족"); return 1
    dset = set(dates)
    nxt = {d: dates[i + 1] for i, d in enumerate(dates[:-1])}

    # ── 진입 시점 전수 수집 (승자편향 방지: 결과를 보고 고르지 않는다) ──
    trades = []          # (date, code, name, value_eok, ret_pct)
    for code, series in by_code.items():
        for d, row in series.items():
            if d not in dset or d not in nxt:
                continue
            if row["ret"] < LIMITUP_MIN:
                continue
            nd = nxt[d]
            nrow = series.get(nd)
            if not nrow or nrow["open"] <= 0 or row["close"] <= 0:
                continue
            gross = (nrow["open"] / row["close"] - 1) * 100
            trades.append((d, code, row["name"], row["value"], gross - COST_PCT))

    if not trades:
        print("상한가 표본 0건"); return 1

    print("=" * 70)
    print("종가매수 상한가 백테 — D일 종가 매수 → D+1 시가 매도 (비용 %.2f%%p 차감)"
          % COST_PCT)
    print("기간 %s ~ %s  (%d 거래일)  |  상한가 진입 전수 %d건"
          % (dates[0], dates[-1], len(dates), len(trades)))
    print("=" * 70)

    rets = [t[4] for t in trades]
    win = sum(1 for v in rets if v > 0)
    print("\n[전수] 평균 %+.3f%%  중앙값 %+.3f%%  승률 %.1f%% (%d/%d)"
          % (sum(rets) / len(rets), statistics.median(rets),
             win * 100.0 / len(rets), win, len(rets)))

    # ── 핵심 질문: 거래대금(=실전 점수의 주된 재료) 분위별 성과 ──
    print("\n[거래대금 5분위]  ※실전에서 상한가 점수를 좌우하는 것이 거래대금이다")
    print("   낮은 분위 = 실전 점수가 낮아 지금 문턱에 걸리는 쪽")
    vals = sorted(t[3] for t in trades)
    cuts = [vals[int(len(vals) * q / 5)] for q in range(1, 5)]

    def qidx(v):
        for i, c in enumerate(cuts):
            if v < c:
                return i
        return 4

    buckets = defaultdict(list)
    for t in trades:
        buckets[qidx(t[3])].append(t[4])
    labels = ["Q1(최저)", "Q2", "Q3", "Q4", "Q5(최고)"]
    for i in range(5):
        b = buckets.get(i) or []
        if not b:
            continue
        w = sum(1 for v in b if v > 0)
        rng = ("~%.0f억" % cuts[0]) if i == 0 else (
            "%.0f억~" % cuts[3] if i == 4 else "%.0f~%.0f억" % (cuts[i - 1], cuts[i]))
        print("   %-9s %-12s n=%-4d 평균 %+.3f%%  중앙값 %+.3f%%  승률 %.1f%%"
              % (labels[i], rng, len(b), sum(b) / len(b),
                 statistics.median(b), w * 100.0 / len(b)))

    # ── 실전 제약 슬롯 시뮬: 하루 maxpos 개, 거래대금 큰 순 ──
    print("\n[슬롯 시뮬] 하루 최대 %d종목, 거래대금 큰 순으로 매수 (실전 제약 반영)"
          % args.maxpos)
    per_day = defaultdict(list)
    for t in trades:
        per_day[t[0]].append(t)
    picked = []
    for d, lst in per_day.items():
        lst.sort(key=lambda x: -x[3])
        picked += [x[4] for x in lst[:args.maxpos]]
    if picked:
        w = sum(1 for v in picked if v > 0)
        print("   매수일 %d일  체결 %d건  평균 %+.3f%%  중앙값 %+.3f%%  승률 %.1f%%"
              % (len(per_day), len(picked), sum(picked) / len(picked),
                 statistics.median(picked), w * 100.0 / len(picked)))
        print("   누적(1주 기준 단순합) %+.2f%%p" % sum(picked))

    # ── 월별 분해 (특정 시기 몰림 확인) ──
    print("\n[월별]  ※한 달에 몰려 있으면 전체 평균은 신기루다")
    by_month = defaultdict(list)
    for t in trades:
        by_month[t[0][:6]].append(t[4])
    for m in sorted(by_month):
        b = by_month[m]
        w = sum(1 for v in b if v > 0)
        print("   %s  n=%-4d 평균 %+.3f%%  승률 %.1f%%"
              % (m, len(b), sum(b) / len(b), w * 100.0 / len(b)))

    print("\n" + "=" * 70)
    print("판단 요령: Q1(거래대금 최저 = 실전 점수 최저)이 플러스면")
    print("           '점수로 상한가를 거를 이유가 없다'는 코드 주석이 옳다.")
    print("           Q1 만 마이너스면 지금 문턱이 옳고, 낮추면 안 된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
