# -*- coding: utf-8 -*-
"""★[IPC-AUTH-BLANKET 2026-08-05] 8/4 잠금 옆에 열려 있던 문 두 개를 잠갔는지.

8/4 에 SET_REAL_REMOVE_ALL 을 서명 필수로 만들었는데, 같은 일을 하는 길이 둘 더
있었다(8/5 밤 보안점검에서 찾음).
  · SET_REAL_REMOVE 에 screen_no/code = "ALL"  -> 전 종목 실시간 해제가 무인증
  · SETREAL_REG                                 -> broker_state.json 에 적혀
                                                   재기동해도 되살아난다

막으려는 사고는 8/4 와 같다: 브로커는 살아 있고 하트비트도 정상인데 시세만 끊긴다.
워치독은 하트비트·프리징만 보므로 절대 못 잡고, 그 사이 전 전략이 손절·트레일까지
눈이 먼 채로 돈다.

여기서는 '관문이 정말 앞에 서 있는지'를 실제 dispatch 와 실제 BrokerClient 로 본다.
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

from ipc_order_auth_v1 import (
    PROTECTED_TYPES, SECRET_PATH, sign_order_request, verify_order_request)


KEY_READY = SECRET_PATH.exists() and SECRET_PATH.stat().st_size >= 32


class BlanketShapeTests(unittest.TestCase):
    """'싹 지우기' 판정 자체 — 키가 없어도 돌아야 하므로 따로 둔다."""

    def test_shapes(self) -> None:
        from broker_gateway_v1 import _is_blanket_real_remove as blanket

        # 전면 해제로 봐야 하는 것들
        self.assertTrue(blanket({"screen_no": "ALL", "code": "ALL"}))
        self.assertTrue(blanket({"screen_no": "9001", "code": "ALL"}),
                        "화면 번호를 돌리면 전체 해제와 결과가 같다")
        self.assertTrue(blanket({"screen_no": "ALL", "code": "005930"}))
        self.assertTrue(blanket({"screen_no": " all ", "code": "005930"}),
                        "공백·소문자로 검사를 피할 수 있으면 안 된다")

        # 종목 하나짜리 해제는 종전대로 통과
        self.assertFalse(blanket({"screen_no": "9001", "code": "005930"}))

    def test_unreadable_payload_is_treated_as_blanket(self) -> None:
        """판단 불가일 때 열어 두면 그게 구멍이다 — fail-closed 확인."""
        from broker_gateway_v1 import _is_blanket_real_remove as blanket

        class Hostile:
            def get(self, *a, **kw):
                raise RuntimeError("읽을 수 없는 payload")

        self.assertTrue(blanket(Hostile()))


class ProcessSnapshotTests(unittest.TestCase):
    """SHUTDOWN 발신자 추적 — wmic 이 빈손이어도 뭔가는 남아야 한다."""

    def test_os_snapshot_is_not_empty(self) -> None:
        from broker_gateway_v1 import _process_snapshot_win32

        rows = _process_snapshot_win32()
        self.assertGreater(len(rows), 20,
                           "OS 스냅샷이 비었다 - wmic 과 같은 병에 걸린 것이다")
        self.assertTrue(any("pid=" in r and "ppid=" in r for r in rows))

    def test_tracer_falls_back_when_wmic_returns_nothing(self) -> None:
        """8/5 19:00:02 실전에서 일어난 일 그대로 — wmic 이 빈 출력을 돌려준다."""
        import subprocess

        import broker_gateway_v1 as bg
        from broker_gateway_v1 import BrokerGateway

        lines: list[str] = []

        class Recorder:
            def info(self, fmt, *a):
                lines.append(fmt % a if a else fmt)

            warning = error = info

        class EmptyRun:
            stdout = ""          # 예외가 아니라 '빈손' — 실패로 보이지 않던 그 상태

        real_run, real_logger = subprocess.run, bg.logger
        subprocess.run = lambda *a, **kw: EmptyRun()
        bg.logger = Recorder()
        try:
            gw = BrokerGateway.__new__(BrokerGateway)
            gw._log_shutdown_origin("req-1", {"type": "SHUTDOWN"}, None)
        finally:
            subprocess.run, bg.logger = real_run, real_logger

        joined = "\n".join(lines)
        self.assertIn("OS 스냅샷으로 대체", joined, "빈손을 그냥 결론으로 삼았다")
        counted = [l for l in lines if "그때 살아있던 프로세스" in l]
        self.assertEqual(1, len(counted))
        self.assertNotIn("0건", counted[0],
                         "대체 경로를 타고도 0건이면 추적기가 여전히 죽어 있다")


@unittest.skipUnless(KEY_READY, f"IPC auth key not available: {SECRET_PATH}")
class BlanketAuthWiringTests(unittest.TestCase):
    """운영 키로 서명하고 같은 키로 검증한다. 키 내용은 어디에도 드러내지 않는다."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.handled: list[str] = []
        self.responses: list[tuple] = []

    def gateway(self):
        from broker_gateway_v1 import BrokerGateway

        gw = BrokerGateway.__new__(BrokerGateway)   # __init__ 우회(OCX 불필요)
        gw._write_response = lambda request_id, **kw: self.responses.append(
            (request_id, kw))
        gw._handle_setreal_reg_request = (
            lambda request_id, req: self.handled.append(f"REG:{request_id}"))
        gw._handle_set_real_remove_request = (
            lambda request_id, req: self.handled.append(f"REMOVE:{request_id}"))
        return gw

    def write_request(self, payload: dict) -> Path:
        body = dict(payload)
        body.setdefault("request_id", "req-blanket-1")
        body.setdefault("ts", datetime.now().isoformat())
        body.setdefault("ttl_sec", 30)
        body.setdefault("caller", "blanket_wiring_test")
        path = self.root / f"{body['request_id']}.json"
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def run_unsigned(self, payload: dict) -> None:
        self.gateway().process_request(self.write_request(payload))

    # ── SETREAL_REG ───────────────────────────────────────────────────────

    def test_unsigned_setreal_reg_never_reaches_handler(self) -> None:
        self.run_unsigned({"type": "SETREAL_REG", "screen_no": "9001",
                           "code_list": "005930", "fid_list": "10;13"})
        self.assertEqual([], self.handled, "인증 없이 핸들러가 불리면 안 된다")
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    def test_signed_setreal_reg_reaches_handler(self) -> None:
        """정당한 호출까지 막으면 시세를 잃는다."""
        signed = sign_order_request({
            "type": "SETREAL_REG", "request_id": "req-blanket-1",
            "ts": datetime.now().isoformat(), "ttl_sec": 30,
            "caller": "blanket_wiring_test",
            "screen_no": "9001", "code_list": "005930", "fid_list": "10;13",
        })
        self.gateway().process_request(self.write_request(signed))
        self.assertEqual(["REG:req-blanket-1"], self.handled)
        self.assertEqual([], self.responses, "핸들러가 응답을 책임진다")

    # ── SET_REAL_REMOVE ───────────────────────────────────────────────────

    def test_unsigned_all_all_blocked(self) -> None:
        """8/4 잠금을 그대로 우회하던 형태."""
        self.run_unsigned({"type": "SET_REAL_REMOVE",
                           "screen_no": "ALL", "code": "ALL"})
        self.assertEqual([], self.handled)
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    def test_unsigned_screen_wipe_blocked(self) -> None:
        """화면 번호를 돌리면 전체 해제와 결과가 같다 — 여기가 새로 막힌 곳."""
        self.run_unsigned({"type": "SET_REAL_REMOVE",
                           "screen_no": "9250", "code": "ALL"})
        self.assertEqual([], self.handled)
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    def test_unsigned_scoped_remove_still_passes(self) -> None:
        """종목 하나짜리 해제까지 잠그면 정상 운영이 깨진다."""
        self.run_unsigned({"type": "SET_REAL_REMOVE",
                           "screen_no": "9001", "code": "005930"})
        self.assertEqual(["REMOVE:req-blanket-1"], self.handled)
        self.assertEqual([], self.responses)

    def test_signed_blanket_remove_reaches_handler(self) -> None:
        signed = sign_order_request({
            "type": "SET_REAL_REMOVE", "request_id": "req-blanket-1",
            "ts": datetime.now().isoformat(), "ttl_sec": 30,
            "caller": "blanket_wiring_test", "screen_no": "ALL", "code": "ALL",
        })
        self.gateway().process_request(self.write_request(signed))
        self.assertEqual(["REMOVE:req-blanket-1"], self.handled)

    def test_tampered_signature_blocked(self) -> None:
        signed = sign_order_request({
            "type": "SETREAL_REG", "request_id": "req-blanket-1",
            "ts": datetime.now().isoformat(), "ttl_sec": 30,
            "caller": "blanket_wiring_test",
            "screen_no": "9001", "code_list": "005930", "fid_list": "10;13",
        })
        signed["code_list"] = "000660"          # 서명 후 종목 바꿔치기
        self.gateway().process_request(self.write_request(signed))
        self.assertEqual([], self.handled)
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    # ── 실제 BrokerClient ─────────────────────────────────────────────────

    def test_protected_types_cover_both_commands(self) -> None:
        self.assertIn("SETREAL_REG", PROTECTED_TYPES)
        self.assertIn("SET_REAL_REMOVE", PROTECTED_TYPES)
        self.assertIn("SET_REAL_REMOVE_ALL", PROTECTED_TYPES)   # 8/4 잠금 유지
        self.assertIn("SENDORDER_REAL", PROTECTED_TYPES)        # 대조군

    def test_broker_client_signs_both_on_disk(self) -> None:
        """호출 코드는 그대로 — 클라이언트가 알아서 서명해야 한다."""
        from broker_client import BrokerClient

        for idx, (call, kind) in enumerate((
            (lambda c: c.setreal_reg("9001", "005930", "10;13", "0",
                                     timeout_sec=0.3), "SETREAL_REG"),
            (lambda c: c.set_real_remove("ALL", "ALL", timeout_sec=0.3),
             "SET_REAL_REMOVE"),
        )):
            with self.subTest(kind=kind):
                base = self.root / f"ipc{idx}"
                result = call(BrokerClient(ipc_base=base))
                self.assertEqual("TIMEOUT", result["status"],
                                 "테스트에는 브로커가 없다")

                written = list((base / "requests").glob("*.json"))
                self.assertEqual(1, len(written))
                payload = json.loads(written[0].read_text(encoding="utf-8"))
                self.assertEqual(kind, payload["type"])
                for field in ("auth_version", "auth_ts", "auth_nonce", "auth_tag"):
                    self.assertIn(field, payload, f"{field} 가 파일에 없다")
                self.assertEqual(
                    (True, ""),
                    verify_order_request(payload, expected_type=kind))


if __name__ == "__main__":
    unittest.main()
