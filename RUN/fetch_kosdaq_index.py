# -*- coding: utf-8 -*-
# 코스닥 종합지수 직접조회 → DATA/kosdaq_index.json (보드 표시 전용, 매매 무연결).
# [2026-06-09] 수집기 U201(prices_1m)는 내일 collector 기동부터. 오늘 보드 표시용으로 직접조회.
# opt20003 업종='101'(코스닥 종합). broker_client 사용(키움 OCX는 broker_gateway 공유).
import sys, json, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
OUT = Path(r"C:\stock_bot\DATA\kosdaq_index.json")

def main():
    cache_min = 0.0
    for a in sys.argv[1:]:
        if a.startswith("--cache-min="):
            try: cache_min = float(a.split("=", 1)[1])
            except ValueError: pass
    if cache_min > 0 and OUT.exists():
        try:
            if (time.time() - OUT.stat().st_mtime) / 60.0 < cache_min:
                print("[KOSDAQ] cache fresh skip"); return
        except OSError:
            pass
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            print("[KOSDAQ] broker dead"); return
        bc = BrokerClient()
        r = bc.tr("opt20003", {"업종코드": "101", "틱범위": "1"},
                  ["현재가", "전일대비", "대비기호"], screen_no="9703", timeout_sec=6.0)
        recs = (r.get("data") or {}).get("records") or []
        if not recs:
            print("[KOSDAQ] no data:", r.get("error")); return
        rec = recs[0]
        def f(v):
            s = str(v).strip()
            try: return float(s) if s else 0.0
            except ValueError: return 0.0
        price = abs(f(rec.get("현재가", "0")))
        diff = abs(f(rec.get("전일대비", "0")))
        sign = str(rec.get("대비기호", "")).strip()
        if sign in ("4", "5"):   # 4=하한, 5=하락
            diff = -diff
        prev = price - diff
        chg = round(diff / prev * 100, 2) if prev > 0 else None
        out = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "price": round(price, 2), "prev": round(prev, 2), "chg": chg}
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print("[KOSDAQ] saved price=%.2f 전일대비=%.2f%%" % (price, chg if chg is not None else 0))
    except Exception as e:
        print("[KOSDAQ] fail:", e)

if __name__ == "__main__":
    main()
