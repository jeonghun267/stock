# -*- coding: utf-8 -*-
"""★[SHUTDOWN-ORIGIN-ORDER 2026-08-04] 종료 응답이 발신자 추적보다 먼저 나가야 한다.

8/3 27초 시세 공백의 발신자를 못 찾아 `_log_shutdown_origin`(wmic 호출)을 넣었는데,
그게 `_write_response` 앞에 들어가 있었다. wmic 이 걸리는 동안 client 가 응답을
기다린다("응답 먼저 작성"이라는 바로 위 주석과도 어긋났다).
프로세스 목록은 몇 ms 뒤에 찍어도 같으므로 추적 가치는 그대로다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import broker_gateway_v1 as gateway_module  # noqa: E402
from broker_gateway_v1 import BrokerGateway, BrokerState  # noqa: E402


class ShutdownOriginOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        # 진짜 lock 파일을 지우지 않도록 모듈 함수를 잠시 갈아끼운다.
        real_release = gateway_module.release_singleton_lock
        gateway_module.release_singleton_lock = lambda: self.calls.append("lock")
        self.addCleanup(
            setattr, gateway_module, "release_singleton_lock", real_release)

    def gateway(self) -> BrokerGateway:
        gw = BrokerGateway.__new__(BrokerGateway)      # __init__ 우회(OCX 불필요)
        gw.state = BrokerState.CONNECTED
        gw.app = None                                  # QTimer 경로 회피
        gw._write_response = lambda request_id, **kw: self.calls.append("response")
        gw._log_shutdown_origin = (
            lambda request_id, req, req_path: self.calls.append("origin"))
        gw.set_state = lambda state: self.calls.append("state")
        gw.write_heartbeat = lambda: self.calls.append("heartbeat")
        return gw

    def test_response_is_written_before_origin_tracing(self) -> None:
        self.gateway()._handle_shutdown_request("req-1", {"type": "SHUTDOWN"}, None)

        self.assertIn("response", self.calls)
        self.assertIn("origin", self.calls)
        self.assertLess(
            self.calls.index("response"),
            self.calls.index("origin"),
            f"응답이 발신자 추적보다 먼저 나가야 한다: {self.calls}",
        )

    def test_shutdown_still_completes_its_sequence(self) -> None:
        """순서만 바꿨지 종료 절차를 빠뜨리지 않았는지."""
        self.gateway()._handle_shutdown_request("req-1", {"type": "SHUTDOWN"}, None)

        for step in ("response", "origin", "state", "heartbeat", "lock"):
            self.assertIn(step, self.calls, f"{step} 단계가 사라졌다")

    def test_origin_tracing_failure_never_blocks_shutdown(self) -> None:
        """추적이 실패해도(wmic 은 Windows 가 걷어내는 중) 종료는 진행돼야 한다."""
        def explode(request_id, req, req_path):
            raise RuntimeError("wmic is gone")

        gw = self.gateway()
        gw._log_shutdown_origin = explode

        gw._handle_shutdown_request("req-1", {"type": "SHUTDOWN"}, None)

        self.assertIn("response", self.calls)
        self.assertIn("lock", self.calls, "추적 실패가 종료를 막으면 안 된다")


if __name__ == "__main__":
    unittest.main()
