# -*- coding: utf-8 -*-
"""
[REGIME-STD 그림자 v1 2026-06-13 주말설계 — 시장판정 단일표준의 실측 수집기]
배경: 4눈(rt_risk/exec/sender/눌림엔진)은 REGIME-TODAY로 당일 U201 ±1.5% 통일済.
  남은 빈칸 = 회색지대(±1.5% 이내)에서 각 눈이 제각각 옛 로직(D-1 기반)으로 갈라짐.
  백테 검증(BACKTEST/regime_gray_breadth_v1.py): 전체에선 breadth<0.40 열위(승24% vs 32%)
  확인되나 회색지대 한정은 표본 5일+방향역전=노이즈 → 백테로 규칙 채택 불가(친구님 지침).
역할: 5분마다 [당일 U201 + 당일 breadth(수집풀, 전일종가 위 비율) + 표준판정]을 기록만.
  매매 0연결. 10거래일+ 쌓이면 회색지대 lean(0.60/0.40 문턱, 사전문서화)과 그날
  실성적·4눈 판정 불일치를 실측 비교 → 회색지대 규칙 장착 여부 결정.
판정라인(사전문서화): GRAY에서 LEAN별 그날 눌림성적 차이 ≥0.5%p & 10거래일+ 이면 장착검토.
출력: DATA/market_regime_std.json (최신) + data/BACKTEST/regime_std_shadow.csv (누적)
"""
import csv, io, json, os, sys
from datetime import datetime
from pathlib import Path

IDX = Path(r"C:\stock_bot\DATA\kosdaq_index.json")
PREV = Path(r"C:\stock_bot\DATA\prev_day_summary.csv")
P1M = Path(r"C:\stock_bot\DATA\prices_1m.csv")
OUT_JSON = Path(r"C:\stock_bot\DATA\market_regime_std.json")
OUT_CSV = Path(r"C:\stock_bot\data\BACKTEST\regime_std_shadow.csv")
US_FILE = Path(r"C:\stock_bot\DATA\us_overnight.json")   # [REGIME-US 2026-06-14] 미국 나스닥 반영용
US_BEAR_PCT = float(os.environ.get("REGIME_US_BEAR_PCT", "-2.0"))   # 회색지대서 나스닥 이하 → 약세보조
US_BULL_PCT = float(os.environ.get("REGIME_US_BULL_PCT", "1.0"))    # 회색지대서 나스닥 이상 → 강세보조

BAND_PCT = float(os.environ.get("REGIME_STD_BAND_PCT", "1.5"))
LEAN_HI = float(os.environ.get("REGIME_STD_LEAN_HI", "0.60"))
LEAN_LO = float(os.environ.get("REGIME_STD_LEAN_LO", "0.40"))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

def main():
    now = datetime.now()
    if now.weekday() >= 5 or not ("0900" <= now.strftime("%H%M") <= "1531"):
        print(f"[{now:%H:%M}] 장외 — skip"); return
    today = now.strftime("%Y%m%d")

    # ① 당일 U201 (kosdaq_index.json, 신선도 600s)
    u201_chg, idx_fresh = None, False
    try:
        idx = json.loads(IDX.read_text(encoding="utf-8-sig"))
        its = str(idx.get("ts", ""))
        age = (now - datetime.strptime(its, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if its[:10] == now.strftime("%Y-%m-%d") and age <= 600:
            u201_chg, idx_fresh = float(idx.get("chg")), True
    except Exception as e:
        print(f"[WARN] 지수 읽기 실패: {e}")

    # ② 전일종가 (prev_day_summary)
    pc = {}
    try:
        with io.open(PREV, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    v = float(r.get("prev_close") or 0)
                    if v > 0: pc[r["code"]] = v
                except (TypeError, ValueError):
                    continue
    except Exception as e:
        print(f"[WARN] prev_day_summary 실패: {e}")

    # ③ 당일 breadth — 수집풀 마지막 체결가 vs 전일종가
    last_cl = {}
    try:
        with io.open(P1M, encoding="utf-8-sig", errors="replace") as f:
            rd = csv.reader(f); next(rd)
            for c in rd:
                if not c[1].startswith(today) or c[0] in ("U001", "U201"): continue
                cur = last_cl.get(c[0])
                if cur is None or c[1] > cur[0]:
                    try: last_cl[c[0]] = (c[1], float(c[5]))
                    except (ValueError, IndexError): pass
    except Exception as e:
        print(f"[WARN] prices_1m 실패: {e}")
    up = n = 0
    for code, (_, cl) in last_cl.items():
        p = pc.get(code)
        if not p: continue
        n += 1
        if cl > p: up += 1
    breadth = round(up / n, 4) if n >= 50 else None

    # ④ 표준판정 — 확실구간은 현행 REGIME-TODAY와 동일, 회색지대는 lean 기록만
    if not idx_fresh:
        band = "NO_INDEX"
    elif u201_chg >= BAND_PCT:
        band = "BULL"
    elif u201_chg <= -BAND_PCT:
        band = "BEAR"
    else:
        band = "GRAY"
    if band == "GRAY" and breadth is not None:
        lean = "LEAN_BULL" if breadth >= LEAN_HI else ("LEAN_BEAR" if breadth <= LEAN_LO else "FLAT")
    else:
        lean = ""

    # ⑤ [REGIME-US 2026-06-14 ★친구님] 미국 나스닥 반영 새 판정(그림자 기록만, 매매·보드 무연결).
    #   백테: 미국 나스닥이 그날 코스닥 방향 강하게 예측(강세 하락46% → -2%↓ 하락82%). VIX는 무력→제외.
    #   규칙: U201 명확(±BAND밖)=U201 그대로 / 회색지대=미국 보조(-2↓ 약세·+1↑ 강세)·없으면 breadth lean.
    nasdaq = None
    try:
        ud = json.loads(US_FILE.read_text(encoding="utf-8-sig"))
        if str(ud.get("ts", ""))[:10] == now.strftime("%Y-%m-%d"):   # 당일 신선 데이터만
            nasdaq = ud.get("data", {}).get("nasdaq", {}).get("chg")
            nasdaq = float(nasdaq) if nasdaq is not None else None
    except Exception:
        nasdaq = None
    if band in ("BULL", "BEAR"):
        band_us = band                                  # U201 명확 → 그대로(당일 실제가 제일 정확)
    elif band == "GRAY" and nasdaq is not None and nasdaq <= US_BEAR_PCT:
        band_us = "LEAN_BEAR_US"                         # 회색지대 + 미국 약세
    elif band == "GRAY" and nasdaq is not None and nasdaq >= US_BULL_PCT:
        band_us = "LEAN_BULL_US"                         # 회색지대 + 미국 강세
    elif band == "GRAY":
        band_us = lean if lean else "FLAT"               # 미국 없음 → breadth lean
    else:
        band_us = band                                  # NO_INDEX

    rec = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "u201_chg": u201_chg,
           "idx_fresh": idx_fresh, "breadth": breadth, "breadth_n": n,
           "band": band, "gray_lean": lean,
           "nasdaq": nasdaq, "band_us": band_us,
           "note": "SHADOW — 매매·보드 무연결, 미국반영 band_us 실측 10거래일+ 후 장착결정"}
    tmp = str(OUT_JSON) + ".tmp"
    Path(tmp).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, str(OUT_JSON))

    new_file = not OUT_CSV.exists() or OUT_CSV.stat().st_size < 10
    with io.open(OUT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "u201_chg", "idx_fresh", "breadth", "breadth_n", "band", "gray_lean", "nasdaq", "band_us"])
        w.writerow([rec["ts"], u201_chg, int(idx_fresh), breadth, n, band, lean, nasdaq, band_us])
    print(f"[{now:%H:%M}] band={band} u201={u201_chg} breadth={breadth}(n={n}) lean={lean} | 나스닥={nasdaq} band_us={band_us}")

if __name__ == "__main__":
    main()
