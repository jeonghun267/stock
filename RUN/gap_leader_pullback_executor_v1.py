# -*- coding: utf-8 -*-
"""[갭 대장 눌림 실전 executor — 폭발장 전용] 친구님 2026-06-29 "소액 실전·바로 고치기".
   신호: 전일대장 ∩ 당일 갭업≥GAP_MIN(15%) ∩ 장중고점 대비 -DEPTH%(5%) 눌림 → ★BUY.
   = 폭발급 갭 대장이 첫 눌림 줄 때 사서 종가까지 보유(백테: 15%+갭 +3.6~6.4%/승60~80%·n10 예비).
   ★안전: GAPLEAD_LIVE=NO면 모의(주문0)·소액캡·1종목·종목당1회·하드손절-5%·EOD청산(15:18·종가보유).
   매수차단버튼(manual_buy_block)·전역캡(position_budget)은 broker_client/게이트에서 자동적용.
   주문경로=deep_v와 동일 검증된 broker. 충돌배제: rt_open strategy=GAPLEAD.
   실행: pick(09:01~BUY_CUTOFF 1분) / sell(15:18). 롤백 setx GAPLEAD_LIVE NO."""
import sys, json, uuid, os
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")
import pandas as pd, numpy as np

PRICES_1M = r"C:\stock_bot\data\prices_1m.csv"
SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
POS = Path(r"C:\stock_bot\DATA\gap_leader_positions.json")
EOD_GAP_POS    = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")                    # [CONFLICT 2026-06-30] 종가매수 보유 — 중복매수 차단
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")   # [CONFLICT 2026-06-30] 종가매수(pickup) — 중복매수 차단
LOG = Path(r"C:\stock_bot\data\LOG\gap_leader_pullback.log")

# ── 설정 (env 롤백 가능) ──────────────────────────────────────────────
LIVE = os.environ.get("GAPLEAD_LIVE", "NO").strip().upper() == "YES"
CAP = int(float(os.environ.get("GAPLEAD_CAP_KRW") or "200000"))      # 소액(검증전 n10)
GAP_MIN = float(os.environ.get("GAPLEAD_GAP_MIN", "15.0"))           # 폭발급 갭(백테 엣지=15%)
ENTRY_DEPTH = float(os.environ.get("GAPLEAD_DEPTH", "5.0"))          # 장중고점 대비 이만큼 눌리면 진입
HARD_STOP = float(os.environ.get("GAPLEAD_STOP", "5.0"))            # 하드손절 -%
TRAIL = float(os.environ.get("GAPLEAD_TRAIL", "3.0"))               # ★상승 고점 대비 이만큼 빠지면 매도(줄때먹고빠지기)
TRAIL_ARM = float(os.environ.get("GAPLEAD_TRAIL_ARM", "2.0"))       # 고점이익 이%↑부터 트레일 작동(노이즈 방지)
EOD_HM = os.environ.get("GAPLEAD_EOD_HM", "1518")                   # 안 튀면 종가보유(백테 best)·트레일 안먹은것 backstop
BUY_CUTOFF = os.environ.get("GAPLEAD_BUY_CUTOFF", "1500")
MAX_POS = int(os.environ.get("GAPLEAD_MAX_POS", "1"))
CAND = Path(rf"C:\stock_bot\DATA\gap_leader_cand_{datetime.now():%Y%m%d}.json")
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()

# [CHE-EXIT 통합 2026-06-30 친구님 "손절은 체결량·5일·20일선 규칙 따르게"] 갭대장=갭+15% 모멘텀이라 MA선 위
#   → 돌파처럼 체결강도→5일선→20일선 레이어 청산 적합(깊은V와 달리 면제 안함). EXIT_MA_LAYER=YES면 MA층 자동.
#   GAPLEAD_CHE_EXIT=NO면 기존 고정 -5%/트레일 폴백. 친구님 기존 손절-5%·트레일발동+2%는 params로 계승.
CHE_EXIT_ON = os.environ.get("GAPLEAD_CHE_EXIT", "YES").strip().upper() == "YES"
try:
    import che_exit as _che_mod
    GAPLEAD_CHE_PARAMS = _che_mod.default_params("GENERIC")
    GAPLEAD_CHE_PARAMS.update(hard_pct=HARD_STOP, retr_arm=TRAIL_ARM)   # 하드손절·트레일발동은 기존값 유지
except Exception:
    _che_mod = None; GAPLEAD_CHE_PARAMS = {}


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(s + "\n")
    except Exception: pass


def _jload(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag):
    # ★[2026-07-01 대장주 순위표 게이트] 매수는 전날 종가 대장주 순위표 안에서만.
    #   board 없거나 LEADER_FILTER OFF면 is_leader=True(fail-open). 롤백 setx GAPLEAD_LEADER_BOARD NO
    if side == "BUY" and os.environ.get("GAPLEAD_LEADER_BOARD", "YES").strip().upper() == "YES":
        try:
            import leader_filter as _lf
            if not _lf.is_leader(bc, code):
                _log(f"[{tag}][대장외] {code} 전날 순위표 밖 → 매수차단"); return False
        except Exception:
            pass
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (GAPLEAD_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"gaplead_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"GAPLEAD_{side}_{code}", screen_no="9712")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} → {str(r)[:110]}")
        _st = str((r or {}).get("status", "")).upper()
        # [BUGFIX 2026-06-30 #1 비대칭] 매수=OK|TIMEOUT 기록(미체결확인불가→재매수 중복위험 회피)·매도=OK만 완료(비OK는 OPEN유지 재시도)
        if side == "BUY":
            _ok = _st in ("OK", "TIMEOUT")
        else:
            _ok = (_st == "OK")
        if not _ok or _st != "OK":
            _log(f"[{tag}] 주문 status={_st or 'EMPTY'} → " + ("성공" if _ok else "실패처리") + (" (TIMEOUT=체결미확인·수동확인 권장)" if _st == "TIMEOUT" else ""))
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _today_bars():
    """당일 1분봉 {code:(O,H,L,Cur,run_high,daylow)}. prices_1m 읽기."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str}, usecols=["code", "ts", "open", "high", "low", "close"])
    except Exception as e:
        _log(f"prices_1m 못읽음: {e}"); return {}
    df = df[df["ts"].astype(str).str[:8] == today].copy()
    if df.empty: return {}
    df["code"] = df["code"].str.zfill(6)
    for c in ["open", "high", "low", "close"]: df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().sort_values(["code", "ts"])
    out = {}
    for cd, x in df.groupby("code"):
        H = x["high"].values; Lo = x["low"].values
        out[cd] = (float(x["open"].iloc[0]), float(H.max()), float(Lo.min()),
                   float(x["close"].iloc[-1]), float(np.maximum.accumulate(H)[-1]), float(Lo.min()))
    return out


def _candidates():
    """전일대장 {code: prev_close}. 하루1회 계산·캐시."""
    c = _jload(CAND)
    if c: return c
    today = datetime.now().strftime("%Y%m%d")
    cols = ["date", "code", "market", "close", "value", "daily_return", "value_ratio", "vol_ratio"]
    e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=cols, low_memory=False)
    e = e[e["market"] == "KOSDAQ"].copy(); e["code"] = e["code"].str.zfill(6)
    for c2 in cols[3:]: e[c2] = pd.to_numeric(e[c2], errors="coerce")
    e = e.dropna(subset=["close", "value"]).sort_values(["code", "date"])
    g = e.groupby("code")
    e["ma5"] = g["close"].transform(lambda s: s.rolling(5).mean()); e["c5"] = g["close"].shift(5)
    e["ret5"] = (e["close"] / e["c5"] - 1) * 100; e["dev5"] = (e["close"] / e["ma5"] - 1) * 100
    e["vr"] = e["value_ratio"].fillna(0); e["volr"] = e["vol_ratio"].fillna(0); e["eok"] = e["value"] / 100.0
    e["mkt5"] = e.groupby("date")["ret5"].transform("mean"); e["RS5"] = e["ret5"] - e["mkt5"]
    e["locked"] = (e["daily_return"] >= 0.28)
    prevdates = sorted(d for d in e["date"].unique() if d < today)
    if not prevdates: return {}
    pv = prevdates[-1]; ep = e[e["date"] == pv]
    s = ep[(ep["vr"] > 2.6) & (ep["dev5"] >= 10) & (ep["RS5"] >= 2) & (ep["volr"] >= 2) & (~ep["locked"]) & (ep["eok"] >= 5)]
    cand = {r.code: float(r.close) for r in s.itertuples(index=False)}
    _jsave(CAND, cand); _log(f"전일({pv}) 대장후보 {len(cand)}종목 캐시")
    return cand


def _safe_float(x, default=0.0):
    """[BUGFIX 2026-06-30 #6] 스냅샷 che_str가 비숫자여도 안전 변환(che_exit.decide 비교 TypeError 방지)."""
    try:
        if x is None: return default
        return float(x)
    except (TypeError, ValueError): return default


def _eod_held():
    """[CONFLICT 2026-06-30] 종가매수분(eod_gap·eod_pickup) 오버나잇 보유 — 갭리더가 같은종목 중복매수 차단. env CONFLICT_EXCLUDE_EOD=NO로 끔."""
    if os.environ.get("CONFLICT_EXCLUDE_EOD", "YES").strip().upper() != "YES":
        return set()
    s = set()
    try:
        d = _jload(EOD_GAP_POS)
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
    except Exception: pass
    try:
        d = _jload(EOD_PICKUP_POS)
        if isinstance(d, dict):
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            for dt, codes in d.items():
                if not (isinstance(dt, str) and dt.isdigit() and dt >= cutoff and isinstance(codes, dict)): continue
                for c, p in codes.items():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
    except Exception: pass
    return s


def _held_now():
    """충돌배제: rt_open 전체 + 자체보유 + 종가매수분(eod)."""
    s = set()
    for c, v in _jload(RT_OPEN).items():
        if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
    for c, v in _jload(POS).items():
        if isinstance(v, dict) and v.get("status") == "OPEN": s.add(str(c).zfill(6))
    s |= _eod_held()   # [BUGFIX 2026-06-30 #3] 종가매수 오버나잇 중복매수 차단
    return s


def mode_pick():
    hm = datetime.now().strftime("%H%M")
    _log(f"=== GAPLEAD pick (LIVE={LIVE} CAP={CAP:,} GAP≥{GAP_MIN:.0f}% DEPTH-{ENTRY_DEPTH:.0f}%) ===")
    if hm >= BUY_CUTOFF:
        _log(f"매수마감({BUY_CUTOFF}) 지남 → skip"); return
    held = _jload(POS)
    opens = [c for c, v in held.items() if isinstance(v, dict) and v.get("status") == "OPEN"]
    if len(opens) >= MAX_POS:
        _log(f"이미 {len(opens)}/{MAX_POS} 보유 → 신규없음"); return
    # 전역캡
    try:
        import position_budget as _gb
        if _gb.budget_on():
            try:
                _gr = _gb.remaining_intraday()
            except Exception as _re:
                _gr = 0   # [BUGFIX 2026-06-30] 캡 ON인데 읽기 실패 → 보수적 차단(fail-closed)
                _log(f"[GLOBAL-CAP] remaining 읽기실패 → 보류(fail-closed): {_re}")
            if _gr <= 0:
                _log(f"[GLOBAL-CAP] 전역상한 도달 → 보류"); return
    except Exception: pass
    cand = _candidates()
    if not cand:
        _log("후보없음(전일대장 0)"); return
    bars = _today_bars()
    excl = _held_now()
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("broker dead → 매수보류"); return
    picks = []
    for code, pcl in cand.items():
        if code in excl or code in held: continue
        b = bars.get(code)
        if not b or not pcl or pcl <= 0: continue
        O, Hmax, Lmin, cur, run_hi, daylo = b
        gap = (O / pcl - 1) * 100
        if gap < GAP_MIN or gap > 31: continue                  # 폭발급 갭만 + 가짜갭 제거
        if run_hi <= O: continue                                # 갭후 더 올라간 놈만(런)
        lvl = run_hi * (1 - ENTRY_DEPTH / 100)
        if cur > lvl: continue                                  # 아직 -DEPTH% 안 눌림
        if cur <= 0: continue
        picks.append((gap, code, cur))
    picks.sort(key=lambda x: -x[0])   # 갭 큰 순
    bought = 0
    for gap, code, cur in picks:
        if len(opens) + bought >= MAX_POS: break
        # [정배열 전용 2026-06-29 친구님 "모든 전략 횡보·역배열 진입금지·정배열만"] ★갭리더 눌림도 strict 정배열일 때만.
        try:
            import trend_filter as _tf
            if not _tf.is_jeongbae(code, "strict"):
                _log(f"★GAPLEAD 스킵 {code}(정배열 아님·횡보/역배열 진입금지)"); continue
        except Exception:
            pass
        qty = max(1, int(CAP // cur))
        try:                                       # ★[2026-07-06] 스마트머니 던지기 회피(공용·외국인+프로그램 실시간)
            import smart_money as _SM
            _blk, _smi = _SM.dumping(bc, code, cur)
            if _blk:
                _log(f"⛔ GAPLEAD {code} 스마트머니 던지기 차단 [{_smi}] — 매수스킵"); continue
        except Exception:
            pass
        _log(f"★GAPLEAD 매수 {code} 갭{gap:+.1f}% 고점-{ENTRY_DEPTH:.0f}%눌림 @{cur:,.0f} x{qty}={qty*cur:,.0f}원")
        if _order(bc, code, qty, "BUY", "PICK"):
            if LIVE:
                held[code] = {"code": code, "qty": qty, "buy_price": cur, "gap": round(gap, 1),
                              "date": datetime.now().strftime("%Y%m%d"), "status": "OPEN",
                              "stop": round(cur * (1 - HARD_STOP / 100)), "ts": datetime.now().isoformat()}
                _jsave(POS, held)
                rt = _jload(RT_OPEN)
                rt[code] = {"qty": qty, "entry_price": cur, "code": code, "strategy": "GAPLEAD",
                            "peak_price": cur, "stop_price": round(cur * (1 - HARD_STOP / 100))}
                _jsave(RT_OPEN, rt)
            bought += 1
    if not bought:
        _log(f"신호없음 (후보 {len(cand)}·갭조건통과 {len(picks)})")


def _cur_price(code):
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str}, usecols=["code", "ts", "close"])
        g = df[df["code"] == code].sort_values("ts")
        if len(g): return float(g["close"].iloc[-1])
    except Exception: pass
    try:
        d = json.loads(SNAP.read_text(encoding="utf-8")); c = d.get("codes", {}).get(code, {})
        v = float(c.get("cur", 0) or 0)
        if v > 0: return v
    except Exception: pass
    return 0.0


def mode_manage(force_eod=False):
    held = _jload(POS)
    opens = {c: v for c, v in held.items() if isinstance(v, dict) and v.get("status") == "OPEN" and float(v.get("qty", 0) or 0) > 0}
    if not opens: return
    hm = datetime.now().strftime("%H%M")
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("[MANAGE] broker dead → 청산보류"); return
    snap = (_jload(SNAP) or {}).get("codes", {})   # [CHE-EXIT] 체결강도(che_str) 스냅샷
    for code, p in list(opens.items()):
      try:   # [BUGFIX 2026-06-30 #4] per-종목 격리 — 한 종목 오류가 나머지 청산을 막지 않도록
        qty = int(p["qty"]); buy = float(p["buy_price"]); cur = _cur_price(code)
        reason = None
        if cur <= 0:
            if force_eod or hm >= EOD_HM:
                _log(f"[MANAGE] ★EOD강제청산(가격조회실패→시장가) {code} x{qty}")
                if _order(bc, code, qty, "SELL", "MANAGE"):
                    held[code]["status"] = "CLOSED"; _jsave(POS, held)
                    rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)
            continue
        pnl = (cur / buy - 1) * 100
        peak = max(float(p.get("peak", buy) or buy), cur)
        if peak != p.get("peak"):
            held[code]["peak"] = peak; _jsave(POS, held)
        pk_gain = (peak / buy - 1) * 100
        if force_eod or hm >= EOD_HM:                               # ③ 안 튀면 종가보유 backstop(최후·오버나잇 방지)
            reason = f"EOD청산 {pnl:+.1f}%"
        elif os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES":
            # [통일 매도 2026-07-01 친구님] 하드손절 유지 → 수급/MA/트레일은 vol_exit(매수우위 보유·매도우위+20선 무조건 매도)
            che = _safe_float((snap.get(code) or {}).get("che_str"), None)
            if cur <= buy * (1 - HARD_STOP / 100):
                reason = f"하드손절-{HARD_STOP:.0f}% {pnl:+.1f}%"
            else:
                try:
                    import vol_exit as _VE
                    _s, _r = _VE.decide(code, buy, peak, cur, ma20_hard=True, che=che)
                    if _s:
                        reason = f"{_r} {pnl:+.1f}%"
                except Exception:
                    pass
        elif CHE_EXIT_ON and _che_mod is not None:                  # ★체결강도→5일선→20일선 레이어(전 전략 통일)
            che = _safe_float((snap.get(code) or {}).get("che_str"), None)   # [#6] 안전변환(문자열→None)
            try:
                import exit_ma as _DMA; _m5, _m20 = _DMA.ma5(code), _DMA.ma20(code)
            except Exception:
                _m5 = _m20 = 0.0
            sell, rs, tg, _drop, _strong = _che_mod.decide(cur, buy, peak, pnl, che, p.get("che_prev"), GAPLEAD_CHE_PARAMS, ma5=_m5, ma20=_m20)
            if che is not None and che != p.get("che_prev"):
                held[code]["che_prev"] = che; _jsave(POS, held)
            if sell:
                reason = f"{tg} {pnl:+.1f}%"
        else:                                                       # 폴백: 기존 고정 -5%/트레일(che_exit 불가시)
            if cur <= buy * (1 - HARD_STOP / 100):
                reason = f"하드손절-{HARD_STOP:.0f}% {pnl:+.1f}%"
            elif TRAIL > 0 and pk_gain >= TRAIL_ARM and cur <= peak * (1 - TRAIL / 100):
                reason = f"트레일·고점-{TRAIL:.0f}% {pnl:+.1f}%(고점+{pk_gain:.1f}%)"
        if reason:
            _log(f"[MANAGE] ★매도 {code} x{qty} @{cur:,.0f} ({reason})")
            if _order(bc, code, qty, "SELL", "MANAGE"):
                held[code]["status"] = "CLOSED"; held[code]["sell_price"] = cur; _jsave(POS, held)
                if LIVE:
                    rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)
      except Exception as _e:   # [BUGFIX 2026-06-30 #4] 한 종목 오류 격리 → 나머지 청산 계속
        _log(f"[MANAGE] {code} 처리오류(격리·다음종목 계속): {_e}")
        continue


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    _log(f"=== GAPLEAD executor [{mode}] LIVE={LIVE} ===")
    if mode == "pick":
        mode_pick(); mode_manage()
    elif mode == "manage":
        mode_manage()
    elif mode == "sell":
        mode_manage(force_eod=True)
    _log(f"=== GAPLEAD executor [{mode}] done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)
