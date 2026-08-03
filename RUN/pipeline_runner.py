"""
pipeline_runner.py  [2026-04-29]
SAFEPLUS PIPELINE - Adaptive Learning System (Hedge Fund Grade)

  STARTUP (1회):
    STEP 0a: make_prev_day_summary   (feature freshness - prev_day_summary.csv)
    STEP 0b: collect_prices_3m       (feature freshness - prices_3m.csv)

  DAEMON LOOP (09:00~15:30, LOOP_INTERVAL_SEC 간격):
    STEP 1 : INTRADAY               (signal / entry)
    STEP 2 : SIGA / SCOREBOARD     ─┐
    STEP 3 : BRIDGE_EOD             │  INTRADAY RC≠0 이면 이번 사이클 스킵
    STEP 4 : RISK                   │
    STEP 5 : EXEC                   │
    STEP 6 : BRIDGE                 │
    STEP 7 : QUEUE                 ─┘

  EOD (15:30 이후 1회):
    STEP 8 : EVOLUTION              (자기진화 - 항상 실행)
    STEP 9 : PNL / LEDGER / FEEDBACK (fill → ledger - 항상 실행)

설계 원칙:
  Task Scheduler는 데몬 시작 1회만 담당.
  장중 반복 실행은 내부 루프가 담당. 스케줄러 의존 없음.
  매매(STEP 2~7)와 학습(STEP 8~9) 완전 분리.
  어떤 상황에서도 STEP 8/9 실행 보장.
  단일 사이클 실패가 데몬 전체를 중단시키지 않음.
  Reference: Lopez de Prado, Advances in Financial Machine Learning
"""
import json


# [CYCLE-6 2026-05-21] event_journal.jsonl inline helper
def _emit_event(event_type, entity, entity_id="", payload=None):
    """[CYCLE-6] event_journal.jsonl append-only (fail-safe)."""
    try:
        from pathlib import Path as _P
        from datetime import datetime as _dt
        _evt_path = _P(r"C:\stock_bot\LOG") / f"event_journal_{_dt.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": _dt.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "pipeline_runner",
        }
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PYTHON   = r"C:\Python310-32\python.exe"
BASE     = Path(r"C:\stock_bot")
RUN_DIR  = BASE / "RUN"
DATA_DIR = BASE / "DATA"
LOG_DIR  = DATA_DIR / "LOG"
PB_DIR   = BASE / "추세눌림"

LOOP_INTERVAL_SEC  = 45    # [v4_9-PT] 사이클 간격 30→45초 (종목 많을 때 타임아웃 회피)
CYCLE_TIMEOUT_SEC  = 120   # [R26 2026-05-14] 60→120 (R15 CONNECT_TIMEOUT_SEC=60 실 작동 보장).
                           # [v4_9-PT] 단일 사이클 최대 허용 시간 30→60초 (R26 이전)
                           # subprocess timeout = CYCLE_TIMEOUT_SEC - 2 = 118s (R26 후) → buy_sender LOGIN 60s + 여유 58s
MARKET_OPEN_HHMM   = 900   # 09:00
MARKET_CLOSE_HHMM  = 1530  # 15:30

HEARTBEAT_FILE   = LOG_DIR / "pipeline_heartbeat.txt"
EXEC_SIGNAL_FILE = LOG_DIR / "rt_execution_signal.json"

# 이전 사이클이 실행 중인 동안 새 사이클 진입을 막는 락
_CYCLE_LOCK = threading.Lock()


def _run(script: Path) -> int:
    # [NO-WINDOW 2026-05-08] CREATE_NO_WINDOW — STEP 자식 프로세스 콘솔창 폭주 방지
    return subprocess.run(
        [PYTHON, "-X", "utf8", str(script)],
        check=False,
        timeout=CYCLE_TIMEOUT_SEC - 2,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hhmm() -> int:
    return int(datetime.now().strftime("%H%M"))


def _check(label: str, path: Path) -> None:
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [FILE] {label}: 존재 / 최종 수정 {mtime}", flush=True)
    else:
        print(f"  [WARN] {label}: 없음", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# HEARTBEAT  - watchdog 감지용. 매 루프 반복마다 파일 갱신 + 로그 출력.
# ──────────────────────────────────────────────────────────────────────────

def _write_heartbeat(cycle: int) -> None:
    try:
        HEARTBEAT_FILE.write_text(f"{_ts()}  cycle={cycle}", encoding="utf-8")
    except OSError:
        pass
    print(f"[ALIVE] {_ts()}  cycle={cycle}", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# SYMBOL ORDER LOCK + DATA GUARD
#   · EXEC_SIGNAL_FILE(rt_execution_signal.json) 에서 종목·날짜 검증.
#   · 동일 종목은 당일 1회만 QUEUE 진입 허용.
#   · 락 파일: DATA/symbol_order_lock_YYYYMMDD.json
# ──────────────────────────────────────────────────────────────────────────

def _order_lock_file() -> Path:
    return DATA_DIR / f"symbol_order_lock_{datetime.now().strftime('%Y%m%d')}.json"


def _load_exec_signal() -> dict | None:
    try:
        if EXEC_SIGNAL_FILE.exists():
            return json.loads(EXEC_SIGNAL_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _queue_has_pending_buy() -> bool:
    """[LIMBO-FIX 2026-06-05] 큐에 미체결 BUY행이 있는지 확인(=buy_sender 드레인 필요).
    freshness(30분 stale) 판정은 buy_sender에 위임 — 여기선 BUY행 존재만 본다.
    예외/없음 → False(보수적, 드레인 안 함)."""
    try:
        import csv
        qp = DATA_DIR / "queue" / "kjs_execute_queue.csv"
        if not qp.exists():
            return False
        with open(qp, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if str(row.get("side", "")).strip().upper() == "BUY":
                    return True
    except Exception:
        return False
    return False


def _check_siga_bought() -> bool:
    sig = _load_exec_signal()
    if not sig:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if str(sig.get("date", "")) != today:
        return False
    try:
        return int(sig.get("siga_daily_count", 0)) > 0
    except (TypeError, ValueError):
        return False


def _is_symbol_ordered(symbol: str) -> bool:
    try:
        f = _order_lock_file()
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            return symbol in data.get("ordered", {})
    except (json.JSONDecodeError, OSError):
        pass
    return False


def _mark_symbol_ordered(symbol: str, signal: dict) -> None:
    f   = _order_lock_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    if "ordered" not in data:
        data["ordered"] = {}
    data["ordered"][symbol] = {
        "time":  _ts(),
        "price": signal.get("price_ref", 0),
        "qty":   signal.get("qty", 0),
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if f.exists():
            f.unlink()
        tmp.rename(f)
        print(
            f"[ORDER_LOCK] {symbol} 주문 lock 설정 - "
            f"price={signal.get('price_ref', 0)}  qty={signal.get('qty', 0)}",
            flush=True,
        )
    except OSError as e:
        print(f"[ORDER_LOCK] lock 파일 저장 실패: {e}", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# SAFE LOOP GUARD  - 사이클을 별도 스레드로 실행.
#   · 이전 사이클이 아직 실행 중이면 즉시 skip (주문 폭주 방지).
#   · CYCLE_TIMEOUT_SEC 초과 시 timeout 로그 후 메인 루프 복귀.
#     (백그라운드 스레드는 완료까지 계속 실행되며, 완료 시 락 해제.)
# ──────────────────────────────────────────────────────────────────────────

def _run_cycle_guarded(scripts: dict, cycle: int) -> None:
    if not _CYCLE_LOCK.acquire(blocking=False):
        print(f"[GUARD] CYCLE {cycle} - 이전 사이클 실행 중, 건너뜀.", flush=True)
        return

    def _target() -> None:
        try:
            _run_cycle(scripts, cycle)
        finally:
            _CYCLE_LOCK.release()

    t = threading.Thread(target=_target, daemon=True)
    t_start = time.monotonic()
    t.start()
    t.join(timeout=CYCLE_TIMEOUT_SEC)
    elapsed = time.monotonic() - t_start

    if t.is_alive():
        print(
            f"[GUARD] CYCLE {cycle} timeout - {elapsed:.1f}s 초과 "
            f"(한도 {CYCLE_TIMEOUT_SEC}s). 다음 사이클 진행.",
            flush=True,
        )


# ──────────────────────────────────────────────────────────────────────────
# STARTUP: STEP 0a / 0b  (데몬 시작 시 1회)
# ──────────────────────────────────────────────────────────────────────────

def _run_startup(scripts: dict, data: dict) -> None:
    print(f"\n[STEP 0a] make_prev_day_summary  [{_ts()}]", flush=True)
    if scripts["PREV_SUMMARY"].exists():
        rc = _run(scripts["PREV_SUMMARY"])
        print(f"[STEP 0a] RC={rc}", flush=True)
        if rc != 0:
            print(f"[WARN] PREV_SUMMARY RC={rc} - 구버전 prev_day_summary.csv 유지.", flush=True)
        else:
            print("[OK] PREV_SUMMARY done.", flush=True)
        _check("prev_day_summary.csv", data["PREV_DAY_CSV"])
    else:
        print("[SKIP] STEP 0a - file not found.", flush=True)

    _write_heartbeat(0)  # startup 진행 중 watchdog에 생존 신호

    print(f"\n[STEP 0b] collect_prices_3m  [{_ts()}]", flush=True)
    if scripts["PRICES_3M"].exists():
        rc = _run(scripts["PRICES_3M"])
        print(f"[STEP 0b] RC={rc}", flush=True)
        if rc != 0:
            print(f"[WARN] PRICES_3M RC={rc} - 구버전 prices_3m.csv 유지.", flush=True)
        else:
            print("[OK] PRICES_3M done.", flush=True)
        _check("prices_3m.csv", data["PRICES_3M_CSV"])
    else:
        print("[SKIP] STEP 0b - file not found.", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# TRADING CYCLE: STEP 1~7  (루프 1회 반복)
# 반환값 없음. 실패 시 return으로 이번 사이클 중단 → 데몬은 계속 실행.
# ──────────────────────────────────────────────────────────────────────────

def _run_cycle(scripts: dict, cycle: int) -> None:
    # [PATCH-PREFLIGHT] STEP 0c: 1일 1회 preflight 실행
    #   당일 preflight_result.json 없거나 어제자 → 실행 (mtime 기준)
    #   실행 후 siga_to_signal_bridge가 size_mult 자동 활용
    _pf_path = LOG_DIR / "preflight_result.json"
    _pf_today = False
    try:
        if _pf_path.exists():
            _pf_mtime_date = datetime.fromtimestamp(_pf_path.stat().st_mtime).date()
            _pf_today = (_pf_mtime_date == datetime.now().date())
    except OSError:
        pass
    if not _pf_today:
        _pf_script = RUN_DIR / "safeplus_preflight_gate_v2_4_VIX_FIXED.py"
        if _pf_script.exists():
            print(f"\n[STEP 0c] PREFLIGHT  [{_ts()}]", flush=True)
            rc = _run(_pf_script)
            print(f"[STEP 0c] RC={rc}", flush=True)
            if rc == 0:
                print("[OK] PREFLIGHT done.", flush=True)
            else:
                print(f"[WARN] PREFLIGHT RC={rc} - size_mult=1.0 폴백 사용", flush=True)

    # STEP 1: INTRADAY
    print(f"\n[STEP 1] INTRADAY  [{_ts()}]", flush=True)
    rc = _run(scripts["INTRADAY"])
    print(f"[STEP 1] RC={rc}", flush=True)
    if rc == 200:
        print(f"[WARN] INTRADAY RC=200 - 장외 / 신호 없음, 다음 단계 계속.", flush=True)
    elif rc != 0:
        print(f"[WARN] INTRADAY RC={rc} - 이번 사이클 스킵.", flush=True)
        return
    else:
        print("[OK] INTRADAY done.", flush=True)

    # STEP 1b: prices_3m 갱신 — [3M-INTRADAY 2026-06-01] 13:55부터 매 사이클 갱신.
    #   기존 15:28-only → 오후 스코어보드 선별창(14:00~15:28)에 3분봉이 비어 STEP1 HOLD되던 문제 해소.
    #   STEP1c(rt)·STEP2(스코어보드)보다 앞서 실행되므로 매 사이클 신선한 3분봉 공급.
    #   스크립트 ~4s·순수CSV·broker무관이라 45s 사이클 부담 미미. 15:28+는 수집기 종료 후 full rebuild 역할 유지.
    if _hhmm() >= 1355:
        print(f"\n[STEP 1b] PRICES_3M refresh (hhmm>=1355, 오후 상시갱신)  [{_ts()}]", flush=True)
        if scripts["PRICES_3M"].exists():
            rc = _run(scripts["PRICES_3M"])
            print(f"[STEP 1b] RC={rc}", flush=True)
            if rc != 0:
                print(f"[WARN] PRICES_3M refresh RC={rc} - 구버전 유지 후 계속.", flush=True)
            else:
                print("[OK] PRICES_3M refresh done.", flush=True)
        else:
            print("[SKIP] STEP 1b - file not found.", flush=True)

    # STEP 1c: rt_intraday.csv 최신화 (prices_1m → rt_intraday)  [PATCH-4]
    print(f"\n[STEP 1c] RT_INTRADAY_BUILD  [{_ts()}]", flush=True)
    if scripts["RT_INTRADAY_BUILD"].exists():
        rc = _run(scripts["RT_INTRADAY_BUILD"])
        print(f"[STEP 1c] RC={rc}", flush=True)
        if rc != 0:
            print(f"[WARN] RT_INTRADAY_BUILD RC={rc} - 구버전 rt_intraday 유지 후 계속.", flush=True)
        else:
            print("[OK] RT_INTRADAY_BUILD done.", flush=True)
    else:
        print("[SKIP] STEP 1c - file not found.", flush=True)

    # STEP 2: SIGA
    print(f"\n[STEP 2] SIGA  [{_ts()}]", flush=True)
    rc = _run(scripts["SIGA"])
    print(f"[STEP 2] RC={rc}", flush=True)
    if rc == 500:
        print("[FAIL] SIGA RC=500 - 엔진 halt, 이번 사이클 중단.", flush=True)
        return
    if rc != 0:
        print(f"[WARN] SIGA RC={rc} - 장중 HOLD, STEP3 스킵 후 계속.", flush=True)
    else:
        print("[OK] SIGA done.", flush=True)

    # STEP 3: BRIDGE_EOD
    print(f"\n[STEP 3] BRIDGE_EOD  [{_ts()}]", flush=True)
    rc = _run(scripts["BRIDGE_EOD"])
    print(f"[STEP 3] RC={rc}", flush=True)
    if rc != 0:
        print(f"[WARN] BRIDGE_EOD RC={rc} - HOLD, STEP4 계속.", flush=True)
    else:
        print("[OK] BRIDGE_EOD done.", flush=True)

    # STEP 4: RISK
    print(f"\n[STEP 4] RISK  [{_ts()}]", flush=True)
    rc = _run(scripts["RISK"])
    print(f"[STEP 4] RC={rc}", flush=True)
    if rc == 500:
        print("[FAIL] RISK RC=500 - 엔진 halt, 이번 사이클 중단.", flush=True)
        return
    if rc == 200:
        print(f"[WARN] RISK RC=200 - 종목 없음, STEP5 계속.", flush=True)
    elif rc != 0:
        print(f"[WARN] RISK RC={rc} - 이번 사이클 스킵.", flush=True)
        return
    else:
        print("[OK] RISK done.", flush=True)

    # STEP 5: EXEC
    # [SIGA-RETIRE 2026-06-01] 아침 시가매수(siga_to_signal_bridge) 폐기.
    #   사용자 설계: 아침은 EOD_PICK 시가매도 + PULLBACK만. 시가갭매수는 종가매수(EOD_PICK)로 대체됨.
    #   기존 09:00~09:08 SIGA / 09:09 SIGA유지 분기 제거 → 항상 rt_execution(PULLBACK).
    #   PULLBACK은 rt_execution 릴레이(포지션 청산 시 진입)+일반경로로 통제. _check_siga_bought 사문화.
    _hm = _hhmm()
    _exec_script = scripts["EXEC"]
    print(f"\n[STEP 5] EXEC  [{_ts()}]  target={_exec_script.name}", flush=True)
    rc = _run(_exec_script)
    print(f"[STEP 5] RC={rc}", flush=True)
    # [STEP5-RC200-FIX 2026-05-26] rt_execution_engine RC_HOLD=200 은 정상 HOLD (매수 후보 없음).
    # STEP1 INTRADAY / STEP4 RISK 와 동일 패턴으로 rc=200 시 다음 사이클 중단하지 않고 STEP6 BRIDGE 계속.
    # cycle health 유지 + bridge 호출 정상화 목적. 매수 게이트 완화 아님.
    if rc == 200:
        print(f"[WARN] EXEC RC=200 - 매수 후보 없음/HOLD, STEP6 계속.", flush=True)
    elif rc != 0:
        print(f"[WARN] EXEC RC={rc} - 이번 사이클 중단.", flush=True)
        return
    else:
        print("[OK] EXEC done.", flush=True)

    # STEP5 실행 후 signal 읽기 (ORDER_LOCK 용)
    signal    = _load_exec_signal()
    symbol    = signal.get("code", "").strip() if signal else ""
    today_str = datetime.now().strftime("%Y-%m-%d")

    # STEP 6: BRIDGE
    print(f"\n[STEP 6] BRIDGE  [{_ts()}]", flush=True)
    rc = _run(scripts["BRIDGE"])
    print(f"[STEP 6] RC={rc}", flush=True)
    # [CYCLE-6 2026-05-21] event_journal BRIDGE_RC emit
    _emit_event("BRIDGE_RC", entity="pipeline", payload={"rc": int(rc)})
    if rc == 0:
        print("[OK] BRIDGE done.", flush=True)
    elif rc == 200:
        # [LIMBO-FIX 2026-06-05] bridge rc=200(새 수락 없음/already_processed)이어도
        #   큐에 미체결 BUY행이 남아있으면 STEP7(buy_sender)을 실행해 드레인.
        #   기존: 무조건 return → 정상 후보가 큐에 박혀도 buy_sender 재실행 안 돼 영구 미체결(limbo).
        #   buy_sender 자체 게이트(conv/balance/30분stale제거/per-code ORDER_LOCK)가 안전판.
        if _queue_has_pending_buy():
            print("[LIMBO-FIX] BRIDGE RC=200 but 큐 미체결 BUY행 존재 → STEP7 드레인 진행.", flush=True)
            symbol = ""  # 스테일 exec-signal symbol로 인한 ORDER_LOCK 오판 방지 (buy_sender 자체 락 사용)
        else:
            print("[HOLD] BRIDGE RC=200 & 큐 미체결 없음 - 다음 사이클에서 재시도.", flush=True)
            # [CYCLE-6] STEP7_SKIP emit (bridge_rc_200)
            _emit_event("STEP7_SKIP", entity="pipeline", payload={"reason": "bridge_rc_200"})
            return
    else:
        print(f"[WARN] BRIDGE RC={rc} - 이번 사이클 중단.", flush=True)
        _emit_event("STEP7_SKIP", entity="pipeline", payload={"reason": f"bridge_rc_{rc}"})
        return

    # STEP 7: QUEUE - 주문 직전 종목 lock 확인, 주문 성공 후 lock 설정
    if scripts["QUEUE"].exists():
        if symbol and _is_symbol_ordered(symbol):
            print(f"[ORDER_LOCK] {symbol} 오늘 이미 주문됨 - QUEUE 스킵.", flush=True)
            # [CYCLE-6] STEP7_SKIP emit (symbol_locked)
            _emit_event("STEP7_SKIP", entity="pipeline", entity_id=symbol, payload={"reason": "symbol_locked"})
            return
        print(f"\n[STEP 7] BUY ORDER  [{_ts()}]  target={symbol}", flush=True)
        rc = _run(scripts["QUEUE"])
        print(f"[STEP 7] RC={rc}", flush=True)
        if rc == 0:
            print("[OK] BUY ORDER done.", flush=True)
            if symbol:
                _mark_symbol_ordered(symbol, signal)
        elif rc in (1, 200):
            print(f"[WARN] BUY ORDER RC={rc} - continue", flush=True)
        else:
            print(f"[FAIL] BUY ORDER RC={rc}", flush=True)
    else:
        print("\n[SKIP] STEP 7 BUY ORDER - file not found.", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# EOD: STEP 8~9  (15:30 이후 1회, 항상 실행 보장)
# ──────────────────────────────────────────────────────────────────────────

def _run_eod(scripts: dict, data: dict) -> None:
    if scripts["EVOL"].exists():
        print(f"\n[STEP 8] EVOLUTION  [{_ts()}]", flush=True)
        rc = _run(scripts["EVOL"])
        print(f"[STEP 8] RC={rc}", flush=True)
        if rc != 0:
            print(f"[WARN] EVOLUTION RC={rc} - 당일 진화 스킵, 파이프라인 계속.", flush=True)
        else:
            print("[OK] EVOLUTION done.", flush=True)
        _check("evolved_params.json", data["EVOL_PARAMS"])
    else:
        print("\n[SKIP] STEP 8 EVOLUTION - file not found.", flush=True)

    # STEP 8b: rt_learning_engine (PULLBACK 통계 학습)
    if 1530 <= _hhmm() <= 1600:
        _learning_script = Path(r"C:\stock_bot\추세눌림\rt_learning_engine_v4_5_SORTINO_FIXED.py")
        if _learning_script.exists():
            print(f"\n[STEP 8b] LEARNING  [{_ts()}]", flush=True)
            rc = _run(_learning_script)
            print(f"[STEP 8b] RC={rc}", flush=True)

    if scripts["PNL_TRACKER"].exists():
        print(f"\n[STEP 9] rt_pnl_tracker  [{_ts()}]", flush=True)
        rc = _run(scripts["PNL_TRACKER"])
        print(f"[STEP 9] RC={rc}", flush=True)
        if rc != 0:
            print(f"[WARN] PNL_TRACKER RC={rc} - rt_daily_pnl / ledger 미갱신.", flush=True)
            print("[WARN] Risk Engine / Evolution 다음 실행 시 fallback 동작 예상.", flush=True)
        else:
            print("[OK] PNL_TRACKER done.", flush=True)
        _check("rt_daily_pnl.json",    data["PNL_JSON"])
        _check("rt_trades_ledger.csv", data["TRADES_LEDGER"])
        today = datetime.now().strftime("%Y-%m-%d")
        _check(f"feedback_{today}.json", data["FB_DIR"] / f"feedback_{today}.json")
    else:
        print("\n[SKIP] STEP 9 PNL_TRACKER - file not found.", flush=True)
        print("[WARN] PNL_TRACKER 없음 - rt_daily_pnl / ledger 미갱신.", flush=True)
        print("[WARN] Kelly / Risk Engine 다음 실행 시 fallback 동작 예상.", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 스크립트 경로
    F_EXEC = RUN_DIR / "rt_execution_engine_v1_0.py"
    if not F_EXEC.exists():
        F_EXEC = RUN_DIR / "rt_execution_engine_v4_29.py"
    F_BRIDGE = RUN_DIR / "bridge_scoreboard_to_kjs_queue_v1_2_SAFEPLUS_FINAL.py"
    if not F_BRIDGE.exists():
        F_BRIDGE = RUN_DIR / "rt_signal_to_queue_bridge_v3_7_7.py"

    scripts = {
        "PREV_SUMMARY":       RUN_DIR / "make_prev_day_summary_v7_6_SAFEPLUS_FINAL.py",
        "PRICES_3M":          RUN_DIR / "collect_prices_3m_from_1m_v3_5_97점.py",
        "INTRADAY":           PB_DIR  / "rt_intraday_trend_pullback_engine_v5_14.py",
        "RT_INTRADAY_BUILD":  RUN_DIR / "make_rt_intraday_from_prices_1m_v7_23.py",  # [PATCH-4]
        "SIGA":               RUN_DIR / "kjs_scoreboard_eod_v7_9.py",
        "BRIDGE_EOD":   RUN_DIR / "kjs_bridge_eod_v9_9.py",
        "RISK":         RUN_DIR / "rt_risk_engine_v6_6.py",
        "EXEC":         F_EXEC,
        "BRIDGE":       F_BRIDGE,
        "QUEUE":        RUN_DIR / "kiwoom_buy_order_sender_v4_9.py",
        "EVOL":         RUN_DIR / "evolution_engine_v3_13_FIXED.py",
        "PNL_TRACKER":  PB_DIR  / "rt_pnl_tracker.py",
    }
    data = {
        "PREV_DAY_CSV":  DATA_DIR / "prev_day_summary.csv",
        "PRICES_3M_CSV": DATA_DIR / "prices_3m.csv",
        "EVOL_PARAMS":   DATA_DIR / "evolution" / "evolved_params.json",
        "PNL_JSON":      DATA_DIR / "rt_daily_pnl.json",
        "TRADES_LEDGER": DATA_DIR / "LEDGER" / "rt_trades_ledger.csv",
        "FB_DIR":        DATA_DIR / "evolution" / "feedback",
    }

    # PRECHECK
    print(f"[PRECHECK] {_ts()} Verifying required files...", flush=True)
    fail = False
    for label, path in [
        ("PYTHON",     Path(PYTHON)),
        ("INTRADAY",   scripts["INTRADAY"]),
        ("SIGA",       scripts["SIGA"]),
        ("BRIDGE_EOD", scripts["BRIDGE_EOD"]),
        ("RISK",       scripts["RISK"]),
        ("EXEC",       scripts["EXEC"]),
        ("BRIDGE",     scripts["BRIDGE"]),
    ]:
        if not path.exists():
            print(f"[FAIL] {label} not found: {path}", flush=True)
            fail = True
    for label, path in [
        ("PREV_SUMMARY", scripts["PREV_SUMMARY"]),
        ("PRICES_3M",    scripts["PRICES_3M"]),
    ]:
        if not path.exists():
            print(f"[WARN] {label} not found - step skipped: {path}", flush=True)
    if fail:
        print("[ABORT] Pre-check failed.", flush=True)
        sys.exit(1)
    print("[OK] Pre-check passed.", flush=True)

    # [ORDER] 매매 사이클 실행 순서 명시 — Bridge → Risk → Exec → SignalBridge → BuySender
    print(
        "[ORDER] 매매 사이클 실행 순서:\n"
        "  STEP 1  INTRADAY      = " + str(scripts["INTRADAY"]) + "\n"
        "  STEP 1c RT_INTRADAY   = " + str(scripts["RT_INTRADAY_BUILD"]) + "\n"
        "  STEP 2  SIGA          = " + str(scripts["SIGA"]) + "\n"
        "  STEP 3  BRIDGE_EOD    = " + str(scripts["BRIDGE_EOD"]) + "\n"
        "  STEP 4  RISK          = " + str(scripts["RISK"]) + "\n"
        "  STEP 5  EXEC          = " + str(scripts["EXEC"]) + "\n"
        "  STEP 6  SIGNAL_BRIDGE = " + str(scripts["BRIDGE"]) + "\n"
        "  STEP 7  BUY_ORDER     = " + str(scripts["QUEUE"]),
        flush=True,
    )

    # PRECHECK 완료 직후 첫 heartbeat - watchdog 타이머 시작점
    _write_heartbeat(0)

    # STARTUP: STEP 0a/0b (1회)
    _run_startup(scripts, data)

    # DAEMON LOOP
    print(
        f"\n[DAEMON] 시작 - 시장: {MARKET_OPEN_HHMM:04d}~{MARKET_CLOSE_HHMM:04d}"
        f"  루프간격: {LOOP_INTERVAL_SEC}s  사이클한도: {CYCLE_TIMEOUT_SEC}s  [{_ts()}]",
        flush=True,
    )
    eod_done = False
    cycle = 0

    while True:
        now = _hhmm()
        _write_heartbeat(cycle)

        # 장 마감 후: EOD 1회 실행 (매수 루프는 계속)
        if now >= MARKET_CLOSE_HHMM and not eod_done:
            print(f"\n[EOD] 15:30 도달 - STEP 8/9 실행  [{_ts()}]", flush=True)
            _run_eod(scripts, data)
            eod_done = True

        # 장 시작 전: 대기
        if now < MARKET_OPEN_HHMM:
            print(f"[WAIT] 장 시작 대기 중... 현재 {now:04d}  [{_ts()}]", flush=True)
            time.sleep(LOOP_INTERVAL_SEC)
            continue

        # 장중: 매매 사이클 (Safe Loop Guard 적용)
        cycle += 1
        print(f"\n{'='*60}", flush=True)
        print(f"[CYCLE {cycle}] {_ts()}  (현재 {now:04d})", flush=True)
        print(f"{'='*60}", flush=True)
        _run_cycle_guarded(scripts, cycle)
        time.sleep(LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    main()
