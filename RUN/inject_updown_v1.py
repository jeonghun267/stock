# -*- coding: utf-8 -*-
# ============================================================================
# inject_updown_v1.py   [수집기 universe 보강 — 등락율 순위 커버리지 (친구님 2026-06-27)]
#  문제: inject_movers는 거래대금순 top10이라 '소형 고-등락율'(삼기56억·케스피온6억=+30%)을 놓침.
#        = 어제 등락율 top20 중 우리 매매 0개(커버리지 구멍). 강한 종목 놓침의 근원.
#  해결: 네이버(외부·키움TR無) 코스닥 상승률(등락율) 상위 → 순수 등락율 순서 top N → IPC/micro_watch_updown.json.
#        수집기 STRATEGY-INJECT(micro_watch_*.json glob·Fix A 풀밖우선)가 자동수집 → 익일 NEW_PB/DEEPV/돌파가 봄.
#  ★주문0·키움TR0(네이버만)·커버리지 전용(추격매수 아님·진입은 각 전략 게이트가 함).
#  ★기존 inject_movers·수집기 안 건드림(별도 파일·별도 출력). 단발실행(스케줄 3분).
# ============================================================================
import os, sys, io, json, urllib.request, re
from pathlib import Path
from datetime import datetime

OUT = Path(r"C:\stock_bot\IPC\micro_watch_updown.json")
LOG = Path(r"C:\stock_bot\DATA\LOG\inject_updown.log")
N = int(os.environ.get("INJECT_UPDOWN_N", "15"))   # 등락율 상위 N (소형 무버 포함하려 거래대금 컷 안함)
ETF = re.compile(r'KODEX|TIGER|KIWOOM|ACE|SOL|RISE|PLUS|KBSTAR|ARIRANG|HANARO|KOSEF|TIMEFOLIO|머니마켓|국고|국채|CD금리|레버리지|인버스|ETN|채권|배당|선물')

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    codes = []; info = {}
    try:
        # 네이버 '상승률 상위'(up) = 등락율 순서. 거래대금 컷 안하고 순수 등락율 top N.
        j = fetch(f"https://m.stock.naver.com/api/stocks/up/KOSDAQ?page=1&pageSize={max(N*2, 30)}")
        for s in (j.get("stocks") or []):
            c = str(s.get("itemCode", "")).strip(); nm = str(s.get("stockName", ""))
            if len(c) != 6 or ETF.search(nm): continue
            try: fr = float(str(s.get("fluctuationsRatio", "0")).replace(",", "").replace("+", ""))
            except Exception: fr = 0
            if c not in info:
                info[c] = (nm, fr); codes.append(c)
            if len(codes) >= N: break
    except Exception as e:
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] fetch실패 {e}\n")
    out = {"codes": codes, "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "src": "naver_kosdaq_updown"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%H:%M:%S}] updown {len(codes)}: " + ", ".join(f"{c}({info[c][0][:6]} {info[c][1]:+.0f}%)" for c in codes) + "\n")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"등락율 커버리지 {len(codes)}종목: " + ", ".join(f"{info[c][0][:8]}({info[c][1]:+.0f}%)" for c in codes))
    except Exception: pass

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print("[ERR] inject_updown:", e)
