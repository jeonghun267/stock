# -*- coding: utf-8 -*-
"""★[IPC-AUTH-SCOPE 2026-08-04] SET_REAL_REMOVE_ALL 인증이 실제로 배선됐는지.

단위 테스트(test_ipc_order_auth_v1)는 서명 함수만 본다. 여기서는 실제 dispatch 와
실제 BrokerClient 를 태워 '관문이 정말 앞에 서 있는지'를 확인한다.

막으려는 사고: 브로커를 살려 둔 채 전 종목 실시간만 끊는 명령이라, 하트비트·프리징을
보는 워치독이 절대 못 잡는다. 그 사이 전 전략이 손절·트레일까지 눈이 먼 채로 돈다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ipc_order_auth_v1 import SECRET_PATH, sign_order_request, verify_order_request


KEY_READY = SECRET_PATH.exists() and SECRET_PATH.stat().st_size >= 32


@unittest.skipUnless(KEY_READY, f"IPC auth key not available: {SECRET_PATH}")
class RealRemoveAllAuthWiringTests(unittest.TestCase):
    """운영 키로 서명하고 같은 키로 검증한다. 키 내용은 어디에도 드러내지 않는다."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.handled: list[str] = []
        self.responses: list[tuple] = []

    # ── 게이트웨이 dispatch ────────────────────────────────────────────────

    def gateway(self):
        from broker_gateway_v1 import BrokerGateway

        gw = BrokerGateway.__new__(BrokerGateway)   # __init__ 우회(OCX 불필요)
        gw._write_response = lambda request_id, **kw: self.responses.append(
            (request_id, kw))
        gw._handle_set_real_remove_all_request = (
            lambda request_id, req: self.handled.append(f"REMOVE_ALL:{request_id}"))
        gw._handle_sendorder_real_request = (
            lambda request_id, req: self.handled.append(f"ORDER:{request_id}"))
        return gw

    def write_request(self, payload: dict) -> Path:
        body = dict(payload)
        body.setdefault("request_id", "req-remove-all-1")
        body.setdefault("ts", datetime.now().isoformat())
        body.setdefault("ttl_sec", 30)
        body.setdefault("caller", "wiring_test")
        path = self.root / f"{body['request_id']}.json"
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def test_unsigned_remove_all_never_reaches_handler(self) -> None:
        """8/4 이전 상태 - 아무나 넣은 파일이 그대로 실행됐다."""
        path = self.write_request({"type": "SET_REAL_REMOVE_ALL"})
        self.gateway().process_request(path)

        self.assertEqual([], self.handled, "인증 없이 핸들러가 불리면 안 된다")
        self.assertEqual(1, len(self.responses))
        _, kw = self.responses[0]
        self.assertEqual("ERROR", kw["status"])
        self.assertIn("authentication rejected", kw["error"])

    def test_signed_remove_all_reaches_handler(self) -> None:
        """정당한 호출까지 막으면 킬스위치를 잃는다."""
        signed = sign_order_request({
            "type": "SET_REAL_REMOVE_ALL",
            "request_id": "req-remove-all-1",
            "ts": datetime.now().isoformat(),
            "ttl_sec": 30,
            "caller": "wiring_test",
        })
        self.gateway().process_request(self.write_request(signed))

        self.assertEqual(["REMOVE_ALL:req-remove-all-1"], self.handled)
        self.assertEqual([], self.responses, "핸들러가 응답을 책임진다")

    def test_tampered_signature_never_reaches_handler(self) -> None:
        signed = sign_order_request({
            "type": "SET_REAL_REMOVE_ALL",
            "request_id": "req-remove-all-1",
            "ts": datetime.now().isoformat(),
            "ttl_sec": 30,
            "caller": "wiring_test",
        })
        signed["caller"] = "somebody_else"      # 서명 후 변조
        self.gateway().process_request(self.write_request(signed))

        self.assertEqual([], self.handled)
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    def test_signed_order_path_still_works(self) -> None:
        """대조군 - 기존 실주문 인증을 건드리지 않았음을 확인한다."""
        signed = sign_order_request({
            "type": "SENDORDER_REAL",
            "request_id": "req-order-1",
            "ts": datetime.now().isoformat(),
            "ttl_sec": 30,
            "caller": "wiring_test",
            "idempotency_key": "order-1",
        })
        self.gateway().process_request(self.write_request(signed))

        self.assertEqual(["ORDER:req-order-1"], self.handled)

    # ── 실제 BrokerClient ─────────────────────────────────────────────────

    def test_broker_client_signs_remove_all_on_disk(self) -> None:
        """호출 코드는 그대로 - 클라이언트가 알아서 서명해야 한다."""
        from broker_client import BrokerClient

        client = BrokerClient(ipc_base=self.root / "ipc")
        result = client.set_real_remove_all(timeout_sec=0.3)
        self.assertEqual("TIMEOUT", result["status"], "테스트에는 브로커가 없다")

        written = list((self.root / "ipc" / "requests").glob("*.json"))
        self.assertEqual(1, len(written))
        payload = json.loads(written[0].read_text(encoding="utf-8"))

        self.assertEqual("SET_REAL_REMOVE_ALL", payload["type"])
        for field in ("auth_version", "auth_ts", "auth_nonce", "auth_tag"):
            self.assertIn(field, payload, f"{field} 가 파일에 없다")
        self.assertEqual(
            (True, ""),
            verify_order_request(payload, expected_type="SET_REAL_REMOVE_ALL"),
        )


if __name__ == "__main__":
    unittest.main()
