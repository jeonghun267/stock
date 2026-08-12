# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ipc_order_auth_v1 import (
    NonceStore,
    PROTECTED_TYPES,
    OrderAuthError,
    sign_order_request,
    verify_order_request,
)


class IpcOrderAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = Path(self.temp.name) / "order.key"
        self.key.write_bytes(b"k" * 32)
        self.payload = {
            "type": "SENDORDER_REAL",
            "request_id": "11111111-2222-3333-4444-555555555555",
            "caller": "unit_test",
            "idempotency_key": "order-1",
            "code": "005930",
            "qty": 1,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_signed_order_is_accepted(self):
        signed = sign_order_request(self.payload, secret_path=self.key, now=1000)
        self.assertEqual(
            verify_order_request(signed, secret_path=self.key, now=1001),
            (True, ""),
        )

    def test_unsigned_order_is_rejected(self):
        ok, reason = verify_order_request(self.payload, secret_path=self.key, now=1000)
        self.assertFalse(ok)
        self.assertIn("auth version", reason)

    def test_tampered_order_is_rejected(self):
        signed = sign_order_request(self.payload, secret_path=self.key, now=1000)
        signed["qty"] = 99
        ok, reason = verify_order_request(signed, secret_path=self.key, now=1001)
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_stale_order_is_rejected(self):
        signed = sign_order_request(self.payload, secret_path=self.key, now=1000)
        ok, reason = verify_order_request(signed, secret_path=self.key, now=1031)
        self.assertFalse(ok)
        self.assertIn("expired", reason)

    def test_missing_key_blocks_signing(self):
        with self.assertRaises(OrderAuthError):
            sign_order_request(
                self.payload, secret_path=Path(self.temp.name) / "missing.key")

    def test_nonce_replay_is_blocked_after_restart(self):
        state = Path(self.temp.name) / "nonces.json"
        nonce = "a" * 32
        first = NonceStore(state_path=state)
        self.assertTrue(first.consume(nonce))
        restarted = NonceStore(state_path=state)
        self.assertFalse(restarted.consume(nonce))

    def test_corrupt_nonce_state_fails_closed(self):
        state = Path(self.temp.name) / "nonces.json"
        state.write_text("{broken", encoding="utf-8")
        self.assertFalse(NonceStore(state_path=state).consume("b" * 32))

    # ── ★[IPC-AUTH-SCOPE 2026-08-04] SET_REAL_REMOVE_ALL 서명 ──────────────

    def remove_all(self):
        return {
            "type": "SET_REAL_REMOVE_ALL",
            "request_id": "99999999-8888-7777-6666-555555555555",
            "caller": "unit_test",
        }

    def test_set_real_remove_all_is_protected(self):
        self.assertIn("SET_REAL_REMOVE_ALL", PROTECTED_TYPES)

    def test_account_queries_are_protected(self):
        self.assertIn("ACCOUNT_INFO", PROTECTED_TYPES)
        self.assertIn("BALANCE_TR", PROTECTED_TYPES)

    def test_signed_remove_all_is_accepted(self):
        signed = sign_order_request(
            self.remove_all(), secret_path=self.key, now=1000)
        self.assertEqual(
            verify_order_request(
                signed,
                expected_type="SET_REAL_REMOVE_ALL",
                secret_path=self.key,
                now=1001,
            ),
            (True, ""),
        )

    def test_unsigned_remove_all_is_rejected(self):
        """이게 8/4 이전 상태 - 아무나 넣으면 전 종목 시세가 끊겼다."""
        ok, reason = verify_order_request(
            self.remove_all(), secret_path=self.key, now=1000)
        self.assertFalse(ok)
        self.assertIn("auth version", reason)

    def test_tampered_remove_all_is_rejected(self):
        signed = sign_order_request(
            self.remove_all(), secret_path=self.key, now=1000)
        signed["caller"] = "somebody_else"
        ok, reason = verify_order_request(
            signed, secret_path=self.key, now=1001)
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_stale_remove_all_is_rejected(self):
        signed = sign_order_request(
            self.remove_all(), secret_path=self.key, now=1000)
        ok, reason = verify_order_request(
            signed, secret_path=self.key, now=1031)
        self.assertFalse(ok)
        self.assertIn("expired", reason)

    def test_signed_order_cannot_be_replayed_as_remove_all(self):
        """서명된 실주문을 다른 분기로 흘려보내지 못한다."""
        signed = sign_order_request(self.payload, secret_path=self.key, now=1000)
        ok, reason = verify_order_request(
            signed,
            expected_type="SET_REAL_REMOVE_ALL",
            secret_path=self.key,
            now=1001,
        )
        self.assertFalse(ok)
        self.assertIn("type mismatch", reason)

    def test_unprotected_type_cannot_be_signed(self):
        """서명 대상이 아닌 명령까지 서명해서 관문을 흐리지 않는다.

        ★[IPC-AUTH-BLANKET 2026-08-05] SET_REAL_REMOVE 를 이 목록에서 뺐다.
          8/5 밤 보안점검에서 이 명령에 screen_no/code="ALL" 을 넣으면
          SET_REAL_REMOVE_ALL 과 똑같은 일이 무인증으로 되는 것을 찾았고,
          그래서 서명 대상이 됐다. 이 시험은 그때까지 '서명되면 안 된다'를
          지키고 있었으므로 그대로 뒀으면 새 잠금이 실패로 보였을 것이다.
        ★[IPC-TR-AUTH 2026-08-10] TR도 브로커 조회 자원을 점유하므로 서명 대상으로
          전환했다. 연결 상태 확인용 PING만 무인증으로 남는다.
        """
        for request_type in ("PING",):
            with self.subTest(type=request_type):
                with self.assertRaises(OrderAuthError):
                    sign_order_request(
                        {"type": request_type, "request_id": "x"},
                        secret_path=self.key,
                    )

    def test_shutdown_requires_signature(self):
        """[IPC-AUTH-SHUTDOWN 2026-08-06] SHUTDOWN 이 서명 대상으로 잠겼는지 못박는다.

        되돌리면(PROTECTED_TYPES 에서 SHUTDOWN 제거) 이 시험이 셋 다 깨진다.
        ①서명이 되고 ②그 서명이 검증 통과하고 ③무서명은 거부되는지.
        """
        # ① SHUTDOWN 이 서명 가능해야 한다(안 되면 야간정지가 무서명으로 나가 거부됨)
        signed = sign_order_request(
            {"type": "SHUTDOWN", "request_id": "shutdown-1"},
            secret_path=self.key, now=1000,
        )
        # ② 그 서명이 SHUTDOWN 분기에서 통과해야 한다
        ok, reason = verify_order_request(
            signed, expected_type="SHUTDOWN", secret_path=self.key, now=1001)
        self.assertTrue(ok, reason)
        # ③ 무서명 SHUTDOWN 은 거부돼야 한다
        bad_ok, bad_reason = verify_order_request(
            {"type": "SHUTDOWN", "request_id": "shutdown-2"},
            expected_type="SHUTDOWN", secret_path=self.key, now=1001)
        self.assertFalse(bad_ok)

    def test_missing_key_blocks_remove_all_signing(self):
        """키가 없으면 요청 파일 자체가 안 써진다 - 조용히 무서명 통과 금지."""
        with self.assertRaises(OrderAuthError):
            sign_order_request(
                self.remove_all(),
                secret_path=Path(self.temp.name) / "missing.key",
            )


if __name__ == "__main__":
    unittest.main()
