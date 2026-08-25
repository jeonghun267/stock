# -*- coding: utf-8 -*-
"""★[GHOST-BLOCK-ON 2026-08-05] 늦은 주문을 실제로 거부하는가.

7/30 에 만든 차단이 그림자(경고만)로 6일간 켜져 있지 않았다. "7/31 에 age_sec 를
보고 켜자"고 적어 두고 아무도 안 봤고, 스위치가 환경변수라 꺼져 있다는 게 눈에
보이지도 않았다. 그래서 기본값을 코드에 박고 여기서 잠근다.

막으려는 사고: 클라이언트가 이미 포기한 주문을 게이트웨이가 뒤늦게 집행하는 것
(유령 주문). 체결은 됐는데 엔진은 모르는 상태가 되고, 7/16 유령 잔량과 같은 꼴이 된다.
"""
from __future__ import annotations

import ast
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


class GhostBlockDefaultTests(unittest.TestCase):
    """스위치의 '기본값'이 무엇인지 — 환경변수가 없을 때 실제로 정하는 값."""

    def test_default_is_block_not_shadow(self) -> None:
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        found = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "_GHOST_SHADOW"
                       for t in node.targets):
                continue
            for call in ast.walk(node.value):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "get"
                        and len(call.args) == 2
                        and isinstance(call.args[1], ast.Constant)):
                    found.append(call.args[1].value)
        self.assertEqual(["NO"], found,
                         "기본값이 NO 가 아니면 차단이 꺼진 채로 돈다 "
                         "(7/30~8/5 에 실제로 그랬다)")

    def test_module_constant_agrees(self) -> None:
        import broker_gateway_v1 as bg

        self.assertFalse(
            bg._GHOST_SHADOW,
            "지금 프로세스에 BROKER_GHOST_SHADOW=YES 가 걸려 있거나 기본값이 되돌려졌다")


    def test_only_explicit_yes_enables_shadow(self) -> None:
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        self.assertIn('.strip().upper() == "YES"', src)


class GhostBlockBehaviourTests(unittest.TestCase):
    """실제 핸들러에 낡은 주문을 넣어 본다."""

    def setUp(self) -> None:
        self.responses: list[tuple] = []
        self.reached: list[str] = []

    def gateway(self):
        import broker_gateway_v1 as bg
        from broker_gateway_v1 import BrokerGateway, BrokerState

        outer = self

        class Ocx:
            def dynamicCall(self, *a, **kw):
                if a and "GetLoginInfo" in str(a[0]):
                    return "0000000000;"
                outer.reached.append("ocx")     # 여기 닿았다 = TTL 관문을 지났다
                return 0

        gw = BrokerGateway.__new__(BrokerGateway)   # __init__ 우회(OCX 불필요)
        gw.state = BrokerState.CONNECTED
        gw.ocx = Ocx()
        gw._sendorder_idempotency_cache = {}
        gw._save_sendorder_idempotency = lambda: True
        gw._micro_snapshot = {}
        gw._purge_sendorder_idempotency = lambda: None
        gw._write_response = lambda request_id, **kw: self.responses.append(
            (request_id, kw))
        self.bg = bg
        return gw

    def order(self, *, age_sec: float, order_type: int = 2) -> dict:
        """order_type 2 = 매도. 매수 상한 검사를 안 타는 쪽으로 관문만 본다."""
        return {
            "type": "SENDORDER_REAL",
            "request_id": "req-ghost-1",
            "idempotency_key": f"ghost-{age_sec}-{order_type}",
            "ts": (datetime.now() - timedelta(seconds=age_sec)).isoformat(),
            "ttl_sec": 15,          # 클라 기본값. 유효 문턱은 min(15, 8) = 8초
            "account": "0000000000",
            "code": "005930",
            "qty": 1,
            "order_type": order_type,
            "price": 0,
            "hoga_gb": "06",
        }

    def test_stale_order_is_rejected(self) -> None:
        gw = self.gateway()
        gw._handle_sendorder_real_request("req-ghost-1", self.order(age_sec=12.0))

        self.assertEqual([], self.reached, "늦은 주문이 키움까지 갔다")
        self.assertEqual(1, len(self.responses))
        _, kw = self.responses[0]
        self.assertEqual("ERROR", kw["status"])
        self.assertTrue(kw["error"].startswith("ORDER_TTL"), kw["error"])

    def test_fresh_order_passes_the_gate(self) -> None:
        """정상 주문까지 막으면 이 차단은 켜면 안 되는 것이다."""
        gw = self.gateway()
        gw._handle_sendorder_real_request("req-ghost-1", self.order(age_sec=0.3))

        self.assertIn("ocx", self.reached, "정상 주문이 관문에서 막혔다")
        for _, kw in self.responses:
            self.assertNotIn("ORDER_TTL", str(kw.get("error") or ""))

    def test_shadow_switch_still_lets_stale_through(self) -> None:
        """되돌리기 지렛대(setx BROKER_GHOST_SHADOW YES)가 살아 있는가."""
        gw = self.gateway()
        real = self.bg._GHOST_SHADOW
        self.bg._GHOST_SHADOW = True
        try:
            gw._handle_sendorder_real_request("req-ghost-1",
                                              self.order(age_sec=12.0))
        finally:
            self.bg._GHOST_SHADOW = real

        self.assertIn("ocx", self.reached,
                      "그림자 모드인데 막혔다 — 되돌릴 길이 없어진 것이다")

    def test_broken_timestamp_is_blocked(self) -> None:
        """ts 를 못 읽으면 나이 판정 불가 — 주문 경로는 보수적으로 통과시킨다."""
        gw = self.gateway()
        payload = self.order(age_sec=0.3)
        payload["ts"] = "이건 시각이 아니다"
        gw._handle_sendorder_real_request("req-ghost-1", payload)

        self.assertEqual([], self.reached)
        self.assertIn("ORDER_TTL_INVALID", self.responses[-1][1]["error"])

    def test_non_login_account_is_rejected_before_sendorder(self) -> None:
        gw = self.gateway()
        payload = self.order(age_sec=0.3)
        payload["account"] = "1111111111"

        gw._handle_sendorder_real_request("req-account-mismatch", payload)

        self.assertEqual([], self.reached)
        self.assertEqual(
            "SENDORDER_REAL account mismatch", self.responses[-1][1]["error"]
        )


if __name__ == "__main__":
    unittest.main()
