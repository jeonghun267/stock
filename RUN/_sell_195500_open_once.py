# -*- coding: utf-8 -*-
"""[일회성] 195500 마니커에프앤지 익일 개장 시장가 매도.
친구님 2026-06-30 "내일 아침 195500 재매도". 오늘 동시호가 미체결로 오버나잇 보유분 정리.
★실제 계좌 보유수량을 조회해서 그만큼만 시장가 매도(JSON엔 CLOSED라 계좌가 진실).
★날짜 가드: 20260701에만 실행(중복/오발화 방지)."""
import sys, json, uuid, os
sys.path.insert(0, r"C:\stock_bot\RUN")
from datetime import datetime

CODE = "195500"
RUN_DAY = "20260701"          # 이 날짜에만 매도 실행
ACC = os.environ.get("KIWOOM_ACCOUNT", "")   # [2026-07-24] 하드코딩 제거 — 파이프라인 env 로드
DONE_FLAG = r"C:\stock_bot\IPC\_sell_195500_done.flag"


def log(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line)
    try:
        with open(r"C:\stock_bot\LOG\sell_195500_open.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def main():
    today = datetime.now().strftime("%Y%m%d")
    if today != RUN_DAY:
        log(f"오늘({today}) != 실행예정일({RUN_DAY}) → 매도 안함(가드)"); return
    if os.path.exists(DONE_FLAG):
        log("이미 처리됨(flag 존재) → 중복매도 방지"); return

    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        log("broker dead → 매도불가(다음 사이클 재시도)"); return
    bc = BrokerClient()

    # 실제 계좌 보유수량 조회
    res = bc.balance_tr(
        tr_code="opw00018",
        inputs={"계좌번호": ACC, "비밀번호": "", "비밀번호입력매체구분": "00", "조회구분": "2"},
        output_fields=["종목번호", "종목명", "보유수량", "매매가능수량"],
        rqname="잔고조회195500", screen_no="5400", timeout_sec=12.0)
    recs = (res.get("data") or {}).get("records") or []
    qty = 0
    for r in recs:
        if str(r.get("종목번호", "")).lstrip("A").zfill(6) == CODE:
            try: qty = int(float(str(r.get("매매가능수량") or r.get("보유수량") or 0)))
            except Exception: qty = 0
            break
    if qty <= 0:
        log(f"{CODE} 보유 0 또는 매매가능 0 → 매도불필요(이미 정리됨)")
        try: open(DONE_FLAG, "w").write(datetime.now().isoformat())
        except Exception: pass
        return

    log(f"★시장가 매도 {CODE} x{qty}...")
    r = bc.send_order_real(
        idempotency_key=f"sell195500_open_{uuid.uuid4()}", account=ACC,
        code=CODE, qty=qty, order_type=2, price=0, hoga_gb="06",
        rqname="SELL195500_OPEN", screen_no="9715")
    log(f"매도 결과: {str(r)[:180]}")
    if str((r or {}).get("status", "")).upper() == "OK":
        try: open(DONE_FLAG, "w").write(datetime.now().isoformat())
        except Exception: pass
        log("✅ 매도 주문 접수 완료 (done flag 기록)")
    else:
        log("⚠️ 매도 거부/실패 — flag 미기록(다음 사이클 재시도)")


if __name__ == "__main__":
    try: main()
    except Exception as ex:
        log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
