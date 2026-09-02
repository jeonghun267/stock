# -*- coding: utf-8 -*-
"""
[Position Reconciler P1 2026-06-05] broker 실계좌(opw00018)=단일 진실원 → rt_open_positions reconcile.
근본 해결 키스톤. 설계: DOCS/execution_truth_reconcile_design_20260605.md

DRY-RUN(기본): broker 실보유 조회 → rt_open_positions와 비교 → 차이 로그만(쓰기 X). 안전, 장마감에도 가능.
--write: rt_open_positions를 broker 진실로 reconcile (수량·평단 broker 우선, strategy 메타 merge 보존). 검증 후에만.

해결: 유령(ACK오판 미등록)·드리프트·미체결 송신 phantom → broker 실보유로 자동 정합.
모든 게이트(count/cap/DUPLICATE)가 rt_open 참조 → SoT 신뢰되면 자동 정확.
"""
import argparse, json, os, sys, time
from pathlib import Path
from datetime import datetime

# [Phase A 2026-06-06] 동시쓰기 상호배제 — 매도엔진/buy_sender(ARCH1)와 동일 .lock 공유.
try:
    import msvcrt as _msvcrt
    def _lock(f):   _msvcrt.locking(f.fileno(), _msvcrt.LK_LOCK, 1)
    def _unlock(f):
        try: _msvcrt.locking(f.fileno(), _msvcrt.LK_UNLCK, 1)
        except Exception: pass
except ImportError:
    def _lock(f): pass
    def _unlock(f): pass

sys.path.insert(0, r"C:\stock_bot\RUN")
BASE = Path(r"C:\stock_bot")
RT_OPEN = BASE / "DATA" / "rt_open_positions.json"


def _f(x, d=0.0):
    try:
        return float(str(x).strip().replace(",", "")) if str(x).strip() not in ("", "None") else d
    except (TypeError, ValueError):
        return d


def _get_account(bc) -> str:
    try:
        res = bc.request({"type": "ACCOUNT_INFO", "tag": "ACCNO"}, timeout_sec=4.0)
        if res and res.get("status") == "OK":
            accs = str((res.get("data") or {}).get("accounts", "")).strip()
            return accs.split(";")[0].strip() if accs else ""
    except Exception:
        pass
    return ""


def _broker_holdings(bc, acc_no: str) -> dict:
    """opw00018 → {code: {qty, avg_price, name, eval_pl}}. 실패→None."""
    res = bc.balance_tr(
        tr_code="opw00018",
        inputs={"계좌번호": str(acc_no), "비밀번호": "",
                "비밀번호입력매체구분": "00", "조회구분": "2"},
        output_fields=["종목번호", "종목명", "보유수량", "매입가", "평가금액", "평가손익", "수익률(%)"],
        rqname="잔고reconcile", screen_no="5100", timeout_sec=10.0,
    )
    if res.get("status") != "OK":
        print(f"[RECONCILE] broker opw00018 실패: {res.get('status')} {res.get('error')}")
        return None
    out = {}
    for rec in ((res.get("data") or {}).get("records") or []):
        raw = str(rec.get("종목번호", "")).strip().lstrip("A").zfill(6)
        if not raw or raw == "000000":
            continue
        qty = int(_f(rec.get("보유수량")))
        if qty <= 0:
            continue
        out[raw] = {"qty": qty, "avg_price": _f(rec.get("매입가")),
                    "name": str(rec.get("종목명", "")).strip(),
                    "eval_pl": _f(rec.get("평가손익"))}
    return out


def _load_rt_open() -> dict:
    try:
        if RT_OPEN.exists():
            return json.loads(RT_OPEN.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def _safe_to_write(
    broker: dict, rt_codes: set, *, confirmed_empty: bool = False,
) -> tuple:
    """[Phase A] anti-wipe 가드 — broker 빈응답(글리치)이 rt_open 전체를 지우는 사고 방지.
    독립 조회 2회가 모두 빈 보유를 확인한 경우에만 마지막 phantom 제거를 허용한다."""
    if len(broker) == 0 and len(rt_codes) > 0 and not confirmed_empty:
        return False, f"broker 0건인데 rt_open {len(rt_codes)}건 보유 → 글리치 의심, write 중단(fail-safe)"
    return True, ""


class _Tee:
    """[Phase A] stdout를 파일에도 남김 — 스케줄 dry-run 결과 검토용(Phase B 정확성 확인)."""
    def __init__(self, *streams):
        self.streams = streams
    def write(self, d):
        for s in self.streams:
            try: s.write(d)
            except Exception: pass
    def flush(self):
        for s in self.streams:
            try: s.flush()
            except Exception: pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rt_open_positions를 broker로 reconcile(검증 후에만)")
    ap.add_argument("--strategy", default="EOD_PICK", help="유령 신규편입 strategy 라벨(기본 EOD_PICK=다음장 시가 관리)")
    args = ap.parse_args()
    global RECON_STRATEGY
    RECON_STRATEGY = args.strategy
    mode = "WRITE" if args.write else "DRY-RUN"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # [Phase A] 결과를 LOG/position_reconcile.log 에도 기록(검토용)
    try:
        logdir = BASE / "LOG"
        logdir.mkdir(parents=True, exist_ok=True)
        _logf = open(logdir / "position_reconcile.log", "a", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, _logf)
        print(f"\n===== [{now}] mode={mode} =====")
    except Exception:
        pass

    from broker_client import BrokerClient
    bc = BrokerClient()
    acc = _get_account(bc)
    if not acc:
        print("[RECONCILE] 계좌번호 취득 실패 → 중단(fail-safe)")
        return 1
    print(f"[RECONCILE] {now} mode={mode} 계좌={acc[:4]}***")

    broker = _broker_holdings(bc, acc)
    if broker is None:
        print("[RECONCILE] broker 조회 실패 → rt_open 유지(fail-safe)")
        return 1
    rt = _load_rt_open()
    rt_codes = {c for c, v in rt.items() if isinstance(v, dict) and _f(v.get("qty")) > 0}
    bk_codes = set(broker.keys())

    # ── 차이 비교 ──
    ghost = bk_codes - rt_codes          # broker엔 있는데 rt_open 없음(=유령, 매도누락 위험)
    phantom = rt_codes - bk_codes        # rt_open엔 있는데 broker 없음(=실보유0, 미체결/오등록)
    common = bk_codes & rt_codes
    print(f"[RECONCILE] broker 실보유 {len(bk_codes)}종목 vs rt_open 보유 {len(rt_codes)}종목")
    if broker:
        for c, v in broker.items():
            print(f"   [broker] {c} {v['name']} qty={v['qty']} 평단={v['avg_price']:.0f} 평가손익={v['eval_pl']:.0f}")
    if ghost:
        print(f"   ⚠유령(broker보유·rt누락→매도누락위험)={sorted(ghost)}")
    if phantom:
        print(f"   ⚠phantom(rt보유·broker없음→실보유0)={sorted(phantom)}")
    for c in common:
        if int(_f(rt[c].get("qty"))) != broker[c]["qty"]:
            print(f"   ⚠수량불일치 {c}: rt={int(_f(rt[c].get('qty')))} vs broker={broker[c]['qty']}")
    if not (ghost or phantom):
        print("   ✅ broker ↔ rt_open 일치(보유종목 동일)")

    if not args.write:
        print("[RECONCILE] DRY-RUN — 쓰기 안 함. (--write로 reconcile, 검증 후)")
        return 0

    # ── [Phase A 안전장치1] 2회 연속 일치 확인: 일시적 글리치(부분/빈 응답) 배제 ──
    time.sleep(2.0)
    broker2 = _broker_holdings(bc, acc)
    if broker2 is None:
        print("[RECONCILE] 2차 조회 실패 → write 중단(fail-safe)")
        return 1
    if set(broker.keys()) != set(broker2.keys()):
        diff = sorted(set(broker.keys()) ^ set(broker2.keys()))
        print(f"[RECONCILE] ⚠ 2회 조회 종목 불일치 {diff} → 글리치 의심, write 중단")
        return 1
    for c in broker:
        if broker[c]["qty"] != broker2.get(c, {}).get("qty"):
            print(f"[RECONCILE] ⚠ {c} 2회 수량 불일치(rt={broker[c]['qty']}/{broker2[c]['qty']}) → write 중단")
            return 1

    # ── [Phase A 안전장치2] anti-wipe: 빈 보유는 독립 조회 2회 일치 때만 허용 ──
    ok, why = _safe_to_write(
        broker,
        rt_codes,
        confirmed_empty=(not broker and not broker2),
    )
    if not ok:
        print(f"[RECONCILE] ⚠ {why}")
        return 1

    # ── [Phase A 안전장치3] WRITE: 공유 .lock 하에서 read-modify-write (동시쓰기 충돌 방지) ──
    lockfile = str(RT_OPEN) + ".lock"
    try:
        with open(lockfile, "a+", encoding="utf-8") as lf:
            _lock(lf)
            try:
                rt_now = _load_rt_open()   # 락 안에서 재읽기(그새 매도엔진이 갱신했을 수 있음)
                new = {}
                for c, v in broker.items():
                    prev = rt_now.get(c, {}) if isinstance(rt_now.get(c), dict) else {}
                    merged = dict(prev)
                    merged.update({"code": c, "qty": v["qty"], "entry_price": v["avg_price"],
                                   "name": v["name"], "_reconciled_ts": now})
                    if not merged.get("strategy"):
                        merged["strategy"] = RECON_STRATEGY   # 유령 신규편입 라벨(매도엔진 관리용)
                        merged["_ghost_reconciled"] = now
                    new[c] = merged
                # phantom(broker 실보유0)은 제거(실보유 기준). 비-포지션 메타키는 보존.
                dropped = 0
                for c, v in rt_now.items():
                    if not (isinstance(v, dict) and "qty" in v):
                        new[c] = v
                    elif c not in broker:
                        dropped += 1
                tmp = str(RT_OPEN) + ".tmp"
                Path(tmp).write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, str(RT_OPEN))
                print(f"[RECONCILE] ✅ WRITE 완료 — rt_open_positions = broker 진실 {len(broker)}종목 (phantom {dropped} 제거)")
            finally:
                _unlock(lf)
    except Exception as e:
        print(f"[RECONCILE] write 실패(락/IO) → rt_open 유지: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
