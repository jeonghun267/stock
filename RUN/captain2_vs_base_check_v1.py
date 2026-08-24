# -*- coding: utf-8 -*-
"""베이스돌파 OFF 후, 캡틴2가 그 종목들을 실제로 잡는지 검증 (2026-07-23 친구님 지시).
읽기전용·TR0·엔진무수정. 오늘 베이스돌파 그림자가 '샀을 종목'(FILL) 각각에 대해
캡틴2가 ①실제매수 ②BUY_READY만 ③못봄 중 무엇인지 분류. 바탕화면에 출력.
전제: VH_BB=NO(실전 베이스돌파 OFF)라 실제 매매는 안 나감. 그림자 관찰기는 계속 돎."""
import os, csv, io
from collections import defaultdict
from datetime import datetime

BASE = r"C:\stock_bot"
TODAY = datetime.now().strftime("%Y%m%d")
SHADOW = os.path.join(BASE, "LOG", "base_breakout_shadow.csv")
EVT = os.path.join(BASE, "data", "shadow", f"captain2_events_{TODAY}.csv")
OUT = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\UserK"), "Desktop",
                   f"캡틴2_vs_베이스_{TODAY}.txt")


def sec(hms):
    return int(hms[:2]) * 3600 + int(hms[3:5]) * 60 + int(hms[6:8])


def main():
    L = ["══ 베이스돌파 OFF 후 캡틴2 대체 검증  %s ══" % datetime.now().strftime("%Y-%m-%d %H:%M"),
         "  베이스돌파 그림자가 '샀을' 종목을 캡틴2가 실제로 잡았는지 분류", ""]

    # 오늘 베이스돌파 그림자 FILL = 베이스돌파가 진입했을 종목(시각·가격)
    base_fills = []
    try:
        with io.open(SHADOW, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); next(rd)
            for r in rd:
                if len(r) >= 5 and r[0] == TODAY and r[4] == "FILL":
                    base_fills.append({"code": r[2], "name": r[3],
                                       "sec": sec(r[1]), "hms": r[1], "px": r[11]})
    except Exception as e:
        L.append(f"  베이스돌파 그림자 읽기 실패: {e}")

    # 캡틴2 오늘 이벤트 — 종목별 BUY 시각 / BUY_READY 시각
    cap_buy = defaultdict(list); cap_ready = defaultdict(list)
    try:
        with io.open(EVT, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); next(rd)
            for r in rd:
                if len(r) < 4:
                    continue
                if r[3] == "BUY":
                    cap_buy[r[1]].append(r[0][11:19])
                elif r[3] == "BUY_READY":
                    cap_ready[r[1]].append(r[0][11:19])
    except Exception as e:
        L.append(f"  캡틴2 이벤트 읽기 실패: {e}")

    if not base_fills:
        L.append("  오늘 베이스돌파 진입신호(FILL) 없음 — 미발생(비교 대상 없음)")
        io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
        print("\n".join(L)); return

    n_bought = n_ready = n_miss = 0
    L.append(f"  베이스돌파가 샀을 종목: {len(base_fills)}개\n")
    L.append(f"  {'종목':<10}{'코드':<8}{'베이스진입':<10}{'캡틴2 결과'}")
    for b in base_fills:
        code = b["code"]
        # 캡틴2 BUY가 베이스진입 ±15분 내 있으면 '실제매수'
        bought = [t for t in cap_buy.get(code, []) if abs(sec(t) - b["sec"]) <= 900]
        ready = cap_ready.get(code, [])
        if bought:
            res = f"✅ 실제매수 {bought[0]}"; n_bought += 1
        elif ready:
            res = f"△ BUY_READY 도달했으나 미매수({len(ready)}회) — 슬롯/게이트"; n_ready += 1
        else:
            res = "✗ 캡틴2 미인지"; n_miss += 1
        L.append(f"  {b['name']:<10}{code:<8}{b['hms']:<10}{res}")

    L.append("")
    L.append(f"  ══ 요약: 베이스돌파 {len(base_fills)}종목 중 → "
             f"캡틴2 실제매수 {n_bought} · BUY_READY만 {n_ready} · 미인지 {n_miss} ══")
    L.append("  판정: 실제매수 비율이 높을수록 '캡틴2가 돌파를 대체' 입증.")
    L.append("        BUY_READY만 많으면 = 봤지만 슬롯/게이트로 놓침(경쟁·문턱 점검).")
    io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        io.open(OUT, "w", encoding="utf-8").write(f"검증 스크립트 오류: {type(e).__name__}: {e}")
        raise
