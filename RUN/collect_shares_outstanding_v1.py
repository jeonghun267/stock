# -*- coding: utf-8 -*-
"""[상장주식수/시가총액 수집 → 회전율용 · READ-ONLY TR(SendOrder 0)] 친구님 2026-06-19.

목적: 생존분석 회전율(거래대금÷시총)용 상장주식수 확보. 영웅문(키움) opt10001로만 받을 수 있음.
  · 상장주식수는 거의 불변 → 1회 전수 수집하면 과거 전부 백필 가능(그날 종가×주식수=그날 시총).
  · eod_pickup_market_cap_v1.fetch_market_cap(검증된 read-only IPC, screen 0802)을 그대로 재사용.

★실매매 0 (SendOrder 없음·opt10001 조회 TR뿐). ★장중 금지 — 라이브 TR과 경합. 마감 후(15:45) 실행.

동작:
  · 유니버스 = 최신 eod KOSDAQ 전 종목 (또는 --codes).
  · 증분: 기존 shares_outstanding.csv에 있고 STALE_DAYS 이내면 건너뜀(=첫날만 무겁고 이후 가벼움).
    상장주식수 변동(증자·분할) 반영 위해 STALE_DAYS(기본30) 지나면 갱신.
  · 브로커 DEAD면 즉시 중단(아무것도 안 망침). 종목별 try/except 격리. 호출간 sleep로 throttle.
출력: DATA/shares_outstanding.csv (code,name,shares,market_cap_eok,price,collected_at)
실행: C:\\Python310-32\\python.exe -X utf8 C:\\stock_bot\\RUN\\collect_shares_outstanding_v1.py [--codes a,b] [--refresh] [--limit N]
"""
import os, sys, io, csv, time, argparse
from datetime import datetime, timedelta

BASE = r"C:\stock_bot"
RUN = os.path.join(BASE, "RUN")
EOD = os.path.join(BASE, "data", "eod_daily_bars.csv")
OUT = os.path.join(BASE, "DATA", "shares_outstanding.csv")
LOG = os.path.join(BASE, "LOG", "collect_shares.log")
SLEEP_SEC = 0.30          # 호출간 throttle (키움 rate limit 보호)
STALE_DAYS = 30           # 이 일수 지난 기존 종목은 재수집(증자/분할 반영)
if RUN not in sys.path: sys.path.insert(0, RUN)


def log(m):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    try:
        with io.open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception:
        pass


def z(c): return str(c).zfill(6)


def load_existing():
    rows = {}
    if os.path.exists(OUT):
        with io.open(OUT, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                c = z(r.get("code", ""))
                if c: rows[c] = r
    return rows


def kosdaq_universe():
    import pandas as pd
    codes = set()
    recent = (datetime.now() - timedelta(days=20)).strftime("%Y%m%d")
    for ch in pd.read_csv(EOD, dtype={"date": str, "code": str},
                          usecols=["date", "code", "market"], chunksize=200000, low_memory=True):
        ch = ch[(ch["market"] == "KOSDAQ") & (ch["date"] >= recent)]
        for r in ch.itertuples(index=False):
            codes.add(z(r.code))
    return sorted(codes)


def is_fresh(row):
    try:
        ts = datetime.fromisoformat(str(row.get("collected_at", "")))
        return (datetime.now() - ts).days < STALE_DAYS and float(row.get("shares", 0) or 0) > 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=None, help="콤마분리 코드(지정시 유니버스 대체)")
    ap.add_argument("--refresh", action="store_true", help="기존도 전부 재수집")
    ap.add_argument("--limit", type=int, default=0, help="이번 실행 최대 수집수(0=무제한)")
    args = ap.parse_args()

    # 장중 가드 (09:00~15:30) — 라이브 TR 경합 방지
    now = datetime.now(); hm = now.hour * 100 + now.minute
    if 900 <= hm <= 1530 and not args.codes:
        log("⚠ 장중(09:00~15:30) 전수수집 금지 — 마감 후 실행하세요. (--codes 소량은 허용) 중단.")
        return

    try:
        from eod_pickup_market_cap_v1 import fetch_market_cap
    except Exception as e:
        log(f"fetch_market_cap import 실패: {e}"); return
    try:
        from broker_client import BrokerClient
        if not BrokerClient().alive():
            log("broker DEAD → 중단(아무것도 안 망침)."); return
    except Exception as e:
        log(f"broker 확인 실패: {e} → 중단."); return

    existing = load_existing()
    if args.codes:
        universe = [z(c) for c in args.codes.split(",") if c.strip()]
    else:
        universe = kosdaq_universe()
    todo = [c for c in universe if args.refresh or c not in existing or not is_fresh(existing[c])]
    if args.limit > 0: todo = todo[:args.limit]
    log(f"유니버스 {len(universe)} · 기존 {len(existing)} · 이번 대상 {len(todo)} (sleep {SLEEP_SEC}s)")
    if not todo:
        log("수집 대상 없음(전부 최신). 종료."); return

    ok = fail = 0
    result = dict(existing)
    for i, code in enumerate(todo):
        try:
            mc = fetch_market_cap(code)
        except Exception as e:
            mc = None; log(f"  예외 {code}: {e}")
        if mc:
            shares = int(mc.get("listed_shares_kju", 0) or 0) * 1000   # 천주 → 주
            result[code] = {
                "code": code, "name": mc.get("name", ""),
                "shares": shares, "market_cap_eok": mc.get("market_cap_eok", 0),
                "price": mc.get("current_price", 0),
                "collected_at": datetime.now().isoformat(),
            }
            ok += 1
        else:
            fail += 1
        if (i + 1) % 50 == 0:
            log(f"  진행 {i+1}/{len(todo)} (OK {ok} FAIL {fail}) — 중간저장")
            write_out(result)
        time.sleep(SLEEP_SEC)

    write_out(result)
    nz = sum(1 for r in result.values() if float(r.get("shares", 0) or 0) > 0)
    log(f"완료: 이번 OK {ok} FAIL {fail} · 누적 {len(result)}종목(주식수>0 {nz}) → {OUT}")


def write_out(rows):
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["code", "name", "shares", "market_cap_eok", "price", "collected_at"])
            w.writeheader()
            for c in sorted(rows):
                r = rows[c]
                w.writerow({k: r.get(k, "") for k in ["code", "name", "shares", "market_cap_eok", "price", "collected_at"]})
        os.replace(tmp, OUT)
    except Exception as e:
        log(f"저장 실패: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[FATAL] {e}")
        import traceback; traceback.print_exc()
        sys.exit(0)
