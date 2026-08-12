# -*- coding: utf-8 -*-
"""12거래일(7/23~8/7) 다일 재생 검증 — 읽기 전용.

검증하는 것 (8/6·8/7 이틀에서 발견한 것들이 12일 전체에서도 성립하는가)
  ① 반등 꼭지 높이: 가짜 반등(밑 먼저)은 저점에서 몇 %까지 갔다 떨어지나 vs 진짜(위 먼저)
  ② 흡수: 저점→신호 사이 매수÷매도 대금(dip_buy_sell_ratio, 엔진이 직접 기록)이 승패를 가르나
  ③ 문턱+손절 조합: 저점+X% 도달을 기다렸다 살 때, 손절을 -2%로 두는 것 vs 저점에 묶는 것

원칙
  · 판정 재구현 없음 — 실제 S02 모듈 process_point() 에 틱을 먹인다 (cmp807.py 방식 그대로)
  · 분석 전 재생기 계약서 검증(★절대 규칙) — 실패하면 exit 2
  · 관문은 0 (월요일 실전과 동일 = 철회 상태) · 나머지 모듈 설정은 현재 실전 기본값 그대로
  · 재생 우주 = 그날 1초 캡처에 있는 종목 중 낙폭 예선 통과(시가 -2.7% 또는 고점 -4.7%,
    실전 문턱 3%/5%보다 느슨하게 잡아 누락 방지) — 실전 후보선별(돈맥·고저폭)은 안 거치므로
    실전보다 신호가 많다. 절대 승률이 아니라 '가르는 선'이 목적이다.
"""
import csv
import json
import pathlib
import statistics
import sys
import time
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
import replay_buy_method_v1 as RB                  # noqa: E402
import strategy_02_low_buy_signal_v1 as S02        # noqa: E402
from 저점매수_매도소진 import MarketPoint            # noqa: E402

S02.MIN_LOW_RESET_STEPS = 0        # 월요일 실전과 동일(관문 철회)

HERE = pathlib.Path(__file__).parent
CAP = pathlib.Path(r"C:\stock_bot\data\shadow\mf_1s_capture")
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
DATES = ["20260723", "20260724", "20260727", "20260728", "20260729", "20260730",
         "20260731", "20260803", "20260804", "20260805", "20260806", "20260807"]
UP, DOWN = 1.0, -2.0
LINES = (2.0, 2.2, 2.4, 2.6, 2.8, 3.0)
COMBO_X = (2.0, 2.4, 2.5)


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def day_candidates(date):
    """1차 훑기: 낙폭 예선. (시가 9천원 미만 제외 — 실전 최소가 1만원)"""
    src = CAP / f"mf_1s_{date}.csv"
    st = {}
    with src.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        header = fh.readline().lstrip("\ufeff").rstrip("\r\n").split(",")
        idx = {n: i for i, n in enumerate(header)}
        missing = [c for c in RB.COLS if c not in idx]
        if missing:
            return None, missing
        i_ts, i_code, i_px = idx["ts"], idx["code"], idx["current_price"]
        nmax = max(i_ts, i_code, i_px) + 1
        for line in fh:
            p = line.split(",", nmax)
            if len(p) <= i_px:
                continue
            ts = p[i_ts]
            if len(ts) < 19 or ts[11:19] < "09:00:00":
                continue
            try:
                px = float(p[i_px])
            except ValueError:
                continue
            if px <= 0:
                continue
            c = p[i_code]
            s = st.get(c)
            if s is None:
                st[c] = [px, px, 0.0, 0.0]      # 시가, 진행고점, 고점대비최저%, 시가대비최저%
            else:
                if px > s[1]:
                    s[1] = px
                dd = (px / s[1] - 1) * 100
                if dd < s[2]:
                    s[2] = dd
                fo = (px / s[0] - 1) * 100
                if fo < s[3]:
                    s[3] = fo
    cands = {c for c, s in st.items()
             if s[0] >= 9000 and (s[3] <= -2.7 or s[2] <= -4.7)}
    return cands, None


def fast_extract(date, codes):
    """2차 훑기: 캐시 없는 종목만 뽑아 재생기와 같은 형식(RB.COLS)으로 저장."""
    todo = {c for c in codes if not (CACHE / f"{date}_{c}.csv").exists()}
    if not todo:
        return 0
    src = CAP / f"mf_1s_{date}.csv"
    buf = {c: [] for c in todo}
    with src.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        header = fh.readline().lstrip("\ufeff").rstrip("\r\n").split(",")
        idx = {n: i for i, n in enumerate(header)}
        sel = [idx[c] for c in RB.COLS]
        i_code = idx["code"]
        for line in fh:
            p3 = line.split(",", 2)
            if len(p3) < 3 or p3[1] not in buf:
                continue
            p = line.rstrip("\r\n").split(",")
            try:
                buf[p3[1]].append([p[i] for i in sel])
            except IndexError:
                continue
    for c, rows in buf.items():
        rows.sort(key=lambda r: r[0])
        with (CACHE / f"{date}_{c}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(RB.COLS)
            w.writerows(rows)
    return len(todo)


def drive(code, rows):
    """cmp807.py 의 운전대 그대로 — 실제 판정 모듈에 틱을 순서대로 먹인다."""
    mon = S02.LowBuySignalMonitor()
    open_px = 0.0
    run_high = 0.0
    last_ask = last_bid = 0.0
    out = []
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
        # 호가 잔량이 빈 틱은 실전 스냅샷처럼 마지막 값을 이월. 한 번도 없었으면 건너뜀
        # (합이 0이면 모듈 내부 불균형 계산이 0으로 나눈다 — 실전엔 없는 틱)
        ask, bid = _f(r["ask_tot"]), _f(r["bid_tot"])
        if ask + bid <= 0:
            ask, bid = last_ask, last_bid
            if ask + bid <= 0:
                continue
        last_ask, last_bid = ask, bid
        point = MarketPoint(
            ts=ts, price=price, cum_vol=_f(r["cum_vol"]), che_str=_f(r["che_str"]),
            ask_tot=ask, bid_tot=bid,
            buy_money_cum=_f(r["buy_money_cum"]), sell_money_cum=_f(r["sell_money_cum"]),
            buy_vol_cum=_f(r["buy_vol_cum"], -1.0), sell_vol_cum=_f(r["sell_vol_cum"], -1.0),
        )
        row, hit = mon.process_point(code, code, point, allow_signal=True,
                                     open_price=open_px, session_high=run_high)
        if hit:
            row = dict(row)
            row["_t"] = ts.strftime("%H:%M:%S")
            out.append(row)
    return out


def episode_cross(tk, low_i, low, lvl):
    """저점이 안 깨진 동안 lvl 에 처음 닿은 틱 번호. 먼저 깨지면 None."""
    for i in range(low_i, len(tk)):
        q = tk[i][1]
        if q < low:
            return None
        if q >= lvl:
            return i
    return None


def score_fire(tk, fire):
    """신호 1건 채점. tk = [(시각, 가격)]"""
    price = _f(fire.get("price"))
    low = _f(fire.get("anchor_low"))
    low_t = str(fire.get("anchor_low_ts"))[11:19]
    t_sig = fire["_t"]
    if price <= 0 or low <= 0:
        return None
    low_i = next((i for i, (h, _) in enumerate(tk) if h >= low_t), None)
    sig_i = next((i for i, (h, _) in enumerate(tk) if h >= t_sig), None)
    if low_i is None or sig_i is None:
        return None
    res, stop_i = 0, None
    for i in range(sig_i, len(tk)):
        r = (tk[i][1] / price - 1) * 100
        if r <= DOWN:
            res, stop_i = -1, i
            break
        if r >= UP:
            res, stop_i = 1, i
            break
    span_end = stop_i if (res == -1 and stop_i is not None) else len(tk) - 1
    peak = (max(q for _, q in tk[low_i:span_end + 1]) / low - 1) * 100
    deeper = None
    if res == -1 and stop_i is not None:
        deeper = (min(q for _, q in tk[stop_i:]) / low - 1) * 100

    combos = {}
    for x in COMBO_X:
        ci = episode_cross(tk, low_i, low, low * (1 + x / 100))
        if ci is None:
            combos[x] = None            # 그 높이까지 못 오고 저점이 깨짐(또는 미도달)
            continue
        entry = tk[ci][1]
        ra = rb = 0
        for i in range(ci, len(tk)):
            q = tk[i][1]
            if ra == 0:
                rr = (q / entry - 1) * 100
                if rr <= DOWN:
                    ra = -1
                elif rr >= UP:
                    ra = 1
            if rb == 0:
                if q < low:
                    rb = -1
                elif q >= entry * (1 + UP / 100):
                    rb = 1
            if ra and rb:
                break
        combos[x] = {"entry": entry, "stop2": ra, "stoplow": rb,
                     "loss_low": (low / entry - 1) * 100}
    return dict(res=res, peak=peak, deeper=deeper, combos=combos,
                entry_gap=(price / low - 1) * 100,
                absorb=_f(fire.get("dip_buy_sell_ratio")),
                steps=int(_f(fire.get("dip_low_reset_steps"))),
                drop=_f(fire.get("dip_drop_pct")))


def main():
    global DATES
    if sys.argv[1:]:
        DATES = sys.argv[1:]
    t0 = time.time()
    print("[0] 재생기 계약서 검증 (실패 시 전체 중단)", flush=True)
    if not RB.verify(verbose=True):
        sys.exit(2)

    all_fires = []
    day_lines = []
    n_cheap = n_late = n_nodata = n_err = 0
    jsonl = (HERE / "multi12_fires.jsonl").open("w", encoding="utf-8")

    for date in DATES:
        td = time.time()
        cands, missing = day_candidates(date)
        if cands is None:
            print(f"[{date}] 열 형식 불일치 {missing} — 건너뜀", flush=True)
            continue
        new = fast_extract(date, cands)
        fires_day = 0
        scored_day = []
        for code in sorted(cands):
            p = CACHE / f"{date}_{code}.csv"
            if not p.exists():
                continue
            with p.open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            if len(rows) < 1000:
                n_nodata += 1
                continue
            try:
                fires = drive(code, rows)
            except Exception as e:                          # 한 종목 오류가 전체를 죽이지 않게
                print(f"  [재생오류] {date} {code}: {type(e).__name__} {e}", flush=True)
                n_err += 1
                continue
            if not fires:
                continue
            tk = []
            for r in rows:
                h = r["ts"][11:19]
                if h < "09:00:00":
                    continue
                px = _f(r["current_price"])
                if px > 0:
                    tk.append((h, px))
            for fire in fires:
                fires_day += 1
                if _f(fire.get("price")) < 10000:
                    n_cheap += 1
                    continue
                if fire["_t"] > "14:20:00":
                    n_late += 1
                    continue
                sc = score_fire(tk, fire)
                if sc is None:
                    n_nodata += 1
                    continue
                sc.update(date=date, code=code, t=fire["_t"])
                scored_day.append(sc)
                all_fires.append(sc)
                jsonl.write(json.dumps(sc, ensure_ascii=False) + "\n")
        jsonl.flush()
        W = [s for s in scored_day if s["res"] == 1]
        L = [s for s in scored_day if s["res"] == -1]
        lmax = max((s["peak"] for s in L), default=float("nan"))
        wmin = min((s["peak"] for s in W), default=float("nan"))
        line = (f"[{date}] 후보 {len(cands):>3} (새추출 {new:>3}) · 원신호 {fires_day:>3}"
                f" · 채점 {len(scored_day):>3} = 승 {len(W):>2} 패 {len(L):>2}"
                f" 애매 {len(scored_day)-len(W)-len(L):>2}"
                f" · 패자꼭지최대 {lmax:+.2f}% · 승자꼭지최소 {wmin:+.2f}%"
                f" · {time.time()-td:.0f}초")
        day_lines.append(line)
        print(line, flush=True)
    jsonl.close()

    # ---- 집계 ----
    out = []
    P = out.append
    W = [s for s in all_fires if s["res"] == 1]
    L = [s for s in all_fires if s["res"] == -1]
    M = [s for s in all_fires if s["res"] == 0]
    P("=" * 100)
    P("12일 다일 재생 검증 — 집계")
    P("=" * 100)
    P(f"채점 신호 {len(all_fires)}건 = 승 {len(W)} · 패 {len(L)} · 애매 {len(M)}"
      f"   (제외: 1만원 미만 {n_cheap} · 14:20 이후 {n_late} · 자료부족 {n_nodata}"
      f" · 재생오류 종목 {n_err})")
    P("")
    P("① 반등 꼭지 높이 (저점 대비, 패자는 손절 닿기 전까지)")
    for name, G in (("패자", L), ("승자", W)):
        v = sorted(s["peak"] for s in G)
        if not v:
            continue
        P(f"  {name} {len(v):>3}건: 최소 {v[0]:+.2f}% · 중앙 {statistics.median(v):+.2f}%"
          f" · 90분위 {v[int(len(v)*0.9)]:+.2f}% · 최대 {v[-1]:+.2f}%")
    dv = [s["deeper"] for s in L if s["deeper"] is not None]
    if dv:
        P(f"  패자의 손절 후 옛 저점 밑 추가하락: 중앙 {statistics.median(dv):+.2f}%p"
          f" · 옛 저점 밑을 다시 본 비율 {sum(1 for x in dv if x < 0)}/{len(dv)}")
    P("")
    P("  가르는 선 후보별 성적 (선 미만이면 '가짜로 보고 거른다'고 가정할 때)")
    P(f"  {'선':>6} {'가짜 중 걸러짐':>14} {'진짜 중 잘못 걸러짐':>18}")
    for ln in LINES:
        fl = sum(1 for s in L if s["peak"] < ln)
        fw = sum(1 for s in W if s["peak"] < ln)
        P(f"  {ln:>5.1f}% {fl:>7}/{len(L):<6} {fw:>9}/{len(W):<8}")
    P("")
    P("② 흡수 (엔진 기록 dip_buy_sell_ratio = 저점→신호 매수÷매도 대금)")
    for name, G in (("패자", L), ("승자", W)):
        v = sorted(s["absorb"] for s in G if s["absorb"] > 0)
        if v:
            P(f"  {name} {len(v):>3}건: 4분위 {v[int(len(v)*0.25)]:.2f}"
              f" / 중앙 {statistics.median(v):.2f} / {v[int(len(v)*0.75)]:.2f}")
    P("  흡수비 구간별 승률(애매 제외):")
    for lo, hi in ((0, 0.9), (0.9, 1.0), (1.0, 1.1), (1.1, 1.3), (1.3, 99)):
        g = [s for s in W + L if lo <= s["absorb"] < hi]
        w = sum(1 for s in g if s["res"] == 1)
        if g:
            P(f"    [{lo:>4.1f}~{hi:<4.1f}) {len(g):>4}건 · 승률 {w/len(g)*100:5.1f}%")
    P("")
    P("③ 문턱+손절 조합 (같은 반등 안에서 저점+X% 도달 시 매수)")
    P(f"  {'문턱':>6} {'손절방식':>12} {'매수':>5} {'승':>4} {'패':>4} {'애매':>4}"
      f" {'승률':>7} {'건당기대%':>9}")
    for x in COMBO_X:
        for style, key in (("-2%고정", "stop2"), ("저점깨짐", "stoplow")):
            win = lose = tie = 0
            pnl = []
            for s in all_fires:
                c = s["combos"].get(x) or s["combos"].get(str(x))
                if c is None:
                    continue
                r = c[key]
                if r == 1:
                    win += 1
                    pnl.append(UP)
                elif r == -1:
                    lose += 1
                    pnl.append(DOWN if key == "stop2" else c["loss_low"])
                else:
                    tie += 1
            n = win + lose
            wr = win / n * 100 if n else float("nan")
            ev = statistics.mean(pnl) if pnl else float("nan")
            P(f"  {x:>5.1f}% {style:>12} {win+lose+tie:>5} {win:>4} {lose:>4} {tie:>4}"
              f" {wr:>6.1f}% {ev:>+8.3f}")
    P(f"  (기준: 현행 그대로 = 승률 {len(W)/(len(W)+len(L))*100:.1f}%"
      f" · 건당기대 {statistics.mean([UP]*len(W)+[DOWN]*len(L)):+.3f}%)")
    P("")
    P("④ 저점 리셋 횟수 (참고 — 철회된 축)")
    for name, G in (("패자", L), ("승자", W)):
        v = sorted(s["steps"] for s in G)
        if v:
            P(f"  {name}: 중앙 {statistics.median(v):.0f}회 · 4미만 비율"
              f" {sum(1 for x in v if x < 4)}/{len(v)}")
    P("")
    P("일별:")
    out.extend(day_lines)
    P(f"\n총 소요 {(time.time()-t0)/60:.1f}분")

    text = "\n".join(str(x) for x in out)
    (HERE / "multi12_결과.txt").write_text(text, encoding="utf-8")
    print("\n" + text, flush=True)


if __name__ == "__main__":
    main()
