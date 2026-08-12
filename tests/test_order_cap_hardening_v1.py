# -*- coding: utf-8 -*-
"""★[SEC-CAP 2026-08-05] 주문 빗장의 구멍 두 개.

① 일일 매수 건수가 메모리 변수뿐이라 브로커를 다시 띄우면 0 이 됐다.
   워치독이 자동 재기동하므로 BROKER_MAX_DAILY_BUY=100 은 '하루 100건'이 아니라
   '브로커 수명당 100건'이었다.
② 상한값이 0 이면 검사부(`if _max > 0 and ...`)가 통째로 꺼졌다.
   BROKER_MAX_ORDER_QTY=0 한 줄로 수량 빗장이 로그 한 줄 없이 사라졌다.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# 실행 중인 브로커가 broker_journal.log 를 잠가도 단위시험은 파일을 열지 않는다.
_LOG_HANDLER_PATCH = patch(
    "logging.handlers.RotatingFileHandler",
    side_effect=lambda *args, **kwargs: logging.NullHandler(),
)
_LOG_HANDLER_PATCH.start()

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


class CapEnvTests(unittest.TestCase):
    """② 상한을 조용히 끄는 길이 남아 있나."""

    NAME = "BROKER_TEST_CAP_ONLY"

    def setUp(self) -> None:
        import broker_gateway_v1 as bg

        self.bg = bg
        self.addCleanup(os.environ.pop, self.NAME, None)

    def cap(self, value=None):
        if value is None:
            os.environ.pop(self.NAME, None)
        else:
            os.environ[self.NAME] = str(value)
        return self.bg._order_cap_env(self.NAME, 5)

    def test_zero_and_negative_fall_back_to_default(self) -> None:
        for value in ("0", "-1", " 0 ", "-999"):
            with self.subTest(value=value):
                self.assertEqual(5, self.cap(value),
                                 "0 이하로 상한을 끌 수 있으면 빗장이 아니다")

    def test_garbage_falls_back_to_default(self) -> None:
        for value in ("", "abc", "3.7"):
            with self.subTest(value=value):
                self.assertEqual(5, self.cap(value))

    def test_normal_values_are_honoured(self) -> None:
        self.assertEqual(3, self.cap("3"))
        self.assertEqual(1, self.cap("1"))
        self.assertEqual(5, self.cap(None), "미설정이면 기본값")


class BuyCountPersistTests(unittest.TestCase):
    """① 일일 매수 건수가 재기동을 견디나."""

    def setUp(self) -> None:
        import broker_gateway_v1 as bg
        from broker_gateway_v1 import BrokerGateway

        self.bg = bg
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "broker_buy_count.json"
        self.real_path = bg.BUY_COUNT_FILE
        bg.BUY_COUNT_FILE = self.path
        self.addCleanup(setattr, bg, "BUY_COUNT_FILE", self.real_path)

        self.gw = BrokerGateway.__new__(BrokerGateway)
        self.today = datetime.now().strftime("%Y%m%d")

    def write(self, date: str, count: int) -> None:
        self.path.write_text(json.dumps({"date": date, "count": count}),
                             encoding="utf-8")

    def test_missing_file_starts_at_zero(self) -> None:
        self.assertEqual((self.today, 0), self.gw._load_buy_count(self.today))

    def test_missing_file_reconstructs_today_from_idempotency(self) -> None:
        today_iso = datetime.now().isoformat()
        self.gw._sendorder_idempotency_cache = {
            "buy-1": (datetime.now().timestamp(), {
                "status": "OK", "data": {"order_type": 1, "ts": today_iso},
            }),
            "sell-1": (datetime.now().timestamp(), {
                "status": "OK", "data": {"order_type": 2, "ts": today_iso},
            }),
        }
        self.assertEqual((self.today, 1), self.gw._load_buy_count(self.today))

    def test_same_day_count_survives_restart(self) -> None:
        """이게 이번 수리의 핵심 — 재기동해도 오늘 건수를 이어받는다."""
        self.write(self.today, 7)
        self.assertEqual((self.today, 7), self.gw._load_buy_count(self.today))

    def test_yesterday_file_does_not_leak_into_today(self) -> None:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        self.write(yesterday, 99)
        self.assertEqual((self.today, 0), self.gw._load_buy_count(self.today))

    def test_corrupt_file_fails_closed(self) -> None:
        """파일 하나 깨졌다고 그날 매수를 통째로 막으면 더 위험하다."""
        self.path.write_text("{망가진 json", encoding="utf-8")
        expected = self.bg._order_cap_env("BROKER_MAX_DAILY_BUY", 100)
        self.assertEqual(
            (self.today, expected), self.gw._load_buy_count(self.today)
        )

    def test_save_then_load_round_trip(self) -> None:
        self.gw._buy_count_date = self.today
        self.gw._buy_count = 4
        self.gw._save_buy_count()
        self.assertTrue(self.path.exists())
        self.assertEqual((self.today, 4), self.gw._load_buy_count(self.today))


class DailyCapAcrossRestartTests(unittest.TestCase):
    """실제 주문 핸들러로 — 새로 뜬 브로커가 어제 상태를 이어받는가."""

    def setUp(self) -> None:
        import broker_gateway_v1 as bg
        from broker_gateway_v1 import BrokerGateway, BrokerState

        self.bg = bg
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "broker_buy_count.json"
        self.idempotency_path = Path(self.temp.name) / "broker_idempotency.json"
        self.manual_block_path = Path(self.temp.name) / "manual_buy_block.flag"
        self.only_moneyflow_path = Path(self.temp.name) / "only_moneyflow.flag"
        self.kosdaq_path = Path(self.temp.name) / "kosdaq_index.json"
        self.us_path = Path(self.temp.name) / "us_overnight.json"
        self.shares_path = Path(self.temp.name) / "shares_outstanding.csv"
        real_path = bg.BUY_COUNT_FILE
        real_idempotency_path = bg.SENDORDER_IDEMPOTENCY_FILE
        real_manual_block_path = bg.MANUAL_BUY_BLOCK_FILE
        real_only_moneyflow_path = bg.ONLY_MONEYFLOW_FLAG
        real_kosdaq_path = bg.KOSDAQ_INDEX_FILE
        real_us_path = bg.US_OVERNIGHT_FILE
        real_shares_path = bg.SHARES_OUTSTANDING_FILE
        bg.BUY_COUNT_FILE = self.path
        bg.SENDORDER_IDEMPOTENCY_FILE = self.idempotency_path
        bg.MANUAL_BUY_BLOCK_FILE = self.manual_block_path
        bg.ONLY_MONEYFLOW_FLAG = self.only_moneyflow_path
        bg.KOSDAQ_INDEX_FILE = self.kosdaq_path
        bg.US_OVERNIGHT_FILE = self.us_path
        bg.SHARES_OUTSTANDING_FILE = self.shares_path
        bg._GATEWAY_SHARES_CACHE = {}
        bg._GATEWAY_SHARES_MTIME = None
        self.addCleanup(setattr, bg, "BUY_COUNT_FILE", real_path)
        self.addCleanup(
            setattr, bg, "SENDORDER_IDEMPOTENCY_FILE", real_idempotency_path
        )
        self.addCleanup(
            setattr, bg, "MANUAL_BUY_BLOCK_FILE", real_manual_block_path
        )
        self.addCleanup(setattr, bg, "ONLY_MONEYFLOW_FLAG", real_only_moneyflow_path)
        self.addCleanup(setattr, bg, "KOSDAQ_INDEX_FILE", real_kosdaq_path)
        self.addCleanup(setattr, bg, "US_OVERNIGHT_FILE", real_us_path)
        self.addCleanup(setattr, bg, "SHARES_OUTSTANDING_FILE", real_shares_path)

        os.environ["BROKER_MAX_DAILY_BUY"] = "2"
        os.environ["SAFEPLUS_MIN_PRICE"] = "0"
        os.environ["SAFEPLUS_MIN_MARKETCAP"] = "0"
        self.addCleanup(os.environ.pop, "BROKER_MAX_DAILY_BUY", None)
        self.addCleanup(os.environ.pop, "SAFEPLUS_MIN_PRICE", None)
        self.addCleanup(os.environ.pop, "SAFEPLUS_MIN_MARKETCAP", None)
        for name in ("ONLY_MF_ALLOW", "MARKET_REGIME_GATE",
                     "MARKET_DROP_REDUCE", "MARKET_DROP_STOP",
                     "REGIME_STOP_EXEMPT", "US_DANGER_BLOCK"):
            self.addCleanup(os.environ.pop, name, None)

        self.responses: list[tuple] = []
        self.reached: list[str] = []
        self.order_args = None
        self.ocx_ret = 0
        self.master_price = 0
        outer = self

        class Ocx:
            def dynamicCall(self, *a, **kw):
                if a and "GetLoginInfo" in str(a[0]):
                    return "0000000000;"
                if a and "GetMasterLastPrice" in str(a[0]):
                    outer.reached.append("master-price")
                    return outer.master_price
                outer.reached.append("ocx")
                if a and "SendOrder" in str(a[0]) and len(a) > 1:
                    outer.order_args = a[1]
                return outer.ocx_ret

        gw = BrokerGateway.__new__(BrokerGateway)   # 방금 뜬 브로커와 같은 상태
        gw.state = BrokerState.CONNECTED
        gw.ocx = Ocx()
        gw._sendorder_idempotency_cache = {}
        gw._micro_snapshot = {"005930": {"cur": 1000}}
        gw._purge_sendorder_idempotency = lambda: None
        gw._write_response = lambda request_id, **kw: self.responses.append(
            (request_id, kw))
        self.gw = gw
        self.today = datetime.now().strftime("%Y%m%d")

    def buy(self, key: str) -> None:
        self.gw._handle_sendorder_real_request(key, {
            "type": "SENDORDER_REAL", "request_id": key,
            "idempotency_key": key, "ts": datetime.now().isoformat(),
            "ttl_sec": 15, "account": "0000000000", "code": "005930",
            "qty": 1, "order_type": 1, "price": 1000, "hoga_gb": "00",
        })

    def test_restart_does_not_reset_the_daily_cap(self) -> None:
        """8/5 이전: 재기동하면 여기서 그냥 통과했다."""
        self.path.write_text(json.dumps({"date": self.today, "count": 2}),
                             encoding="utf-8")
        self.buy("after-restart-1")

        self.assertEqual([], self.reached, "상한을 넘겼는데 키움까지 갔다")
        self.assertEqual(1, len(self.responses))
        self.assertTrue(self.responses[0][1]["error"].startswith("ORDER_CAP"),
                        self.responses[0][1]["error"])
        self.assertIn("일일 매수 건수", self.responses[0][1]["error"])

    def test_counter_is_written_to_disk_on_each_buy(self) -> None:
        self.buy("fresh-1")
        self.assertIn("ocx", self.reached, "정상 주문이 막혔다")
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.today, saved["date"])
        self.assertEqual(1, saved["count"])

    def test_initial_buy_count_save_failure_leaves_no_inflight(self) -> None:
        self.gw._save_buy_count = lambda: False
        self.buy("count-save-fail")

        self.assertEqual([], self.reached)
        self.assertNotIn("count-save-fail", self.gw._sendorder_idempotency_cache)
        self.assertIn("BUY_COUNT_PERSIST_FAILED", self.responses[-1][1]["error"])

    def test_rejected_buy_rolls_back_daily_count(self) -> None:
        self.ocx_ret = -1
        self.buy("rejected-1")

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(0, saved["count"])
        self.assertEqual(0, self.gw._buy_count)

    def test_idempotency_survives_broker_restart(self) -> None:
        from broker_gateway_v1 import BrokerGateway, BrokerState

        self.buy("durable-key-1")
        self.reached.clear()
        restarted = BrokerGateway.__new__(BrokerGateway)
        restarted.state = BrokerState.CONNECTED
        restarted._sendorder_idempotency_cache = (
            restarted._load_sendorder_idempotency()
        )
        restarted._write_response = lambda request_id, **kw: self.responses.append(
            (request_id, kw)
        )

        restarted._handle_sendorder_real_request("retry", {
            "idempotency_key": "durable-key-1",
            "account": "0000000000", "code": "005930", "qty": 1,
            "order_type": 1, "price": 1000, "hoga_gb": "00",
        })

        self.assertEqual([], self.reached)
        self.assertIn("durable-key-1", restarted._sendorder_idempotency_cache)

    def test_old_reconciliation_states_survive_restart_ttl(self) -> None:
        from broker_gateway_v1 import BrokerGateway

        old_ts = (datetime.now() - timedelta(days=3)).timestamp()
        self.idempotency_path.write_text(json.dumps({"entries": {
            "uncertain-old": {"ts": old_ts, "response": {
                "status": "ERROR", "data": {"state": "IN_FLIGHT"},
                "error": "SENDORDER_IN_FLIGHT_RECONCILE_REQUIRED",
            }},
            "__LOAD_FAILED__": {"ts": old_ts, "response": {
                "status": "ERROR", "data": None,
                "error": "SENDORDER_IDEMPOTENCY_LOAD_FAILED",
            }},
        }}), encoding="utf-8")
        restarted = BrokerGateway.__new__(BrokerGateway)
        restored = restarted._load_sendorder_idempotency()
        self.assertIn("uncertain-old", restored)
        self.assertIn("__LOAD_FAILED__", restored)

    def test_cancel_and_modify_require_origin_order_number(self) -> None:
        for order_type in (3, 4, 5, 6):
            with self.subTest(order_type=order_type):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(f"origin-{order_type}", {
                    "idempotency_key": f"origin-{order_type}",
                    "account": "0000000000", "code": "005930", "qty": 1,
                    "order_type": order_type, "price": 1000, "hoga_gb": "00",
                    "origin_order_no": "",
                })
                self.assertEqual([], self.reached)
                self.assertIn("origin_order_no", self.responses[-1][1]["error"])

    def test_origin_order_number_must_be_ascii_digits(self) -> None:
        for index, origin in enumerate(("ABC123", "１２３", "1" * 21)):
            with self.subTest(origin=origin):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(f"bad-origin-{index}", {
                    "idempotency_key": f"bad-origin-{index}",
                    "account": "0000000000", "code": "005930", "qty": 1,
                    "order_type": 3, "price": 0, "hoga_gb": "00",
                    "origin_order_no": origin,
                })
                self.assertEqual([], self.reached)
                self.assertIn("ASCII digits", self.responses[-1][1]["error"])

    def test_inflight_record_contains_reconciliation_metadata(self) -> None:
        captured = {}

        def fail_first_save():
            captured.update(self.gw._sendorder_idempotency_cache)
            return False

        self.gw._save_sendorder_idempotency = fail_first_save
        self.buy("metadata-1")

        self.assertEqual([], self.reached)
        response = captured["metadata-1"][1]
        self.assertEqual("IN_FLIGHT", response["data"]["state"])
        self.assertEqual("005930", response["data"]["code"])
        self.assertEqual(1, response["data"]["qty"])
        self.assertEqual("0000**", response["data"]["account_masked"])
        self.assertNotIn("account", response["data"])

    def test_unresolved_order_blocks_later_orders(self) -> None:
        self.gw._sendorder_idempotency_cache["uncertain-1"] = (
            datetime.now().timestamp(),
            {"status": "ERROR", "data": {"state": "IN_FLIGHT"},
             "error": "SENDORDER_IN_FLIGHT_RECONCILE_REQUIRED"},
        )
        self.buy("later-1")

        self.assertEqual([], self.reached)
        self.assertIn("SENDORDER_RECONCILE_REQUIRED",
                      self.responses[-1][1]["error"])

    def test_unresolved_order_does_not_block_sell(self) -> None:
        self.gw._sendorder_idempotency_cache["uncertain-buy"] = (
            datetime.now().timestamp(),
            {"status": "ERROR", "data": {"state": "IN_FLIGHT"},
             "error": "SENDORDER_IN_FLIGHT_RECONCILE_REQUIRED"},
        )
        self.gw._handle_sendorder_real_request("exit-despite-uncertain", {
            "idempotency_key": "exit-despite-uncertain",
            "ts": datetime.now().isoformat(), "ttl_sec": 8,
            "account": "0000000000", "code": "005930", "qty": 1,
            "order_type": 2, "price": 1000, "hoga_gb": "00",
            "screen_no": "9999", "rqname": "exit-despite-uncertain",
        })
        self.assertIn("ocx", self.reached)

    def test_idempotency_load_failure_does_not_block_sell(self) -> None:
        self.gw._sendorder_idempotency_cache = {
            "__LOAD_FAILED__": (
                datetime.now().timestamp(),
                {"status": "ERROR", "data": None,
                 "error": "SENDORDER_IDEMPOTENCY_LOAD_FAILED"},
            ),
        }
        self.gw._handle_sendorder_real_request("exit-after-load-failure", {
            "idempotency_key": "exit-after-load-failure",
            "ts": datetime.now().isoformat(), "ttl_sec": 8,
            "account": "0000000000", "code": "005930", "qty": 1,
            "order_type": 2, "price": 1000, "hoga_gb": "00",
            "screen_no": "9999", "rqname": "exit-after-load-failure",
        })
        self.assertIn("ocx", self.reached)
        self.assertIn("__LOAD_FAILED__", self.gw._sendorder_idempotency_cache)

    def test_final_idempotency_save_failure_blocks_retries(self) -> None:
        calls = 0

        def save_sequence():
            nonlocal calls
            calls += 1
            return calls == 1

        self.gw._save_sendorder_idempotency = save_sequence
        self.buy("final-save-fail-1")

        self.assertIn("ocx", self.reached)
        self.assertEqual("SENDORDER_RESULT_PERSIST_FAILED_RECONCILE_REQUIRED",
                         self.responses[-1][1]["error"])
        cached = self.gw._sendorder_idempotency_cache["final-save-fail-1"][1]
        self.assertEqual("SENDORDER_IN_FLIGHT_RECONCILE_REQUIRED", cached["error"])

    def test_buy_count_rollback_failure_blocks_next_buy(self) -> None:
        self.ocx_ret = -1
        calls = 0

        def save_sequence():
            nonlocal calls
            calls += 1
            return calls == 1

        self.gw._save_buy_count = save_sequence
        self.buy("rollback-save-fail-1")
        self.assertTrue(self.gw._buy_count_persist_failed)
        self.assertIn("BUY_COUNT_RECONCILE_REQUIRED",
                      self.responses[-1][1]["error"])

        self.reached.clear()
        self.responses.clear()
        self.ocx_ret = 0
        self.buy("blocked-after-rollback-1")
        self.assertEqual([], self.reached)
        self.assertIn("BUY_COUNT_RECONCILE_REQUIRED",
                      self.responses[-1][1]["error"])

    def test_invalid_and_future_order_times_are_blocked(self) -> None:
        for label, ts in (
            ("missing", ""),
            ("broken", "not-a-time"),
            ("future", (datetime.now() + timedelta(minutes=5)).isoformat()),
        ):
            with self.subTest(label=label):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(label, {
                    "idempotency_key": label, "ts": ts, "ttl_sec": 8,
                    "account": "0000000000", "code": "005930", "qty": 1,
                    "order_type": 2, "price": 1000, "hoga_gb": "00",
                })
                self.assertEqual([], self.reached)
                self.assertIn("ORDER_TTL", self.responses[-1][1]["error"])

    def test_negative_price_is_blocked(self) -> None:
        self.gw._handle_sendorder_real_request("negative-price", {
            "idempotency_key": "negative-price", "ts": datetime.now().isoformat(),
            "ttl_sec": 8, "account": "0000000000", "code": "005930",
            "qty": 1, "order_type": 1, "price": -1000, "hoga_gb": "00",
        })
        self.assertEqual([], self.reached)
        self.assertIn("price must be >= 0", self.responses[-1][1]["error"])

    def test_same_key_with_different_order_is_rejected(self) -> None:
        self.buy("same-key-1")
        self.reached.clear()
        self.responses.clear()
        self.gw._handle_sendorder_real_request("retry-different", {
            "idempotency_key": "same-key-1", "ts": datetime.now().isoformat(),
            "ttl_sec": 8, "account": "0000000000", "code": "005930",
            "qty": 2, "order_type": 1, "price": 1000, "hoga_gb": "00",
        })
        self.assertEqual([], self.reached)
        self.assertIn("PAYLOAD_MISMATCH", self.responses[-1][1]["error"])

    def test_legacy_idempotency_entry_requires_reconciliation(self) -> None:
        self.gw._sendorder_idempotency_cache["legacy-key"] = (
            datetime.now().timestamp(),
            {"status": "OK", "data": {"ret": 0, "code": "005930"},
             "error": None},
        )
        self.buy("legacy-key")
        self.assertEqual([], self.reached)
        self.assertIn("LEGACY_RECONCILE_REQUIRED",
                      self.responses[-1][1]["error"])

    def test_idempotency_key_is_bounded_safe_ascii(self) -> None:
        for index, key in enumerate(("x" * 129, "한글-key", "bad/key")):
            with self.subTest(key=key):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(f"bad-key-{index}", {
                    "idempotency_key": key, "account": "0000000000",
                    "code": "005930", "qty": 1, "order_type": 2,
                    "price": 1000, "hoga_gb": "00",
                })
                self.assertEqual([], self.reached)
                self.assertIn("safe ASCII", self.responses[-1][1]["error"])

    def test_unresolved_order_is_never_ttl_purged(self) -> None:
        old = datetime.now().timestamp() - self.gw._SENDORDER_IDEMPOTENCY_TTL_SEC - 10
        self.gw._sendorder_idempotency_cache["uncertain-old"] = (
            old,
            {"status": "ERROR", "data": {"state": "IN_FLIGHT"},
             "error": "SENDORDER_IN_FLIGHT_RECONCILE_REQUIRED"},
        )
        self.gw._purge_sendorder_idempotency()
        self.assertIn("uncertain-old", self.gw._sendorder_idempotency_cache)

    def test_gateway_manual_block_cannot_be_bypassed(self) -> None:
        self.manual_block_path.write_text("BLOCK", encoding="utf-8")
        self.buy("gateway-manual-block")
        self.assertEqual([], self.reached)
        self.assertIn("manual_buy_block", self.responses[-1][1]["error"])

    def test_gateway_manual_block_read_error_fails_closed(self) -> None:
        class BrokenPath:
            def exists(self):
                raise OSError("denied")

        self.bg.MANUAL_BUY_BLOCK_FILE = BrokenPath()
        self.buy("gateway-manual-read-error")
        self.assertEqual([], self.reached)
        self.assertIn("check unavailable", self.responses[-1][1]["error"])

    def test_gateway_only_moneyflow_block_cannot_be_bypassed(self) -> None:
        self.only_moneyflow_path.write_text("BLOCK", encoding="utf-8")
        os.environ["ONLY_MF_ALLOW"] = "MFLOW"
        self.buy("gateway-only-moneyflow")
        self.assertEqual([], self.reached)
        self.assertIn("only_moneyflow", self.responses[-1][1]["error"])

    def test_gateway_market_regime_stop_cannot_be_bypassed(self) -> None:
        os.environ["MARKET_REGIME_GATE"] = "YES"
        self.kosdaq_path.write_text(json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%dT09:01:00"),
            "chg": -3.5,
        }), encoding="utf-8")
        self.buy("gateway-regime-stop")
        self.assertEqual([], self.reached)
        self.assertIn("-3.50%", self.responses[-1][1]["error"])

    def test_gateway_applies_market_regime_reduction_once(self) -> None:
        os.environ["MARKET_REGIME_GATE"] = "YES"
        os.environ["REGIME_CUT"] = "0.5"
        self.kosdaq_path.write_text(json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%dT09:01:00"),
            "chg": -2.5,
        }), encoding="utf-8")
        self.gw._handle_sendorder_real_request("gateway-regime-cut", {
            "idempotency_key": "gateway-regime-cut",
            "ts": datetime.now().isoformat(), "ttl_sec": 8,
            "account": "0000000000", "code": "005930", "qty": 4,
            "order_type": 1, "price": 1000, "hoga_gb": "00",
            "screen_no": "9999", "rqname": "gateway-regime-cut",
        })
        self.assertEqual(2, self.order_args[5])

    def test_invalid_market_regime_values_fail_closed(self) -> None:
        os.environ["MARKET_REGIME_GATE"] = "YES"
        for name, value in (("REGIME_CUT", "0"),
                            ("MARKET_DROP_STOP", "0"),
                            ("MARKET_DROP_REDUCE", "-4")):
            with self.subTest(name=name, value=value):
                os.environ[name] = value
                self.responses.clear()
                self.reached.clear()
                self.buy(f"invalid-regime-{name}")
                self.assertEqual([], self.reached)
                self.assertIn("MARKET_REGIME_CONFIG_INVALID",
                              self.responses[-1][1]["error"])
                os.environ.pop(name, None)

    def test_gateway_enforces_minimum_price_for_direct_ipc(self) -> None:
        os.environ["SAFEPLUS_MIN_PRICE"] = "1000"
        self.gw._micro_snapshot = {"005930": {"cur": 500}}
        self.buy("gateway-min-price")
        self.assertEqual([], self.reached)
        self.assertIn("price_floor", self.responses[-1][1]["error"])

    def test_gateway_uses_master_price_before_caller_limit_price(self) -> None:
        os.environ["SAFEPLUS_MIN_PRICE"] = "1000"
        self.gw._micro_snapshot = {}
        self.master_price = 500
        self.gw._handle_sendorder_real_request("inflated-limit-price", {
            "idempotency_key": "inflated-limit-price",
            "ts": datetime.now().isoformat(), "ttl_sec": 8,
            "account": "0000000000", "code": "005930", "qty": 1,
            "order_type": 1, "price": 5000, "hoga_gb": "00",
            "screen_no": "9999", "rqname": "inflated-limit-price",
        })
        self.assertIsNone(self.order_args)
        self.assertIn("price_floor", self.responses[-1][1]["error"])

    def test_gateway_blocks_when_trusted_price_is_unavailable(self) -> None:
        os.environ["SAFEPLUS_MIN_PRICE"] = "1000"
        self.gw._micro_snapshot = {}
        self.master_price = 0
        self.buy("trusted-price-missing")
        self.assertIsNone(self.order_args)
        self.assertIn("PRICE_UNAVAILABLE", self.responses[-1][1]["error"])

    def test_invalid_universe_values_fail_closed(self) -> None:
        for name, value in (("SAFEPLUS_MIN_PRICE", "NaN"),
                            ("SAFEPLUS_MIN_MARKETCAP", "-1")):
            with self.subTest(name=name, value=value):
                os.environ[name] = value
                self.responses.clear()
                self.reached.clear()
                self.buy(f"invalid-universe-{name}")
                self.assertEqual([], self.reached)
                self.assertIn("BUY_UNIVERSE_CONFIG_INVALID",
                              self.responses[-1][1]["error"])
                os.environ[name] = "0"

    def test_gateway_enforces_marketcap_for_direct_ipc(self) -> None:
        os.environ["SAFEPLUS_MIN_MARKETCAP"] = "1000000"
        self.gw._micro_snapshot = {"005930": {"cur": 1000}}
        self.shares_path.write_text(
            "code,name,shares\n005930,SAMPLE,100\n", encoding="utf-8"
        )
        self.buy("gateway-min-marketcap")
        self.assertEqual([], self.reached)
        self.assertIn("mcap_floor", self.responses[-1][1]["error"])

    def test_gateway_blocks_when_shares_are_unavailable(self) -> None:
        os.environ["SAFEPLUS_MIN_MARKETCAP"] = "1000000"
        self.gw._micro_snapshot = {"005930": {"cur": 1000}}
        self.buy("shares-missing")
        self.assertEqual([], self.reached)
        self.assertIn("SHARES_UNAVAILABLE", self.responses[-1][1]["error"])

    def test_rate_limit_still_allows_sell(self) -> None:
        from broker_gateway_v1 import BrokerState

        self.gw.state = BrokerState.RATE_LIMIT
        self.gw._handle_sendorder_real_request("rate-limit-sell", {
            "idempotency_key": "rate-limit-sell", "ts": datetime.now().isoformat(),
            "ttl_sec": 8, "account": "0000000000", "code": "005930",
            "qty": 1, "order_type": 2, "price": 1000, "hoga_gb": "00",
            "screen_no": "9999", "rqname": "rate-limit-sell",
        })
        self.assertIn("ocx", self.reached)

    def test_rate_limit_poll_dispatches_order_to_handler(self) -> None:
        from broker_gateway_v1 import BrokerState

        ipc_dir = Path(self.temp.name) / "requests"
        ipc_dir.mkdir()
        request_path = ipc_dir / "rate-limit-order.json"
        request_path.write_text(json.dumps({
            "type": "SENDORDER_REAL", "request_id": "rate-limit-order",
        }), encoding="utf-8")
        real_ipc_req = self.bg.IPC_REQ
        self.bg.IPC_REQ = ipc_dir
        self.addCleanup(setattr, self.bg, "IPC_REQ", real_ipc_req)
        self.gw.state = BrokerState.RATE_LIMIT
        self.gw._poll_in_progress = False
        dispatched = []
        self.gw.process_request = lambda path: dispatched.append(path.name)

        self.gw.poll_requests()

        self.assertEqual(["rate-limit-order.json"], dispatched)

    def test_price_and_hoga_semantics_are_validated(self) -> None:
        for key, price, hoga in (
            ("limit-zero", 0, "00"),
            ("market-positive", 1000, "03"),
            ("best-positive", 1000, "06"),
        ):
            with self.subTest(key=key):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(key, {
                    "idempotency_key": key, "ts": datetime.now().isoformat(),
                    "ttl_sec": 8, "account": "0000000000", "code": "005930",
                    "qty": 1, "order_type": 2, "price": price,
                    "hoga_gb": hoga, "screen_no": "9999", "rqname": key,
                })
                self.assertEqual([], self.reached)
                self.assertIn("requires price", self.responses[-1][1]["error"])

    def test_buy_modify_does_not_consume_daily_new_buy_count(self) -> None:
        self.gw._handle_sendorder_real_request("modify-count", {
            "idempotency_key": "modify-count", "ts": datetime.now().isoformat(),
            "ttl_sec": 8, "account": "0000000000", "code": "005930",
            "qty": 1, "order_type": 5, "price": 1000, "hoga_gb": "00",
            "origin_order_no": "12345", "screen_no": "9999",
            "rqname": "modify-count",
        })
        self.assertIn("ocx", self.reached)
        self.assertEqual(0, self.gw._buy_count)

    def test_order_identifiers_are_validated(self) -> None:
        cases = (
            ("bad-code", "A05930", "9999", "valid"),
            ("bad-screen", "005930", "99", "valid"),
            ("bad-rqname", "005930", "9999", "x" * 41),
        )
        for key, code, screen, rqname in cases:
            with self.subTest(key=key):
                self.responses.clear()
                self.reached.clear()
                self.gw._handle_sendorder_real_request(key, {
                    "idempotency_key": key, "ts": datetime.now().isoformat(),
                    "ttl_sec": 8, "account": "0000000000", "code": code,
                    "qty": 1, "order_type": 2, "price": 1000,
                    "hoga_gb": "00", "screen_no": screen, "rqname": rqname,
                })
                self.assertEqual([], self.reached)
                self.assertIn("invalid", self.responses[-1][1]["error"])

    def test_account_is_masked_in_validation_error(self) -> None:
        self.gw._handle_sendorder_real_request("masked-account", {
            "idempotency_key": "masked-account", "account": "1234567890",
            "code": "", "qty": 1, "order_type": 2, "price": 1000,
            "hoga_gb": "00",
        })
        error = self.responses[-1][1]["error"]
        self.assertIn("1234**", error)
        self.assertNotIn("1234567890", error)


class BrokerClientBuyModifySafetyTests(unittest.TestCase):
    def test_buy_modify_obeys_manual_buy_block(self) -> None:
        from broker_client import BrokerClient

        client = BrokerClient.__new__(BrokerClient)
        with patch("os.path.exists", return_value=True):
            result = client.send_order_real(
                idempotency_key="modify-1", account="0000000000",
                code="005930", qty=1, order_type=5, price=1000,
                origin_order_no="12345",
            )
        self.assertEqual("ERROR", result["status"])
        self.assertIn("manual_buy_block", result["error"])

    def test_client_validation_masks_account(self) -> None:
        from broker_client import BrokerClient

        client = BrokerClient.__new__(BrokerClient)
        result = client.send_order_real(
            idempotency_key="masked-client", account="1234567890",
            code="", qty=1, order_type=2,
        )
        self.assertIn("1234**", result["error"])
        self.assertNotIn("1234567890", result["error"])


if __name__ == "__main__":
    unittest.main()
