# -*- coding: utf-8 -*-
# 추세 진입 진단 로거 [2026-06-09 신규, 진단 전용 / READ-ONLY].
#   목적: "왜 못 샀나 + 못 산 종목이 이후 올랐나"를 기록해, VWAP/거래량/기관필터/dead-zone을
#         감이 아니라 데이터로 판단하기 위함.
#   ★매매/주문/queue/bridge/매도 절대 무연결. 조건/score 무수정. 기록만.
#   입력: DATA\trend_diag_snapshot.csv (엔진이 _signals 끝에서 덤프한 feature 스냅샷)
#   출력: DATA\trend_entry_diagnosis_log.csv
#   모드: (기본)capture = 스냅샷 읽어 코드별 1회/일 기록 / --backfill = 이후수익 채움
import csv, os, sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
SNAP = BASE / "DATA" / "trend_diag_snapshot.csv"
LOG  = BASE / "DATA" / "trend_entry_diagnosis_log.csv"
PRICES = BASE / "DATA" / "prices_1m.csv"

# 엔진 추세조건 임계 (재평가용 — 엔진 CFG와 동일값, 수정 아님 복제)
TREND_VWAP_MIN = 0.98
TREND_SLOPE_MID_MIN = 0.0002
TREND_VAL_RATIO = 0.70
INST_TREND_MIN = 2

COLS = ["date","snap_ts","code","name","entry_trend","entry_pullback","dead_zone",
        "close","vwap","close_vs_vwap_pct","value_ratio_5m","slope_short","slope_mid",
        "ret_from_prev_close","above_ma5","rsi14","pullback_pct","prev_high_break",
        "gap_grade","inst_consec","market_regime","time_regime",
        "trendA_current","trendB_vwap100","trendC_val100","trendD_instsoft","trendE_all",
        "trend_fail_reason",
        "next_5m_return","next_10m_return","next_30m_return","eod_return"]


def _f(v, d=0.0):
    try: return float(str(v).strip().lstrip("+"))
    except Exception: return d


def _b(v):
    return str(v).strip().lower() in ("true","1","yes","y")


def capture():
    if not SNAP.exists():
        print("[DIAG] 스냅샷 없음 (엔진 재시작 후 생성됨) — skip"); return
    rows = list(csv.DictReader(open(SNAP, encoding="utf-8-sig", errors="replace")))
    if not rows:
        print("[DIAG] 스냅샷 비어있음 — skip"); return
    today = datetime.now().strftime("%Y-%m-%d")
    # 이미 오늘 기록된 코드 (dedup)
    logged = set()
    if LOG.exists():
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig", errors="replace")):
            if r.get("date") == today:
                logged.add(r.get("code"))
    new = []
    for r in rows:
        code = str(r.get("code","")).strip()
        if not code or code in logged:
            continue
        et = _b(r.get("entry_trend")); ep = _b(r.get("entry_pullback"))
        close = _f(r.get("close")); vwap = _f(r.get("anchored_vwap") or r.get("vwap"))
        cvw = (close/vwap - 1)*100 if vwap > 0 else 0.0
        vr = _f(r.get("value_ratio_5m")); ss = _f(r.get("trend_slope_short"), -1)
        sm = _f(r.get("trend_slope_mid"), -1); ret = _f(r.get("ret_from_prev_close"), -1)
        ma5 = _b(r.get("price_above_ma5")); inst = _f(r.get("inst_consec"))
        phb = _b(r.get("prev_high_break"))
        # dead-zone 후보 (내 판단): 둘다 미진입인데 추세후보성 (돌파 or VWAP위 or 거래량강)
        dz = (not et) and (not ep) and (phb or cvw >= 0 or vr >= 1.0)
        # 추세조건 변형 재평가 (feature에서 직접 — regime 오염 배제)
        base_cond = (ss > 0) and (sm >= TREND_SLOPE_MID_MIN) and (ret > 0) and ma5
        instok = inst >= INST_TREND_MIN
        tA = (close >= vwap*TREND_VWAP_MIN) and (vr >= TREND_VAL_RATIO) and base_cond and instok
        tB = (close >= vwap*1.000)          and (vr >= TREND_VAL_RATIO) and base_cond and instok
        tC = (close >= vwap*TREND_VWAP_MIN) and (vr >= 1.0)             and base_cond and instok
        tD = (close >= vwap*TREND_VWAP_MIN) and (vr >= TREND_VAL_RATIO) and base_cond  # inst soft
        tE = (close >= vwap*1.000)          and (vr >= 1.0)             and base_cond  # B+C+D
        # 추세 탈락사유
        fr = []
        if close < vwap*TREND_VWAP_MIN: fr.append("vwap")
        if ss <= 0: fr.append("slope_short")
        if sm < TREND_SLOPE_MID_MIN: fr.append("slope_mid")
        if vr < TREND_VAL_RATIO: fr.append("value")
        if ret <= 0: fr.append("ret_prev")
        if not ma5: fr.append("ma5")
        if not instok: fr.append("inst")
        if not (et or ep or dz):
            continue  # 진입도 dead-zone도 아니면 기록 안 함(노이즈 컷)
        new.append({
            "date": today, "snap_ts": r.get("snap_ts",""), "code": code,
            "name": r.get("name",""), "entry_trend": et, "entry_pullback": ep, "dead_zone": dz,
            "close": close, "vwap": round(vwap,2), "close_vs_vwap_pct": round(cvw,2),
            "value_ratio_5m": round(vr,3), "slope_short": ss, "slope_mid": sm,
            "ret_from_prev_close": ret, "above_ma5": ma5, "rsi14": _f(r.get("rsi14")),
            "pullback_pct": _f(r.get("intraday_pullback_pct")), "prev_high_break": phb,
            "gap_grade": r.get("gap_grade",""), "inst_consec": inst,
            "market_regime": r.get("market_regime",""), "time_regime": r.get("time_regime",""),
            "trendA_current": tA, "trendB_vwap100": tB, "trendC_val100": tC,
            "trendD_instsoft": tD, "trendE_all": tE, "trend_fail_reason": "|".join(fr),
            "next_5m_return": "", "next_10m_return": "", "next_30m_return": "", "eod_return": "",
        })
        logged.add(code)
    if not new:
        print("[DIAG] 신규 기록 없음 (이미 기록됨 or 후보 0)"); return
    write_header = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if write_header: w.writeheader()
        for n in new: w.writerow(n)
    print(f"[DIAG] capture: {len(new)}건 기록 (entry/dead-zone)")


def backfill():
    # 이후수익(5/10/30분·eod) 채움 — prices_1m에서. 오늘 날짜만.
    if not LOG.exists():
        print("[DIAG] 로그 없음 — backfill skip"); return
    today = datetime.now().strftime("%Y%m%d")
    # prices_1m 오늘 봉 로드 (code별 hhmm→close)
    px = {}
    with open(PRICES, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            ts = r.get("ts",""); c = r.get("code","").strip()
            if c.startswith("U") or not ts.startswith(today): continue
            try: px.setdefault(c, {})[int(ts[8:12])] = float(r["close"])
            except Exception: pass
    rows = list(csv.DictReader(open(LOG, encoding="utf-8-sig", errors="replace")))
    filled = 0
    for r in rows:
        if r.get("date") != datetime.now().strftime("%Y-%m-%d"): continue
        if r.get("eod_return"): continue  # 이미 채움
        c = r.get("code"); st = r.get("snap_ts","")
        if c not in px or len(st) < 16: continue
        try: hm = int(st[11:13])*100 + int(st[14:16])
        except Exception: continue
        bars = px[c]
        def at(target):
            cands = [m for m in bars if m >= target]
            return bars[min(cands)] if cands else None
        p0 = at(hm)
        if not p0 or p0 <= 0: continue
        for col, mn in [("next_5m_return",5),("next_10m_return",10),("next_30m_return",30)]:
            p = at(hm+mn)
            if p: r[col] = round((p/p0-1)*100, 2)
        pe = bars[max(bars)] if bars else None  # eod = 마지막봉
        if pe: r["eod_return"] = round((pe/p0-1)*100, 2)
        filled += 1
    with open(LOG, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows: w.writerow({k: r.get(k,"") for k in COLS})
    print(f"[DIAG] backfill: {filled}건 이후수익 채움")


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        backfill()
    else:
        capture()
