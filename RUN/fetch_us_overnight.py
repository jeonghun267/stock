# -*- coding: utf-8 -*-
# 미국 overnight 지수 수집 → DATA/us_overnight.json
# [2026-06-09 표시/로그 전용 — 매매 로직 무연결. 주문/체결/브릿지/리스크/매도 어디에도 안 씀.]
# 소스: Yahoo Finance chart API (urllib, 외부 패키지 불필요).
import json, sys, time, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime

OUT = Path(r"C:\stock_bot\DATA\us_overnight.json")
SYMS = [
    ("nasdaq", "^IXIC", "나스닥"),
    ("sox",    "^SOX",  "반도체SOX"),
    ("sp500",  "^GSPC", "S&P500"),
    ("vix",    "^VIX",  "VIX"),
    ("nq_fut", "NQ=F",  "나스닥선물"),
]

def fetch_one(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?interval=1d&range=5d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        j = json.loads(r.read().decode("utf-8"))
    res = j["chart"]["result"][0]
    m = res["meta"]
    price = float(m.get("regularMarketPrice") or 0)
    # [전일종가 안정화] 일봉 종가 배열의 마지막 '완료' 종가를 전일종가로 사용(range 무관).
    #   meta.chartPreviousClose는 range에 따라 흔들려 사용 안 함.
    closes = []
    try:
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, TypeError, IndexError):
        closes = []
    prev = 0.0
    if len(closes) >= 2:
        # closes[-1]=현재(또는 당일 형성중), closes[-2]=직전 완료 종가
        if price <= 0:
            price = float(closes[-1])
        prev = float(closes[-2])
    if prev <= 0:
        prev = float(m.get("previousClose") or m.get("chartPreviousClose") or 0)
    chg = round((price / prev - 1) * 100, 2) if prev > 0 else None
    return round(price, 2), round(prev, 2), chg

def compute_risk(d):
    def g(k):
        v = d.get(k, {})
        return v.get("chg") if isinstance(v, dict) else None
    nq, sx, vx, fu = g("nasdaq"), g("sox"), g("vix"), g("nq_fut")
    if ((nq is not None and nq <= -3.0) or (sx is not None and sx <= -5.0)
            or (vx is not None and vx >= 20.0) or (fu is not None and fu <= -0.7)):
        return "DANGER"
    if ((nq is not None and nq <= -2.0) or (sx is not None and sx <= -3.5)
            or (vx is not None and vx >= 10.0)):
        return "CAUTION"
    return "NORMAL"

def main():
    cache_min = 0.0
    for a in sys.argv[1:]:
        if a.startswith("--cache-min="):
            try: cache_min = float(a.split("=", 1)[1])
            except ValueError: pass
    if cache_min > 0 and OUT.exists():
        try:
            age = (time.time() - OUT.stat().st_mtime) / 60.0
            if age < cache_min:
                print("[US] cache fresh (%.1fmin < %.1f) skip" % (age, cache_min)); return
        except OSError:
            pass
    data = {}; fail = 0
    for key, sym, label in SYMS:
        try:
            price, prev, chg = fetch_one(sym)
            data[key] = {"label": label, "sym": sym, "price": price, "prev": prev, "chg": chg}
        except Exception as e:
            data[key] = {"label": label, "sym": sym, "error": str(e)[:60]}
            fail += 1
    risk = "DATA_FAIL" if fail >= len(SYMS) else compute_risk(data)
    out = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "risk": risk, "fail": fail, "n": len(SYMS), "data": data}
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[US] saved risk=%s fail=%d/%d" % (risk, fail, len(SYMS)))
    except OSError as e:
        print("[US] write fail: %s" % e)

if __name__ == "__main__":
    main()
