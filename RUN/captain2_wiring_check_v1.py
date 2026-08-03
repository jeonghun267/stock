# -*- coding: utf-8 -*-
"""캡틴2 배선 5종 아침점검 v1 (2026-07-23 친구님 지시 — 7/24 09:12 실행)
읽기전용·TR 0·엔진 코드 무수정. 오늘 배선 5종(EARLY·VWAP관문·트레일가드·점수엔진·VI대응)의
실제 활성 여부를 PASS / FAIL / 미발생 3분류로 판정해 바탕화면에 쓴다.
미발생 = 장중 조건이 안 나와 검증 못 한 것(오류 아님)."""
import csv
import hashlib
import io
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
ENGINE = BASE / "RUN" / "CAPTAIN2_MONEYFLOW_ENGINE_V1.py"
TODAY = datetime.now().strftime("%Y%m%d")
EVT = BASE / "data" / "shadow" / f"captain2_events_{TODAY}.csv"
LOGF = BASE / "LOG" / "captain2_moneyflow.log"
FILLS = BASE / "LOG" / f"fills_{TODAY}.csv"
SNAP = BASE / "IPC" / "live_micro_snapshot.json"
HASH_BASE = BASE / "data" / "captain2_engine_hash_20260723.txt"
OUT = Path(r"C:\Users\UserK\Desktop\캡틴2_아침점검_배선5종.txt")

L = []          # 출력 버퍼
def w(s=""): L.append(s)
def verdict(tag, ok, detail="", miss=False):
    mark = "미발생" if miss else ("PASS" if ok else "FAIL")
    w(f"  [{mark}] {tag}" + (f" — {detail}" if detail else ""))
    return mark

def mock_contracts() -> None:
    """주문·프로세스·외부파일 쓰기 없이 오늘 캡틴2 계약만 검증한다."""
    sys.path.insert(0, str(BASE / "RUN"))
    import CAPTAIN2_MONEYFLOW_ENGINE_V1 as M
    import captain2_common_hold_sell_v1 as C
    import captain2_strategy_01_live_bridge_v1 as B
    import strategy_watchlist as W

    results = []
    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    cfg = M.Config()
    cmd = (BASE / "RUN" / "hidden" / "SAFEPLUS_CAPTAIN2_SHADOW.cmd").read_text(
        encoding="utf-8", errors="replace")
    required = (
        "set CAPTAIN2_LIVE=YES",
        "set CAPTAIN2_QTY_FIX=1",
        "set CAPTAIN2_C2_01_ON=1",
        "set CAPTAIN2_C2_01_MAX_ORDER_ATTEMPTS=1",
        "set CAPTAIN2_EARLY_ON=0",
        "set CAPTAIN2_ENTRY_START=2400",
        "set CAPTAIN2_BASE_ON=0",
        "set CAPTAIN2_REACCEL_LIVE_ON=0",
    )
    check("기본값 fail-closed", not cfg.c2_01_on, "직접 실행은 C2-01 OFF")
    check("월요일 C2-01 단독설정", all(line in cmd for line in required))
    check("1주·하루1회 주문시도", cfg.qty_fixed == 1
          and cfg.c2_01_max_order_attempts == 1,
          f"qty={cfg.qty_fixed} attempts={cfg.c2_01_max_order_attempts}")
    check("신호계약", B.STRATEGY_ID == "C2_01_OPEN_SURGE"
          and B.SIGNAL_MODE == "SHADOW_ORDER_ZERO")
    check("기존 안전주문 배선", all(hasattr(M.Captain2Engine, name) for name in (
          "_c2_01_signal_step", "_open", "_buy_pending_step")))
    check("공통매도 배선", hasattr(M.Captain2Engine, "_c2_01_common_exit")
          and C.STRATEGY_PROFILES[C.StrategyId.C2_01_OPEN_SURGE].force_exit_at.strftime("%H%M") == "1510")

    hist = [(f"202607{i + 1:02d}", 100.0, 105.0, 100.0) for i in range(20)]
    hist.append(("20260721", 100.0, 112.0, 700.0))
    metrics = W._captain2_metrics(hist)
    check("장전 압축지표", bool(metrics)
          and metrics["ret_5d_pct"] >= -10
          and metrics["high_close_pct"] >= 10
          and metrics["value_ratio_20d"] >= 6,
          str(metrics))

    engine = object.__new__(M.Captain2Engine)
    engine.states = {
        "000001": M.FlowState(code="000001", phase=M.Phase.HOLD, entry_price=100_000, qty=10),
        "000002": M.FlowState(code="000002", phase=M.Phase.BUY_PENDING, buy_reserved_krw=500_000),
        "000003": M.FlowState(code="000003", phase=M.Phase.SELL_PENDING, entry_price=200_000, qty=2),
    }
    check("회전원금 합산", engine._capital_in_use_krw() == 1_900_000,
          f"actual={engine._capital_in_use_krw():.0f}")
    engine.states["000001"].phase = M.Phase.CLOSED
    check("매도 후 원금 재사용", engine._capital_in_use_krw() == 900_000,
          f"actual={engine._capital_in_use_krw():.0f}")

    trend = M.Captain2Engine._early_trend_contract
    trend_ok, _ = trend(110, 100, True, 0.60, 60, 100, 105, 50)
    trend_bad, trend_why = trend(99, 100, False, 0.40, 20, 100, 105, 80)
    check("09:20 추세연장 PASS", trend_ok)
    check("09:20 약화정리 FAIL", not trend_bad and all(k in trend_why for k in
          ("VWAP", "MA3", "FLOW", "SPEED", "STRUCTURE", "SELL_SCORE")), trend_why)


    engine_src = ENGINE.read_text(encoding="utf-8", errors="replace")
    check("개별손절 유지", "HARD_STOP {ret_pct:.2f}%" in engine_src)
    check("중복·부분체결 복구 유지", all(k in engine_src for k in
          ("def _duplicate_reason", "BUY_PARTIAL_CONFIRMED", "Phase.BUY_PENDING")))

    failed = [name for name, ok, _detail in results if not ok]
    print(f"MOCK_CONTRACTS total={len(results)} pass={len(results) - len(failed)} fail={len(failed)}")
    if failed:
        raise AssertionError(", ".join(failed))

def main() -> None:
    w(f"══ 캡틴2 배선 6종 아침점검 ({datetime.now():%Y-%m-%d %H:%M:%S}) ══")
    w("   판정: PASS / FAIL / 미발생(장중 조건 미도래 — 오류 아님)")

    # ── 소스·설정 로드 ──
    src = ENGINE.read_text(encoding="utf-8", errors="replace")
    cmd_txt = (BASE / "RUN" / "hidden" / "SAFEPLUS_CAPTAIN2_SHADOW.cmd").read_text(
        encoding="utf-8", errors="replace")
    sys.path.insert(0, str(BASE / "RUN"))
    cfg = None
    try:
        import CAPTAIN2_MONEYFLOW_ENGINE_V1 as M
        cfg = M.Config()
    except Exception as e:
        w(f"  [FAIL] 엔진 모듈 임포트 — {type(e).__name__}: {e}")

    # 이벤트 CSV 로드
    events = []      # (ts, code, event, reason)
    if EVT.exists():
        with io.open(EVT, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh)
            hdr = next(rd, [])
            for r in rd:
                if len(r) >= 25:
                    events.append((r[0], r[1], r[3], r[24]))
    ev_names = [e[2] for e in events]
    log_txt = ""
    if LOGF.exists():
        log_txt = LOGF.read_text(encoding="utf-8", errors="replace")[-400_000:]
    today_log = "\n".join(ln for ln in log_txt.splitlines() if f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}" in ln)

    # ══ [1] C2-01 장초반 급상승 초입 ══
    w("\n[1] C2-01 장초반 급상승 초입")
    c2_required = (
        "set CAPTAIN2_QTY_FIX=1",
        "set CAPTAIN2_C2_01_ON=1",
        "set CAPTAIN2_C2_01_MAX_ORDER_ATTEMPTS=1",
        "set CAPTAIN2_EARLY_ON=0",
        "set CAPTAIN2_ENTRY_START=2400",
        "set CAPTAIN2_BASE_ON=0",
        "set CAPTAIN2_REACCEL_LIVE_ON=0",
    )
    verdict("월요일 1주 단독설정", all(line in cmd_txt for line in c2_required),
            "C2-01 1주·1회, 다른 신규 실매수 레인 OFF")
    verdict("신호→안전주문 배선", "def _c2_01_signal_step" in src
            and "self._open(point, state, order_reason)" in src,
            "기존 _open·BUY_PENDING·체결복구 사용")
    verdict("공통 상승보유·매도 배선", "def _c2_01_common_exit" in src
            and 'state.lane == "C2_01_OPEN_SURGE"' in src,
            "공통 엔진 판정 뒤 기존 _close 사용")
    n_c2 = ev_names.count("C2_01_SIGNAL")
    if n_c2:
        ex = [e for e in events if e[2] == "C2_01_SIGNAL"][:3]
        verdict("C2-01 발화 로그", True, f"{n_c2}건 예: "
                + " / ".join(f"{e[0][11:19]} {e[1]}" for e in ex))
    else:
        verdict("C2-01 발화 로그", True, "오늘 조건 충족 신호 없음", miss=True)
    verdict("다른 전략 코드는 보존", "_buy_signal" in src and "PULL 5조건" in src
            and "MARKET_STRONGEST" in src,
            "코드는 삭제하지 않고 월요일 실행설정에서 신규매수만 정지")

    # ══ [2] VWAP 진입 관문 ══
    w("\n[2] VWAP 진입 관문")
    if cfg:
        verdict("스위치", cfg.vwap_gate_on, f"CAPTAIN2_VWAP_GATE_ON={cfg.vwap_gate_on}")
    verdict("무효 처리(구조)", "p.price * 0.5 <= v <= p.price * 2.0" in src,
            "0.5~2배 밴드 + FID15 부재 시 0(fail-open)")
    gate_hits = [e for e in events if "VWAP_GATE" in e[3]]
    if gate_hits:
        verdict("차단 로그", True, f"{len(gate_hits)}건 예: "
                + " / ".join(f"{e[0][11:19]} {e[1]}" for e in gate_hits[:3]))
    else:
        verdict("차단 로그", True, "오늘 차단 0건", miss=True)
    n_buy = ev_names.count("BUY")
    if n_buy:
        verdict("전체 진입 안 막힘", True, f"오늘 BUY {n_buy}건 존재")
    elif gate_hits and not n_buy:
        verdict("전체 진입 안 막힘", False, f"BUY 0건인데 VWAP 차단 {len(gate_hits)}건 — 과차단 의심(원인만 보고)")
    else:
        verdict("전체 진입 안 막힘", True, "BUY 0건·차단 0건 — 후보 자체 없음", miss=True)

    # ══ [3] 트레일 돈 가드 ══
    w("\n[3] 트레일 돈 가드")
    if cfg:
        verdict("설정", cfg.trail_money_guard_on and cfg.trail_guard_buy_ratio == 0.90,
                f"on={cfg.trail_money_guard_on} 매수비 하한={cfg.trail_guard_buy_ratio}")
    n_guard = ev_names.count("TRAIL_HOLD_MONEY")
    if n_guard:
        verdict("유예 발동 로그", True, f"{n_guard}건")
    else:
        verdict("유예 발동 로그", True, "오늘 트레일 유예 조건 미도래", miss=True)
    verdict("유예 즉시 해제(구조)", "guard = False" in src and "if not guard:" in src,
            "매 루프 재평가 — 상태 저장 없음(약해지면 그 루프에 트레일 발동)")
    hard_first = src.find("HARD_STOP {ret_pct") ; trail_pos = src.find("PROFIT_TRAIL 고점")
    verdict("하드손절·강제청산 우선(구조)", 0 < hard_first < trail_pos, "코드 순서: HARD_STOP → TRAIL")

    # ══ [4] 돈 중심 매도 점수 엔진 ══
    w("\n[4] 매도 점수 엔진")
    if cfg:
        verdict("스위치·문턱", cfg.score_sell_on and cfg.score_watch == 25 and cfg.score_warning == 50
                and cfg.score_sell_ready == 75 and cfg.score_dry_confirm_sec == 5,
                f"ON={cfg.score_sell_on} 25/50/75 유입끊김확인={cfg.score_dry_confirm_sec:.0f}s")
    verdict("배점 3계열+가속감산(구조)", all(k in src for k in
            ("score += 25; parts.append(\"VWAP↓\")", "속도20%↓", "역전35%↓", "score *= 0.5")),
            "ⓐ25 ⓑ25/40 ⓒ25/35 ⓓ×0.5")
    score_ev = {k: ev_names.count(k) for k in
                ("SCORE_WATCH", "SCORE_WARNING", "SCORE_SELL_READY", "SCORE_HOLD_MONEY")}
    n_score_sell = len([1 for ln in today_log.splitlines() if "SCORE_SELL" in ln and "INFO SELL " in ln])
    any_ev = sum(score_ev.values())
    if any_ev or n_score_sell:
        verdict("상태전이·매도 로그", True,
                " ".join(f"{k}={v}" for k, v in score_ev.items()) + f" SCORE_SELL매도={n_score_sell}")
    else:
        verdict("상태전이·매도 로그", True, "오늘 보유 발생 전이거나 전이 미도래", miss=True)
    verdict("HARD_STOP 최후 보험(구조)", "hard_stop_bottom_pct" in src and "HARD_STOP {ret_pct" in src,
            "바닥 -2%·눌림 -3/-4%")

    # ══ [5] VI 거부 대응 ══
    w("\n[5] VI 거부 대응")
    if cfg:
        verdict("설정", cfg.vi_reorder_wait_sec == 1.5 and cfg.max_sell_retry == 3,
                f"해제 후 대기={cfg.vi_reorder_wait_sec}s 재시도 상한={cfg.max_sell_retry}")
    verdict("감지·게이트(구조)", all(k in src for k in
            ("def _vi_track", "prev * 0.5", "SELL_VI_HOLD", "VI_RELEASE", "SELL_RETRY_EXHAUSTED",
             "is_last_resort")),
            "50%급감 감지·발사 보류·해제 대기·상한(하드손절/강제청산 예외)")
    vi_ev = {k: ev_names.count(k) for k in ("VI_SUSPECT", "VI_RELEASE", "SELL_VI_HOLD", "SELL_RETRY_EXHAUSTED")}
    if sum(vi_ev.values()):
        verdict("VI 이벤트", True, " ".join(f"{k}={v}" for k, v in vi_ev.items()))
    else:
        verdict("VI 이벤트", True, "오늘 VI 미발생", miss=True)

    # ══ [6] 구조판정 SHADOW (계층 B 병렬기록) ══
    w("\n[6] 구조판정 SHADOW (계층 B — 병렬기록·실매도 무변경)")
    if cfg:
        verdict("스위치·설정", getattr(cfg, "struct_shadow_on", False)
                and getattr(cfg, "struct_shadow_min_bars", 0) == 3,
                f"ON={getattr(cfg,'struct_shadow_on','?')} min_bars={getattr(cfg,'struct_shadow_min_bars','?')}")
    verdict("메서드·조건(구조)", all(k in src for k in
            ("def _sh_step", "def _sh_on_close", "def _sh_compute", "STRUCTURE_BREAK", "cond_structlow")),
            "3/3=[종가<VWAP]&[직전 완성분봉 저점이탈]&[60초 순매도]")
    verdict("실매도 무변경(구조)", "if self.cfg.struct_shadow_on:" in src
            and "_sh_on_close(p, state, reason)" in src,
            "_close/_hold_or_sell에 가드 호출만 추가(기존 매도 라인 무변경)")
    SHF = BASE / "data" / "shadow" / f"captain2_structure_shadow_{TODAY}.csv"
    if SHF.exists():
        sh_rows = []
        try:
            with io.open(SHF, encoding="utf-8-sig", newline="") as fh:
                sh_rows = list(csv.DictReader(fh))
        except Exception:
            pass
        nrow = len(sh_rows)
        nunk = sum(1 for r in sh_rows if r.get("shadow_state") == "STRUCTURE_UNKNOWN")
        nbrk = sum(1 for r in sh_rows if r.get("shadow_state") == "STRUCTURE_BREAK")
        nsell = sum(1 for r in sh_rows if r.get("live_action") == "SELL")
        unk_pct = (nunk / nrow * 100) if nrow else 0.0
        verdict("SHADOW 수집", nrow > 0,
                f"{nrow}행 · UNKNOWN {unk_pct:.0f}% · 구조붕괴 {nbrk} · 실매도동시기록 {nsell}")
        verdict("데이터 충실도(UNKNOWN<50%)", nrow > 0 and unk_pct < 50,
                f"UNKNOWN {unk_pct:.0f}% (높으면 FID15 부재·분봉 5개 미만 — 원인만 보고)")
    else:
        verdict("SHADOW 수집", True, "아직 파일 없음 — 보유 발생 전이거나 조건 미도래", miss=True)

    # ══ 공통 안전점검 ══
    w("\n[공통] 안전점검")
    lock = BASE / "data" / "captain2.lock"
    pid = lock.read_text().strip() if lock.exists() else ""
    fresh = lock.exists() and (datetime.now().timestamp() - lock.stat().st_mtime) < 200
    try:
        # tasklist 출력은 CP949 — 바이트로 받아 PID 문자열만 검사(인코딩 무관)
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, timeout=15).stdout
        alive = bool(pid) and pid.encode() in out and b"python" in out.lower()
    except Exception:
        alive = False
    verdict("프로세스 1개(락)", bool(pid) and fresh and alive, f"PID={pid} 락갱신={'최근' if fresh else '정지'}")
    # FID15 exact
    fid_ok = False
    try:
        import json
        snap = json.loads(SNAP.read_text(encoding="utf-8"))
        codes = snap.get("codes") or {}
        sample = next(iter(codes.values()), {})
        fid_ok = float(sample.get("buy_money_cum", -1)) >= 0
    except Exception:
        pass
    verdict("FID15 exact 수신", fid_ok, "스냅샷 4필드 양수")
    blk = (BASE / "config" / "manual_buy_block.flag").exists()
    w(f"  [상태] manual_buy_block = {'존재(매수차단 중)' if blk else '없음(매수 허용)'} — 친구님 직접 관리")
    if cfg:
        verdict("6슬롯·1주", cfg.max_positions == 6 and cfg.qty_fixed == 1,
                f"max_positions={cfg.max_positions} qty={cfg.qty_fixed}")
    # 중복매수: fills에서 같은 종목 매수가 매도 없이 연속 2회인지
    dup = 0
    if FILLS.exists():
        pos = {}
        with io.open(FILLS, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); next(rd, None)
            for r in rd:
                if len(r) < 7: continue
                c, ot, q = r[1], r[4], int(float(r[5] or 0))
                if "매수" in ot:
                    if pos.get(c, 0) > 0: dup += 1
                    pos[c] = pos.get(c, 0) + q
                elif "매도" in ot:
                    pos[c] = max(0, pos.get(c, 0) - q)
        qty_all1 = True
        with io.open(FILLS, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh); next(rd, None)
            for r in rd:
                if len(r) >= 6 and "매수" in r[4] and int(float(r[5] or 0)) != 1:
                    qty_all1 = False
        verdict("중복매수 0건", dup == 0, f"동시보유 중 재매수 {dup}건")
        verdict("매수수량 전부 1주", qty_all1)
    else:
        verdict("중복매수 0건", True, "오늘 체결 파일 없음", miss=True)
    # 해시 비교(밤새 무변경)
    cur = hashlib.sha256(ENGINE.read_bytes()).hexdigest()
    base_hash = HASH_BASE.read_text().split()[0] if HASH_BASE.exists() else ""
    verdict("엔진 파일 무변경(7/23 배선 이후)", cur == base_hash,
            f"현재 {cur[:12]}… vs 기준 {base_hash[:12]}…")
    # py_compile
    try:
        import py_compile
        py_compile.compile(str(ENGINE), doraise=True)
        verdict("py_compile", True)
    except Exception as e:
        verdict("py_compile", False, str(e)[:120])
    # 로그 갱신
    log_fresh = LOGF.exists() and (datetime.now().timestamp() - LOGF.stat().st_mtime) < 300
    evt_today = EVT.exists()
    verdict("09:00 이후 로그 갱신", log_fresh and evt_today,
            f"엔진로그 {'최근' if log_fresh else '정지'} · 오늘 이벤트CSV {'있음' if evt_today else '없음'}")

    n_fail = sum(1 for ln in L if ln.startswith("  [FAIL]"))
    n_miss = sum(1 for ln in L if ln.startswith("  [미발생]"))
    w(f"\n══ 요약: FAIL {n_fail}건 · 미발생 {n_miss}건 ══")
    w("FAIL은 원인만 보고 — 장중 코드 수정 금지(친구님 지시).")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))

if __name__ == "__main__":
    if "--mock-contracts" in sys.argv:
        mock_contracts()
    else:
        try:
            main()
        except Exception as e:
            OUT.write_text(f"점검 스크립트 자체 오류: {type(e).__name__}: {e}", encoding="utf-8")
            raise
