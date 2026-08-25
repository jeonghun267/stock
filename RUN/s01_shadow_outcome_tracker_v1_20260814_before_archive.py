# -*- coding: utf-8 -*-
"""S01 무눌림 그림자(ABOVE_OPEN_REBREAK)의 사후 성과 추적기.

배경 (2026-08-14 친구님 지시):
  S01 은 2026-08-10 부터 '시가 아래로 눌린 적 없는 종목'을 매수에서 제외한다
  (PULLBACK_BELOW_OPEN_NOT_SEEN). 제외된 종목은 그림자 CSV 에 기록돼 왔지만
  **진입 지표만 있고 그 뒤 성과가 없어** "이 조건을 풀어야 하나"를 판단할 수 없었다.
  이 도구가 그 빈칸을 채운다.

원칙:
  - 읽기 전용. 브로커 IPC 호출 0 (2026-08-13 그림자가 브로커를 독점해 일봉/종가매수를
    마비시킨 사고 재발 방지). 파일만 읽는다.
  - 큰 CSV 는 복사본으로 읽는다 (2026-08-10 저장잠금 사고: 원본을 열고만 있어도
    엔진의 os.replace 가 거부된다).
  - 자료가 없으면 추정하지 않고 빈칸으로 두고 이유를 남긴다 (fail-closed).

자료원 우선순위:
  1) data\prices_1m.csv  — 있으면 +10/+30/+60분·종가 전부 계산 (정밀)
  2) data\eod_daily_bars.csv — 1분봉이 없는 날은 종가 수익률만 (근사)

사용:
  C:\python310\python.exe -X utf8 C:\stock_bot\RUN\s01_shadow_outcome_tracker_v1.py
  C:\python310\python.exe -X utf8 ... --date 20260811      (특정일만)
출력:
  보고서\S01그림자_성과.csv          (누적, 신호 1건 = 1행)
  보고서\S01그림자_성과_요약.txt     (한국어 요약)
"""
import argparse
import csv
import glob
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta

BASE = r"C:\stock_bot"
SHADOW_DIR = os.path.join(BASE, "data", "shadow")
PRICES_1M = os.path.join(BASE, "data", "prices_1m.csv")
EOD = os.path.join(BASE, "data", "eod_daily_bars.csv")
OUT_DIR = os.path.join(BASE, "보고서")
OUT_CSV = os.path.join(OUT_DIR, "S01그림자_성과.csv")
OUT_TXT = os.path.join(OUT_DIR, "S01그림자_성과_요약.txt")

HORIZONS = (10, 30, 60)          # 분
FIELDS = ["date", "ts", "code", "name", "entry_price", "dip_pct", "rebound_pct",
          "gap_pct", "listed_turnover_pct", "ret_10m", "ret_30m", "ret_60m",
          "ret_close", "max_gain", "max_loss", "source", "note"]


def _copy_read(path):
    """복사본 경로를 돌려준다(원본을 붙잡지 않기 위해). 실패 시 None."""
    try:
        fd, tmp = tempfile.mkstemp(suffix=os.path.basename(path))
        os.close(fd)
        shutil.copy2(path, tmp)
        return tmp
    except Exception:
        return None


def load_shadow_signals(only_date=None):
    """그림자 CSV 들에서 신호 행을 뽑는다."""
    rows = []
    for path in sorted(glob.glob(os.path.join(
            SHADOW_DIR, "strategy_01_above_open_rebreak_shadow_*.csv"))):
        d = os.path.basename(path).split("_")[-1].split(".")[0]
        if only_date and d != only_date:
            continue
        tmp = _copy_read(path)
        if not tmp:
            continue
        try:
            with open(tmp, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if not (r.get("code") or "").strip():
                        continue
                    rows.append({
                        "date": d,
                        "ts": r.get("ts", ""),
                        "code": r["code"].strip(),
                        "name": (r.get("name") or "").strip(),
                        "entry_price": r.get("price") or "",
                        "dip_pct": r.get("dip_pct") or "",
                        "rebound_pct": r.get("rebound_pct") or "",
                        "gap_pct": r.get("gap_pct") or "",
                        "listed_turnover_pct": r.get("listed_turnover_pct") or "",
                    })
        finally:
            os.unlink(tmp)
    return rows


def load_1m_for(codes_by_date):
    """필요한 (날짜, 종목)만 1분봉에서 뽑는다. 반환 {(date, code): [(HHMM, close)]}"""
    if not os.path.exists(PRICES_1M):
        return {}
    want = {(d, c) for d, codes in codes_by_date.items() for c in codes}
    if not want:
        return {}
    tmp = _copy_read(PRICES_1M)
    if not tmp:
        return {}
    series = defaultdict(list)
    try:
        with open(tmp, encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return {}
            idx_code, idx_ts = 0, 1
            try:
                idx_close = header.index("close")
            except ValueError:
                idx_close = 5
            for row in reader:
                if len(row) <= idx_close:
                    continue
                code, ts = row[idx_code], row[idx_ts]
                if len(ts) < 12:
                    continue
                key = (ts[:8], code)
                if key in want:
                    try:
                        series[key].append((ts[8:12], float(row[idx_close])))
                    except ValueError:
                        pass
    finally:
        os.unlink(tmp)
    for k in series:
        series[k].sort()
    return series


def load_eod_close(codes_by_date):
    """일봉에서 (날짜, 종목) 종가. 큰 파일이라 한 번만 스캔."""
    if not os.path.exists(EOD):
        return {}
    want = {(d, c) for d, codes in codes_by_date.items() for c in codes}
    if not want:
        return {}
    tmp = _copy_read(EOD)
    if not tmp:
        return {}
    out = {}
    try:
        with open(tmp, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                key = ((r.get("date") or "").strip(), (r.get("code") or "").strip())
                if key not in want:
                    continue
                try:
                    o = float(r.get("open") or 0)
                    h = float(r.get("high") or 0)
                    lo = float(r.get("low") or 0)
                    c = float(r.get("close") or 0)
                    v = float(r.get("volume") or 0)
                except ValueError:
                    continue
                # ★[2026-08-14] 빈 껍데기 행 차단.
                #   장 시작 전에 수집이 끝나면 당일 행이 OHLC 전부 전일종가 + 거래량 0
                #   으로 들어온다. 이걸 종가로 쓰면 전 종목이 가짜 마이너스가 된다.
                #   (실제로 이 도구 첫 실행에서 8/14 34건이 전부 마이너스로 나왔다.)
                if v <= 0 or (o == h == lo == c):
                    continue
                out[key] = c
    finally:
        os.unlink(tmp)
    return out


def pct(a, b):
    try:
        if not a or not b:
            return ""
        return round((float(b) / float(a) - 1) * 100, 3)
    except (ValueError, ZeroDivisionError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYYMMDD 하루만")
    args = ap.parse_args()

    signals = load_shadow_signals(args.date)
    if not signals:
        print("[S01-SHADOW] 대상 신호 없음")
        return 0

    codes_by_date = defaultdict(set)
    for s in signals:
        codes_by_date[s["date"]].add(s["code"])

    m1 = load_1m_for(codes_by_date)
    eod = load_eod_close(codes_by_date)

    results = []
    for s in signals:
        key = (s["date"], s["code"])
        row = dict(s)
        row.update({k: "" for k in
                    ("ret_10m", "ret_30m", "ret_60m", "ret_close",
                     "max_gain", "max_loss")})
        entry = s["entry_price"]
        bars = m1.get(key) or []
        if bars and entry:
            # 진입 시각 이후 봉만
            try:
                t0 = datetime.strptime(s["ts"][11:19], "%H:%M:%S")
            except ValueError:
                t0 = None
            after = []
            for hhmm, close in bars:
                try:
                    t = datetime.strptime(hhmm, "%H%M")
                except ValueError:
                    continue
                if t0 is None or t >= t0.replace(second=0):
                    after.append((t, close))
            if after:
                for h in HORIZONS:
                    if t0:
                        target = t0.replace(second=0) + timedelta(minutes=h)
                        cand = [c for t, c in after if t <= target]
                        if cand:
                            row["ret_%dm" % h] = pct(entry, cand[-1])
                row["ret_close"] = pct(entry, after[-1][1])
                highs = [c for _, c in after]
                row["max_gain"] = pct(entry, max(highs))
                row["max_loss"] = pct(entry, min(highs))
                row["source"] = "1m"
                row["note"] = ""
        if not row.get("source"):
            close = eod.get(key)
            if close and entry:
                row["ret_close"] = pct(entry, close)
                row["source"] = "eod"
                row["note"] = "1분봉 없음 - 종가만"
            else:
                row["source"] = "none"
                row["note"] = "가격자료 없음"
        results.append(row)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in FIELDS})

    # 요약
    lines = []
    lines.append("S01 무눌림 그림자 성과 요약  (생성 %s)"
                 % datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("=" * 52)
    lines.append("대상: 시가 아래로 눌리지 않아 S01 이 매수하지 않은 신호")
    lines.append("")
    by_date = defaultdict(list)
    for r in results:
        by_date[r["date"]].append(r)
    for d in sorted(by_date):
        rows = by_date[d]
        lines.append("[%s] 신호 %d건" % (d, len(rows)))
        for field, label in (("ret_10m", "10분"), ("ret_30m", "30분"),
                             ("ret_60m", "60분"), ("ret_close", "종가")):
            vals = [float(r[field]) for r in rows
                    if r.get(field) not in ("", None)]
            if vals:
                win = sum(1 for v in vals if v > 0)
                lines.append("   %s : 평균 %+.2f%%  승률 %.0f%% (%d/%d)"
                             % (label, sum(vals) / len(vals),
                                win * 100.0 / len(vals), win, len(vals)))
            else:
                lines.append("   %s : 자료 없음" % label)
        srcs = defaultdict(int)
        for r in rows:
            srcs[r.get("source") or "?"] += 1
        lines.append("   자료원: " + ", ".join("%s=%d" % kv for kv in srcs.items()))
        lines.append("")
    lines.append("판단 기준: 종가 평균이 뚜렷한 플러스이고 표본이 30건 이상이면")
    lines.append("           무눌림 차단(2026-08-10 배선) 완화를 검토할 수 있다.")
    lines.append("           그 전에는 그림자 유지. 표본 부족 상태의 결론은 금물.")
    text = "\n".join(lines)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print()
    print("저장: %s" % OUT_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
