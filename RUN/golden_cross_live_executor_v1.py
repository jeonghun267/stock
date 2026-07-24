# -*- coding: utf-8 -*-
"""[골든크로스 추세시작 executor — 친구님 2026-06-30 "5/20 만나 오름 타기 시작·60선도 우상향"]
신호(진입): 5선이 20선 상향돌파(골든크로스·5선↑) ∩ 60선도 우상향 ∩ 강한마감(종가위치≥0.6) ∩ 이격≤3%(막 시작) ∩ 유동성
            ∩ ★실시간 체결강도≥120(우리표준·데이터없으면 매수금지) → BUY.
청산(매도): ★당일청산(친구님 "당일 매수매도"). che_exit(체결강도 약화 + 5선 이탈) + 하드손절 + EOD 15:18 강제청산(오버나잇X).
            셋업=일봉 5/20 수렴·상향(워치리스트)·트리거=장중 급등+체결강도≥120·당일 안에 사고 당일 안에 판다.
⚠️당일치기는 분봉 과거데이터 없어 백테불가(셋업만 일봉으로 검증)→페이퍼로 실거동 확인 필수.

★★안전: GCLIVE=NO면 전부 모의(주문0·페이퍼). 친구님 원칙=그림자→페이퍼검증→실탄. 스윙(오버나잇)이라 페이퍼 필수.
주문경로=deep_v와 동일 검증 broker. 충돌배제 rt_open strategy=GCROSS. 전역캡(position_budget)·매수차단 자동.
실행: pick(09:05~BUY_CUTOFF) / manage(장중 주기·청산만·EOD강제청산 안함). 롤백 setx GCLIVE NO(또는 스케줄 삭제)."""
import sys, json, uuid, os
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")
import pandas as pd, numpy as np

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
PRICES_1M = r"C:\stock_bot\data\prices_1m.csv"
SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
POS = Path(r"C:\stock_bot\DATA\gcross_positions.json")
EOD_GAP_POS = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")
CAND = Path(rf"C:\stock_bot\DATA\gcross_cand_{datetime.now():%Y%m%d}.json")
LOG = Path(r"C:\stock_bot\data\LOG\golden_cross_live.log")

LIVE = os.environ.get("GCLIVE", "NO").strip().upper() == "YES"   # 기본 페이퍼(주문0)
CAP = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
try:
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
CHE_BUY = float(os.environ.get("GCROSS_CHE", "120.0"))        # 체결강도 하드게이트(우리표준)
DEV_MAX = float(os.environ.get("GCROSS_DEV_MAX", "3.0"))      # 이격 상한(막 시작)
CLPOS_MIN = float(os.environ.get("GCROSS_CLPOS", "0.6"))      # 강한마감
EOK_MIN = float(os.environ.get("GCROSS_EOK", "10.0"))         # 유동성(억)
HARD_STOP = float(os.environ.get("GCROSS_STOP", "8.0"))       # 하드손절%
MAX_POS = int(os.environ.get("GCROSS_MAX_POS", "3"))
BUY_CUTOFF = os.environ.get("GCROSS_BUY_CUTOFF", "1430")
EOD_HM = os.environ.get("GCROSS_EOD_HM", "1518")              # ★당일청산 시각(오버나잇X)
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()

CHE_EXIT_ON = os.environ.get("GCROSS_CHE_EXIT", "YES").strip().upper() == "YES"
try:
    import che_exit as _che_mod
    GC_CHE_PARAMS = _che_mod.default_params("GENERIC")
    GC_CHE_PARAMS.update(hard_pct=HARD_STOP, che_strong=CHE_BUY)
except Exception:
    _che_mod = None; GC_CHE_PARAMS = {}


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


def _safe_float(x, default=0.0):
    try:
        if x is None: return default
        return float(x)
    except (TypeError, ValueError): return default


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag):
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (GCLIVE=NO·페이퍼)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"gcross_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"GCROSS_{side}_{code}", screen_no="9713")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} → {str(r)[:110]}")
        _st = str((r or {}).get("status", "")).upper()
        _ok = (_st in ("OK", "TIMEOUT")) if side == "BUY" else (_st == "OK")
        if not _ok or _st != "OK":
            _log(f"[{tag}] 주문 status={_st or 'EMPTY'} → " + ("성공" if _ok else "실패처리"))
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _candidates():
    """진입 후보. ★친구님 2026-06-30 통합패치: GCROSS_STRICT_V2=YES(기본)면 '신규-골든크로스 v2'
       (횡보 churn 제거 — 직전봉 아래→현재봉 위 + 이격0.2~1.2 + 5/20기울기 + 가격위치 + 체결량1.5배
        + 20봉변동폭3% + 같은크로스 재매수금지). 라이브 1분봉을 3분봉 재집계해 거래량/고저까지 본다.
       NO면 기존 3분봉 golden_cross(롤백). 매수 판단부만 교체(매도/주문/리스크/수집 무관)."""
    if os.environ.get("GCROSS_STRICT_V2", "YES").strip().upper() == "YES":
        try:
            import golden_cross_signal as _gcs
            out = _gcs.scan()
            if out:
                _log(f"★신규GC(v2) {len(out)}종목: {sorted(out)[:10]}")
            return out
        except Exception as ex:
            _log(f"[candidates v2 실패→보류] {ex}")
            return {}
    # --- 레거시(GCROSS_STRICT_V2=NO 롤백용) ---
    try:
        import intraday_ma as _im
        out = {}
        for code in _im.all_codes():
            if _im.golden_cross(code):
                cl = _im.bars3(code)
                out[code] = {"signal_close": (cl[-1] if cl else 0.0), "info": "3분봉GC"}
        if out:
            _log(f"3분봉 골든크로스 {len(out)}종목: {sorted(out)[:10]}")
        return out
    except Exception as ex:
        _log(f"[candidates 3분봉 실패] {ex}")
        return {}


def _eod_held():
    if os.environ.get("CONFLICT_EXCLUDE_EOD", "YES").strip().upper() != "YES": return set()
    s = set()
    for fp, nested in ((EOD_GAP_POS, False), (EOD_PICKUP_POS, True)):
        try:
            d = _jload(fp)
            if not isinstance(d, dict): continue
            if nested:
                cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                for dt, codes in d.items():
                    if isinstance(dt, str) and dt.isdigit() and dt >= cutoff and isinstance(codes, dict):
                        for c, p in codes.items():
                            if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
            else:
                for c, p in d.items():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
        except Exception: pass
    return s


def _held_now():
    s = set()
    for c, v in _jload(RT_OPEN).items():
        if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0: s.add(str(c).zfill(6))
    for c, v in _jload(POS).items():
        if isinstance(v, dict) and v.get("status") == "OPEN": s.add(str(c).zfill(6))
    s |= _eod_held()
    return s


def _cur_price(code):
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str}, usecols=["code", "ts", "close"])
        gg = df[df["code"].str.zfill(6) == code].sort_values("ts")
        if len(gg): return float(gg["close"].iloc[-1])
    except Exception: pass
    try:
        d = json.loads(SNAP.read_text(encoding="utf-8-sig")); c = d.get("codes", {}).get(code, {})
        v = float(c.get("cur", 0) or 0)
        if v > 0: return v
    except Exception: pass
    return 0.0


def _snap_che(code):
    try:
        d = json.loads(SNAP.read_text(encoding="utf-8-sig"))
        return _safe_float((d.get("codes", {}).get(code) or {}).get("che_str"), None)
    except Exception:
        return None


def mode_pick():
    hm = datetime.now().strftime("%H%M")
    _log(f"=== GCROSS pick (LIVE={LIVE} CAP={CAP:,} CHE≥{CHE_BUY:g}) ===")
    if hm >= BUY_CUTOFF:
        _log(f"매수마감({BUY_CUTOFF}) 지남 → skip"); return
    held = _jload(POS)
    opens = [c for c, v in held.items() if isinstance(v, dict) and v.get("status") == "OPEN"]
    if len(opens) >= MAX_POS:
        _log(f"이미 {len(opens)}/{MAX_POS} 보유 → 신규없음"); return
    try:
        import position_budget as _gb
        if _gb.budget_on():
            try: _gr = _gb.remaining_intraday()
            except Exception: _gr = 0
            if _gr <= 0: _log("[GLOBAL-CAP] 전역상한 → 보류"); return
    except Exception: pass
    cand = _candidates()
    if not cand:
        _log("후보 0 (추세시작 종목 없음)"); return
    excl = _held_now()
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("broker dead → 매수보류"); return
    bought = 0
    for code, info in cand.items():
        if len(opens) + bought >= MAX_POS: break
        if code in excl or (code in held and held[code].get("status") == "OPEN"): continue
        cur = _cur_price(code)
        if cur <= 0: continue
        che = _snap_che(code)
        if che is None or che < CHE_BUY:                  # ★체결강도 하드게이트(데이터없으면 매수금지)
            _log(f"매수보류 {code}: 체결강도 {che} < {CHE_BUY:g} (확인필수)"); continue
        # [대장주 우선 필터 2026-06-30 친구님] 거래대금 상위 LEADER_TOP_N 밖이면 소형주로 보고 매수금지. fail-open·끄기 setx LEADER_FILTER NO.
        try:
            import leader_filter as _lf
            if not _lf.is_leader(bc, code):
                _log(f"매수보류 {code}: 거래대금 상위 {_lf.TOP_N}위 밖(비대장·소형주) — 대장주우선필터"); continue
        except Exception:
            pass
        qty = max(1, int(CAP // cur))
        # ★[2026-07-06 친구님 "GC560도 넣어줘"] 스마트머니 던지기 회피(공용모듈·외국인+프로그램 실시간)
        try:
            import smart_money as _SM
            _blk, _smi = _SM.dumping(bc, code, cur)
            if _blk:
                _log(f"⛔ GCROSS {code} 스마트머니 던지기 차단 [{_smi}] — 매수스킵"); continue
        except Exception:
            pass
        _log(f"★GCROSS 매수 {code} 3분봉골든크로스 체결{che:.0f} @{cur:,.0f} x{qty}")
        if _order(bc, code, qty, "BUY", "PICK"):
            held[code] = {"code": code, "qty": qty, "buy_price": cur, "info": info.get("info", "3분봉GC"),
                          "date": datetime.now().strftime("%Y%m%d"), "status": "OPEN",
                          "peak": cur, "che_prev": che, "ts": datetime.now().isoformat()}
            _jsave(POS, held)
            try:                                   # ★재매수 금지 가드(스펙8): MA5<MA20 재발생 전엔 같은 크로스 재매수 안함
                import golden_cross_signal as _gcs; _gcs.mark_bought(code)
            except Exception: pass
            if LIVE:
                rt = _jload(RT_OPEN)
                rt[code] = {"qty": qty, "entry_price": cur, "code": code, "strategy": "GCROSS", "peak_price": cur}
                _jsave(RT_OPEN, rt)
            bought += 1
    if not bought:
        _log(f"신규매수 0 (후보 {len(cand)}·체결강도/충돌/캡)")


def mode_manage(force_eod=False):
    """청산(당일): che_exit(체결강도+5선이탈) + 하드손절 + ★EOD 15:18 강제청산(오버나잇X·당일 매수매도)."""
    held = _jload(POS)
    opens = {c: v for c, v in held.items() if isinstance(v, dict) and v.get("status") == "OPEN" and float(v.get("qty", 0) or 0) > 0}
    if not opens: return
    hm = datetime.now().strftime("%H%M")
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("[MANAGE] broker dead → 청산보류"); return
    try:
        import exit_ma as _DMA
    except Exception:
        _DMA = None
    for code, p in list(opens.items()):
      try:
        qty = int(p["qty"]); buy = float(p["buy_price"]); cur = _cur_price(code)
        if cur <= 0:
            if force_eod or hm >= EOD_HM:        # 가격조회실패+장마감 → 시장가 강제청산(오버나잇 방지)
                _log(f"[MANAGE] ★EOD강제청산(가격조회실패→시장가) {code} x{qty}")
                if _order(bc, code, qty, "SELL", "MANAGE"):
                    held[code]["status"] = "CLOSED"; _jsave(POS, held)
                    if LIVE: rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)
            continue
        pnl = (cur / buy - 1) * 100
        peak = max(float(p.get("peak", buy) or buy), cur)
        if peak != p.get("peak"): held[code]["peak"] = peak; _jsave(POS, held)
        m5 = _DMA.ma5(code) if _DMA else 0.0
        m20 = _DMA.ma20(code) if _DMA else 0.0
        che = _snap_che(code)
        reason = None
        if force_eod or hm >= EOD_HM:            # ★당일청산(오버나잇X) — 친구님 "당일 매수매도"
            reason = f"EOD당일청산 {pnl:+.1f}%"
        elif cur <= buy * (1 - HARD_STOP / 100):
            reason = f"하드손절-{HARD_STOP:.0f}% {pnl:+.1f}%"
        elif os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES":
            # [통일 매도 2026-07-01 친구님] 수급/MA는 vol_exit(매수우위 보유·매도우위+20선 무조건 매도)
            try:
                import vol_exit as _VE
                _s2, _r2 = _VE.decide(code, buy, peak, cur, ma20_hard=True, che=(che if isinstance(che, (int, float)) else None))
                if _s2:
                    reason = f"{_r2} {pnl:+.1f}%"
            except Exception:
                pass
        elif CHE_EXIT_ON and _che_mod is not None:
            sell, rs, tg, _d, _s = _che_mod.decide(cur, buy, peak, pnl, che, p.get("che_prev"), GC_CHE_PARAMS, ma5=m5, ma20=m20)
            if che is not None and che != p.get("che_prev"): held[code]["che_prev"] = che; _jsave(POS, held)
            if sell: reason = f"{tg} {pnl:+.1f}%"
        if not reason and os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() != "YES" and m5 > 0 and cur < m5:            # 폴백: che_exit 못쓸때 5선이탈(통일매도시 vol_exit이 처리)
            reason = f"5선이탈 {pnl:+.1f}%"
        if reason:
            _log(f"[MANAGE] ★매도 {code} x{qty} @{cur:,.0f} ({reason})")
            if _order(bc, code, qty, "SELL", "MANAGE"):
                held[code]["status"] = "CLOSED"; held[code]["sell_price"] = cur; _jsave(POS, held)
                if LIVE:
                    rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)
      except Exception as _e:
        _log(f"[MANAGE] {code} 처리오류(격리): {_e}"); continue


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    _log(f"=== GCROSS executor [{mode}] LIVE={LIVE} ===")
    if mode == "pick":
        mode_pick(); mode_manage()
    elif mode == "manage":
        mode_manage()
    elif mode == "sell":
        mode_manage(force_eod=True)        # ★당일청산(15:18 스케줄)
    _log(f"=== GCROSS executor [{mode}] done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)
