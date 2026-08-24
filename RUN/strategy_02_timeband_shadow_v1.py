# -*- coding: utf-8 -*-
"""[S02 시간대 그림자 2026-08-03 친구님 지시 "그림자로 대조해봐"] 주문 0·읽기 전용.

무엇: 그날 1초 캡처를 재생해 전략2 신호를 그대로 뽑고, **시간대 처방 후보들**을
      나란히 채점해 하루 한 줄씩 CSV에 쌓는다. 실전 코드는 전혀 건드리지 않는다.

왜: 8/3 실측에서 2번의 손실이 12~13시 매수에 몰렸다(그 구간 10건 합계 -12.02%,
    09~11시 13건은 +12.53%). 저점 찾기는 정상이고(산 뒤 30분 안에 손절선 터치
    4%뿐) 그 시간대에 '반등이 안 오는' 것이 원인이다.
    ⚠️그런데 하루 10건을 놓고 조건을 고르면 7/31에 실패한 방식(확인 조건을
      더할수록 전부 나빠짐)을 반복하게 된다. 그래서 정하지 않고 며칠 쌓는다.

후보(동시 기록·서로 독립):
    BASE   현행 그대로(09:06~14:20 전 구간)
    CUT12  12:00~14:00 매수 차단
    CUT11  11:30 이후 매수 차단
    DEEP   12:00~14:00 에는 발동 낙폭을 더 깊게 요구(고점 대비 -5% 이상 밀림)
    FLOW   12:00~14:00 에는 매수 대금속도 > 매도 대금속도 를 추가로 요구

매도는 다섯 후보 모두 동일 규칙으로 채점한다(매수 처방만 비교하기 위함).
매도 = -2% 하드손절 · 50초 주기 트레일(1%/1.5%/2%) · 3분봉 상승보유 · 15:10 청산.

쓰는 법:
    C:\\python310\\python.exe C:\\stock_bot\\RUN\\strategy_02_timeband_shadow_v1.py 20260803
    (날짜 생략 시 오늘)
출력:
    C:\\stock_bot\\data\\shadow\\strategy_02_timeband_shadow.csv   (하루 5줄·후보별)
    C:\\stock_bot\\data\\shadow\\strategy_02_timeband_signals.csv  (신호 한 건당 1줄)
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

csv.field_size_limit(10_000_000)

from strategy_02_low_buy_signal_v1 import LowBuySignalMonitor
from 저점매수_매도소진 import MarketPoint

CAP_DIR = Path(r"C:\stock_bot\data\shadow\mf_1s_capture")
NAMES = Path(r"C:\stock_bot\data\_code_name_cache.json")
HR = Path(r"C:\stock_bot\IPC\micro_watch_high_range.json")
OUT_DAY = Path(r"C:\stock_bot\data\shadow\strategy_02_timeband_shadow.csv")
OUT_SIG = Path(r"C:\stock_bot\data\shadow\strategy_02_timeband_signals.csv")

HARD_STOP = -2.0
TRAIL = ((1.0, 1.0), (3.0, 1.5), (6.0, 2.0))
INTERVAL = 50
FORCE_EXIT = "15:10:00"

# ★[2026-08-03 친구님 "원래 오후 시간대는 좀더 강하게 넣는게 맞아"]
#   오후 = 12:00 이후 전 구간(S02 매수창 끝 14:20 까지). 8/3 실측에서
#   12~13시 10건 -12.02%, 14시대 4건 -0.69% 로 오후 전체가 약했다.
AFTERNOON_START = "12:00:00"

# 오후 강화 문턱 후보 — 지금 하나를 고르지 않는다. 며칠 쌓아 고른다.
#   이름 -> (오후 최소 낙폭 %, 매수속도 우위 요구 여부)
AFTERNOON_RULES = {
    "AFT3": (3.0, False),      # 현행 발동 문턱과 동일 = 대조군
    "AFT4": (4.0, False),
    "AFT5": (5.0, False),
    "AFT6": (6.0, False),
    "AFT5F": (5.0, True),      # 낙폭 5%↑ + 매수속도 우위
}


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_targets():
    try:
        raw = json.loads(HR.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [str(c).zfill(6) for c in (raw.get("codes") or [])]


def load_names():
    try:
        raw = json.loads(NAMES.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return raw.get("map", raw)


def load_series(path, targets):
    rows = {c: [] for c in targets}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            code = str(raw.get("code") or "").zfill(6)
            if code not in rows:
                continue
            price = number(raw.get("current_price"))
            if price <= 0:
                continue
            rows[code].append((
                datetime.fromisoformat(raw["ts"]), price,
                number(raw.get("buy_money_cum")), number(raw.get("sell_money_cum")),
                number(raw.get("cum_vol")), number(raw.get("che_str")),
                number(raw.get("ask_tot")), number(raw.get("bid_tot")),
            ))
    for code in targets:
        rows[code].sort()
    return rows


def money_rate(rows, stamps, index, window, column):
    start = max(0, min(bisect.bisect_left(stamps, stamps[index] - window), index))
    span = max(1.0, stamps[index] - stamps[start])
    return (rows[index][column] - rows[start][column]) / span


def three_minute_closes(rows, until_ts):
    """재생용 3분봉 종가 — 실전 ma3_common_v1 과 같은 격자(블록 마지막 종가)."""
    blocks = {}
    for stamp, price, *_ in rows:
        if stamp >= until_ts:
            break
        key = stamp.replace(second=0, microsecond=0)
        blocks[key.replace(minute=(key.minute // 3) * 3)] = price
    return [blocks[k] for k in sorted(blocks)]


def run_exit(rows, stamps, start_index, entry_price, closes_cache):
    """다섯 후보 공통 매도 규칙. (수익률, 사유) 반환."""
    peak, last_eval = entry_price, stamps[start_index - 1] if start_index else stamps[0]
    for index in range(start_index, len(rows)):
        stamp, price = rows[index][0], rows[index][1]
        peak = max(peak, price)
        gain = (price / entry_price - 1.0) * 100.0
        if gain <= HARD_STOP:
            return gain, "HARD_STOP"
        if stamp.strftime("%H:%M:%S") >= FORCE_EXIT:
            return gain, "FORCE_EXIT"
        if stamps[index] - last_eval < INTERVAL:
            continue
        last_eval = stamps[index]
        peak_gain = (peak / entry_price - 1.0) * 100.0
        threshold = 0.0
        for armed, drop in TRAIL:
            if peak_gain >= armed:
                threshold = drop
        if threshold <= 0 or (peak - price) / peak * 100.0 < threshold:
            continue
        # 상승보유 — 3분봉 20선 우상향 + 현재가가 10선(침범 시 20선) 위
        closes = closes_cache(stamp)
        if len(closes) >= 21:
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma20_prev = sum(closes[-21:-1]) / 20
            if ma20 > ma20_prev and (price >= ma10 or price >= ma20):
                continue
        # 매수세 우위 — 꺾였을 때만 판다
        buy10 = money_rate(rows, stamps, index, 10, 2)
        buy30 = money_rate(rows, stamps, index, 30, 2)
        sell10 = money_rate(rows, stamps, index, 10, 3)
        sell30 = money_rate(rows, stamps, index, 30, 3)
        if buy30 > 0 and sell30 > 0:
            if buy10 >= sell10 and not (buy10 < buy30 and sell10 > sell30):
                continue
        return gain, "TRAIL"
    last = rows[-1][1]
    return (last / entry_price - 1.0) * 100.0, "OPEN"


def variant_allows(name, stamp, drop_pct, buy_lead):
    """후보별 매수 허용 여부. 오전은 전 후보가 동일(현행) — 오후만 갈린다."""
    clock = stamp.strftime("%H:%M:%S")
    afternoon = clock >= AFTERNOON_START
    if name == "BASE":
        return True
    if name == "CUT12":                       # 참조용: 오후 통째 차단
        return not afternoon
    if not afternoon:
        return True
    rule = AFTERNOON_RULES.get(name)
    if not rule:
        return True
    min_drop, need_lead = rule
    if drop_pct < min_drop:
        return False
    return (buy_lead is True) if need_lead else True


VARIANTS = ("BASE", "AFT3", "AFT4", "AFT5", "AFT6", "AFT5F", "CUT12")


def append_rows(path: Path, rows: list, day: str) -> None:
    """같은 날짜 행을 먼저 지우고 새로 쓴다(재실행해도 중복이 안 쌓이게).

    ★태스크가 두 번 돌거나 손으로 한 번 더 돌리면 같은 날이 두 번 들어가
      합계·평균이 통째로 틀어진다(8/3 실측: 27건이 54건으로 뻥튀기).
    """
    kept = []
    if path.exists():
        try:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                kept = [r for r in csv.DictReader(fh)
                        if str(r.get("date") or "") != day]
        except OSError:
            kept = []
    fields = list(rows[0])
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in kept:
            writer.writerow({k: row.get(k, "") for k in fields})
        writer.writerows(rows)
    os.replace(tmp, path)


def main() -> int:
    day = (sys.argv[1] if len(sys.argv) > 1
           else datetime.now().strftime("%Y%m%d"))
    path = CAP_DIR / f"mf_1s_{day}.csv"
    if not path.exists():
        print(f"1초 캡처 없음: {path}")
        return 1
    targets = load_targets()
    if not targets:
        print("고저폭30 목록을 못 읽었다")
        return 1
    names = load_names()
    series = load_series(path, targets)

    signals = []
    for code in targets:
        rows = series[code]
        if len(rows) < 500:
            continue
        stamps = [r[0].timestamp() for r in rows]
        cache = {}

        def closes_cache(stamp, _rows=rows, _cache=cache):
            key = stamp.strftime("%H%M")
            if key not in _cache:
                _cache[key] = three_minute_closes(_rows, stamp)
            return _cache[key]

        session_high = 0.0
        monitor = LowBuySignalMonitor()
        for index, (stamp, price, buy_cum, sell_cum,
                    volume, che, ask, bid) in enumerate(rows):
            session_high = max(session_high, price)
            try:
                _, fired = monitor.process_point(code, names.get(code, code), MarketPoint(
                    ts=stamp, price=price, cum_vol=volume, che_str=che,
                    ask_tot=ask, bid_tot=bid,
                    buy_money_cum=buy_cum, sell_money_cum=sell_cum))
            except Exception:
                continue
            if not fired:
                continue
            drop_pct = ((session_high - price) / session_high * 100.0
                        if session_high > 0 else 0.0)
            buy10 = money_rate(rows, stamps, index, 10, 2)
            sell10 = money_rate(rows, stamps, index, 10, 3)
            buy30 = money_rate(rows, stamps, index, 30, 2)
            sell30 = money_rate(rows, stamps, index, 30, 3)
            buy_lead = (buy10 > sell10) if (buy30 > 0 and sell30 > 0) else None
            gain, why = run_exit(rows, stamps, index + 1, price, closes_cache)
            forward = [r[1] for r in rows[index + 1:]]
            mfe = ((max(forward) / price - 1.0) * 100.0) if forward else 0.0
            signals.append({
                "date": day, "code": code, "name": names.get(code, code),
                "buy_at": stamp.strftime("%H:%M:%S"), "buy_price": round(price, 1),
                "drop_pct": round(drop_pct, 2),
                "buy_lead": "" if buy_lead is None else ("O" if buy_lead else "X"),
                "gain_pct": round(gain, 3), "exit_why": why, "mfe_pct": round(mfe, 2),
            })

    if not signals:
        print(f"{day}: 신호 0건")
        return 0

    OUT_SIG.parent.mkdir(parents=True, exist_ok=True)
    append_rows(OUT_SIG, signals, day)

    print("=" * 88)
    print(f"S02 시간대 그림자 — {day}   신호 {len(signals)}건")
    print("=" * 88)
    print(f"{'후보':<8}{'건수':>5}{'합계':>10}{'평균':>9}{'승률':>10}{'손절':>6}  설명")
    print("-" * 88)
    rows_day = []
    labels = {"BASE": "현행(오후 조건 없음)", "CUT12": "오후 통째 차단(참조)"}
    for key, (min_drop, need_lead) in AFTERNOON_RULES.items():
        labels[key] = (f"오후 낙폭 {min_drop:.0f}%↑"
                       + (" + 매수속도 우위" if need_lead else ""))
    for name in VARIANTS:
        taken = [s for s in signals
                 if variant_allows(name,
                                   datetime.strptime(f"{day} {s['buy_at']}",
                                                     "%Y%m%d %H:%M:%S"),
                                   s["drop_pct"],
                                   None if s["buy_lead"] == ""
                                   else s["buy_lead"] == "O")]
        count = len(taken)
        total = sum(s["gain_pct"] for s in taken)
        wins = sum(1 for s in taken if s["gain_pct"] > 0)
        stops = sum(1 for s in taken if s["exit_why"] == "HARD_STOP")
        avg = total / count if count else 0.0
        rate = f"{wins}/{count}" if count else "-"
        print(f"{name:<8}{count:>5}{total:>9.2f}%{avg:>8.2f}%{rate:>10}{stops:>6}  "
              f"{labels[name]}")
        rows_day.append({"date": day, "variant": name, "signals": count,
                         "total_pct": round(total, 3), "avg_pct": round(avg, 3),
                         "wins": wins, "hard_stops": stops})
    print("=" * 88)
    print("⚠️ 하루 표본으로 후보를 고르지 말 것 — 며칠 쌓은 뒤 판단한다.")

    append_rows(OUT_DAY, rows_day, day)
    print(f"기록: {OUT_DAY}")
    print(f"      {OUT_SIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
