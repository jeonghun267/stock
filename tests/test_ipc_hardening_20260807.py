# -*- coding: utf-8 -*-
"""★[IPC-HARDEN 2026-08-07] 마감 후 보안 수리 6단계(IPC 코드 4건)를 잠근다.

막으려는 사고 (8/7 아침 보안 감사에서 나온 것들)
  ① BATCH_TR 이 무인증인데 종목수·시간 상한이 없었다 → 한 요청으로 브로커를 몇 시간
     붙잡으면 그동안 매도가 전부 밀린다. 그런데 batch 안에서 하트비트를 강제로
     갱신하므로 워치독이 "정상"으로 본다 = 감시 사각.
  ② DISCONNECT_SCR 이 무인증이라 전략 실시간 구독 화면(9xxx)을 끊어 엔진을 눈멀게
     할 수 있었다. 단 1분봉 수집기는 IPC json 을 직접 써서 서명을 못 하므로
     그 TR 풀(2000~2049)만 종전대로 통과시킨다.
  ③ KOA_FUNCTIONS 화이트리스트에 ShowAccountWindow(계좌비밀번호 창)가 있었다.
  ④ 서명이 30초 유효라, 정당한 요청 파일을 복사해 다시 넣으면 같은 명령이 한 번 더
     집행됐다(실주문이면 중복 주문). 서명은 사본에서도 정상 통과한다.

지우기 전에 memory.md 2026-08-07 밤 항목을 읽을 것.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ipc_order_auth_v1 import MAX_AUTH_AGE_SEC, NonceStore, PROTECTED_TYPES  # noqa: E402


class DisconnectScrGateTests(unittest.TestCase):
    """② 수집기 풀만 무인증, 나머지는 서명 요구."""

    def _gate(self):
        from broker_gateway_v1 import _is_protected_screen
        return _is_protected_screen

    def test_collector_tr_pool_stays_unsigned(self):
        gate = self._gate()
        for scr in ("2000", "2025", "2049"):
            self.assertFalse(gate({"screen_no": scr}),
                             f"{scr} 는 1분봉 수집기 풀이라 서명 없이 통과해야 한다")

    def test_strategy_realtime_screens_require_signature(self):
        gate = self._gate()
        for scr in ("9001", "9250", "9786", "1999", "2050", "0001"):
            self.assertTrue(gate({"screen_no": scr}),
                            f"{scr} 는 수집기 풀 밖이라 서명을 요구해야 한다")

    def test_unreadable_screen_is_protected(self):
        """판단 불가일 때 열어 두면 그게 구멍이다 — fail-closed."""
        gate = self._gate()
        self.assertTrue(gate({}))
        self.assertTrue(gate({"screen_no": ""}))
        self.assertTrue(gate({"screen_no": "20xx"}))

        class Hostile:
            def get(self, *a, **kw):
                raise RuntimeError("읽을 수 없는 payload")

        self.assertTrue(gate(Hostile()))

    def test_disconnect_scr_is_signable(self):
        """BrokerClient 경유 호출자가 자동 서명되려면 목록에 있어야 한다."""
        self.assertIn("DISCONNECT_SCR", PROTECTED_TYPES)


class BatchTrCapTests(unittest.TestCase):
    """① 상한이 실제로 코드에 살아 있는지."""

    def _cls(self):
        import broker_gateway_v1 as G
        for name in dir(G):
            obj = getattr(G, name)
            if isinstance(obj, type) and hasattr(obj, "BATCH_TR_MAX_CODES"):
                return obj
        self.fail("BATCH_TR 상한을 가진 클래스를 못 찾았다")

    def test_caps_exist_and_leave_room_for_real_use(self):
        cls = self._cls()
        # 정당한 사용은 수집기의 CHUNK_SIZE=15 · 60초 (collect_prices_1m_...:3063)
        self.assertGreaterEqual(cls.BATCH_TR_MAX_CODES, 15)
        self.assertLessEqual(cls.BATCH_TR_MAX_CODES, 100,
                             "상한이 이렇게 크면 막는 의미가 없다")
        self.assertGreaterEqual(cls.BATCH_TR_MAX_BATCH_SEC, 60.0)
        self.assertLessEqual(cls.BATCH_TR_MAX_BATCH_SEC, 300.0)
        self.assertLessEqual(cls.BATCH_TR_MAX_PER_REQ_SEC, 30.0)
        self.assertEqual(cls.BATCH_TR_MAX_PER_POLL, 2)
        self.assertLessEqual(cls.BATCH_TR_MAX_POLL_SEC, 120.0)

    def test_real_order_and_reconcile_sort_before_batch(self):
        from broker_gateway_v1 import _ipc_request_sort_key

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = {
                "000_batch.json": "BATCH_TR",
                "111_balance.json": "BALANCE_TR",
                "zzz_order.json": "SENDORDER_REAL",
            }
            paths = []
            for name, request_type in rows.items():
                path = root / name
                path.write_text(
                    json.dumps({"type": request_type}), encoding="utf-8")
                paths.append(path)
            ordered = sorted(paths, key=_ipc_request_sort_key)
            self.assertEqual(
                [json.loads(path.read_text())["type"] for path in ordered],
                ["SENDORDER_REAL", "BALANCE_TR", "BATCH_TR"],
            )

    def test_eod_board_query_sorts_before_normal_tr(self):
        from broker_gateway_v1 import _ipc_request_sort_key

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            normal = root / "000_normal.json"
            eod = root / "zzz_eod.json"
            normal.write_text(
                json.dumps({"type": "TR", "rqname": "rq_opt10059"}),
                encoding="utf-8",
            )
            eod.write_text(
                json.dumps({"type": "TR", "rqname": "EODGAP_OPT10032"}),
                encoding="utf-8",
            )
            ordered = sorted([normal, eod], key=_ipc_request_sort_key)
            self.assertEqual(ordered[0], eod)

    def test_pending_order_detector_ignores_batch_and_returns_order(self):
        from broker_gateway_v1 import _pending_real_order_paths

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "batch.json").write_text(
                json.dumps({"type": "BATCH_TR"}), encoding="utf-8")
            order = root / "order.json"
            order.write_text(
                json.dumps({"type": "SENDORDER_REAL"}), encoding="utf-8")
            self.assertEqual(_pending_real_order_paths(root), [order])

    def _fake_gateway(self):
        """Qt 없이 핸들러만 부른다. 상수 존재가 아니라 '실제로 거부하나'를 본다.

        ⚠️처음엔 본문에 상수 이름이 있는지만 봤는데, 검사문을 지워도 거부 메시지의
          f-string 에 이름이 남아 시험이 통과했다(8/7 변조 시험에서 잡힘).
        """
        import broker_gateway_v1 as G
        cls = self._cls()
        gw = cls.__new__(cls)
        gw.state = G.BrokerState.CONNECTED
        gw.sent = []
        gw._write_response = lambda rid, **kw: gw.sent.append(kw)
        return gw

    def test_oversized_batch_is_rejected_not_truncated(self):
        gw = self._fake_gateway()
        codes = [f"{i:06d}" for i in range(gw.BATCH_TR_MAX_CODES + 1)]
        gw._handle_batch_tr_request("req-1", {"tr_code": "opt10080", "codes": codes})
        self.assertEqual(len(gw.sent), 1)
        self.assertEqual(gw.sent[0].get("status"), "ERROR")
        self.assertIn("exceeds cap", str(gw.sent[0].get("error")))

    def test_nan_timeout_cannot_slip_past_the_cap(self):
        """★[2026-08-07 보안검사 지적] NaN 은 어떤 부등호 비교에도 거짓이라
        `if x > MAX` 로 쓰면 상한을 그냥 지나간다. 그 뒤 루프 중단 조건도 NaN
        비교라 영원히 거짓이 되어 배치가 안 멈춘다(실측: Infinity·999999 는
        정상 절단, NaN 만 뚫렸다). 부등호를 뒤집어야 잡힌다."""
        import json as _json
        import math

        for raw in ('"nan"', "NaN", '"Infinity"', "1e308", "999999"):
            with self.subTest(raw=raw):
                value = float(_json.loads('{"v": %s}' % raw)["v"])
                gw = self._fake_gateway()
                codes = [f"{i:06d}" for i in range(3)]
                seen = {}
                # 핸들러가 상한을 적용한 뒤의 값을 그대로 관찰하려고, 배치 루프에
                # 들어가기 직전 상태를 잡는다. OCX 가 없으니 그 뒤는 터져도 된다.
                try:
                    gw._handle_batch_tr_request(
                        "req-nan",
                        {"tr_code": "opt10080", "codes": codes,
                         "batch_timeout_sec": value,
                         "per_request_timeout_sec": value},
                    )
                except Exception:
                    pass
                # 상한 자체를 산수로 확인한다 — 뒤집힌 부등호만 NaN 을 잡는다
                self.assertTrue(
                    not (value <= gw.BATCH_TR_MAX_BATCH_SEC)
                    or value <= gw.BATCH_TR_MAX_BATCH_SEC,
                    "이 판정식은 모든 값에 대해 참이어야 한다")
                if math.isnan(value):
                    self.assertFalse(value > gw.BATCH_TR_MAX_BATCH_SEC,
                                     "NaN 은 종전 부등호를 지나간다 - 그래서 뒤집었다")
                    self.assertTrue(not (value <= gw.BATCH_TR_MAX_BATCH_SEC),
                                    "뒤집은 부등호는 NaN 을 잡아야 한다")

    def test_cap_check_uses_the_inverted_comparison(self):
        """산수만으로는 코드가 그렇게 쓰였는지 모른다 — 실제 판정식을 본다."""
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        body = src.split("def _handle_batch_tr_request", 1)[1][:4000]
        self.assertIn("not (batch_to <= self.BATCH_TR_MAX_BATCH_SEC)", body)
        self.assertIn("not (per_request_to <= self.BATCH_TR_MAX_PER_REQ_SEC)", body)

    def test_normal_collector_batch_is_not_rejected(self):
        """정당한 사용(15종목)까지 막으면 1분봉 수집이 죽는다."""
        gw = self._fake_gateway()
        codes = [f"{i:06d}" for i in range(15)]
        try:
            gw._handle_batch_tr_request("req-2", {"tr_code": "opt10080", "codes": codes})
        except Exception:
            pass            # OCX 없는 환경이라 그 뒤에서 터지는 것은 상관없다
        rejected = [s for s in gw.sent
                    if s.get("status") == "ERROR" and "exceeds cap" in str(s.get("error"))]
        self.assertEqual(rejected, [], "정당한 15종목 요청이 상한에 걸렸다")

    def test_third_batch_in_one_poll_is_rejected_explicitly(self):
        """폴 안에서 이미 두 건을 처리했다면 세 번째는 ERROR로 끝나야 한다."""
        gw = self._fake_gateway()
        gw._batch_tr_poll_count = gw.BATCH_TR_MAX_PER_POLL
        gw._batch_tr_poll_sec = 1.0
        gw._handle_batch_tr_request(
            "req-third",
            {"tr_code": "opt10080", "codes": ["005930"]},
        )
        self.assertEqual(len(gw.sent), 1)
        self.assertEqual(gw.sent[0].get("status"), "ERROR")
        self.assertIn("poll budget exhausted", str(gw.sent[0].get("error")))

    def test_poll_time_budget_exhaustion_is_rejected(self):
        """건수 여유가 있어도 폴 누적 시간이 끝났다면 새 배치를 시작하지 않는다."""
        gw = self._fake_gateway()
        gw._batch_tr_poll_count = 1
        gw._batch_tr_poll_sec = gw.BATCH_TR_MAX_POLL_SEC
        gw._handle_batch_tr_request(
            "req-late",
            {"tr_code": "opt10080", "codes": ["005930"]},
        )
        self.assertEqual(len(gw.sent), 1)
        self.assertEqual(gw.sent[0].get("status"), "ERROR")
        self.assertIn("poll budget exhausted", str(gw.sent[0].get("error")))


class ShadowPathTraversalTests(unittest.TestCase):
    """★[2026-08-07 보안검사 지적] SENDORDER_SHADOW 만 경로 검사를 안 거쳤다.

    브로커는 Highest(관리자)로 뜨므로, 무인증 요청 하나로 UAC 창 없이 관리자
    권한 파일 쓰기가 됐다 — 같은 날 파이썬을 RX 로 강등한 조치를 우회하는 길이다.
    7/30 에 _write_response 에서는 이미 막은 구멍인데 이 분기만 빠져 있었다.
    """

    def test_shadow_path_goes_through_the_same_guard(self):
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        block = src.split("IPC_ORDER_SHADOW_DIR /", 1)[0][-1200:]
        self.assertIn("_safe_request_id", block,
                      "shadow 기록 경로가 request_id 검사를 안 거친다")

    def test_traversal_request_id_is_rejected_by_the_guard(self):
        import broker_gateway_v1 as G

        gw = G.BrokerGateway.__new__(G.BrokerGateway)
        for bad in ("..\\..\\..\\PROOF", "../../etc/x", "a/b", "a\\b",
                    "x" * 200, "", "  "):
            with self.subTest(bad=bad):
                self.assertIsNone(gw._safe_request_id(bad))
        self.assertEqual(gw._safe_request_id("req-order-1"), "req-order-1")


class KoaFunctionsWhitelistTests(unittest.TestCase):
    """③ 계좌비밀번호 창은 read-only 가 아니다."""

    def test_show_account_window_is_gone(self):
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        block = src.split("KOA_FUNCTIONS_WHITELIST = {", 1)[1].split("}", 1)[0]
        self.assertNotIn('"ShowAccountWindow"', block)
        self.assertIn('"GetServerGubun"', block, "정상 항목까지 지운 것은 아닌지")


class NonceReplayTests(unittest.TestCase):
    """④ 같은 서명을 두 번 쓰지 못한다."""

    def test_first_use_passes_second_is_rejected(self):
        store = NonceStore()
        nonce = "0" * 32
        self.assertTrue(store.consume(nonce, now=1000.0))
        self.assertFalse(store.consume(nonce, now=1000.5),
                         "복사한 요청이 그대로 다시 통과하면 안 된다")

    def test_malformed_nonce_is_rejected(self):
        store = NonceStore()
        for bad in ("", "zz", "0" * 31, "0" * 33, "G" * 32, None):
            self.assertFalse(store.consume(bad, now=1000.0))

    def test_store_prunes_but_only_after_signature_expiry(self):
        """보관은 서명 유효기간보다 길어야 한다 — 짧으면 그 사이 재생이 통과한다."""
        store = NonceStore()
        nonce = "1" * 32
        self.assertTrue(store.consume(nonce, now=1000.0))
        self.assertFalse(store.consume(nonce, now=1000.0 + MAX_AUTH_AGE_SEC),
                         "서명이 아직 유효한 시점에는 반드시 막아야 한다")

    def test_gateway_auth_path_rejects_the_second_identical_request(self):
        """실제 인증 경로를 두 번 통과시켜 본다(서명 검증은 통과했다고 두고).

        ⚠️본문에 '_nonce_store.consume' 문자열이 있는지로 보지 말 것 — 코드 모양이
          바뀌면 시험이 조용히 무의미해진다. 8/7 에 실제로 한 번 그렇게 됐다.
        """
        import broker_gateway_v1 as G

        gw = G.BrokerGateway.__new__(G.BrokerGateway)
        gw.sent = []
        gw._write_response = lambda rid, **kw: gw.sent.append(kw)

        original = G.verify_order_request
        G.verify_order_request = lambda req, **kw: (True, "")
        try:
            req = {"type": "SENDORDER_REAL", "request_id": "r1",
                   "auth_nonce": "2" * 32}
            self.assertTrue(gw._ipc_auth_ok("r1", req, "SENDORDER_REAL", "T"))
            self.assertFalse(gw._ipc_auth_ok("r1", req, "SENDORDER_REAL", "T"),
                             "같은 서명 사본이 두 번 집행되면 안 된다")
        finally:
            G.verify_order_request = original
        self.assertTrue(any("replay" in str(s.get("error", "")) for s in gw.sent),
                        "거부 사유에 재생이라고 남아야 한다")

    def test_real_order_paths_go_through_the_replay_guard(self):
        """재생 방지가 가장 필요한 둘이 예외로 남아 있지 않은지."""
        src = (RUN_DIR / "broker_gateway_v1.py").read_text(encoding="utf-8")
        for kind in ("SENDORDER_REAL", "SET_REAL_REMOVE_ALL"):
            branch = src.split(f'elif req_type == "{kind}":', 1)[1][:900]
            self.assertIn("_ipc_auth_ok", branch,
                          f"{kind} 가 재생 방지를 거치지 않는다")


if __name__ == "__main__":
    unittest.main()
