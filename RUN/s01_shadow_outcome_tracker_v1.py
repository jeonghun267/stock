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
import json
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
# 목표 시각 봉이 결측일 때 허용할 뒤로 오차. 이보다 멀면 그 시점 성과는 빈칸으로 둔다.
HORIZON_TOLERANCE = timedelta(minutes=3)
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


def _scan_1m_file(path, want, series):
    """한 파일에서 필요한 (날짜,종목)만 뽑아 series 에 채운다."""
    tmp = _copy_read(path)
    if not tmp:
        return 0
    hits = 0
    try:
        with open(tmp, encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return 0
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
                        hits += 1
                    except ValueError:
                        pass
    finally:
        os.unlink(tmp)
    return hits


def load_1m_for(codes_by_date):
    """필요한 (날짜, 종목)만 1분봉에서 뽑는다. 반환 {(date, code): [(HHMM, close)]}

    ★[ARCHIVE 2026-08-14 친구님 지시 "고쳐"] 당일 작업파일(prices_1m.csv) 뿐 아니라
      일별 아카이브(prices_1m_clean_YYYYMMDD.csv)도 읽는다.
      왜 — prices_1m.csv 는 날짜가 바뀌면 새로 시작하고 전날치는 clean 파일로 떨어진다.
      작업파일만 보면 과거는 언제나 자료 없음이 되어, 그림자 성과를 종가로만 계산하게 된다
      (8/14 첫 실행에서 8/12·8/13 이 그렇게 종가로 계산됐다).
      ⚠️8/11~8/13 clean 은 인증차단 고장기라 실제로 비어 있다(8/11 은 종목 2개뿐).
        비어 있으면 자연히 eod 종가 경로로 넘어가고 note 에 사유가 남는다.
      되돌리기: s01_shadow_outcome_tracker_v1_20260814_before_archive.py
    """
    want = {(d, c) for d, codes in codes_by_date.items() for c in codes}
    if not want:
        return {}
    series = defaultdict(list)
    # 날짜별 아카이브 먼저 — 필요한 날짜의 파일만 연다
    for d in sorted(codes_by_date):
        arch = os.path.join(BASE, "data", "prices_1m_clean_%s.csv" % d)
        if os.path.exists(arch):
            _scan_1m_file(arch, want, series)
    # 당일 작업파일 (오늘 날짜 신호는 여기에만 있다)
    if os.path.exists(PRICES_1M):
        _scan_1m_file(PRICES_1M, want, series)
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


def _actual_hold_minutes():
    """실제 보유시간(분) 목록을 감사 기록에서 뽑는다.

    ★[GPT 지적 2026-08-14] 요약문에 "9분/23분/48분"을 글로 박아두면 거래가 쌓일수록
      틀린 말이 된다. 매번 감사기록에서 다시 센다. 없으면 문구 자체를 안 쓴다.
    """
    out = []
    root = os.path.join(BASE, "data", "audit", "hold_sell")
    if not os.path.isdir(root):
        return out
    for path in glob.glob(os.path.join(root, "*", "*", "*.jsonl")):
        try:
            first = last = None
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip():
                        first = first or line
                        last = line
            if not (first and last) or first is last:
                continue
            t0 = datetime.fromisoformat(json.loads(first)["captured_at"])
            t1 = datetime.fromisoformat(json.loads(last)["captured_at"])
            mins = (t1 - t0).total_seconds() / 60.0
            if 0 < mins < 400:
                out.append(int(round(mins)))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
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
                # ★[HORIZON-TOL 2026-08-14 GPT 지적 반영] 목표 시각에 도달하지 못한
                #   이전 봉을 그 시점 성과로 쓰면 안 된다.
                #   종전: target 이하 봉 중 마지막을 무조건 채택 → 자료가 09:05 까지밖에
                #   없어도 09:05 봉이 "60분 후 성과"로 기록됐다(8/14 처럼 수집이 늦게
                #   살아난 날 전부 오기록). 이제 허용오차 안에 실제로 도달했을 때만 쓴다.
                for h in HORIZONS:
                    if not t0:
                        continue
                    target = t0.replace(second=0) + timedelta(minutes=h)
                    cand = [(t, c) for t, c in after if t <= target]
                    if cand and (target - cand[-1][0]) <= HORIZON_TOLERANCE:
                        row["ret_%dm" % h] = pct(entry, cand[-1][1])
                row["ret_close"] = pct(entry, after[-1][1])
                highs = [c for _, c in after]
                row["max_gain"] = pct(entry, max(highs))
                row["max_loss"] = pct(entry, min(highs))
                row["source"] = "1m"
                # 관측이 어디까지 있었는지 남긴다 — ret_close·max_* 해석에 필요하다
                row["note"] = "관측 %s~%s" % (
                    after[0][0].strftime("%H:%M"), after[-1][0].strftime("%H:%M"))
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
    lines.append("판단 기준 [2026-08-14 친구님 지적 반영]")
    lines.append("  ★주력은 10분·30분이다. 종가는 참고만 한다.")
    hold = _actual_hold_minutes()
    if hold:
        lines.append("   실전 보유시간(감사기록 %d건 실측): 중앙값 %d분 / 최대 %d분"
                     % (len(hold), sorted(hold)[len(hold) // 2], max(hold)))
    else:
        lines.append("   실전 보유시간: 감사기록 없음 — 종가 기준 판단 금물이라는 원칙만 유지")
    lines.append("   종가(6시간 보유)로 판단하면 실전에 없는 시점을 보는 것이다.")
    lines.append("  · 30분 평균이 뚜렷한 플러스 + 표본 30건 이상 -> 무눌림 차단 완화 검토")
    lines.append("  · 그 전에는 그림자 유지. 표본 부족 상태의 결론은 금물.")
    lines.append("  · 자료원 1m 이 아닌 행(eod/none)은 분 단위 판단에서 제외한다.")
    lines.append("  · 목표 시각 봉이 %d분 넘게 결측이면 그 시점은 빈칸으로 둔다(오기록 방지)."
                 % int(HORIZON_TOLERANCE.total_seconds() // 60))
    text = "\n".join(lines)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print()
    print("저장: %s" % OUT_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
