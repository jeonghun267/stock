"""
siga_to_signal_bridge.py
SIGA 전용 연결 브릿지: score_eod.csv + rt_intraday.csv → rt_execution_signal.json
기존 rt_execution_engine / rt_signal_to_queue_bridge 수정 없이 SIGA_RT_DIRECT 신호 생성.

입력:  C:\\stock_bot\\DATA\\scoreboard\\score_eod.csv   (siga_priority_score 기준 1종목 선택)
       C:\\stock_bot\\DATA\\rt_intraday.csv             (현재가 취득)
출력:  C:\\stock_bot\\DATA\\LOG\\rt_execution_signal.json
"""
import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

BASE      = Path(r"C:\stock_bot")
SCORE_EOD = BASE / "DATA" / "scoreboard" / "score_eod.csv"   # [v2] score_eod 직접 읽기
RT_CSV    = BASE / "DATA" / "rt_intraday.csv"
SIGNAL    = BASE / "DATA" / "LOG" / "rt_execution_signal.json"


def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("siga_to_signal_bridge")
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter(
            "[%(asctime)s][%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(h)
    logger.setLevel(logging.INFO)
    return logger


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run() -> int:
    log = _setup_logger()

    # [SIGA-DISABLE 2026-05-27] 시가 매수 chain 비활성화 env 가드 (종가 매수 chain 전환)
    # 사유: 시가 매수 (09:07~09:15) 효과 검증 중 chronic bug + 종가 매수 데이터 우위 (+1.54%) 결정
    # 활성화: env SIGA_ENTRY_DISABLED 제거 또는 != "YES"
    if os.environ.get("SIGA_ENTRY_DISABLED", "").strip().upper() == "YES":
        log.info("[SIGA-DISABLE] env SIGA_ENTRY_DISABLED=YES → HOLD (시가 매수 비활성)")
        return 0

    # [SIGA-WINDOW 2026-05-25] 시가 진입 시간 09:07~09:15 강제
    # 백테스트 시뮬 (1ST 68건 동일 종목, exit_price 동일 가정):
    #   09:05 +1.52% / 09:07 +2.48% / 09:10 +1.82% (승률 65%) / 09:15 +2.77%
    #   원본 09:20~10:24 EV -0.08% → 09:07~09:15 EV +2.0~2.8% 예상
    # SIGA_ENTRY_HHMM_S=905 / E=907 (siga_selection_engine_v3_2_FINAL L306~310) 정합
    _hhmm = int(datetime.now().strftime("%H%M"))
    if _hhmm < 907 or _hhmm > 915:
        log.info("[SIGA-WINDOW] %04d 진입 시간 외 (07~15) -> HOLD", _hhmm)
        return 0
    # [SIGA-RISK 2026-05-25] HARD_STOP 80~100% 시간대 차단 (안전망 — 위 윈도우와 중복이나 명시 유지)
    # 백테 검증: 09:33~09:41 = HARD_STOP 80~100% / 평균 -2.4%
    if 933 <= _hhmm <= 941:
        log.warning("[SIGA-RISK] %04d HARD_STOP 위험 시간대 차단 -> HOLD", _hhmm)
        return 0

    # ── 1) score_eod.csv 읽기 (siga_priority_score 기준 1종목 선택) ─────
    if not SCORE_EOD.exists() or SCORE_EOD.stat().st_size == 0:
        log.error("[FATAL] score_eod.csv 없음 또는 0바이트: %s", SCORE_EOD)
        return 1

    with open(SCORE_EOD, encoding="utf-8-sig", errors="replace") as f:
        eod_rows = list(csv.DictReader(f))

    if not eod_rows:
        log.error("[FATAL] score_eod.csv 행 없음")
        return 1

    # ── rt_intraday 코드 집합 (현재가 있는 종목만) — 교집합 필터용 ──────
    rt_codes: set = set()
    rt_strategy_map: dict = {}   # [v7_9 PATCH1 DUAL] code → strategy_hint
    if RT_CSV.exists():
        try:
            with open(RT_CSV, encoding="utf-8-sig", errors="replace") as f:
                for _row in csv.DictReader(f):
                    _c  = str(_row.get("code", "")).strip().zfill(6)
                    try:
                        _pr = float(_row.get("close_today") or _row.get("price_ref") or 0)
                    except (TypeError, ValueError):
                        _pr = 0.0
                    if _c and _pr > 0:
                        rt_codes.add(_c)
                        rt_strategy_map[_c] = str(_row.get("strategy_hint", "SIGA")).strip().upper()
        except Exception as e:
            log.warning("[SIGA-BRIDGE] rt_intraday.csv(교집합) 읽기 실패: %s", e)

    # siga_entry_class=SKIP 제외 → rt_intraday 교집합 → siga_priority_score 기준 정렬 → 1종목 선택
    cands = [r for r in eod_rows if str(r.get("siga_entry_class", "WATCH")).upper() != "SKIP"]
    if not cands:
        log.warning("[SIGA-BRIDGE] SKIP 아닌 후보 없음 → 전체 대상 fallback")
        cands = eod_rows
    def _f(v, default: float = 0.0) -> float:
        try: return float(v)
        except (TypeError, ValueError): return default
    _test_price_override = 0.0   # TEST fallback 시 prices_1m 주입 가격
    cands = [r for r in cands if str(r.get("code", "")).strip().zfill(6) in rt_codes]
    if not cands:
        _test_mode = os.environ.get("REAL_TEST_MODE", "true").lower() == "true"
        if not _test_mode:
            log.warning("[SIGA-BRIDGE] HOLD: score_eod ∩ rt_intraday = 0 → 현재가 있는 후보 없음")
            return 0
        # ── TEST fallback: rt_intraday 1등 행 직접 선택 ─────────────────
        _rt_all: list = []
        if RT_CSV.exists():
            try:
                with open(RT_CSV, encoding="utf-8-sig", errors="replace") as _f2:
                    _rt_all = [r for r in csv.DictReader(_f2)
                               if str(r.get("code", "")).strip()]
            except Exception as _e:
                log.warning("[SIGA-BRIDGE] TEST rt_intraday 읽기 실패: %s", _e)
        if not _rt_all:
            log.warning("[SIGA-BRIDGE] HOLD(TEST): rt_intraday 후보 없음")
            return 0
        _rt_all.sort(key=lambda r: _f(r.get("prescore_weighted", 0)), reverse=True)
        _fb  = _rt_all[0]
        # [v7_9 PATCH4] fallback 품질 검증 — 미달 시 HOLD
        if _f(_fb.get("prescore_weighted", 0)) < 0.50:
            log.warning("[SIGA-BRIDGE] HOLD(TEST): fallback prescore 미달 %.2f",
                        _f(_fb.get("prescore_weighted", 0)))
            return 0
        if _f(_fb.get("attack_score", 0)) < 0.55:
            log.warning("[SIGA-BRIDGE] HOLD(TEST): fallback attack_score 미달 %.2f",
                        _f(_fb.get("attack_score", 0)))
            return 0
        if _f(_fb.get("stable_score", 0)) < 0.30:
            log.warning("[SIGA-BRIDGE] HOLD(TEST): fallback stable_score 미달 %.2f",
                        _f(_fb.get("stable_score", 0)))
            return 0
        _fbc = str(_fb.get("code", "")).strip().zfill(6)
        # prices_1m.csv에서 종가 취득
        try:
            _p1m = BASE / "DATA" / "prices_1m.csv"
            if _p1m.exists():
                with open(_p1m, encoding="utf-8-sig", errors="replace") as _pf:
                    _last_p = None
                    for _pr in csv.DictReader(_pf):
                        if str(_pr.get("code", "")).strip().zfill(6) == _fbc:
                            _last_p = _pr
                    if _last_p:
                        _test_price_override = _f(
                            _last_p.get("close") or _last_p.get("close_price", 0))
        except Exception as _pe:
            log.warning("[SIGA-BRIDGE] TEST prices_1m 조회 실패: %s", _pe)
        if _test_price_override <= 0:
            log.warning("[SIGA-BRIDGE] HOLD(TEST): prices_1m에서 %s 종가 없음", _fbc)
            return 0
        log.warning("[SIGA-BRIDGE][TEST] fallback 선택: code=%s prescore=%.2f close=%.0f",
                    _fbc, _f(_fb.get("prescore_weighted", 0)), _test_price_override)
        cands = [{
            "code":                _fbc,
            "siga_priority_score": _fb.get("prescore_weighted", "0"),
            "siga_entry_class":    "TEST",
            "attack_score":        _fb.get("attack_score",  "0.70"),
            "defense_score":       _fb.get("stable_score",  "0"),
            "gap_predict_score":   "0",
            "score_final":         _fb.get("prescore_weighted", "0"),
        }]
    # [v7_9 PATCH1 DUAL] strategy_hint 기준으로 점수 컬럼 선택
    def _dual_score_key(r):
        _c = str(r.get("code", "")).strip().zfill(6)
        if rt_strategy_map.get(_c, "SIGA") == "PULLBACK":
            return _f(r.get("pullback_score", 0)) or _f(r.get("siga_priority_score", 0))
        return _f(r.get("siga_score", 0)) or _f(r.get("siga_priority_score", 0))
    cands.sort(key=_dual_score_key, reverse=True)
    top         = cands[0]
    code        = str(top.get("code", "")).strip().zfill(6)
    siga_ps     = _f(top.get("siga_priority_score", 0))
    confidence  = _f(top.get("score_final") or top.get("score", 0))
    close_price = 0.0   # score_eod.csv에 close 없음 → rt_intraday에서 취득
    _gps        = _f(top.get("gap_predict_score", 0))
    gap_grade   = "A" if _gps >= 10 else ("B" if _gps >= 5 else "C")
    attack_sc   = _f(top.get("attack_score", 0.70))
    _ds         = _f(top.get("defense_score", 0))
    stable_sc   = _ds if _ds > 0 else 0.30

    log.info("[SIGA-BRIDGE] score_eod: %d종목(SKIP제외∩RT=%d) → 선택: %s siga_priority_score=%.2f",
             len(cands), len(rt_codes), code, siga_ps)

    # ── 2) rt_intraday.csv 에서 보조 데이터 ─────────────────────────
    rt_row: dict = {}
    if RT_CSV.exists():
        try:
            with open(RT_CSV, encoding="utf-8-sig", errors="replace") as f:
                for row in csv.DictReader(f):
                    if str(row.get("code", "")).strip().zfill(6) == code:
                        rt_row = row
                        break
        except Exception as e:
            log.warning("[SIGA-BRIDGE] rt_intraday.csv 읽기 실패: %s", e)

    ofi_last10   = _f(rt_row.get("ofi_last10", 0))
    kosdaq_chg   = _f(rt_row.get("kosdaq_chg_pct", 0))
    dv_accel     = _f(rt_row.get("dv_accel", 0.0))
    rt_close     = _f(rt_row.get("close_today") or rt_row.get("price_ref", 0))
    if rt_close > 0 and close_price == 0:
        close_price = rt_close
    # [v7_9 PATCH2 VWAP] VWAP 하방 진입 차단 — price_vs_vwap < 1.0 이면 HOLD
    _pvwap = _f(rt_row.get("price_vs_vwap", 1.0))
    if rt_row and 0 < _pvwap < 1.0:
        log.warning("[SIGA-BRIDGE] HOLD(VWAP_RECLAIM): price<vwap pvwap=%.4f → 진입 보류 code=%s",
                    _pvwap, code)
        return 0
    if rt_row:
        log.info("[SIGA-BRIDGE] VWAP OK: pvwap=%.4f code=%s", _pvwap, code)
    if close_price == 0 and _test_price_override > 0:
        close_price = _test_price_override

    # ── 3) 신호 필드 계산 ───────────────────────────────────────────
    ride_score = max(siga_ps / 100.0, 0.50)
    price_ref  = int(close_price) if close_price > 0 else 0
    ts_str     = datetime.now().strftime("%Y%m%d%H%M%S")
    date_str   = datetime.now().strftime("%Y-%m-%d")

    # ── 4) 포지션 사이징 — SIGA = 항상 ATTACK(70%) ──────────────────
    REAL_TEST_MODE    = os.environ.get("REAL_TEST_MODE", "true").lower() == "true"
    REAL_TEST_CAPITAL = int(os.environ.get("REAL_TEST_CAPITAL", "2000000"))
    TOTAL_CAPITAL     = int(os.environ.get("TOTAL_CAPITAL",    "50000000"))
    capital           = REAL_TEST_CAPITAL if REAL_TEST_MODE else TOTAL_CAPITAL

    size_mult = 1.0
    entry_mode_hint = "NORMAL"   # [PATCH-PREFLIGHT-BLOCK] 기본값 (preflight 부재 시 통과)
    pf_path   = BASE / "DATA" / "LOG" / "preflight_result.json"
    try:
        if pf_path.exists():
            with open(pf_path, "r", encoding="utf-8-sig") as _f:
                pf = json.load(_f)
            size_mult = float(pf.get("size_mult", 1.0))
            size_mult = max(0.1, min(1.0, size_mult))
            entry_mode_hint = str(pf.get("entry_mode_hint", "NORMAL")).upper()
    except Exception as e:
        log.warning("[SIGA-BRIDGE] preflight_result 읽기 실패 → size_mult=1.0: %s", e)

    # [PATCH-PREFLIGHT-BLOCK] entry_mode_hint == "BLOCK" → 즉시 HOLD
    #   FORCE_ENTRY/FALLBACK 흐름은 막지 않음 (1일1회 보장 통과)
    if entry_mode_hint == "BLOCK":
        log.warning("[SIGA-BRIDGE][PREFLIGHT-BLOCK] entry_mode_hint=BLOCK → 진입 차단 HOLD")
        return 0

    KELLY_FRAC    = 0.50
    ATTACK_CAP    = 0.70
    fraction      = min(max(KELLY_FRAC, ATTACK_CAP), ATTACK_CAP)  # 0.70
    order_krw     = int(capital * fraction * size_mult)
    qty           = int(order_krw / price_ref) if price_ref > 0 else 0

    log.info(
        "[SIGA-BRIDGE] 사이징 상세: REAL_TEST_MODE=%s capital=%d"
        " fraction=%.2f size_mult=%.2f order_krw=%d price_ref=%d qty=%d",
        REAL_TEST_MODE, capital, fraction, size_mult, order_krw, price_ref, qty,
    )

    # ── 사이징 가드 — 0원/0주 신호 차단 ─────────────────────────────
    if price_ref <= 0:
        log.warning(
            "[SIGA-BRIDGE] HOLD: price_ref=%d ≤ 0"
            " → rt_intraday.csv에 %s 현재가 없음. 신호 생성 중단.",
            price_ref, code,
        )
        return 0
    if capital <= 0:
        log.warning(
            "[SIGA-BRIDGE] HOLD: capital=%d ≤ 0"
            " (REAL_TEST_MODE=%s REAL_TEST_CAPITAL=%d TOTAL_CAPITAL=%d)"
            " → 환경변수 확인 필요. 신호 생성 중단.",
            capital, REAL_TEST_MODE, REAL_TEST_CAPITAL, TOTAL_CAPITAL,
        )
        return 0
    if order_krw <= 0:
        log.warning(
            "[SIGA-BRIDGE] HOLD: order_krw=%d ≤ 0"
            " (capital=%d fraction=%.2f size_mult=%.2f)"
            " → 투자금 산출 불가. 신호 생성 중단.",
            order_krw, capital, fraction, size_mult,
        )
        return 0
    if qty <= 0:
        log.warning(
            "[SIGA-BRIDGE] HOLD: qty=%d ≤ 0"
            " (order_krw=%d price_ref=%d)"
            " → 주문 수량 산출 불가. 신호 생성 중단.",
            qty, order_krw, price_ref,
        )
        return 0

    signal: dict = {
        "code":              code,
        "strategy_hint":     "SIGA_RT_DIRECT",
        "strategy_type":     "SIGA",
        "mode":              "SIGA",
        "ride_score":        round(ride_score, 4),
        "ride_score_live":   round(ride_score, 4),
        "price_ref":         price_ref,
        "qty":               qty,
        "order_krw":         order_krw,
        "regime":            "NEUTRAL",
        "ev_pct":            round(siga_ps, 4),
        "selection_score":   round(siga_ps, 4),
        "gap_grade":         gap_grade,
        "gap_predict_score": gap_grade,
        "siga_enable":       True,
        "pullback_enable":   False,
        "kelly_fraction":    KELLY_FRAC,
        "ts":                ts_str,
        "date":              date_str,
        "daily_trade_count": 1,
        "siga_daily_count":  1,
        "accel":             None,
        "inst_days":         0,
        "ofi_last10":        round(ofi_last10, 4),
        "kosdaq_chg_pct":    round(kosdaq_chg, 2),
        "attack_score":      round(attack_sc, 4),
        "stable_score":      round(stable_sc, 4),
        "profit_factor":     0.0,
        "sharpe":            0.0,
        "sortino":           0.0,
        "max_drawdown":      0.0,
        "prescore":          round(siga_ps, 4),
        "profit_evaluated":  False,
        "evolve_weight":     1.0,
        "time_weight":       1.0,
        "bridge_ev_weight":  1.0,
        "switch_mode":       False,
        "spread_pct":        0.0,
        "tick_accel":        0.0,
        "trade_count":       0,
        "dv_accel":          round(dv_accel, 4),
    }

    _atomic_write_json(SIGNAL, signal)
    log.info(
        "[SIGA-BRIDGE] 신호 저장: code=%s siga_ps=%.2f ride=%.4f price_ref=%d qty=%d order_krw=%d → %s",
        code, siga_ps, ride_score, price_ref, qty, order_krw, SIGNAL,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
