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
    """★[SCOPED-REMOVE 2026-08-07] 형태 판정이 다시 관문이 되지 못하게 잠근다.

    8/5 에는 이 자리에 '싹 지우기 판정이 맞나'를 보는 시험이 있었다. 지금은
    SET_REAL_REMOVE 를 형태와 무관하게 전부 서명 필수로 올렸으므로
    _is_blanket_real_remove 는 기록·진단용일 뿐 관문이 아니다.
    다시 관문으로 쓰면 NUL·전각 우회가 그대로 돌아온다(보안검사 실측).
    """

    def test_dispatch_has_no_shape_based_exemption(self) -> None:
        """파일 전체를 ast 로 읽어 그 분기만 골라 본다(들여쓰기 자르기는 깨진다)."""
        import ast

        tree = ast.parse((RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8"))
        branches = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "SET_REAL_REMOVE"
        ]
        self.assertEqual(1, len(branches), "SET_REAL_REMOVE 분기를 못 찾았다")
        names, attrs = set(), set()
        for node in ast.walk(branches[0]):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    attrs.add(node.func.attr)
        self.assertNotIn("_is_blanket_real_remove", names,
                         "형태 판정이 다시 관문으로 쓰이고 있다")
        self.assertIn("_ipc_auth_ok", attrs, "서명 검사가 사라졌다")

    def test_shape_helper_is_only_diagnostic(self) -> None:
        """남겨는 뒀지만 관문이 아니다 — 형태 판정 자체는 종전대로 동작한다."""
        from broker_gateway_v1 import _is_blanket_real_remove as blanket

        self.assertTrue(blanket({"screen_no": "ALL", "code": "ALL"}))
        self.assertFalse(blanket({"screen_no": "9001", "code": "005930"}),
                         "이 값이 False 라도 이제 서명 없이는 못 지나간다")


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

    def test_unsigned_scoped_remove_is_blocked_too(self) -> None:
        """★[SCOPED-REMOVE 2026-08-07 친구님 지시 "그것도 서명 대상으로 올려"]

        8/5 에는 이 시험이 반대였다 — "종목 하나짜리 해제까지 잠그면 정상 운영이
        깨진다"고 보고 통과시켰다. 보안검사가 반례를 냈다: 구독 종목 목록은
        스냅샷에서 그냥 읽히고 poll 한 번이 발견한 요청을 전부 처리하므로,
        종목 하나짜리를 목록만큼 반복하면 전면 해제와 결과가 같다. 그러면 스냅샷
        갱신이 멈춰 매도·손절 판정까지 신선도 관문에 걸리는데 하트비트는 정상이라
        워치독이 못 잡는다. 정당한 호출자는 실전 코드에 0건임을 전수 확인했다.
        """
        self.run_unsigned({"type": "SET_REAL_REMOVE",
                           "screen_no": "9001", "code": "005930"})
        self.assertEqual([], self.handled)
        self.assertIn("authentication rejected", self.responses[0][1]["error"])

    def test_nul_and_fullwidth_all_are_blocked_too(self) -> None:
        """옛 형태 판정(_is_blanket_real_remove)이 못 잡던 우회들.

        screen_no="ALL\\x00" 은 .strip() 이 NUL 을 안 벗겨 blanket=False 로 새어
        나갔다(보안검사 실측). 이제 형태를 아예 안 따지므로 전부 막힌다.
        """
        for scr in ("ALL\x00", "ＡＬＬ", " all ", "9001"):
            with self.subTest(screen_no=repr(scr)):
                self.setUp()
                self.run_unsigned({"type": "SET_REAL_REMOVE",
                                   "screen_no": scr, "code": "005930"})
                self.assertEqual([], self.handled)

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
        self.assertIn("ACCOUNT_INFO", PROTECTED_TYPES)
        self.assertIn("BALANCE_TR", PROTECTED_TYPES)
        self.assertIn("TR", PROTECTED_TYPES)
        self.assertIn("BATCH_TR", PROTECTED_TYPES)

    def test_unsigned_account_queries_are_blocked(self) -> None:
        for request_type in ("ACCOUNT_INFO", "BALANCE_TR", "TR", "BATCH_TR"):
            with self.subTest(request_type=request_type):
                self.responses.clear()
                self.run_unsigned({"type": request_type})
                self.assertIn(
                    "authentication rejected", self.responses[0][1]["error"]
                )
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
            (lambda c: c.account_info(timeout_sec=0.3), "ACCOUNT_INFO"),
            (lambda c: c.balance_tr(
                "opw00018", {}, [], timeout_sec=0.3), "BALANCE_TR"),
            (lambda c: c.tr(
                "opt10080", {"종목코드": "005930"}, ["현재가"],
                timeout_sec=0.3), "TR"),
            (lambda c: c.batch_tr(
                "opt10080", ["005930"], {"종목코드": "{CODE}"}, ["현재가"],
                client_timeout_sec=0.3), "BATCH_TR"),
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
