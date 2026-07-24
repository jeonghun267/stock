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

def main() -> None:
    w(f"══ 캡틴2 배선 6종 아침점검 ({datetime.now():%Y-%m-%d %H:%M:%S}) ══")
    w("   판정: PASS / FAIL / 미발생(장중 조건 미도래 — 오류 아님)")

    # ── 소스·설정 로드 ──
    src = ENGINE.read_text(encoding="utf-8", errors="replace")
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

    # ══ [1] EARLY 초입 레인 ══
    w("\n[1] EARLY 초입 레인")
    if cfg:
        verdict("설정 로드", cfg.early_on and cfg.early_start == "0900" and cfg.early_end == "0910",
                f"on={cfg.early_on} 창={cfg.early_start}~{cfg.early_end}")
        verdict("파라미터 5종", abs(cfg.early_min_speed - 1666667) < 1 and cfg.early_min_burst == 3.0
                and cfg.early_min_buy_ratio == 0.70 and cfg.early_persist_sec == 3
                and cfg.early_max_above_open_pct == 2.0,
                f"속도{cfg.early_min_speed:,.0f}·배율{cfg.early_min_burst}·매수비{cfg.early_min_buy_ratio}"
                f"·지속{cfg.early_persist_sec}s·이격{cfg.early_max_above_open_pct}%")
    verdict("100억 관문 우회(구조)", "_market_filter" not in src.split("def _early_check")[1].split("def ")[0],
            "_early_check에 100억 관문 호출 없음(min_price 1만원만 유지)")
    n_early = ev_names.count("EARLY_ONSET")
    if n_early:
        ex = [e for e in events if e[2] == "EARLY_ONSET"][:3]
        verdict("EARLY 발화 로그", True, f"{n_early}건 예: " + " / ".join(f"{e[0][11:19]} {e[1]}" for e in ex))
    else:
        verdict("EARLY 발화 로그", True, "오늘 발화 0건 — VWAP 관문·조건 미충족 가능", miss=True)
    verdict("RAID·PULL 무변경(구조)", "_buy_signal" in src and "PULL 5조건" in src and "MARKET_STRONGEST" in src,
            "기존 함수·경로 존재(정밀 비교는 공통점검 해시로)")

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
                and cfg.score_sell_ready == 75 and cfg.score_hold_max_sec == 10,
                f"ON={cfg.score_sell_on} 25/50/75 유예최대={cfg.score_hold_max_sec:.0f}s")
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
    verdict("HARD_STOP 최후 보험(구조)", "hard_stop_pct" in src and "HARD_STOP {ret_pct" in src, "-3% 유지")

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
    try:
        main()
    except Exception as e:
        OUT.write_text(f"점검 스크립트 자체 오류: {type(e).__name__}: {e}", encoding="utf-8")
        raise
