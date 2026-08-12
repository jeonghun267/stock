# -*- coding: utf-8 -*-
"""호가 관문(SIX_STYLE 에서 꺼져 있는 것)을 오늘 28건에 적용하면? 읽기 전용.
근거: Stoikov microprice - 호가 크기 가중가. edge<0 = 다음 체결이 아래로 갈 압력.
      Cont-Kukanov-Stoikov OFI - 호가 큐 불균형이 단기 가격변화를 거의 선형 설명.
"""
import json, pathlib, datetime

sig = json.loads(pathlib.Path(r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json")
                 .read_text(encoding="utf-8-sig"))
d2 = json.loads(pathlib.Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json")
                .read_text(encoding="utf-8-sig"))
snap = json.loads(pathlib.Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
                  .read_text(encoding="utf-8-sig")).get("codes") or {}
sigs = [s for s in (sig.get("signals") or []) if isinstance(s, dict)]


def num(x):
    try:
        return float(str(x).replace(",", "").lstrip("+"))
    except Exception:
        return 0.0


trades = []
for h in (d2.get("history") or []):
    if isinstance(h, dict):
        trades.append((str(h.get("code")).zfill(6), str(h.get("entry_at"))[11:19],
                       num(h.get("gross_return_pct"))))
for k, v in (d2.get("positions") or {}).items():
    if isinstance(v, dict):
        trades.append((str(v.get("code") or k).split(":")[0].zfill(6),
                       str(v.get("entry_at"))[11:19], None))


def match(code, ts):
    for c, t, r in trades:
        if c != code or not t:
            continue
        try:
            a = datetime.datetime.strptime(ts, "%H:%M:%S")
            b = datetime.datetime.strptime(t, "%H:%M:%S")
        except Exception:
            continue
        if 0 <= (b - a).total_seconds() <= 90:
            return r
    return "NOBUY"


print("===== 호가 관문을 오늘 S02 신호 28건에 적용 =====")
print("관문 3개 (코드에 이미 있으나 SIX_STYLE 이라 건너뜀):")
print("  ① spread_bps <= 30        호가 벌어짐")
print("  ② microprice_edge >= 0    호가 압력이 위쪽인가  <- Stoikov microprice")
print("  ③ best_bid_share 우세      최우선매수 잔량 비중\n")
print(f"{'종목':>7} {'시각':>9} {'스프레드':>8} {'마이크로엣지':>11} {'매수1호가비중':>12} "
      f"{'①':>3}{'②':>3}{'③':>3} {'신호후저가':>10}  {'실현'}")
print("-" * 96)

rows = []
for s in sigs:
    code = str(s.get("code")).zfill(6)
    ts = str(s.get("ts"))[11:19]
    sp = num(s.get("spread_bps"))
    eg = num(s.get("microprice_edge_bps"))
    bs = num(s.get("best_bid_share"))
    px = num(s.get("price"))
    lo = num((snap.get(code) or {}).get("lo"))
    deeper = (lo / px - 1) * 100 if (lo and px) else None
    g1, g2, g3 = sp <= 30, eg >= 0, bs >= 0.5
    r = match(code, ts)
    rows.append(dict(code=code, sp=sp, eg=eg, bs=bs, g1=g1, g2=g2, g3=g3,
                     r=r, deeper=deeper))
    real = "안 삼" if r == "NOBUY" else ("보유" if r is None else f"{r:+.2f}%")
    print(f"{code:>7} {ts:>9} {sp:>8.1f} {eg:>11.2f} {bs:>12.3f} "
          f"{'O' if g1 else 'X':>3}{'O' if g2 else 'X':>3}{'O' if g3 else 'X':>3} "
          f"{(f'{deeper:+9.2f}%' if deeper is not None else '-'):>10}  {real}")


def summ(sel, label):
    got = [x['r'] for x in sel if x['r'] != "NOBUY" and x['r'] is not None]
    dp = [x['deeper'] for x in sel if x['deeper'] is not None]
    line = f"  {label:<26} 신호 {len(sel):>2}건"
    if got:
        q = sorted(got)
        line += (f" · 청산 {len(got)}건 합계 {sum(got):+6.2f}% "
                 f"중앙 {q[len(q)//2]:+6.2f}% 플러스 {sum(1 for x in got if x>0)}건")
    else:
        line += " · 청산 0건"
    if dp:
        line += f" · 신호후저가 중앙 {sorted(dp)[len(dp)//2]:+.2f}%"
    return line


print("\n===== 관문별 효과 =====")
print(summ(rows, "전체(현행 = 관문 없음)"))
for key, lab in (('g1', '① 스프레드만'), ('g2', '② 마이크로엣지만'),
                 ('g3', '③ 최우선매수비중만')):
    print(summ([x for x in rows if x[key]], f"{lab} 통과"))
    print(summ([x for x in rows if not x[key]], f"{lab} 탈락"))
allg = [x for x in rows if x['g1'] and x['g2']]
print(summ(allg, "①+② 둘 다 통과"))
print(summ([x for x in rows if not (x['g1'] and x['g2'])], "①+② 하나라도 탈락"))

print("\n===== 마이크로엣지 구간별 (Stoikov: 양수면 다음 체결이 위) =====")
for lo, hi, lab in ((-99, -5, "-5 미만 (매도벽 두꺼움)"), (-5, 0, "-5 ~ 0"),
                    (0, 5, "0 ~ +5"), (5, 99, "+5 이상 (매수벽 두꺼움)")):
    sel = [x for x in rows if lo <= x['eg'] < hi]
    if sel:
        print(summ(sel, lab))
