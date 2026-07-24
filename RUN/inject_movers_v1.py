# -*- coding: utf-8 -*-
# ============================================================================
# inject_movers_v1.py   [수집기 universe 보강 — 당일 급등주 편입]
#  문제: 수집기가 ~48 active만 봐서 당일 NEW 급등주(파루·삼기 등)를 못 잡음(커버리지 갭).
#  해결: 네이버(외부·키움TR無)에서 코스닥 상승률 상위 → 거래대금순 top N → IPC/micro_watch_movers.json.
#        수집기의 기존 STRATEGY-INJECT(micro_watch_*.json glob, cap20)가 active 보장수집.
#  ★안전: N제한(기본10)·네이버 발굴이라 키움TR 0·수집 TR만 N만큼 증가(cap으로 묶임).
#  단발실행(스케줄 3분). 출력 IPC/micro_watch_movers.json · LOG/inject_movers.log
# ============================================================================
import os, sys, io, json, urllib.request
from pathlib import Path
from datetime import datetime
import re

OUT=Path(r"C:\stock_bot\IPC\micro_watch_movers.json")
LOG=Path(r"C:\stock_bot\DATA\LOG\inject_movers.log")
N=int(os.environ.get("INJECT_MOVERS_N","10"))
ETF=re.compile(r'KODEX|TIGER|KIWOOM|ACE|SOL|RISE|PLUS|KBSTAR|ARIRANG|HANARO|KOSEF|TIMEFOLIO|머니마켓|국고|국채|CD금리|레버리지|인버스|ETN|채권|배당|선물')

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Referer":"https://m.stock.naver.com/"})
    with urllib.request.urlopen(req,timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    rows={}
    for kind in ["up","trading"]:   # 상승률상위 + 거래대금상위
        try:
            j=fetch(f"https://m.stock.naver.com/api/stocks/{kind}/KOSDAQ?page=1&pageSize=20")
            for s in (j.get("stocks") or []):
                c=str(s.get("itemCode","")).strip(); nm=str(s.get("stockName",""))
                if len(c)!=6 or ETF.search(nm): continue
                try: tv=float(str(s.get("accumulatedTradingValue","0")).replace(",",""))
                except Exception: tv=0
                # 거래대금 큰 것 우선(중복은 max)
                if c not in rows or tv>rows[c][1]: rows[c]=(nm,tv)
        except Exception as e:
            pass
    top=sorted(rows.items(), key=lambda x:-x[1][1])[:N]
    codes=[c for c,_ in top]
    out={"codes":codes,"ts":datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),"src":"naver_kosdaq_movers"}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False),encoding="utf-8")
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write(f"[{datetime.now():%H:%M:%S}] inject {len(codes)}: "+", ".join(f"{c}({rows[c][0][:6]})" for c in codes)+"\n")
    try: sys.stdout.reconfigure(encoding="utf-8"); print(f"편입 {len(codes)}종목: "+", ".join(f"{rows[c][0][:8]}" for c in codes))
    except Exception: pass

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("[ERR] inject_movers:",e)
