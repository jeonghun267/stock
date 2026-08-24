# -*- coding: utf-8 -*-
"""매수방법 재생기 v1 — 어떤 전략의 매수 판정을 다른 날/다른 종목에 그대로 돌려본다.

★[2026-08-06 친구님 지시 "재생기를 고정시켜라 · 계약서에 박아라 · 안 꺼지게"]

무엇을 위한 것인가
  "S01 이 산 종목을 S02 방법으로 샀다면?" 같은 반사실 질문에 답한다.
  판정 로직을 **절대 재구현하지 않는다** — 실제 전략 모듈(strategy_02_low_buy_signal_v1)
  을 import 해서 그대로 부른다. 재구현하면 그 순간 재생은 거짓말이 된다.

★★ 이 파일의 존재 이유이자 절대 규칙 ★★
  **재생기는 '원본으로 현실을 재현하는가'를 먼저 통과해야 쓸 수 있다.**
  8/5 매도 재생 때 순차 재생이 원본 코드로도 실제 매도를 재현 못 해 폐기한 전례가 있다.
  그래서 이 파일은 verify() 를 먼저 돌리고, 계약서(config\\replay_contract_v1.json)에
  적힌 '이미 아는 정답'을 재현하지 못하면 **분석을 거부한다**(exit 2).
  잠금 시험 tests\\test_replay_buy_method_v1.py 가 이 성질을 매번 못박는다.

자료
  data\\shadow\\mf_1s_capture\\mf_1s_YYYYMMDD.csv (1초 캡처, 하루 1.5~5GB)
  ⚠️이 CSV 는 BOM 이 붙어 있다 — utf-8-sig 로 열지 않으면 ts 열이 통째로 사라진다
    (8/6 에 실제로 겪었다. 그때 재생은 '틱 0개'로 조용히 아무것도 안 했다).

기준값(중요)
  S02 는 09:30 전엔 **시가**, 이후엔 **장중고점**을 기준으로 낙폭을 잰다
  (strategy_02_low_buy_signal_v1.py 의 MORNING_OPEN_REFERENCE_END).
  둘을 같은 값으로 넣으면 재현이 깨진다 — 반드시 나눠서 준다.

쓰는 법
  python replay_buy_method_v1.py --verify                 # 재현 검증만(계약서 대조)
  python replay_buy_method_v1.py --date 20260806 --codes 319660,033160
  되돌리기: 이 파일 삭제(다른 실전 경로가 import 하지 않는다 — 분석 전용).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, time as _time
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

CAPTURE_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
CACHE_DIR = ROOT / "data" / "replay_cache"
CONTRACT = ROOT / "config" / "replay_contract_v1.json"

COLS = ["ts", "code", "current_price", "cum_vol", "che_str", "ask_tot", "bid_tot",
        "buy_vol_cum", "sell_vol_cum", "buy_money_cum", "sell_money_cum"]

# 그날 진짜 저점을 셀 때의 시작 시각. 장 시작 전 호가는 저점이 아니다.
ENTRY_START_FOR_LOW = _time(9, 0)


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def extract(date: str, codes: set[str]) -> dict[str, list[dict]]:
    """1초 캡처에서 해당 종목만 뽑는다(종목별 캐시). 읽기 전용."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[dict]] = {}
    todo = set()
    for code in codes:
        cache = CACHE_DIR / f"{date}_{code}.csv"
        if cache.exists():
            with cache.open(encoding="utf-8", newline="") as fh:
                out[code] = list(csv.DictReader(fh))
        else:
            todo.add(code)
    if todo:
        src = CAPTURE_DIR / f"mf_1s_{date}.csv"
        if not src.exists():
            raise SystemExit(f"캡처 없음: {src}")
        buf: dict[str, list[dict]] = {c: [] for c in todo}
        # ⚠️utf-8-sig 필수 — BOM 때문에 ts 열이 사라진다(위 주석 참조)
        with src.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                c = row.get("code")
                if c in buf:
                    buf[c].append({k: row.get(k, "") for k in COLS})
        for c, rows in buf.items():
            rows.sort(key=lambda r: r["ts"])
            with (CACHE_DIR / f"{date}_{c}.csv").open("w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=COLS)
                w.writeheader()
                w.writerows(rows)
            out[c] = rows
    for c in out:
        out[c].sort(key=lambda r: r["ts"])
    return out


def replay(code: str, rows: list[dict], *, open_ref: float = 0.0,
           high_ref: float = 0.0, morning_fastpath: bool | None = None,
           min_low_reset_steps: int | None = None) -> list[dict]:
    """S02 매수 판정을 그대로 돌린다. open_ref/high_ref 를 주면 그 값을 기준으로 쓴다
    (엔진이 실제로 쓴 값을 재현할 때). 안 주면 캡처에서 진짜 시가·장중고점을 만든다.

    ★[2026-08-06] morning_fastpath 로 아침 급행을 켜고 끌 수 있다.
      None 이면 모듈 기본값 그대로. 과거를 '재현'할 때는 False 를 줘야 한다 —
      그날 실제로 돈 엔진에는 급행이 없었기 때문이다.

    ★[2026-08-07] min_low_reset_steps 도 같은 이유로 끌 수 있다.
      저점리셋 관문은 8/7 에 생겼으므로 그 전날을 '재현'할 때는 0 을 줘야 한다.
      (급행과 똑같은 문제다 — 나중에 생긴 관문은 과거 재현에서 꺼야 한다.)
    """
    from 저점매수_매도소진 import MarketPoint          # noqa: E402
    import strategy_02_low_buy_signal_v1 as S02       # noqa: E402

    saved_fast = S02.MORNING_FASTPATH
    saved_steps = S02.MIN_LOW_RESET_STEPS
    if morning_fastpath is not None:
        S02.MORNING_FASTPATH = bool(morning_fastpath)
    if min_low_reset_steps is not None:
        S02.MIN_LOW_RESET_STEPS = int(min_low_reset_steps)
    try:
        return _replay_inner(S02, MarketPoint, code, rows, open_ref, high_ref)
    finally:
        S02.MORNING_FASTPATH = saved_fast
        S02.MIN_LOW_RESET_STEPS = saved_steps


def _replay_inner(S02, MarketPoint, code, rows, open_ref, high_ref):
    mon = S02.LowBuySignalMonitor()
    open_px = 0.0
    run_high = 0.0
    fired = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (TypeError, ValueError):
            continue
        price = _f(r["current_price"])
        if price <= 0 or ts.time() < S02.ENTRY_START:
            continue
        if open_px <= 0:
            open_px = price
        run_high = max(run_high, price)
        point = MarketPoint(
            ts=ts, price=price, cum_vol=_f(r["cum_vol"]), che_str=_f(r["che_str"]),
            ask_tot=_f(r["ask_tot"]), bid_tot=_f(r["bid_tot"]),
            buy_money_cum=_f(r["buy_money_cum"]), sell_money_cum=_f(r["sell_money_cum"]),
            buy_vol_cum=_f(r["buy_vol_cum"], -1.0), sell_vol_cum=_f(r["sell_vol_cum"], -1.0),
        )
        row, hit = mon.process_point(
            code, code, point, allow_signal=True,
            # 09:30 전=시가 / 이후=장중고점. 같은 값을 주면 재현이 깨진다.
            open_price=(open_ref or open_px),
            session_high=max(high_ref, run_high),
        )
        if hit:
            fired.append({"time": ts.strftime("%H:%M:%S"), "price": price,
                          "drop_pct": row.get("dip_drop_pct"),
                          "anchor_low": row.get("anchor_low")})
    return fired


def verify(verbose: bool = True) -> bool:
    """계약서의 '이미 아는 정답'을 재현하는지 본다. 실패하면 이 재생기는 못 쓴다."""
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    date = spec["기준일"]
    cases = spec["재현대조"]
    tol = float(spec.get("허용_낙폭오차", 0.01))
    data = extract(date, set(cases))
    ok_all = True
    for code, want in cases.items():
        # ★[2026-08-06] 재현은 '그날 엔진이 실제로 한 것'을 맞추는 일이다.
        #   그날 엔진에는 아침 급행이 없었으므로 반드시 끄고 잰다.
        got = replay(code, data.get(code) or [],
                     open_ref=float(want["엔진시가"]), high_ref=float(want["엔진고점"]),
                     morning_fastpath=False, min_low_reset_steps=0)
        hit = got[0] if got else None
        drop_ok = hit is not None and abs(_f(hit["drop_pct"]) - float(want["낙폭"])) <= tol
        ok_all &= bool(drop_ok)
        if verbose:
            shown = f'{hit["time"]} 낙폭{hit["drop_pct"]}' if hit else "신호 없음"
            print(f"  {code} {want['이름']:<10} 기대 낙폭{want['낙폭']} @{want['시각']}"
                  f" / 재생 {shown}  -> {'OK' if drop_ok else 'FAIL'}")
    if verbose:
        print(f"재현 검증: {'통과' if ok_all else '실패 — 이 재생기는 신뢰할 수 없다'}")
    return bool(ok_all)


S01_LOG = ROOT / "data" / "LOG" / "sched_STRATEGY01_LIVE.log"
REPORT_DIR = ROOT / "보고서"


def s01_trades() -> dict[str, list[tuple[str, str, float]]]:
    """S01 실체결(로그)에서 날짜별 (종목코드, 이름, 실현%) 를 뽑는다."""
    import re
    out: dict[str, list[tuple[str, str, float]]] = {}
    if not S01_LOG.exists():
        return out
    seen = set()
    with S01_LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "SELL_CONFIRMED" not in line:
                continue
            d = re.search(r"(\d{4}-\d\d-\d\d)\s+(\d\d:\d\d:\d\d)", line)
            nm = re.search(r"SELL_CONFIRMED\s+([^\s(]+)\((\d{6})\)", line)
            g = re.search(r"gross=(-?[\d.]+)%", line)
            if not (d and nm and g):
                continue
            key = (d.group(1), d.group(2), nm.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.setdefault(d.group(1).replace("-", ""), []).append(
                (nm.group(2), nm.group(1), float(g.group(1))))
    return out


def s01_buys() -> dict[str, dict[str, tuple[str, float]]]:
    """S01 실체결(로그)에서 날짜별 {종목코드: (매수시각, 매수가)} 를 뽑는다.

    ★[2026-08-06 친구님 지시 "중요한 것은 어느 게 저점을 잘 잡느냐는거야"]
      실현손익은 매도규칙이 섞여 매수 품질을 못 본다. 매수가를 그날 진짜 저점과
      대보는 것만이 '저점을 잘 잡았나'의 답이다.
    """
    import re
    out: dict[str, dict[str, tuple[str, float]]] = {}
    if not S01_LOG.exists():
        return out
    with S01_LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "BUY_CONFIRMED" not in line:
                continue
            d = re.search(r"(\d{4}-\d\d-\d\d)\s+(\d\d:\d\d:\d\d)", line)
            m = re.search(r"BUY_CONFIRMED\s+[^\s(]+\((\d{6})\)\s+x\d+\s+([\d.]+)", line)
            if not (d and m):
                continue
            day = out.setdefault(d.group(1).replace("-", ""), {})
            day.setdefault(m.group(1), (d.group(2), float(m.group(2))))  # 첫 체결만
    return out


def day_low(rows: list[dict]) -> tuple[float, str]:
    """캡처에서 그날의 진짜 저점과 그 시각을 만든다(장 시작 이후만).

    ⚠️추정하지 않는다 — 실제로 체결된 가격의 최소값이다."""
    low, low_ts = 0.0, ""
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (TypeError, ValueError):
            continue
        price = _f(r["current_price"])
        if price <= 0 or ts.time() < ENTRY_START_FOR_LOW:
            continue
        if low <= 0 or price < low:
            low, low_ts = price, ts.strftime("%H:%M:%S")
    return low, low_ts


def above_low(price: float, low: float) -> float | None:
    """저점 대비 몇 % 위에서 샀나. 낮을수록 저점을 잘 잡은 것."""
    if price <= 0 or low <= 0:
        return None
    return (price / low - 1.0) * 100.0


def s01_compare() -> int:
    """S01 이 매매한 모든 날에 S02 매수방법을 씌워 전수 비교하고 보고서를 쓴다.
    ⚠️전수다 — 특정 날만 고르지 않는다(승자편향 금지)."""
    if not verify(verbose=True):
        print("재현 검증 실패 — 분석을 거부한다")
        return 2
    trades = s01_trades()
    lines = ["=" * 78,
             "S01 매수방법 교체 검증 — S01 실제 vs S02 매수방법 (전수)",
             "=" * 78,
             "재현 검증 통과 후 산출. 매도규칙 미적용(진입 이후 흐름은 캡처 실측).",
             ""]
    tot_real = tot_n = 0
    buys = s01_buys()
    pairs: list[tuple[float, float]] = []   # (1번 저점근접도, 2번방법 저점근접도)
    win2 = lose2 = tie = no_signal = 0
    for date in sorted(trades):
        cap = CAPTURE_DIR / f"mf_1s_{date}.csv"
        cache_hit = CACHE_DIR.exists() and any(CACHE_DIR.glob(f"{date}_*.csv"))
        rows = trades[date]
        real = sum(g for _c, _n, g in rows)
        tot_real += real
        tot_n += len(rows)
        lines.append(f"[{date}] S01 실제 {len(rows)}건 실현합 {real:+.2f}%")
        if not cap.exists() and not cache_hit:
            lines.append("   캡처 없음 — 재생 건너뜀")
            lines.append("")
            continue
        codes = {c for c, _n, _g in rows}
        data = extract(date, codes)
        day_buys = buys.get(date, {})
        for code in sorted(codes):
            nm = next((n for c, n, _g in rows if c == code), code)
            crows = data.get(code) or []
            low, low_ts = day_low(crows)
            got = replay(code, crows)
            b1 = day_buys.get(code)
            lines.append(
                f"   {code} {nm:<10} 그날 진짜 저점 {int(low):,} ({low_ts})"
                if low > 0 else f"   {code} {nm:<10} 저점 산출 불가 — 대조 제외")
            a1 = above_low(b1[1], low) if b1 else None
            if b1:
                lines.append(f"      1번 실제   {b1[0]} @{int(b1[1]):,}"
                             + (f"   저점+{a1:.2f}%" if a1 is not None else ""))
            else:
                lines.append("      1번 실제   매수기록 없음")
            a2 = None
            if got:
                g0 = got[0]
                a2 = above_low(_f(g0["price"]), low)
                lines.append(f"      2번 방법   {g0['time']} @{int(_f(g0['price'])):,}"
                             + (f"   저점+{a2:.2f}%" if a2 is not None else "")
                             + f"   (낙폭 {g0['drop_pct']}%)")
            else:
                no_signal += 1
                lines.append("      2번 방법   신호 없음 = 안 삼")
            if b1 and got:
                # ★공정 비교는 '매수가 직접 대조'다. 저점근접도는 하루 전체 저점
                #   기준이라 09:20 에 문 닫는 1번에게 구조적으로 불리하다(참고용).
                p1, p2 = b1[1], _f(got[0]["price"])
                gap = (p2 / p1 - 1.0) * 100.0 if p1 > 0 else 0.0
                pairs.append((a1, a2, gap))
                if gap < -0.005:
                    win2 += 1
                    lines.append(f"      -> 2번이 {abs(gap):.2f}% 싸게 샀다")
                elif gap > 0.005:
                    lose2 += 1
                    lines.append(f"      -> 1번이 {gap:.2f}% 싸게 샀다")
                else:
                    tie += 1
                    lines.append("      -> 같은 값에 샀다")
        lines.append("")
    lines.append("-" * 78)
    lines.append(f"S01 실제 전체: {tot_n}건 실현합 {tot_real:+.2f}%")
    lines.append("")
    lines.append("[어느 게 저점을 잘 잡나] 같은 종목·같은 날의 매수가 직접 대조")
    if pairs:
        gaps = [g for _a1, _a2, g in pairs]
        mg = sum(gaps) / len(gaps)
        lines.append(f"  맞대결 {len(pairs)}건 (두 방법이 둘 다 산 건만 — 공정 비교)")
        verdict = ("2번이 평균 %.2f%% 싸게 샀다" % abs(mg)) if mg < 0 else (
                  ("1번이 평균 %.2f%% 싸게 샀다" % mg) if mg > 0 else "차이 없다")
        lines.append(f"    => {verdict}")
        lines.append(f"    건별: 2번 승 {win2} / 1번 승 {lose2} / 무 {tie}")
        both = [(a1, a2) for a1, a2, _g in pairs if a1 is not None and a2 is not None]
        if both:
            m1 = sum(a for a, _b in both) / len(both)
            m2 = sum(b for _a, b in both) / len(both)
            lines.append(f"  [참고] 하루 전체 저점 대비: 1번 저점+{m1:.2f}% / 2번 저점+{m2:.2f}%")
            lines.append("         ⚠️1번은 09:20 에 문을 닫아 그 뒤 저점은 볼 기회가 없다."
                         " 이 줄로 우열을 가리지 말 것.")
    else:
        lines.append("  맞대결 표본 없음")
    lines.append(f"  2번 방법이 아예 안 산 건: {no_signal}건 (위 맞대결에서 빠짐)")
    lines.append("")
    lines.append("⚠️맞대결은 '둘 다 산' 건만 넣었다. 2번이 안 산 건을 섞으면 승자편향이 된다.")
    lines.append("⚠️S02 방법 쪽은 '언제 얼마에 샀을지'만이다. 매도규칙을 씌워야 손익이 나온다.")
    text = "\n".join(lines)
    print(text)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "S01_매수방법비교_최신.txt"
    out.write_text(text, encoding="utf-8")
    print(f"\n보고서: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="계약서 재현 검증만 한다")
    ap.add_argument("--s01-compare", action="store_true",
                    help="S01 이 매매한 모든 날 전수로 S02 매수방법과 비교하고 보고서를 쓴다")
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--codes", help="쉼표로 구분한 종목코드")
    args = ap.parse_args()

    if args.s01_compare:
        return s01_compare()

    print("=" * 70)
    print("매수방법 재생기 v1 — 먼저 재현 검증부터 한다(통과 못하면 분석 거부)")
    print("=" * 70)
    if not verify():
        return 2
    if args.verify:
        return 0
    if not (args.date and args.codes):
        print("\n--date 와 --codes 를 주면 그 종목을 S02 방법으로 재생한다.")
        return 0
    codes = {c.strip().zfill(6) for c in args.codes.split(",") if c.strip()}
    data = extract(args.date, codes)
    print()
    print(f"[{args.date}] S02 매수방법 재생 (진짜 시가·장중고점 기준)")
    for code in sorted(codes):
        got = replay(code, data.get(code) or [])
        if got:
            for g in got:
                print(f"  {code} 매수 {g['time']} @{int(g['price'])} (낙폭 {g['drop_pct']}%)")
        else:
            print(f"  {code} 신호 없음 = 안 삼")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
