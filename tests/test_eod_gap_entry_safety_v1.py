import json
import hashlib
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import eod_gap_fill_check_v1 as fill_check
import eod_gap_live_executor_v1 as executor
import eod_gap_top200_shadow_v1 as top200_shadow


class FakeBroker:
    def send_order_real(self, **kwargs):
        return {"status": "TIMEOUT", "request_id": "test-timeout"}


class EodGapEntrySafetyTests(unittest.TestCase):
    def test_order_defaults_to_best_limit_and_accepts_guard_override(self):
        calls = []

        class CapturingBroker:
            def send_order_real(self, **kwargs):
                calls.append(kwargs)
                return {"status": "OK"}

        with patch.object(executor, "LIVE", True), \
                patch.object(executor, "ACCOUNT", "65020000"), \
                patch.dict(executor.os.environ, {"EODGAP_LEADER_BOARD": "NO"}), \
                patch.object(executor, "_log"):
            self.assertTrue(executor._order(CapturingBroker(), "000001", 1, "SELL", "TEST"))
            self.assertTrue(executor._order(
                CapturingBroker(), "000001", 1, "SELL", "TEST", hoga_gb="00", price=9900
            ))
            self.assertTrue(executor._order(CapturingBroker(), "000001", 1, "BUY", "TEST"))

        self.assertEqual(calls[0]["order_type"], 2)
        self.assertEqual(calls[0]["hoga_gb"], "06")
        self.assertEqual(calls[0]["price"], 0)
        self.assertEqual(calls[1]["hoga_gb"], "00")
        self.assertEqual(calls[1]["price"], 9900)
        self.assertEqual(calls[2]["order_type"], 1)
        self.assertEqual(calls[2]["hoga_gb"], "06")

    def test_sell_guard_plans_06_limit_00_then_guarded_market_03(self):
        now = datetime(2026, 9, 3, 9, 0, 5)
        snap = {"cur": 10000, "best_bid_px": 9900,
                "ob_ts": "2026-09-03T09:00:04"}
        with patch.object(executor, "_read_micro", return_value=snap):
            first = executor._sell_order_plan("000001", 0, now=now)
            second = executor._sell_order_plan("000001", 1, now=now)
            third = executor._sell_order_plan("000001", 2, now=now)
        self.assertEqual((first["hoga_gb"], first["price"]), ("06", 0))
        self.assertEqual((second["hoga_gb"], second["price"]), ("00", 9900))
        self.assertEqual((third["hoga_gb"], third["price"]), ("03", 0))

    def test_sell_guard_defers_wide_market_until_0930_force(self):
        snap = {"cur": 10000, "best_bid_px": 6900,
                "ob_ts": "2026-09-03T09:00:04"}
        with patch.object(executor, "_read_micro", return_value=snap):
            blocked = executor._sell_order_plan(
                "000001", 2, now=datetime(2026, 9, 3, 9, 0, 5)
            )
            forced = executor._sell_order_plan(
                "000001", 2, now=datetime(2026, 9, 3, 9, 30, 0)
            )
        self.assertEqual(blocked["action"], "DEFER")
        self.assertEqual(forced["stage"], "FORCE_MARKET_03")
        self.assertEqual(forced["hoga_gb"], "03")

    def test_sell_defer_expires_per_symbol_after_120_seconds(self):
        code = "000001"
        with patch.dict(executor._SELL_STARTED_AT, {
                code: datetime(2026, 9, 3, 9, 0, 0)}, clear=True):
            before, elapsed_before = executor._sell_defer_expired(
                code, now=datetime(2026, 9, 3, 9, 1, 59)
            )
            expired, elapsed_expired = executor._sell_defer_expired(
                code, now=datetime(2026, 9, 3, 9, 2, 0)
            )
        self.assertFalse(before)
        self.assertEqual(elapsed_before, 119.0)
        self.assertTrue(expired)
        self.assertEqual(elapsed_expired, 120.0)

    def test_sell_recovery_returns_open_on_defer_timeout(self):
        deferred = {"action": "DEFER", "stage": "SLIPPAGE_WAIT",
                    "reason": "QUOTE_MISSING", "hoga_gb": "", "price": 0,
                    "cur": 0.0, "bid": 0.0, "slip_pct": None}
        with patch.object(executor, "_sell_truth", return_value=(1, {})), \
                patch.object(executor, "_sell_order_plan", return_value=deferred), \
                patch.object(executor, "_sell_defer_expired", return_value=(True, 120.0)), \
                patch.object(executor, "_order") as order, \
                patch.object(executor, "_sell_audit_append"), \
                patch.object(executor.time, "sleep"), \
                patch.object(executor, "_log"):
            self.assertFalse(executor._sell_with_recovery(object(), "000001", 1))
        order.assert_not_called()

    def test_sell_recovery_integrates_06_limit_00_and_guarded_market_03(self):
        class Morning(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 3, 9, 0, 5)

        truths = iter([(1, {}), (1, {}), (1, {}), (0, {})])
        snap = {"cur": 10000, "best_bid_px": 9900,
                "ob_ts": "2026-09-03T09:00:04"}
        with patch.object(executor, "datetime", Morning), \
                patch.object(executor, "_read_micro", return_value=snap), \
                patch.object(executor, "_sell_truth", side_effect=lambda *_: next(truths)), \
                patch.object(executor, "_order", return_value=True) as order, \
                patch.object(executor, "LAST_ORDER_STATUS", ""), \
                patch.object(executor, "_sell_audit_append"), \
                patch.object(executor, "_audit_sell_fill"), \
                patch.object(executor.time, "sleep"), \
                patch.object(executor, "_log"):
            self.assertTrue(executor._sell_with_recovery(object(), "000001", 1))

        self.assertEqual([call.kwargs["hoga_gb"] for call in order.call_args_list],
                         ["06", "00", "03"])
        self.assertEqual([call.kwargs["price"] for call in order.call_args_list],
                         [0, 9900, 0])

    def test_entry_capture_writes_hash_chain_and_gate_observations(self):
        pick = (10.0, "000001", "SETUP", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        fake_modules = {
            "foreign_supply": types.SimpleNamespace(buy_gate=lambda *_args, **_kwargs: True),
            "smart_money": types.SimpleNamespace(dumping=lambda *_: (False, "")),
        }
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            eod = base / "eod.csv"
            board = base / "board.json"
            eod.write_text("date,code\n", encoding="utf-8")
            board.write_text("{}", encoding="utf-8")
            old_live = executor.LIVE
            try:
                executor.LIVE = False
                with patch.object(executor, "ENTRY_CAPTURE", True), \
                        patch.object(executor, "ENTRY_AUDIT_DIR", base / "audit"), \
                        patch.object(executor, "ENTRY_REPLAY_DIR", base / "reports"), \
                        patch.object(executor, "EOD", str(eod)), \
                        patch.object(executor, "LIVE_BOARD_CACHE", board), \
                        patch.dict(sys.modules, fake_modules), \
                        patch.object(executor, "_eod_micro_skip", return_value=False), \
                        patch.object(executor, "_order", return_value=True), \
                        patch.object(executor, "_log"):
                    audit = executor._start_entry_audit(
                        "20260828", [("000001", "SETUP", 100.0)], [pick], {}
                    )
                    executor._entry_audit_append({
                        "record_type": "selection_context", "unified_scores": {},
                        "is_friday": True,
                    })
                    executor._entry_audit_append({
                        "record_type": "setup_order",
                        "ordered_setup": [{"route": "A", "candidate": pick}],
                    })
                    executor._entry_audit_append({
                        "record_type": "order_universe", "code": "000001",
                        "passed": True, "reason": "PASS",
                    })
                    executor._entry_audit_append({
                        "record_type": "attempt_order", "ordered_candidates": [pick],
                        "setup_route_codes": ["000001"], "open_now": 0,
                        "global_remaining": 3, "max_positions": 3,
                    })
                    self.assertTrue(executor._buy_one(
                        object(), pick, "20260828", {}, setup_route=True
                    ))
                    replay_ok, replay_reason, replay_report = executor._replay_entry_audit(audit)
                    self.assertTrue(replay_ok, replay_reason)
                    self.assertTrue(replay_report.exists())
                rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rows[-1]["record_type"], "candidate_decision")
                self.assertEqual(rows[-1]["decision"], "ORDER_ELIGIBLE")
                previous = ""
                for row in rows:
                    digest = row.pop("record_sha256")
                    self.assertEqual(row["prev_sha256"], previous)
                    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode("utf-8")
                    self.assertEqual(digest, hashlib.sha256(canonical).hexdigest())
                    previous = digest
            finally:
                executor.LIVE = old_live
                executor._ENTRY_AUDIT_PATH = None
                executor._ENTRY_AUDIT_HASH = ""
                executor._ENTRY_AUDIT_SEQ = 0

    def test_entry_replay_passes_when_all_decisions_match_and_eligible_is_zero(self):
        pick = (10.0, "000002", "BLOCKED", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            eod = base / "eod.csv"
            board = base / "board.json"
            eod.write_text("date,code\n", encoding="utf-8")
            board.write_text("{}", encoding="utf-8")
            try:
                with patch.object(executor, "ENTRY_CAPTURE", True), \
                        patch.object(executor, "ENTRY_AUDIT_DIR", base / "audit"), \
                        patch.object(executor, "ENTRY_REPLAY_DIR", base / "reports"), \
                        patch.object(executor, "EOD", str(eod)), \
                        patch.object(executor, "LIVE_BOARD_CACHE", board), \
                        patch.object(executor, "_log"):
                    audit = executor._start_entry_audit(
                        "20260828", [("000002", "BLOCKED", 100.0)], [pick], {}
                    )
                    executor._entry_audit_append({
                        "record_type": "selection_context", "unified_scores": {},
                        "is_friday": True,
                    })
                    executor._entry_audit_append({
                        "record_type": "setup_order", "ordered_setup": [],
                    })
                    executor._entry_audit_append({
                        "record_type": "order_universe", "code": "000002",
                        "passed": True, "reason": "PASS",
                    })
                    executor._entry_audit_append({
                        "record_type": "attempt_order", "ordered_candidates": [pick],
                        "setup_route_codes": [], "open_now": 0,
                        "global_remaining": 3, "max_positions": 3,
                    })
                    self.assertFalse(executor._buy_one(
                        object(), pick, "20260828", {}, setup_route=False
                    ))
                    ok, reason, report_path = executor._replay_entry_audit(audit)
                    self.assertTrue(ok, reason)
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["eligible_candidates"], 0)
                    self.assertEqual(report["decisions"], [
                        {"code": "000002", "decision": "BLOCK"}
                    ])
            finally:
                executor._ENTRY_AUDIT_PATH = None
                executor._ENTRY_AUDIT_HASH = ""
                executor._ENTRY_AUDIT_SEQ = 0

    def test_saved_raw_score_inputs_drive_identity_regression(self):
        raw_input = {
            "rank0": 0, "universe_size": 10, "turnover": 300.0,
            "value20": 100.0,
            "opt_after": {"n": 2, "aft_ratio": 0.4, "late_ratio": 0.15,
                          "sustained": True},
            "intraday": {
                "aft_val_eok": 0.0, "pm_ratio": 0.0, "close_pos": 1.0,
                "vwap_over": True, "late_drop": 0.0, "upper_wick": 0.0,
                "big13": True, "big1430": True, "big_spike": True,
                "follow": True,
            },
            "theme_rank": 1, "current_close": 110.0,
            "close_prev": 100.0, "close5": 90.0,
        }
        pick = (96.0, "000001", "SAVED", 100.0, 110.0, 40.0, 25.0, 20.0,
                False, 0, 0, 0.1, 3.0, 1)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            eod = base / "eod.csv"
            board = base / "board.json"
            eod.write_text("date,code\n", encoding="utf-8")
            board.write_text("{}", encoding="utf-8")
            try:
                with patch.object(executor, "ENTRY_CAPTURE", True), \
                        patch.object(executor, "ENTRY_AUDIT_DIR", base / "audit"), \
                        patch.object(executor, "EOD", str(eod)), \
                        patch.object(executor, "LIVE_BOARD_CACHE", board), \
                        patch.object(executor, "_log"):
                    audit = executor._start_entry_audit(
                        "20260828", [("000001", "SAVED", 300.0)], [pick], {},
                        {"000001": raw_input},
                    )
                result = top200_shadow.build_shadow("20260828", audit)
                identity = result["score_identity"]
                self.assertEqual(identity["total"], 1)
                self.assertEqual(identity["matched"], 1)
                self.assertEqual(identity["mismatched"], 0)
                self.assertEqual(identity["rows"][0]["recalculated"], 96.0)
                self.assertEqual(result["score_input_source"],
                                 "saved_audit_raw_score_inputs")
            finally:
                executor._ENTRY_AUDIT_PATH = None
                executor._ENTRY_AUDIT_HASH = ""
                executor._ENTRY_AUDIT_SEQ = 0

    def test_sell_recovery_closes_only_after_broker_balance_is_zero(self):
        truths = iter([(1, {}), (0, {})])
        with patch.object(executor, "_sell_truth", side_effect=lambda *_: next(truths)), \
                patch.object(executor, "_order", return_value=True) as order, \
                patch.object(executor, "_sell_audit_append"), \
                patch.object(executor, "_audit_sell_fill"), \
                patch.object(executor.time, "sleep"), \
                patch.object(executor, "_log"):
            self.assertTrue(executor._sell_with_recovery(object(), "000001", 1))
        order.assert_called_once()

    def test_sell_recovery_fails_closed_when_broker_truth_is_unavailable(self):
        with patch.object(executor, "_sell_truth", return_value=None), \
                patch.object(executor, "_order") as order, \
                patch.object(executor, "_sell_audit_append"), \
                patch.object(executor.time, "sleep"), \
                patch.object(executor, "_log"):
            self.assertFalse(executor._sell_with_recovery(object(), "000001", 1))
        order.assert_not_called()

    def test_pick_window_closes_at_1529(self):
        self.assertTrue(executor._pick_window_open(datetime(2026, 8, 11, 15, 28, 59)))
        self.assertFalse(executor._pick_window_open(datetime(2026, 8, 11, 15, 29, 0)))

    def test_final_score_gate_blocks_low_score_before_any_order_work(self):
        pick = (69.9, "000001", "LOW", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        old_min = executor.MIN_SCORE
        try:
            executor.MIN_SCORE = 70.0
            self.assertFalse(executor._buy_one(object(), pick, "20260811", {}))
        finally:
            executor.MIN_SCORE = old_min

    def test_strategy_ab_uses_its_own_gate_and_walks_into_order(self):
        pick = (10.0, "000001", "SETUP", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        fake_modules = {
            "trend_filter": types.SimpleNamespace(is_jeongbae=lambda *_: True),
            "foreign_supply": types.SimpleNamespace(buy_gate=lambda *_args, **_kwargs: True),
            "smart_money": types.SimpleNamespace(dumping=lambda *_: (False, "")),
        }
        old_live = executor.LIVE
        try:
            executor.LIVE = False
            with patch.dict(sys.modules, fake_modules), \
                    patch.object(executor, "_eod_micro_skip", return_value=False), \
                    patch.object(executor, "_order", return_value=True) as order, \
                    patch.object(executor, "_log"):
                self.assertTrue(executor._buy_one(
                    object(), pick, "20260827", {}, setup_route=True
                ))
            order.assert_called_once()
        finally:
            executor.LIVE = old_live

    def test_simulated_buy_never_mutates_position_state(self):
        pick = (80.0, "000001", "SIM", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        held = {}
        fake_modules = {
            "trend_filter": types.SimpleNamespace(is_jeongbae=lambda *_: True),
            "foreign_supply": types.SimpleNamespace(buy_gate=lambda *_args, **_kwargs: True),
            "smart_money": types.SimpleNamespace(dumping=lambda *_: (False, "")),
        }
        old_live = executor.LIVE
        try:
            executor.LIVE = False
            with patch.dict(sys.modules, fake_modules), \
                    patch.object(executor, "_eod_micro_skip", return_value=False), \
                    patch.object(executor, "_order", return_value=True), \
                    patch.object(executor, "_log"):
                self.assertTrue(executor._buy_one(object(), pick, "20260828", held))
            self.assertEqual(held, {})
        finally:
            executor.LIVE = old_live

    def test_pending_batch_continues_only_for_accepted_order(self):
        self.assertFalse(executor._stop_after_pending({"order_status": "OK"}))
        self.assertTrue(executor._stop_after_pending({"order_status": "TIMEOUT"}))

    def test_order_universe_matches_price_and_marketcap_safety(self):
        pick = (80.0, "000001", "SAFE", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        old_price = executor.ORDER_MIN_PRICE
        old_cap = executor.ORDER_MIN_MARKETCAP
        try:
            executor.ORDER_MIN_PRICE = 10000.0
            executor.ORDER_MIN_MARKETCAP = 100_000_000_000.0
            with patch("broker_client._load_shares_cache",
                       return_value={"000001": 10_000_000}), \
                    patch.object(executor, "_log"):
                self.assertTrue(executor._passes_order_universe(pick))
            with patch("broker_client._load_shares_cache", return_value={}), \
                    patch.object(executor, "_log"):
                self.assertFalse(executor._passes_order_universe(pick))
        finally:
            executor.ORDER_MIN_PRICE = old_price
            executor.ORDER_MIN_MARKETCAP = old_cap

    def test_live_board_cache_accepts_owner_approved_ten_minutes(self):
        now = datetime(2026, 8, 27, 15, 26, 0)
        fresh = {
            "date": "20260827",
            "captured_at": (now - timedelta(seconds=599)).isoformat(),
            "rows": [["000001", "TEST", 123.0]],
        }
        stale = dict(fresh, captured_at=(now - timedelta(seconds=601)).isoformat())
        with patch.object(executor, "_jload", return_value=fresh):
            self.assertEqual(
                executor._load_fresh_live_board_cache(now, max_age_sec=600),
                [("000001", "TEST", 123.0)],
            )
        with patch.object(executor, "_jload", return_value=stale):
            self.assertEqual(
                executor._load_fresh_live_board_cache(now, max_age_sec=600), []
            )

    def test_timeout_is_not_order_success(self):
        old_live = executor.LIVE
        old_account = executor.ACCOUNT
        try:
            executor.LIVE = True
            executor.ACCOUNT = "12345678"
            with patch.dict("os.environ", {"EODGAP_LEADER_BOARD": "NO"}), \
                    patch.object(executor, "_log"):
                self.assertFalse(executor._order(FakeBroker(), "000001", 1, "BUY", "TEST"))
            self.assertEqual(executor.LAST_ORDER_STATUS, "TIMEOUT")
        finally:
            executor.LIVE = old_live
            executor.ACCOUNT = old_account

    def test_empty_live_board_never_calls_stale_fallback(self):
        with patch.object(executor, "_pick_window_open", return_value=True), \
                patch.object(executor, "_jload", return_value={}), \
                patch.object(executor, "_broker", return_value=object()), \
                patch.object(executor, "_opt10032_top", return_value=[]), \
                patch.object(executor, "_board_fallback_top") as fallback, \
                patch.object(executor, "_log"):
            executor.mode_pick()
        fallback.assert_not_called()

    def test_live_board_cache_accepts_only_same_day_two_minutes(self):
        now = datetime(2026, 8, 12, 15, 18, 0)
        fresh = {
            "date": "20260812",
            "captured_at": (now - timedelta(seconds=119)).isoformat(),
            "rows": [["000001", "TEST", 123.0]],
        }
        stale = dict(fresh, captured_at=(now - timedelta(seconds=121)).isoformat())
        wrong_day = dict(fresh, date="20260811")
        with patch.object(executor, "_jload", return_value=fresh):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [("000001", "TEST", 123.0)])
        with patch.object(executor, "_jload", return_value=stale):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [])
        with patch.object(executor, "_jload", return_value=wrong_day):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [])

    def test_live_board_cache_fallback_defaults_to_disabled(self):
        self.assertFalse(executor.LIVE_BOARD_CACHE_FALLBACK)

    def test_balance_confirmation_promotes_pending_to_open(self):
        # ★[2026-08-13] repo 안 임시폴더는 관리자·읽기전용 실행에서 PermissionError
        #   가 난다(8/12 P2-b 와 동일) — tempfile 로 전환, repo 오염 0.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pos_path = base / "DATA" / "eod_gap_positions.json"
            pos_path.parent.mkdir(parents=True)
            pos_path.write_text(json.dumps({
                "000001": {
                    "code": "000001", "name": "TEST", "qty": 1,
                    "buy_price": 10000, "status": "PENDING", "live": True,
                }
            }), encoding="utf-8")
            with patch.object(fill_check, "_fetch_balance", return_value={"000001": 1}), \
                    patch.object(fill_check, "_log"):
                fill_check.run_check(base, apply=True)
            saved = json.loads(pos_path.read_text(encoding="utf-8"))
            rt = json.loads((base / "DATA" / "rt_open_positions.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["000001"]["status"], "OPEN")
            self.assertEqual(rt["000001"]["strategy"], "EOD_GAP")


if __name__ == "__main__":
    unittest.main()
