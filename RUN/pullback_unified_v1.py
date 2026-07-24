# -*- coding: utf-8 -*-
"""[눌림 통합엔진 「눌림사냥꾼 PULLBACK HUNTER」 v1 — 친구님 2026-07-04 "제대로 된 눌림·수익 극대화"] 눌림 다수 → 1개.
바닥·돌파사냥꾼의 3형제. 문제: 작은 눌림마다 수없이 발동 → 선별로 '진짜 눌림목'만.

★진입(전부 만족 = 선별):
  ① 정배열 상승추세: 3분봉 5선 > 20선 (강세)
  ② 당일 진짜 상승: 당일 고저 변동 ≥ RUNUP%  (안 오른 잔파동 배제)
  ③ 고점 후 눌림: 당일고점 이후 2봉↑ 지나 + 현재 되돌림 PB_MIN~PB_MAX% (얕은딥/추세훼손 배제)
  ④ 지지: 최근저점이 5선까지 눌렸다(터치) + 20선은 안 깸  (진짜 지지·추세유지)
  ⑤ 반등확인: 5선 양봉 회복 + 막 회복(직전봉 5선 위 아님)  ("빠지는 중" 칼잡기 배제)
  ⑥ che ≥ CHE_MIN (매수우위·데드캣 배제)  + 대장(전략100)·진입~END
★매도 = 추세용(눌림후 재상승 길게): che매수우위 끌기 / 매도우위 20선·5선·넓은트레일 / 하드 / 상한가 익일시가 / EOD
★안전: PBUNI_LIVE=NO(기본)=그림자. 실탄 setx PBUNI_LIVE YES. CAP·che필수·전역상한. 데이터 opt10080+snapshot. 출력 data/눌림사냥꾼/.
"""
import os, sys, json, uuid, csv, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")

LIVE       = os.environ.get("PBUNI_LIVE", "NO").strip().upper() == "YES"
CAP        = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
TOPN       = int(os.environ.get("PBUNI_TOPN", "6"))
LEADER_TOPN= int(os.environ.get("PBUNI_LEADER_TOPN", "100"))
SCALP_UNI  = os.environ.get("PBUNI_SCALP_UNI", "YES").strip().upper() == "YES"  # [7/6 친구님] 유니버스=단타선별. 끄기 setx PBUNI_SCALP_UNI NO
CHE_MIN    = float(os.environ.get("PBUNI_CHE_MIN", "100"))
RUNUP      = float(os.environ.get("PBUNI_RUNUP", "5.0"))    # 당일 고저변동 하한%(진짜 오른것)
PB_MIN     = float(os.environ.get("PBUNI_PB_MIN", "3.0"))   # 고점대비 되돌림 하한%(의미있는 눌림)
PB_MAX     = float(os.environ.get("PBUNI_PB_MAX", "8.0"))   # 되돌림 상한%(넘으면 추세훼손)
VOL_MULT   = float(os.environ.get("PBUNI_VOL_MULT", "1.6"))  # ★반등봉 거래량 재유입 배수(눌림평균 대비)
END        = os.environ.get("PBUNI_END", "1330")

# ★[2026-07-05 친구님 "눌림 전체 보강·어차피 내일 검증·눈으로 안 된 부분 찾겠다"] 프로 눌림 3종 보강 — 항목별 스위치:
#   ①VWAP 지지(PBUNI_VWAP): 현재가가 당일 VWAP(평균체결가) 위 = 기관이 받치는 강한 눌림만. 아래는 계단 입구(바닥사냥꾼) 담당.
#   ②비율 되돌림(PBUNI_FIB): 되돌림이 '당일 상승폭'의 25~62%(황금 구간) — 절대 3~8%의 종목별 왜곡 보정.
#   ③상대 체결국면(PBUNI_REL_REB): 절대 90 OR 당일 저점+15 반등이면 매수우위 인정 — 좁은밴드 종목(에스티팜 35~63) 구제.
#   끄기(항목별 한 줄): setx PBUNI_VWAP NO / setx PBUNI_FIB NO / setx PBUNI_REL_REB 0
VWAP_ON    = os.environ.get("PBUNI_VWAP", "YES").strip().upper() == "YES"
FIB_ON     = os.environ.get("PBUNI_FIB", "YES").strip().upper() == "YES"
FIB_MIN    = float(os.environ.get("PBUNI_FIB_MIN", "25"))
FIB_MAX    = float(os.environ.get("PBUNI_FIB_MAX", "62"))
REL_REB    = float(os.environ.get("PBUNI_REL_REB", "15"))   # 0=끔(절대 90만)
CHE_MIN_LV = CHE_MIN
HARD       = float(os.environ.get("PBUNI_HARD", "3.0"))
TRAIL_ARM  = float(os.environ.get("PBUNI_TRAIL_ARM", "3.0"))
TRAIL_GIVE = float(os.environ.get("PBUNI_TRAIL_GIVE", "4.0"))
EOD_HM     = os.environ.get("PBUNI_EOD_HM", "1518")
BARS_TTL   = float(os.environ.get("PBUNI_BARS_TTL", "60"))

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
OUTD = Path(r"C:\stock_bot\data\눌림사냥꾼")             # ★코드네임 PULLBACK HUNTER
POS  = OUTD / "포지션.json"
CHEST= OUTD / "che_state.json"          # [7/5 REL] 체결국면 당일 저점 추적(상대 눈금용·일 단위 리셋)
BOARD= OUTD / "눌림사냥_현황판.txt"
BARSC= OUTD / "bars_cache.json"
LOG  = Path(r"C:\stock_bot\data\LOG\눌림사냥꾼.log")
RT_OPEN = Path(r"C:\stock_bot\data\rt_open_positions.json")


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True); open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception: pass


def _jload(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, p)


def _snap():
    try: return json.loads(SNAP.read_text(encoding="utf-8")).get("codes", {}) or {}
    except Exception: return {}


def _che(sd):
    try:
        v = sd.get("che_str"); return float(v) if isinstance(v, (int, float)) else None
    except Exception: return None


def _bars(bc, code, cache):
    e = cache.get(code)
    if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= BARS_TTL and e.get("bars"):
        return [tuple(x) for x in e["bars"]]
    def ff(x):
        try: return abs(float(str(x).replace(",", "")))
        except Exception: return 0.0
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량"], timeout_sec=6.0, screen_no="9724")
        today = datetime.now().strftime("%Y%m%d"); out = []
        for z in (((r or {}).get("data") or {}).get("records") or [])[::-1]:
            ts = str(z.get("체결시간", ""))
            if ts[:8] != today: continue
            out.append((ts[8:12], ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가")), ff(z.get("거래량"))))
        if out: cache[code] = {"ts": time.time(), "bars": out}
        return out
    except Exception: return []


def _sma(bars, period, back=0):
    cl = [b[4] for b in bars]; end = len(cl) - back
    if end < period: return None
    return sum(cl[end - period:end]) / period


def gate(bars, cur):
    """★진짜 눌림목 선별 게이트. 반환 dict or None."""
    if len(bars) < 22:
        return None
    ma5 = _sma(bars, 5); ma20 = _sma(bars, 20)
    if ma5 is None or ma20 is None or ma20 <= 0:
        return None
    highs = [b[2] for b in bars]; lows = [b[3] for b in bars]
    day_hi = max(highs); hi_i = highs.index(day_hi); day_lo = min(lows)
    if ma5 <= ma20:                                       # ①정배열
        return None
    runup = (day_hi - day_lo) / day_lo * 100 if day_lo > 0 else 0
    if runup < RUNUP:                                     # ②당일 진짜 상승
        return None
    if (len(bars) - 1 - hi_i) < 2:                        # ③고점 후 2봉↑
        return None
    pb = (day_hi - cur) / day_hi * 100 if day_hi > 0 else 0
    if pb < PB_MIN or pb > PB_MAX:                        # ③되돌림 범위
        return None
    if VWAP_ON or FIB_ON:                                 # ★[7/5 보강] VWAP 지지 + 비율 되돌림
        cum_pv = 0.0; cum_v = 0.0
        for b in bars:
            cum_pv += b[4] * b[5]; cum_v += b[5]
        vwap = cum_pv / cum_v if cum_v > 0 else 0.0
        if VWAP_ON and vwap > 0 and cur < vwap * 0.998:   # ①VWAP 아래 = 약한 눌림(계단 입구 영역) 제외
            return None
        if FIB_ON and day_hi > day_lo:
            ratio = (day_hi - cur) / (day_hi - day_lo) * 100
            if ratio < FIB_MIN or ratio > FIB_MAX:        # ②상승폭 대비 25~62%만(얕음/훼손 배제)
                return None
    recent_low = min(lows[-4:])
    if recent_low > ma5 * 1.012:                          # ④5선까지 눌렸나(지지 터치)
        return None
    if recent_low < ma20 * 0.99:                          # ④20선 안 깸(추세유지)
        return None
    if cur <= ma5:                                        # ⑤5선 회복
        return None
    if cur <= bars[-1][1]:                                # ⑤양봉
        return None
    if bars[-2][4] > ma5 * 1.005:                         # ⑤막 회복만(늦은 추격 배제)
        return None
    vwin = [b[5] for b in bars[-6:-1]]                    # ⑥거래량 재유입: 반등봉 > 직전 눌림 5봉 평균×배수
    vavg = sum(vwin) / len(vwin) if vwin else 0
    if vavg > 0 and bars[-1][5] < vavg * VOL_MULT:
        return None
    volx = round(bars[-1][5] / vavg, 1) if vavg > 0 else 0
    return {"pb": round(pb, 1), "runup": round(runup, 1), "ma5": round(ma5), "ma20": round(ma20), "volx": volx,
            "info": f"눌림-{pb:.1f}%·상승{runup:.0f}%·거래량{volx}배·5선{ma5:,.0f}회복"}


def _order(bc, code, qty, side, tag, live):
    if not (LIVE and live):
        return True
    try:
        ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or []
        if isinstance(accs, str): accs = [a for a in accs.split(";") if a]   # [7/6 근본수정] 브로커 문자열 계좌 파싱
        acc = (accs[0] if isinstance(accs, list) and accs else "") or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()  # env 폴백
        if not acc: _log(f"[{tag}] 계좌없음"); return False
        r = bc.send_order_real(idempotency_key=f"pbuni_{side.lower()}_{code}_{uuid.uuid4()}", account=acc,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"PBUNI_{side}_{code}", screen_no="9725")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[LIVE] {side} {code} x{qty} status={st} → {'성공' if ok else '실패'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _sell_decide(cur, buy, peak, che, ma5, ma20, hm):
    if buy > 0 and (cur / buy - 1) * 100 <= -HARD: return f"하드-{HARD:g}%"
    if hm >= EOD_HM: return "EOD청산"
    if che is not None and che >= CHE_MIN: return None                     # 매수세=끌기
    if ma20 > 0 and cur < ma20: return "20선이탈(추세붕괴)"
    if ma5 > 0 and cur < ma5: return "5선이탈"
    if buy > 0 and peak > 0 and (peak / buy - 1) * 100 >= TRAIL_ARM and cur <= peak * (1 - TRAIL_GIVE / 100.0):
        return f"트레일(고점-{TRAIL_GIVE:g}%)"
    return None


def run():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < "0900" or hm > "1530": return
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive(): _log("broker dead → skip"); return
        bc = BrokerClient()
    except Exception as e:
        _log(f"broker 연결실패 {e}"); return
    OUTD.mkdir(parents=True, exist_ok=True)
    snap = _snap(); pos = _jload(POS)
    bars_cache = _jload(BARSC); bars_cache = bars_cache if isinstance(bars_cache, dict) else {}
    che_state = _jload(CHEST)                              # [7/5 REL] 당일 che 저점 추적 상태
    che_state = che_state if isinstance(che_state, dict) and che_state.get("date") == today else {"date": today}
    def _rel_ok(code, che):
        """상대 매수우위: 체결국면이 당일 저점 대비 +REL_REB 이상 돌아섬(표본 5+)."""
        if REL_REB <= 0 or che is None: return False
        st = che_state.get(code)
        return (isinstance(st, dict) and st.get("min") is not None
                and int(st.get("n", 0)) >= 5 and che >= float(st["min"]) + REL_REB)
    mode = "[LIVE]" if LIVE else "[그림자]"
    try:
        import limitup_exit as LU
    except Exception:
        LU = None

    # ===== 매도관리 =====
    for c, p in list(pos.items()):
        if not isinstance(p, dict) or p.get("status") != "HOLDING": continue
        if LU and LU.should_open_sell(p, today, hm):                       # ★상한가 익일시가매도
            sd = snap.get(c) or {}; cur = float(sd.get("cur", 0) or 0)
            if cur <= 0:
                b = _bars(bc, c, bars_cache); cur = b[0][1] if b else 0.0
            if cur > 0:
                _order(bc, c, int(p.get("qty", 0) or 0), "SELL", "익일시가매도", p.get("live"))
                p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = "익일시가매도(상한가)"; p["sell_hm"] = hm
                _log(f"{mode} SELL {c} @{cur:,.0f} 익일시가매도(상한가)")
                if p.get("live"):
                    try:
                        import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                    except Exception:
                        pass
            continue
        if p.get("date") != today: continue
        sd = snap.get(c) or {}; cur = float(sd.get("cur", 0) or 0)
        b = _bars(bc, c, bars_cache)
        if cur <= 0: cur = b[-1][4] if b else 0.0
        if cur <= 0: continue
        buy = float(p.get("buy_price", 0) or 0); che = _che(sd)
        peak = max(float(p.get("peak", buy) or buy), cur); p["peak"] = peak
        if LU and LU.is_limitup(c, cur):                                   # ★상한가 → 익일 시가매도 유예
            if not p.get("limitup_hold"):
                p["limitup_hold"] = True; _log(f"{mode} 🔒상한가 {c} @{cur:,.0f} → 익일 시가매도 예약")
            continue
        ma5 = _sma(b, 5) or 0.0; ma20 = _sma(b, 20) or 0.0
        che_s = che
        if che is not None and _rel_ok(c, che):
            che_s = max(che, CHE_MIN)                      # [7/5 REL] 상대 매수우위 유지 = 끌기(절대 90 미달이어도)
        sell = _sell_decide(cur, buy, peak, che_s, ma5, ma20, hm)
        if sell:
            _order(bc, c, int(p.get("qty", 0) or 0), "SELL", sell, p.get("live"))
            p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = sell; p["sell_hm"] = hm
            _log(f"{mode} SELL {c} @{cur:,.0f} ({(cur/buy-1)*100:+.1f}%) {sell}")
            if p.get("live"):
                try:
                    import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                except Exception:
                    pass
    _jsave(POS, pos)

    # ===== 진입 =====
    board = [f"=== 눌림사냥꾼 {mode} {now:%H:%M} (정배열+상승{RUNUP:g}%+눌림{PB_MIN:g}~{PB_MAX:g}%+5선회복+che≥{CHE_MIN:.0f}) ==="]
    held = sum(1 for p in pos.values() if isinstance(p, dict) and p.get("status") == "HOLDING")
    budget_block = False
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            budget_block = True; board.append("  [전역상한] 신규진입 보류")
    except Exception: pass
    if not budget_block and hm <= END and held < TOPN:
        uni = []
        if SCALP_UNI:                                 # [7/6 친구님] 거래대금 대신 단타 선별(scalp) 유니버스
            try:
                _bd = json.load(open(r"C:\stock_bot\data\daily_leader_board.json", encoding="utf-8"))
                uni = [str(c).zfill(6) for c in (_bd.get("codes") or [])][:LEADER_TOPN]
            except Exception: uni = []
        if not uni:
            try:
                import leader_filter as lf; uni = list(lf.leader_list(bc) or [])[:LEADER_TOPN]
            except Exception: uni = []
        excl = {str(k).zfill(6) for k, v in _jload(RT_OPEN).items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
        for code in uni:
            if held >= TOPN: break
            code = str(code).zfill(6)
            sd = snap.get(code) or {}
            che = _che(sd)
            if che is not None and hm >= "0910":           # [7/5 REL] 당일 che 저점 추적(개장 극단값 제외)
                _cs = che_state.get(code) if isinstance(che_state.get(code), dict) else {}
                _cs["min"] = che if _cs.get("min") is None else min(float(_cs["min"]), che)
                _cs["n"] = int(_cs.get("n", 0)) + 1
                che_state[code] = _cs
            if code in excl: continue
            he = pos.get(code)
            if isinstance(he, dict) and he.get("date") == today and he.get("status") in ("HOLDING", "DONE"): continue
            bars = _bars(bc, code, bars_cache)
            if not bars or len(bars) < 22: continue
            cur = float(sd.get("cur", 0) or 0) or bars[-1][4]
            if cur <= 0: continue
            g = gate(bars, cur)
            if not g: continue
            rel = _rel_ok(code, che)
            che_dom = (che is not None and che >= CHE_MIN) or rel   # [7/5 REL] 절대 90 OR 저점+15 반등
            if LIVE and not che_dom:
                _st = che_state.get(code) if isinstance(che_state.get(code), dict) else {}
                board.append(f"  ⏸ {code} 눌림통과·che대기(che={che} 저점{_st.get('min')})"); continue
            try:                                   # ★[2026-07-06] 스마트머니 던지기 회피(공용·외국인+프로그램 실시간)
                import smart_money as _SM
                _blk, _smi = _SM.dumping(bc, code, cur)
                if _blk:
                    board.append(f"  ⛔ {code} 스마트머니 던지기 차단 [{_smi}]"); continue
            except Exception:
                pass
            qty = max(1, int(CAP / cur)) if cur > 0 else 0
            if not _order(bc, code, qty, "BUY", "진입 눌림", LIVE): continue
            pos[code] = {"code": code, "status": "HOLDING", "buy_price": cur, "qty": qty, "peak": cur,
                         "pb": g["pb"], "runup": g["runup"], "che": che, "date": today, "buy_hm": hm, "live": LIVE}
            if LIVE:
                try:
                    import rt_registry as _RT; _RT.register(code, qty, cur, "PBUNI")   # [7/5] 공용장부 즉시등록(중복매수·전역한도 시차 제거)
                except Exception:
                    pass
            held += 1
            _log(f"{mode} BUY {code} @{cur:,.0f} {g['info']} che={che} x{qty}")
            board.append(f"  🎯★매수 {code} @{cur:,.0f} {g['info']} che={che}")
            try:
                f = OUTD / f"눌림사냥_시그널_{today}.csv"; new = not f.exists()
                with open(f, "a", encoding="utf-8-sig", newline="") as fp:
                    w = csv.writer(fp)
                    if new: w.writerow(["hm", "code", "buy", "pb%", "runup%", "ma5", "ma20", "che"])
                    w.writerow([hm, code, f"{cur:.0f}", g["pb"], g["runup"], g["ma5"], g["ma20"], che])
            except Exception: pass
    for c, p in pos.items():
        if isinstance(p, dict) and p.get("status") == "HOLDING":
            ov = " 🔒익일시가매도" if p.get("limitup_hold") else ""
            board.append(f"  ● 보유 {c} 매수{p.get('buy_price'):,.0f} 고점{p.get('peak',0):,.0f} 눌림{p.get('pb')}%{ov}")
    try: BOARD.write_text("\n".join(board) + "\n", encoding="utf-8")
    except Exception: pass
    _jsave(POS, pos)
    _jsave(BARSC, {c: e for c, e in bars_cache.items() if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= 600})


if __name__ == "__main__":
    try: run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
