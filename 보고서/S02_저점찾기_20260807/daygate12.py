# -*- coding: utf-8 -*-
"""친구님 질문 검증: "흘러내리는 날인지 아침 몇 분 안에 알 수 있는가". 읽기 전용.

전제가 성립해야 나머지(문턱 조정·매수 지연·손절 완화)가 의미를 갖는다.
전제 = 09:0X 시점의 관측만으로 그날 성적을 예측할 수 있는가.

재는 것 (전부 09:00~기준시각 사이 자료만 쓴다 — 그 뒤는 안 본다)
  A. 시가 대비 등락 중앙값        "지금 시장이 밀리고 있나"
  B. 시가 밑에 있는 종목 비율     "폭이 넓나"
  C. 체결강도 중앙값              "매도가 때리고 있나"
  D. 매수대금 ÷ 매도대금 중앙값   "돈이 어느 쪽인가"
그리고 그날의 실제 성적(12일 재생 승률)과 대본다.

⚠️정직 고지 2가지
  1. 우주가 후행이다 — 이 캐시는 '그날 낙폭 예선을 통과한 종목'이라 09:00 에는 모르는 명단이다.
     상대 비교(날짜끼리)에는 쓸 수 있으나, 실전 게이트로 쓰려면 09:00 에 아는 명단으로 다시 재야 한다.
  2. N=12 일이다. 방향을 보는 데는 쓰지만 문턱을 고르기엔 모자란다(7/31 실사고).
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
CUTS = ("09:05:00", "09:10:00", "09:20:00")

rows = [json.loads(x) for x in
        (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
winrate = {}
for r in rows:
    d = winrate.setdefault(r["date"], [0, 0])
    if r["res"] == 1:
        d[0] += 1
    elif r["res"] == -1:
        d[1] += 1
dates = sorted(winrate)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def early_metrics(date, cut):
    """그날 캐시 전 종목의 09:00~cut 관측만으로 시장 상태를 만든다."""
    chg, below, che, ratio = [], 0, [], []
    n = 0
    for path in CACHE.glob(f"{date}_*.csv"):
        if path.stem.endswith("_am"):
            continue
        first_px = last_px = 0.0
        last_che = 0.0
        b0 = s0 = b1 = s1 = 0.0
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                h = r["ts"][11:19]
                if h < "09:00:00":
                    continue
                if h > cut:
                    break
                px = _f(r["current_price"])
                if px <= 0:
                    continue
                if first_px <= 0:
                    first_px = px
                    b0, s0 = _f(r["buy_money_cum"]), _f(r["sell_money_cum"])
                last_px = px
                last_che = _f(r["che_str"]) or last_che
                b1, s1 = _f(r["buy_money_cum"]), _f(r["sell_money_cum"])
        if first_px <= 0 or last_px <= 0:
            continue
        n += 1
        c = (last_px / first_px - 1) * 100
        chg.append(c)
        below += 1 if c < 0 else 0
        if last_che > 0:
            che.append(last_che)
        db, ds = b1 - b0, s1 - s0
        if ds > 0:
            ratio.append(db / ds)
    if n == 0:
        return None
    return {
        "n": n,
        "등락중앙": statistics.median(chg),
        "시가밑비율": below / n * 100,
        "체결강도중앙": statistics.median(che) if che else float("nan"),
        "매수매도비중앙": statistics.median(ratio) if ratio else float("nan"),
    }


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos + 1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


out = []
P = out.append
for cut in CUTS:
    P("=" * 96)
    P(f"기준시각 {cut} — 그 전 자료만 보고 그날을 맞힐 수 있나")
    P("=" * 96)
    P(f"{'날짜':>10} {'종목':>5} {'등락중앙':>9} {'시가밑%':>8} {'체결강도':>8}"
      f" {'매수/매도':>9} | {'그날 승률':>9}")
    table = []
    for d in dates:
        m = early_metrics(d, cut)
        if m is None:
            continue
        w, l = winrate[d]
        wr = w / (w + l) * 100 if (w + l) else float("nan")
        table.append((d, m, wr))
        P(f"{d:>10} {m['n']:>5} {m['등락중앙']:>+8.2f}% {m['시가밑비율']:>7.1f}%"
          f" {m['체결강도중앙']:>8.1f} {m['매수매도비중앙']:>9.2f} | {wr:>8.1f}%")
    P("")
    P("  순위상관(승률과의 관계 · +1 이면 완전 일치, 0 이면 무관):")
    wrs = [t[2] for t in table]
    for key in ("등락중앙", "시가밑비율", "체결강도중앙", "매수매도비중앙"):
        vals = [t[1][key] for t in table]
        rho = spearman(vals, wrs)
        P(f"    {key:>12}  rho = {rho:+.3f}")
    P("")

text = "\n".join(out)
(HERE / "daygate12_결과.txt").write_text(text, encoding="utf-8")
print(text)
