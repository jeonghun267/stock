# -*- coding: utf-8 -*-
"""종가매수(EOD_GAP) 체결확인 — 15:31 잔고 대조로 유령 OPEN 정리 (③·읽기+정리만·주문 0).

★[2026-07-30 밤작업 ③ · 설계 = DOCS\밤작업_기능3건_설계_20260730.md]
배경: 매수는 status=OK(접수)·TIMEOUT 도 OPEN 으로 기록한다. 접수≠체결이라
  미체결이면 유령 OPEN 이 되고, 익일 09:01 매도가 거부되며 슬롯이 영구 점유된다.
  7/30 실전이 첫 사례: 475400 씨메스로보틱스 15:18 접수 → 동시호가에도 미체결 →
  잔고 0 인데 OPEN(수동 잔고 조회로 확정). 상한가는 호가가 잠겨 특히 잘 생긴다.

방법: 추측(에러 문자열) 대신 15:31 에 opw00018 잔고를 직접 조회해 대조한다.
  보유O+수량일치 → OPEN 유지 / 보유O+수량부족 → qty 를 실보유로 정정(부분체결)
  보유X → status="GHOST" + rt_open 에서 제거

안전장치:
  · 주문 0 · 잔고 조회 실패(OK 아님) 시 아무것도 안 바꿈(fail-safe)
  · 기본 그림자(EOD_GAP_FILLCHECK_APPLY=NO): 판정 로그만, 파일 무수정
  · 실반영 전환: setx EOD_GAP_FILLCHECK_APPLY YES
롤백: 태스크 SAFEPLUS_EOD_GAP_FILLCHECK Disable + 이 파일 삭제(기존 파일 무수정).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

DEFAULT_BASE = Path(r"C:\stock_bot")
APPLY = os.environ.get("EOD_GAP_FILLCHECK_APPLY", "NO").strip().upper() == "YES"


def _log(base: Path, message: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    try:
        path = base / "data" / "LOG" / "sched_EOD_GAP_FILLCHECK.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    for attempt in range(4):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.2)


def _fetch_balance(base: Path):
    """실계좌 잔고 {code: qty}. 실패 시 None(그러면 아무것도 안 바꾼다)."""
    import sys
    if str(base / "RUN") not in sys.path:
        sys.path.insert(0, str(base / "RUN"))
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            _log(base, "잔고 조회 불가 사유: is_broker_alive=False")
            return None
        bc = BrokerClient()
        account = os.environ.get("SWING_ACCOUNT", "").strip()
        if not account:
            ai = bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str):
                accs = [a for a in accs.split(";") if a]
            account = accs[0] if accs else ""
        if not account:
            return None
        r = bc.balance_tr(
            "opw00018",
            {"계좌번호": account, "비밀번호": "", "비밀번호입력매체구분": "00", "조회구분": "1"},
            ["종목번호", "보유수량"], timeout_sec=15.0)
        if str(r.get("status", "")).upper() != "OK":
            _log(base, f"잔고 조회 불가 사유: status={r.get('status')} error={str(r.get('error'))[:120]}")
            return None
        balance = {}
        # ★응답 스키마 실측(7/30): 목록 키는 "records" (rows 아님·record_count 0이어도
        #   빈 레코드 1개가 옴 → 코드 빈 것 스킵으로 처리)
        data = r.get("data") or {}
        for row in (data.get("records") or data.get("rows") or []):
            code = str(row.get("종목번호", "")).lstrip("A").strip().zfill(6)
            try:
                qty = int(float(str(row.get("보유수량", "0")).replace(",", "") or 0))
            except (TypeError, ValueError):
                qty = 0
            if code and qty > 0:
                balance[code] = qty
        return balance
    except Exception as exc:
        _log(base, f"잔고 조회 예외: {type(exc).__name__}: {exc}")
        return None


def judge(opens: dict, balance: dict) -> list[dict]:
    """OPEN 포지션 × 잔고 대조 → 판정 목록. 부작용 없음(테스트용 분리).

    판정: KEEP(보유·수량일치) / FIX_QTY(부분체결·실보유로 정정) / GHOST(잔고에 없음)
    """
    decisions = []
    for code, pos in opens.items():
        want = int(float(pos.get("qty", 0) or 0))
        have = int(balance.get(code, 0))
        if have <= 0:
            decisions.append({"code": code, "action": "GHOST", "want": want, "have": 0})
        elif have < want:
            decisions.append({"code": code, "action": "FIX_QTY", "want": want, "have": have})
        else:
            decisions.append({"code": code, "action": "KEEP", "want": want, "have": have})
    return decisions


def run_check(base: Path, apply: bool | None = None) -> int:
    apply = APPLY if apply is None else apply
    pos_path = base / "DATA" / "eod_gap_positions.json"
    rt_path = base / "DATA" / "rt_open_positions.json"
    held = _read_json(pos_path, {})
    opens = {c: p for c, p in held.items()
             if isinstance(p, dict) and p.get("status") in ("OPEN", "PENDING")}
    mode = "실반영" if apply else "그림자(판정만)"
    _log(base, f"=== 체결확인 시작 · OPEN {len(opens)}건 · {mode} ===")
    if not opens:
        _log(base, "대조할 OPEN 없음 — 종료")
        return 0
    balance = None
    for attempt in range(3):          # 일시 TIMEOUT 대비 재시도(7/30 저녁 실측: 간헐 TIMEOUT)
        balance = _fetch_balance(base)
        if balance is not None:
            break
        if attempt < 2:
            time.sleep(2.0)
    if balance is None:
        _log(base, "⚠ 잔고 조회 3회 실패 — 아무것도 바꾸지 않음(fail-safe)")
        return 0
    decisions = judge(opens, balance)
    changed = False

    def promote_pending(code: str, have: int) -> bool:
        pos = held.get(code) or {}
        if pos.get("status") != "PENDING":
            return False
        pos["status"] = "OPEN"
        pos["qty"] = have
        pos["fillcheck"] = f"CONFIRMED_OPEN {datetime.now():%Y%m%d%H%M}"
        rt = _read_json(rt_path, {})
        px = float(pos.get("buy_price", 0) or 0)
        rt[code] = {"qty": have, "entry_price": px, "code": code, "strategy": "EOD_GAP",
                    "peak_price": px, "stop_price": round(px * 0.95), "_eodgap": 1,
                    "_chejan_ts": datetime.now().isoformat()}
        _atomic_write(rt_path, json.dumps(rt, ensure_ascii=False, indent=1))
        _log(base, f"    {code}: PENDING -> OPEN (balance confirmed {have})")
        return True
    for d in decisions:
        code = d["code"]
        name = str((held.get(code) or {}).get("name", ""))
        if d["action"] == "KEEP":
            _log(base, f"  {code} {name}: 보유 {d['have']}주 = 기록 일치 → OPEN 유지")
            if apply and promote_pending(code, d["have"]):
                changed = True
            continue
        if d["action"] == "FIX_QTY":
            _log(base, f"  {code} {name}: 부분체결 — 기록 {d['want']}주 → 실보유 {d['have']}주로 정정"
                       + ("" if apply else " (그림자: 미반영)"))
            if apply:
                held[code]["qty"] = d["have"]
                held[code]["fillcheck"] = f"FIX_QTY {d['want']}->{d['have']} {datetime.now():%Y%m%d%H%M}"
                promote_pending(code, d["have"])
                changed = True
            continue
        # GHOST
        _log(base, f"  ★{code} {name}: 잔고에 없음 = 유령(접수만 되고 미체결) → GHOST 처리"
                   + ("" if apply else " (그림자: 미반영)"))
        if apply:
            held[code]["status"] = "GHOST"
            held[code]["fillcheck"] = f"GHOST {datetime.now():%Y%m%d%H%M}"
            changed = True
            rt = _read_json(rt_path, {})
            if code in rt and str((rt.get(code) or {}).get("strategy", "")) == "EOD_GAP":
                del rt[code]
                _atomic_write(rt_path, json.dumps(rt, ensure_ascii=False, indent=1))
                _log(base, f"    rt_open 에서 {code} 제거")
    if apply and changed:
        _atomic_write(pos_path, json.dumps(held, ensure_ascii=False, indent=1))
        _log(base, "포지션 파일 반영 완료")
    ghosts = sum(1 for d in decisions if d["action"] == "GHOST")
    fixes = sum(1 for d in decisions if d["action"] == "FIX_QTY")
    _log(base, f"=== 결과: 정상 {len(decisions) - ghosts - fixes} · 부분체결 {fixes} · 유령 {ghosts} ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--apply", action="store_true", help="실반영(기본은 env 따름)")
    args = parser.parse_args()
    return run_check(args.base, True if args.apply else None)


if __name__ == "__main__":
    raise SystemExit(main())
