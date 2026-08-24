"""S06 capture-only 기동 — 주문이 절대 발생하지 않는 입력 수집 전용 러너.

[2026-08-20 친구님 지시] "주문이 절대 발생하지 않는 별도 capture-only 기동으로
다음 거래일 입력을 자동 수집하고, 기존 실전 런처는 아직 CAS 갱신하지 않는다."

주문 불가를 "설정"이 아니라 **구조**로 보장한다. Strategy06Engine 은 broker 와 slots 를
주입받으므로(__init__ 의 broker=, slots=), 주문을 낼 수단 자체를 없앤 객체를 넣는다.

  ① _NoOrderBroker  — IPC 연결이 없고 submit/cancel 은 SHADOW 결과만 반환한다.
  ② _NoSlots        — 공용 슬롯과 분리된 메모리 6슬롯만 쓴다(다른 전략 굶김 방지).
  ③ live_requested=False — StrategyBroker 를 아예 만들지 않으므로 IPC 자체가 없다.
  ④ 상태·이벤트·로그·잠금 경로를 전부 capture 전용으로 격리 — 실전 상태파일 무접촉.

⚠️ 알려진 한계(의도된 것):
   신호 뒤 상태는 production의 SHADOW 체결 경로로 진행하지만 실제 브로커 체결·
   잔고·미체결은 재현하지 않는다. 이 기동은 판정 입력→출력 보존 전용이다.

사용: SAFEPLUS_S06_CAPTURE_ONLY.cmd 가 호출한다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

CAPTURE_ROOT = Path(os.environ.get(
    "S06_CAPTURE_ROOT", r"C:\stock_bot\data\s06_capture_only"))


class _NoOrderBroker:
    """IPC 주문 통로가 없는 브로커. 판정은 SHADOW 체결로 끝까지 진행한다."""

    real_session = False
    buy_allowed = False
    mode = "CAPTURE_ONLY"
    last_error = "CAPTURE_ONLY_NO_BROKER"

    def connect(self) -> bool:
        return False

    def holdings(self):
        return {}

    def open_orders(self, code=None, buy=None):
        return {}

    def submit(self, **kwargs) -> str:
        return "SHADOW"

    def cancel(self, **kwargs) -> str:
        return "SHADOW"


class _NoSlots:
    """공용 슬롯을 건드리지 않는 capture 전용 메모리 6슬롯."""

    def __init__(self) -> None:
        self._codes: set[str] = set()

    def acquire(self, code, tag, day) -> bool:
        code6 = str(code).zfill(6)
        if code6 in self._codes:
            return True
        if len(self._codes) >= 6:
            return False
        self._codes.add(code6)
        return True

    def release(self, code, day) -> None:
        self._codes.discard(str(code).zfill(6))


def build_config():
    from strategy_06_crash_low_chase_v1 import Config

    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    (CAPTURE_ROOT / "events").mkdir(parents=True, exist_ok=True)
    (CAPTURE_ROOT / "fills").mkdir(parents=True, exist_ok=True)

    return Config(
        live_requested=False,
        state_path=CAPTURE_ROOT / "strategy_06_capture_state.json",
        lock_path=CAPTURE_ROOT / "strategy_06_capture.lock",
        event_dir=CAPTURE_ROOT / "events",
        fills_dir=CAPTURE_ROOT / "fills",
        log_path=Path(r"C:\stock_bot\LOG\s06_capture_only.log"),
        # 실전 승인·차단 깃발을 읽지 않는다. 어차피 live_requested=False 다.
        approval_path=CAPTURE_ROOT / "never_approved.flag",
        off_flag_path=CAPTURE_ROOT / "never_off.flag",
        manual_buy_block_path=CAPTURE_ROOT / "never_block.flag",
    )


def main() -> int:
    # 기록기가 꺼져 있으면 이 기동은 아무 의미가 없다 — 명시적으로 켠다.
    os.environ.setdefault("S06_EXACT_RECORD", "YES")
    # 실전 스위치가 환경에 남아 있어도 무력화한다(이중 안전장치).
    os.environ["S06_LIVE"] = "NO"

    from strategy_06_crash_low_chase_v1 import ProcessLock, Strategy06Engine

    config = build_config()

    if config.live_requested:  # 도달 불가 — 방어적 확인
        print("CAPTURE_ONLY_ABORT: live_requested 가 True 다", file=sys.stderr)
        return 2

    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("CAPTURE_ONLY_SKIP: 이미 실행 중", file=sys.stderr)
        return 0
    try:
        engine = Strategy06Engine(
            config, broker=_NoOrderBroker(), slots=_NoSlots())
        engine.log.info(
            "S06 capture-only 시작 — 주문 불가 브로커·슬롯 주입, 기록 전용 "
            "(state=%s)", config.state_path)
        return engine.run()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
