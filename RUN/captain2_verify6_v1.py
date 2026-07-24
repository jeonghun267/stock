# -*- coding: utf-8 -*-
"""캡틴2 배선 6종 장중 실측 검증 (2026-07-23 친구님 지시 — 7/24 장 마감 후 실행).
읽기전용·TR 0·엔진 무수정. 섹션0(재기동) + 1~6 기능 + 7 결과표.
판정: PASS / FAIL / 미발생 / 검증불가. 미발생=장중 조건 미도래(오류 아님).
출력: 바탕화면\캡틴2_검증6종_YYYYMMDD.txt"""
import os, csv, io, json, subprocess, hashlib
from datetime import datetime
from collections import defaultdict, OrderedDict

BASE = r"C:\stock_bot"
TODAY = datetime.now().strftime("%Y%m%d")
EVT = os.path.join(BASE, "data", "shadow", f"captain2_events_{TODAY}.csv")
LOG = os.path.join(BASE, "LOG", "captain2_moneyflow.log")
FILLS = os.path.join(BASE, "LOG", f"fills_{TODAY}.csv")
CAP = os.path.join(BASE, "data", "shadow", "mf_1s_capture", f"mf_1s_{TODAY}.csv")
SNAP = os.path.join(BASE, "IPC", "live_micro_snapshot.json")
OUT = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\UserK"), "Desktop",
                   f"캡틴2_검증6종_{TODAY}.txt")
L = []
def w(s=""): L.append(s)


def read_events():
    rows = []
    try:
        with io.open(EVT, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); hdr = next(rd)
            for r in rd:
                if len(r) >= 25:
                    rows.append({"ts": r[0], "code": r[1], "name": r[2], "event": r[3],
                                 "price": r[5], "reason": r[24]})
    except Exception:
        pass
    return rows


def read_log():
    try:
        txt = io.open(LOG, encoding="utf-8", errors="replace").read()
    except Exception:
        return []
    d = f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}"
    return [ln for ln in txt.splitlines() if d in ln]


def read_fills():
    out = []
    try:
        with io.open(FILLS, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("state") == "체결":
                    out.append(r)
    except Exception:
        pass
    return out


def sec_of(ts):
    return int(ts[11:13]) * 3600 + int(ts[14:16]) * 60 + int(ts[17:19])


def load_capture(codes):
    S = defaultdict(list)
    if not codes:
        return S
    try:
        with io.open(CAP, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); hdr = next(rd)
            ix = [hdr.index(k) for k in ("ts", "code", "current_price", "cum_vol",
                  "money_speed_5s", "buy_money_cum", "sell_money_cum")]
            for r in rd:
                c = r[ix[1]]
                if c not in codes:
                    continue
                try:
                    s = sec_of(r[ix[0]]); px = float(r[ix[2]] or 0)
                except Exception:
                    continue
                if px > 0:
                    S[c].append((s, px, float(r[ix[3]] or 0), float(r[ix[4]] or 0),
                                 float(r[ix[5]] or 0), float(r[ix[6]] or 0)))
    except Exception:
        pass
    for c in S:
        S[c] = sorted(set(S[c]))
    return S


def mfemae(S, c, bs, bpx, h):
    w_ = [x[1] for x in S.get(c, []) if bs < x[0] <= bs + h]
    if not w_:
        return None, None
    return (max(w_) / bpx - 1) * 100, (min(w_) / bpx - 1) * 100


def vwap_at(S, c, s):
    row = None
    for x in S.get(c, []):
        if x[0] <= s:
            row = x
        else:
            break
    if not row or row[2] <= 0:
        return 0.0
    v = (row[4] + row[5]) / row[2]
    return v if row[1] * 0.5 <= v <= row[1] * 2.0 else 0.0


def main():
    ev = read_events()
    log = read_log()
    fills = read_fills()
    ev_name = [e["event"] for e in ev]
    # ★캡틴2 전용 스코핑 — fills는 전 엔진(골짜기 포함) 혼재. 캡틴2 이벤트(BUY/SELL)만 사용해야
    #   VWAP관문·재진입가드(캡틴2 전용) 오판정을 막는다. 이벤트 price=실체결가.
    buys = [(sec_of(e["ts"]), e["code"], 1, float(e["price"] or 0))
            for e in ev if e["event"] == "BUY"]
    sells = [(sec_of(e["ts"]), e["code"], float(e["price"] or 0))
             for e in ev if e["event"] == "SELL"]
    traded = {b[1] for b in buys} | {s[1] for s in sells}
    S = load_capture(traded)
    verdicts = OrderedDict()

    w(f"══ 캡틴2 배선 6종 장중 실측 검증  {datetime.now():%Y-%m-%d %H:%M:%S} ══")
    w("  판정: PASS / FAIL / 미발생(조건 미도래) / 검증불가(데이터 없음)")
    w(f"  오늘 캡틴2 체결: 매수 {len(buys)} · 매도 {len(sells)} · 종목 {len(traded)}")

    # ── 0. 재기동 사전점검 ──
    w("\n[0] 재기동 사전점검")
    starts = [ln for ln in log if "CAPTAIN2 시작" in ln]
    w(f"  기동 로그(CAPTAIN2 시작): {len(starts)}회" + (f" — {starts[0][:19]}" if starts else ""))
    recov = [ln for ln in log if "재시작 복구" in ln]
    w(f"  상태복구: {'있음 — ' + recov[0].split('재시작')[1][:40] if recov else '복구대상 없음(정상 첫기동)'}")
    save_err = sum(1 for ln in log if "PermissionError" in ln or "저장" in ln and "실패" in ln)
    w(f"  captain2_state 저장오류: {save_err}건" + ("  ⚠️점검대상" if save_err else " ✓"))
    lock = os.path.join(BASE, "data", "captain2.lock")
    pid = ""
    try:
        pid = io.open(lock).read().strip()
    except Exception:
        pass
    w(f"  락 PID: {pid or '없음'}")
    blk = os.path.exists(os.path.join(BASE, "config", "manual_buy_block.flag"))
    w(f"  manual_buy_block: {'존재(매수차단)' if blk else '없음(매수허용)'}")
    try:
        snap = json.load(io.open(SNAP, encoding="utf-8"))
        smp = next(iter((snap.get("codes") or {}).values()), {})
        fid = float(smp.get("buy_money_cum", -1)) >= 0
    except Exception:
        fid = False
    w(f"  FID15 exact 수신: {'✓' if fid else '✗'}")
    try:
        ss = json.load(io.open(os.path.join(BASE, "data", "shared_slots.json"), encoding="utf-8"))
        w(f"  shared_slots: {len(ss.get('slots', {}))}점유 / 최대6")
    except Exception:
        w("  shared_slots: 읽기실패")
    # 중복매수(동시보유 중 재매수) + 1주 확인
    # ★2026-07-23 버그수정(친구님 지시): 매도를 차감하지 않아 '팔고 재매수'(정상 로테이션)가
    #   전부 중복으로 집계되던 허수 제거 — 매수·매도를 시간순으로 합쳐 포지션 증감.
    #   동시각이면 매도 먼저 처리(허수 방지).
    pos = defaultdict(int); dup = 0; qty_bad = 0
    flow = [(s, 1, c, q) for s, c, q, px in buys] + [(s, 0, c, 1) for s, c, px in sells]
    for s, kind, c, q in sorted(flow):
        if kind == 1:                       # BUY
            if q != 1:
                qty_bad += 1
            if pos[c] > 0:
                dup += 1
            pos[c] += q
        else:                               # SELL
            pos[c] = max(0, pos[c] - q)
    w(f"  중복매수(동시보유중 재매수): {dup}건 · 매수 1주아님: {qty_bad}건")

    # ── 1. EARLY ──
    w("\n[1] EARLY 초입 레인")
    early = [e for e in ev if e["event"] == "EARLY_ONSET"]
    if early:
        for e in early:
            c = e["code"]; bs = sec_of(e["ts"]); bpx = float(e["price"] or 0)
            m30 = mfemae(S, c, bs, bpx, 30); m60 = mfemae(S, c, bs, bpx, 60); m300 = mfemae(S, c, bs, bpx, 300)
            op = next((x[1] for x in S.get(c, []) if x[0] >= 9 * 3600), bpx)
            def fm(m): return f"{m[0]:+.2f}/{m[1]:+.2f}%" if m[0] is not None else "-"
            w(f"  {e['ts'][11:19]} {e['name']}({c}) @{bpx:,.0f} 시가+{(bpx/op-1)*100:+.2f}% "
              f"[{e['reason']}] MFE/MAE 30s {fm(m30)} 1분 {fm(m60)} 5분 {fm(m300)}")
        verdicts["EARLY"] = ("PASS", len(early), "발화 실측 — 상세 위")
    else:
        verdicts["EARLY"] = ("미발생", 0, "09:00~09:10 발화 0건(조건 미충족 또는 후보 없음)")
        w("  발화 0건 — 미발생")

    # ── 2. VWAP 관문 ──
    w("\n[2] VWAP 진입 관문")
    gate = [e for e in ev if "VWAP_GATE" in e["reason"]]
    w(f"  VWAP_GATE 차단: {len(gate)}건")
    below = 0; glitch = 0
    for bs, c, q, bpx in sorted(buys):
        vw = vwap_at(S, c, bs)
        if vw <= 0:
            glitch += 1
            tag = "무효(글리치/FID15부재)"
        elif bpx > vw:
            tag = "위 ✓"
        else:
            below += 1
            tag = "★아래 FAIL"
        w(f"  {datetime.utcfromtimestamp(0).replace(hour=bs//3600,minute=bs%3600//60,second=bs%60):%H:%M:%S} "
          f"{c} 매수 {bpx:,.0f} vs VWAP {vw:,.0f} → {tag}")
    if below > 0:
        verdicts["VWAP"] = ("FAIL", len(gate), f"VWAP 아래 매수 {below}건")
    elif buys:
        verdicts["VWAP"] = ("PASS", len(gate), f"전 매수 VWAP 위(무효 {glitch}건)")
    else:
        verdicts["VWAP"] = ("미발생", len(gate), "매수 0건")

    # ── 3. 트레일 돈 가드 ──
    w("\n[3] 트레일 돈 가드")
    th = [e for e in ev if e["event"] == "TRAIL_HOLD_MONEY"]
    if th:
        for e in th:
            w(f"  {e['ts'][11:19]} {e['name']}({e['code']}) {e['reason']}")
        verdicts["TRAIL가드"] = ("PASS", len(th), "유예 발동 실측")
    else:
        verdicts["TRAIL가드"] = ("미발생", 0, "트레일 유예 조건(매수비90%+속도유지) 미도래")
        w("  TRAIL_HOLD_MONEY 0건 — 미발생")

    # ── 4. 매도 점수 엔진 ──
    w("\n[4] 돈 중심 매도 점수 엔진")
    sc = {k: [e for e in ev if e["event"] == k] for k in
          ("SCORE_WATCH", "SCORE_WARNING", "SCORE_SELL_READY", "SCORE_HOLD_MONEY")}
    score_sells = [ln for ln in log if "SCORE_SELL" in ln and "INFO SELL " in ln]
    w("  상태전이 건수: " + " ".join(f"{k}={len(v)}" for k, v in sc.items()))
    for ln in score_sells:
        w(f"  {ln[ln.find('INFO SELL')+5:].strip()[:90]}")
    hard = [ln for ln in log if "HARD_STOP" in ln and "INFO SELL " in ln]
    w(f"  HARD_STOP 매도: {len(hard)}건" + ("  ✓목표(0~1)" if len(hard) <= 1 else "  ⚠️목표초과"))
    # 일반손실 -1% 안쪽?
    small = sum(1 for ln in score_sells if _pnl(ln) is not None and -1.0 <= _pnl(ln) < 0)
    if score_sells or sc["SCORE_WATCH"]:
        verdicts["SCORE매도"] = ("PASS", len(score_sells), f"SCORE매도 {len(score_sells)}·HARD {len(hard)}")
    else:
        verdicts["SCORE매도"] = ("미발생", 0, "보유 발생 전이거나 전이 미도래")

    # ── 5. VI 대응 ──
    w("\n[5] VI 거부 대응")
    vi = {k: [e for e in ev if e["event"] == k] for k in
          ("VI_SUSPECT", "VI_RELEASE", "SELL_VI_HOLD", "SELL_RETRY_EXHAUSTED")}
    if sum(len(v) for v in vi.values()):
        for k, v in vi.items():
            for e in v:
                w(f"  {e['ts'][11:19]} {k} {e['name']}({e['code']}) {e['reason']}")
        verdicts["VI대응"] = ("PASS", sum(len(v) for v in vi.values()), "VI 이벤트 실측")
    else:
        verdicts["VI대응"] = ("미발생", 0, "오늘 VI 미발생(정상)")
        w("  VI 미발생")

    # ── 6. 재진입 가드 ──
    w("\n[6] 재진입 가드")
    rw = [e for e in ev if "REENTRY_WEAK" in e["reason"]]
    # 종목별 매수 2회 이상 = 재진입 시도
    bycode = defaultdict(list)
    for bs, c, q, bpx in sorted(buys):
        bycode[c].append(bs)
    repeated = {c: v for c, v in bycode.items() if len(v) > 1}
    w(f"  재진입 차단 로그(REENTRY_WEAK): {len(rw)}건")
    for e in rw:
        w(f"    {e['ts'][11:19]} {e['name']}({e['code']}) {e['reason']}")
    w(f"  실제 재매수 성사 종목(2회+): {list(repeated.keys()) if repeated else '없음'}")
    if rw:
        verdicts["재진입가드"] = ("PASS", len(rw), f"차단 {len(rw)}건")
    elif repeated:
        verdicts["재진입가드"] = ("FAIL", 0, f"재매수 성사됐는데 차단로그 없음: {list(repeated)}")
    else:
        verdicts["재진입가드"] = ("미발생", 0, "재진입 시도 자체가 없음")

    # ── 7. 결과표 ──
    w("\n" + "=" * 50)
    w("[7] 공통 결과표")
    w(f"{'기능':<12}{'판정':<8}{'발동':<6}비고")
    for k, (v, n, note) in verdicts.items():
        w(f"{k:<12}{v:<8}{n:<6}{note}")
    n_fail = sum(1 for v in verdicts.values() if v[0] == "FAIL")
    w(f"\n요약: FAIL {n_fail}건. FAIL은 원인·로그위치만 보고(장중 수정 금지).")
    w("로그 위치: 이벤트=data/shadow/captain2_events_%s.csv · 엔진로그=LOG/captain2_moneyflow.log" % TODAY)

    io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


def _pnl(ln):
    try:
        seg = ln.rsplit("|", 1)[-1].strip()
        return float(seg.replace("%", ""))
    except Exception:
        return None


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        io.open(OUT, "w", encoding="utf-8").write(f"검증 스크립트 오류: {type(e).__name__}: {e}")
        raise
