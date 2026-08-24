# -*- coding: utf-8 -*-
"""오늘(8/7) S02 22종목을 실제 판정 모듈로 재생한다.

  python cmp807.py orig    -> 원본 모듈       (재현 검증용)
  python cmp807.py patch   -> 흡수판정 얹은 모듈

판정은 재구현하지 않는다. mon.process_point() 를 그대로 부른다.
아래 for 문은 '자료를 먹이는 운전대'일 뿐 판정이 아니다.
"""
import sys, csv, json, pathlib
from datetime import datetime

SP = pathlib.Path(r"C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK"
                  r"\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad")
MODE = (sys.argv[1] if len(sys.argv) > 1 else "orig").lower()
sys.path.insert(0, r"C:\stock_bot\RUN")
if MODE == "patch":            # 패치본이 RUN 보다 앞이어야 실린다(순서 중요)
    sys.path.insert(0, str(SP / "patched"))

import strategy_02_low_buy_signal_v1 as S02          # noqa: E402
from 저점매수_매도소진 import MarketPoint             # noqa: E402

print(f"[{MODE}] 모듈 = {S02.__file__}")
print(f"[{MODE}] 흡수관문 = {getattr(S02, 'ABSORB_GATE', '없음')}")

CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
codes = sorted((SP / "today_codes.txt").read_text(encoding="ascii").split(","))
fires_real = json.loads((SP / "today_fires.json").read_text(encoding="utf-8"))
real_by_code = {}
for r in fires_real:
    real_by_code.setdefault(str(r["code"]).zfill(6), []).append(r)


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def drive(code, rows, high_ref=0.0):
    """실제 판정 모듈에 1초 틱을 순서대로 먹인다. 신호행 전체를 남긴다."""
    mon = S02.LowBuySignalMonitor()
    open_px = 0.0
    run_high = 0.0
    out = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (TypeError, ValueError):
            continue
        price = f(r["current_price"])
        if price <= 0 or ts.time() < S02.ENTRY_START:
            continue
        if open_px <= 0:
            open_px = price
        run_high = max(run_high, price)
        point = MarketPoint(
            ts=ts, price=price, cum_vol=f(r["cum_vol"]), che_str=f(r["che_str"]),
            ask_tot=f(r["ask_tot"]), bid_tot=f(r["bid_tot"]),
            buy_money_cum=f(r["buy_money_cum"]), sell_money_cum=f(r["sell_money_cum"]),
            buy_vol_cum=f(r["buy_vol_cum"], -1.0), sell_vol_cum=f(r["sell_vol_cum"], -1.0),
        )
        row, hit = mon.process_point(
            code, code, point, allow_signal=True,
            open_price=open_px, session_high=max(high_ref, run_high))
        if hit:
            row = dict(row)
            row["_t"] = ts.strftime("%H:%M:%S")
            out.append(row)
    return out


allf = []
for code in codes:
    p = CACHE / f"20260807_{code}.csv"
    if not p.exists():
        print(f"  {code} 캐시 없음 - 건너뜀")
        continue
    with p.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    hi = max((f(x.get("dip_episode_high")) for x in real_by_code.get(code, [])),
             default=0.0)
    got = drive(code, rows, high_ref=hi)
    for g in got:
        g["_code"] = code
    allf.extend(got)
    real = real_by_code.get(code, [])
    print(f"  {code} 틱{len(rows):>6} · 실제신호 {len(real)}건 · 재생 {len(got)}건"
          + (f"  실제[{','.join(str(x['ts'])[11:19] for x in real)}]"
             f" 재생[{','.join(g['_t'] for g in got)}]" if (real or got) else ""))

(SP / f"fires_{MODE}.json").write_text(json.dumps(allf, ensure_ascii=False, default=str),
                                       encoding="utf-8")
print(f"\n[{MODE}] 재생 신호 총 {len(allf)}건 -> fires_{MODE}.json")
