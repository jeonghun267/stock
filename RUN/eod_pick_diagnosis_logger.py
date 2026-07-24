# -*- coding: utf-8 -*-
# 종가매수(EOD_PICK) 진단 로거 [2026-06-09 신규, 진단 전용 / READ-ONLY].
#   목적: 1종목 몰빵에 맞는 "거래대금 충분 + 막판 거래대금 살아있는" 종목이 선별되는지 검증.
#         (오늘 1-8등 중 6개가 <50억 소액 = 몰빵 부적합 문제 발견 → 데이터로 추적)
#   ★매매/주문/queue 무연결. score_eod·eod_daily_bars 읽기만. 조건/score 무수정.
#   입력: score_eod.csv (막판지표 보유) + eod_daily_bars.csv (거래대금=close*volume, 익일수익)
#   출력: DATA\eod_pick_diagnosis_log.csv
#   모드: (기본)capture = 그날 종가매수 후보 기록 / --backfill = 익일수익 채움
import csv, os, sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

BASE = Path(r"C:\stock_bot")
SCORE = BASE / "data" / "scoreboard" / "score_eod.csv"
EOD   = BASE / "DATA" / "eod_daily_bars.csv"
LOG   = BASE / "DATA" / "eod_pick_diagnosis_log.csv"
TOP_N = 15   # 상위 15등까지 기록 (밀려난 것도 보려고)

COLS = ["board_date","code","name","score","rank","eod_pick_flag",
        "value_krw_억","value_floor_100",
        "close_value_ratio","last5_value_accel","last15_value_ratio","close_position","vwap_ratio",
        "next_gap_pct","next_ret_pct","logged_at"]


def _f(v, d=0.0):
    try: return float(str(v).strip().lstrip("+"))
    except Exception: return d


def _load_eod():
    eod = defaultdict(dict)
    with EOD.open(encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            c = str(r.get("code","")).zfill(6); d = (r.get("date","") or "").replace("-","")
            try:
                cl = float(r["close"]); vol = float(r.get("volume",0) or 0)
                eod[c][d] = (cl, cl*vol)  # 거래대금 = 종가×거래량
            except Exception: pass
    return eod


def capture():
    if not SCORE.exists():
        print("[EODDIAG] score_eod 없음 — skip"); return
    rows = list(csv.DictReader(open(SCORE, encoding="utf-8-sig", errors="replace")))
    if not rows:
        print("[EODDIAG] score_eod 비어있음 — skip"); return
    bdate = (rows[0].get("date","") or "").replace("-","")
    eod = _load_eod()
    # 점수순 top N
    ranked = sorted(rows, key=lambda r: -_f(r.get("score_final")))[:TOP_N]
    # 이미 기록된 (board_date,code)
    logged = set()
    if LOG.exists():
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig", errors="replace")):
            logged.add((r.get("board_date"), r.get("code")))
    new = []
    for i, r in enumerate(ranked, 1):
        code = str(r.get("code","")).zfill(6)
        if (bdate, code) in logged: continue
        v = eod.get(code, {}).get(bdate, (0,0))[1] / 1e8  # 억
        new.append({
            "board_date": bdate, "code": code, "name": r.get("name",""),
            "score": _f(r.get("score_final")), "rank": i,
            "eod_pick_flag": r.get("eod_pick_flag",""),
            "value_krw_억": round(v,0), "value_floor_100": "PASS" if v>=100 else "FAIL",
            "close_value_ratio": _f(r.get("close_value_ratio")),
            "last5_value_accel": _f(r.get("last5_value_accel")),
            "last15_value_ratio": _f(r.get("last15_value_ratio")),
            "close_position": _f(r.get("close_position")),
            "vwap_ratio": _f(r.get("vwap_ratio")),
            "next_gap_pct": "", "next_ret_pct": "",
            "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    if not new:
        print("[EODDIAG] 신규 없음(이미 기록)"); return
    wh = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if wh: w.writeheader()
        for n in new: w.writerow(n)
    floorfail = sum(1 for n in new if n["value_floor_100"]=="FAIL")
    print(f"[EODDIAG] capture: {len(new)}건 기록 (거래대금<100억 미달 {floorfail}건)")


def backfill():
    if not LOG.exists():
        print("[EODDIAG] 로그 없음"); return
    eod = _load_eod()
    def nd(c,d):
        x = sorted(k for k in eod[c] if k>d); return x[0] if x else None
    rows = list(csv.DictReader(open(LOG, encoding="utf-8-sig", errors="replace")))
    filled = 0
    for r in rows:
        if r.get("next_ret_pct"): continue
        c = str(r.get("code","")).zfill(6); d = r.get("board_date","")
        if c not in eod or d not in eod[c]: continue
        n = nd(c,d)
        if not n: continue
        cl = eod[c][d][0]; o2_unknown = None
        # eod엔 open 없으니(close*vol만 로드) 익일 종가수익만; gap은 익일 시가 필요→재로드
        # 간단화: 익일 종가수익만 채움
        c2 = eod[c][n][0]
        if cl>0:
            r["next_ret_pct"] = round((c2/cl-1)*100, 2); filled += 1
    with open(LOG, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
        for r in rows: w.writerow({k: r.get(k,"") for k in COLS})
    print(f"[EODDIAG] backfill: {filled}건 익일수익 채움")


if __name__ == "__main__":
    if "--backfill" in sys.argv: backfill()
    else: capture()
