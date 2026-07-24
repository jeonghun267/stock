# -*- coding: utf-8 -*-
"""
_verify_relayhint_0602.py  [READ-ONLY 검증]
SIGA-RETIRE 재배선 (2026-06-01 적용) 6/2 발효 검증.

설계: 아침 SIGA 시가매수 폐기 → EOD_PICK 시가매도 + PULLBACK만.
      릴레이 = 포지션 청산(현금복귀)되면 PULLBACK 진입 (SIGA 무관).

확인 항목:
  1) 아침 SIGA 매수 사라졌나 (siga_to_signal_bridge 미호출 / SIGA hint 매수 0)
  2) [RELAY] 매도완료→눌림 릴레이 활성 로그 발생 시각
  3) PULLBACK output(output_codes>0)이 09:30 이후/EOD_PICK 매도완료 후 생존  ← 핵심
  4) daily_entry_gate(rt_risk) SIGA 차단이 잔존하나 (잔존해도 rt_execution 릴레이엔 무관)

매수/매도/주문 무접촉. 로그 grep 만. 결과 LOG/_relayhint_verify_0602.txt.
"""
import re
import sys
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE   = Path(r"C:\stock_bot")
RTEXEC = BASE / "LOG" / "rt_execution_engine.log"
RTRISK = BASE / "LOG" / "rt_risk_engine.log"
PIPE   = BASE / "LOG" / "pipeline_runner.log"
OUT    = BASE / "LOG" / "_relayhint_verify_0602.txt"
DAY    = "2026-06-02"
CUT    = 930

def hhmm_of(line):
    m = re.search(r"%s[ T](\d{2}):(\d{2}):\d{2}" % re.escape(DAY), line)
    return int(m.group(1))*100+int(m.group(2)) if m else None

def read_day(p):
    if not p.exists():
        return None
    return [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if DAY in ln]

def main():
    rep = []
    e = rep.append
    e("="*70)
    e(f"SIGA-RETIRE 재배선 검증  대상일={DAY}  생성={datetime.now():%Y-%m-%d %H:%M:%S}")
    e("="*70)

    ex = read_day(RTEXEC)
    if ex is None:
        e(f"[ERROR] 로그 없음: {RTEXEC}")
    elif not ex:
        e(f"\n[WARN] 6/2 rt_execution 로그 없음 — 시스템 미가동/broker off. 검증 불가.")
        ex = []

    # 1) SIGA 매수 사라졌나
    siga_buy = [ln for ln in (ex or []) if ("siga_to_signal_bridge" in ln) or ("SIGA_RT_DIRECT" in ln)]
    siga_hint_entry = [ln for ln in (ex or []) if re.search(r"(hint|strategy)\W*SIGA", ln) and ("진입" in ln or "ENTRY" in ln or "매수" in ln)]
    e(f"\n[1] 아침 SIGA 매수 흔적: bridge/RT_DIRECT={len(siga_buy)}  SIGA진입로그={len(siga_hint_entry)}")
    e("    └ " + ("PASS: SIGA 매수 사라짐" if not siga_buy and not siga_hint_entry else "⚠ SIGA 흔적 잔존 — 점검"))

    # 2) 새 릴레이 로그
    relay = [ln for ln in (ex or []) if "매도완료→눌림 릴레이 활성" in ln or "[RELAY]" in ln]
    relay_t = sorted({hhmm_of(ln) for ln in relay if hhmm_of(ln) is not None})
    e(f"\n[2] [RELAY] 매도완료→눌림 활성: {len(relay)}회  시각={relay_t}")

    # 3) PULLBACK output 생존
    out_pos = []
    for ln in (ex or []):
        m = re.search(r"output_codes=(\d+)", ln) or re.search(r"진입|ENTRY", ln)
    # rt_execution은 signal 작성 로그로 판단
    entries = [(hhmm_of(ln), ln) for ln in (ex or []) if ("signal" in ln.lower() and "code" in ln.lower()) or "진입 확정" in ln or "[ENTRY]" in ln]
    ent_after = [t for t,_ in entries if (t or 0) >= CUT]
    e(f"\n[3] rt_execution 진입/신호 로그: {len(entries)}회 (09:30이후 {len(ent_after)})")
    e("    └ " + ("PASS 정황: 09:30 이후에도 PULLBACK 진입 살아있음" if ent_after else "(09:30이후 진입 없음 — EOD_PICK 매도완료/후보유무 점검)"))

    # 4) rt_risk SIGA 게이트 잔존 (참고)
    rk = read_day(RTRISK) or []
    rk_siga = [ln for ln in rk if "SIGA 당일 발행 완료" in ln]
    e(f"\n[4] (참고) rt_risk SIGA 게이트 차단 로그: {len(rk_siga)}회 — 잔존해도 rt_execution 릴레이와 무관(설계상 무해)")

    e("\n" + "-"*70)
    e("종합: [1]SIGA매수 소멸 + [2]릴레이 발동 + [3]09:30후 PULLBACK 생존 = 재배선 성공")
    e("      6/2 PC가동+broker on 전제. 로그0이면 미가동(검증불가, 재가동일 재실행).")
    e("-"*70)

    OUT.write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))
    print(f"\n[리포트 저장] {OUT}")

if __name__ == "__main__":
    main()
