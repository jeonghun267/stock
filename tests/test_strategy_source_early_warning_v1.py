"""자료원 조기 경보 검사기 테스트.

정상 / WARN(장 시작 전) / LIVE FAIL / 잘못된 자료형 / 늦은 기동 / 보고서 누적.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_source_early_warning_v1 as ew  # noqa: E402


PREOPEN = datetime(2026, 8, 18, 8, 55, 0)
LIVE = datetime(2026, 8, 18, 9, 0, 20)
TODAY = "20260818"


def _board(**over):
    payload = {
        "for_date": TODAY,
        "source_date": "20260814",
        "expected_source_date": "20260814",
        "source_stale": False,
        "candidate_count": 42,
    }
    payload.update(over)
    return payload


def _context(now: datetime = PREOPEN, **over):
    stamp = now.isoformat(timespec="microseconds")
    payload = {
        "for_date": TODAY,
        "ts": stamp,
        "order_capability": 0,
        "source_status": {
            "captain_money_rank": {"fresh": True, "accepted_count": 30,
                                   "source_ts": stamp},
            "moneyflow_selector": {"fresh": True, "accepted_count": 13,
                                   "source_ts": stamp},
            "moneyflow_watch": {"fresh": True, "accepted_count": 158,
                                "source_ts": stamp},
            "high_range_top30": {"fresh": True, "accepted_count": 41,
                                 "source_ts": stamp},
        },
    }
    payload.update(over)
    return payload


def _by_level(results, level):
    return [(name, detail) for lv, name, detail in results if lv == level]


class BoardCheckTests(unittest.TestCase):
    def test_healthy_board_passes(self) -> None:
        self.assertEqual(_by_level(ew.check_board(PREOPEN, _board()), ew.FAIL), [])

    def test_zero_candidates_fails(self) -> None:
        """8/14 재현 — 후보 0건이면 08:59 사전점검이 SOURCE_EMPTY 로 죽는다."""
        fails = _by_level(ew.check_board(PREOPEN, _board(candidate_count=0)), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["고저폭판 후보수"])
        self.assertIn("SOURCE_EMPTY:high_range_top30", fails[0][1])

    def test_date_mismatch_fails(self) -> None:
        fails = _by_level(ew.check_board(PREOPEN, _board(for_date="20260814")), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["고저폭판 날짜"])

    def test_stale_source_fails(self) -> None:
        fails = _by_level(ew.check_board(PREOPEN, _board(source_stale=True)), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["고저폭판 원본"])

    def test_unreadable_file_reports_fail_not_exception(self) -> None:
        fails = _by_level(ew.check_board(PREOPEN, {}, "JSON 형식이 깨짐"), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["고저폭판 파일"])


class BadTypeTests(unittest.TestCase):
    """숫자가 아닌 값이 와도 예외로 죽지 않고 FAIL 로 적어야 한다."""

    def test_non_numeric_candidate_count(self) -> None:
        for bad in ("많음", None, True, [], {}, "12.5"):
            with self.subTest(bad=bad):
                fails = _by_level(
                    ew.check_board(PREOPEN, _board(candidate_count=bad)), ew.FAIL)
                self.assertEqual([n for n, _ in fails], ["고저폭판 후보수"])
                self.assertIn("숫자가 아님", fails[0][1])

    def test_non_numeric_order_capability(self) -> None:
        fails = _by_level(
            ew.check_context(PREOPEN, _context(order_capability="영"),
                             realtime_level=ew.WARN), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["주문권한 0"])
        self.assertIn("숫자가 아님", fails[0][1])

    def test_non_numeric_accepted_count(self) -> None:
        payload = _context()
        payload["source_status"]["high_range_top30"]["accepted_count"] = "없음"
        fails = _by_level(
            ew.check_context(PREOPEN, payload, realtime_level=ew.WARN), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["자료원 high_range_top30"])
        self.assertIn("숫자가 아님", fails[0][1])

    def test_source_status_not_a_dict(self) -> None:
        fails = _by_level(
            ew.check_context(PREOPEN, _context(source_status=[]),
                             realtime_level=ew.WARN), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["자료원 목록"])

    def test_non_boolean_source_stale(self) -> None:
        fails = _by_level(ew.check_board(PREOPEN, _board(source_stale="no")), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["고저폭판 원본"])

    def test_broken_timestamp_is_treated_as_stale(self) -> None:
        fails = _by_level(
            ew.check_context(PREOPEN, _context(ts="어제"), realtime_level=ew.FAIL),
            ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["통합자료 신선도"])
        self.assertIn("읽기실패", fails[0][1])


class PreopenWarnTests(unittest.TestCase):
    """장 시작 전 실시간 3종이 비는 것은 정상일 수 있다 → WARN, 팝업 없음."""

    def test_empty_realtime_sources_are_warn_only(self) -> None:
        payload = _context()
        for source in ew.REALTIME_SOURCES:
            payload["source_status"][source]["accepted_count"] = 0
        results = ew.check_context(PREOPEN, payload, realtime_level=ew.WARN)
        self.assertEqual(_by_level(results, ew.FAIL), [])
        self.assertEqual(
            sorted(n for n, _ in _by_level(results, ew.WARN)),
            sorted(f"자료원 {s}" for s in ew.REALTIME_SOURCES))

    def test_stale_context_ts_is_warn_before_open(self) -> None:
        old = datetime(2026, 8, 18, 8, 50, 0).isoformat(timespec="microseconds")
        results = ew.check_context(PREOPEN, _context(ts=old), realtime_level=ew.WARN)
        self.assertEqual(_by_level(results, ew.FAIL), [])
        self.assertEqual([n for n, _ in _by_level(results, ew.WARN)],
                         ["통합자료 신선도"])

    def test_high_range_source_still_fails_before_open(self) -> None:
        """고저폭판은 08:40 산출물이라 장 시작 전에도 차 있어야 한다."""
        payload = _context()
        payload["source_status"]["high_range_top30"]["accepted_count"] = 0
        fails = _by_level(
            ew.check_context(PREOPEN, payload, realtime_level=ew.WARN), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["자료원 high_range_top30"])

    def test_date_and_capability_fail_even_before_open(self) -> None:
        fails = _by_level(
            ew.check_context(PREOPEN, _context(for_date="20260814"),
                             realtime_level=ew.WARN), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["통합자료 날짜"])


class LiveFailTests(unittest.TestCase):
    """장이 열린 뒤 같은 상태는 곧 사전점검 실패 → FAIL."""

    def test_empty_realtime_sources_fail_after_open(self) -> None:
        payload = _context(LIVE)
        payload["source_status"]["captain_money_rank"]["accepted_count"] = 0
        fails = _by_level(
            ew.check_context(LIVE, payload, realtime_level=ew.FAIL), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["자료원 captain_money_rank"])
        self.assertIn("SOURCE_EMPTY", fails[0][1])

    def test_stale_source_ts_fails_after_open(self) -> None:
        payload = _context(LIVE)
        payload["source_status"]["moneyflow_watch"]["source_ts"] = (
            datetime(2026, 8, 18, 8, 59, 0).isoformat(timespec="microseconds"))
        fails = _by_level(
            ew.check_context(LIVE, payload, realtime_level=ew.FAIL), ew.FAIL)
        self.assertEqual([n for n, _ in fails], ["자료원 moneyflow_watch"])
        self.assertIn("SOURCE_TIMESTAMP_STALE", fails[0][1])

    def test_live_retries_until_deadline_then_gives_up(self) -> None:
        payload = _context(LIVE)
        payload["source_status"]["captain_money_rank"]["accepted_count"] = 0
        after = datetime(2026, 8, 18, 9, 1, 30)
        results, attempts = ew.run_checks_until_deadline(
            LIVE, "live", reader=lambda: (payload, ""), clock=lambda: after,
            sleeper=lambda _s: None)
        self.assertEqual([n for n, _ in _by_level(results, ew.FAIL)],
                         ["자료원 captain_money_rank"])
        self.assertEqual(attempts, 1)

    def test_live_stops_as_soon_as_source_fills(self) -> None:
        empty = _context(LIVE)
        empty["source_status"]["captain_money_rank"]["accepted_count"] = 0
        payloads = [empty, empty, _context(LIVE)]
        seen = []

        def reader():
            seen.append(1)
            return payloads[min(len(seen) - 1, len(payloads) - 1)], ""

        results, attempts = ew.run_checks_until_deadline(
            LIVE, "live", reader=reader, clock=lambda: LIVE,
            sleeper=lambda _s: None)
        self.assertEqual(_by_level(results, ew.FAIL), [])
        self.assertEqual(attempts, 3)

    def test_warn_alone_does_not_trigger_retry(self) -> None:
        """WARN 은 재시도 사유가 아니다 — 장 전 자료는 원래 늦게 찬다."""
        payload = _context(PREOPEN)
        payload["source_status"]["captain_money_rank"]["accepted_count"] = 0
        calls = []

        def reader():
            calls.append(1)
            return payload, ""

        _results, attempts = ew.run_checks_until_deadline(
            PREOPEN, "preopen", reader=reader, clock=lambda: PREOPEN,
            sleeper=lambda _s: None)
        self.assertEqual(attempts, 1)


class LateStartTests(unittest.TestCase):
    """늦게 기동하면 엉뚱한 검사를 돌리지 않는다."""

    def test_board_window(self) -> None:
        self.assertTrue(ew.phase_window_ok(datetime(2026, 8, 18, 8, 45), "board")[0])
        ok, why = ew.phase_window_ok(datetime(2026, 8, 18, 9, 10), "board")
        self.assertFalse(ok)
        self.assertIn("늦은 기동", why)

    def test_preopen_window(self) -> None:
        self.assertTrue(
            ew.phase_window_ok(datetime(2026, 8, 18, 8, 55), "preopen")[0])
        self.assertFalse(
            ew.phase_window_ok(datetime(2026, 8, 18, 9, 5), "preopen")[0])

    def test_live_window_closes_at_s01_entry_end(self) -> None:
        self.assertTrue(
            ew.phase_window_ok(datetime(2026, 8, 18, 9, 0, 20), "live")[0])
        self.assertTrue(
            ew.phase_window_ok(datetime(2026, 8, 18, 9, 20), "live")[0])
        self.assertFalse(
            ew.phase_window_ok(datetime(2026, 8, 18, 9, 21), "live")[0])

    def test_unknown_phase_is_rejected(self) -> None:
        ok, why = ew.phase_window_ok(datetime(2026, 8, 18, 8, 45), "무엇")
        self.assertFalse(ok)
        self.assertIn("알 수 없는 단계", why)

    def test_eod_window(self) -> None:
        self.assertTrue(ew.phase_window_ok(datetime(2026, 8, 18, 17, 10), "eod")[0])
        self.assertFalse(ew.phase_window_ok(datetime(2026, 8, 18, 21, 0), "eod")[0])


class EodHealthTests(unittest.TestCase):
    @staticmethod
    def _journal(now: datetime, ok: int, timeout: int, delayed: int) -> list[str]:
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        rows = [f"[{stamp}][INFO][BROKER_v1] RES ok-{i} status=OK" for i in range(ok)]
        rows += [f"[{stamp}][INFO][BROKER_v1] RES to-{i} status=TIMEOUT"
                 for i in range(timeout)]
        rows += [
            f"[{stamp}][WARNING][BROKER_v1] OnReceiveTrData 현재 요청 불일치 - "
            "지연 응답 무시 got=(B1,opt10001,2211) expected=(B2,opt10081,7001)"
            for _ in range(delayed)
        ]
        return rows

    def test_fresh_progress_and_low_timeout_pass(self) -> None:
        now = datetime(2026, 8, 18, 17, 10)
        heartbeat = {"ts": "2026-08-18T17:09:30", "idx": 80, "total": 158}
        results = ew.check_eod_health(
            now, {}, heartbeat, self._journal(now, 18, 2, 3))
        self.assertEqual(_by_level(results, ew.FAIL), [])

    def test_stall_timeout_and_repeated_screen_all_fail(self) -> None:
        now = datetime(2026, 8, 18, 17, 10)
        heartbeat = {"ts": "2026-08-18T17:05:00", "idx": 40, "total": 158}
        results = ew.check_eod_health(
            now, {}, heartbeat, self._journal(now, 10, 20, 30))
        self.assertEqual(
            [name for name, _ in _by_level(results, ew.FAIL)],
            ["일봉 진행 정지", "브로커 TIMEOUT 비율", "TR 화면 지연응답 반복"],
        )

    def test_done_today_does_not_false_fail_old_heartbeat(self) -> None:
        now = datetime(2026, 8, 18, 20, 0)
        done = {"done_at": "2026-08-18T19:56:26", "status": "OK",
                "qa_score": 100, "codes": 1636}
        heartbeat = {"ts": "2026-08-18T19:55:52", "idx": 158, "total": 158}
        results = ew.check_eod_health(
            now, done, heartbeat, self._journal(now, 20, 0, 0))
        self.assertEqual(_by_level(results, ew.FAIL), [])


class TradingDayTests(unittest.TestCase):
    def test_saturday_is_skipped(self) -> None:
        trading, notes = ew.trading_day_results(datetime(2026, 8, 22, 8, 45))
        self.assertFalse(trading)
        self.assertIn("NOT_A_WEEKDAY", notes[0][2])

    def test_listed_holiday_is_skipped(self) -> None:
        """config\\krx_holidays.txt 에 실제로 든 20260817(대체공휴일)."""
        trading, notes = ew.trading_day_results(datetime(2026, 8, 17, 8, 45))
        self.assertFalse(trading)
        self.assertIn("KRX_HOLIDAY", notes[0][2])

    def test_normal_weekday_is_trading_day(self) -> None:
        trading, notes = ew.trading_day_results(datetime(2026, 8, 18, 8, 45))
        self.assertTrue(trading)
        self.assertEqual(notes, [])

    def test_unreadable_holiday_file_fails_but_keeps_going(self) -> None:
        original = ew.HOLIDAYS
        try:
            ew.HOLIDAYS = Path(r"C:\stock_bot\config\없는파일_krx.txt")
            trading, notes = ew.trading_day_results(datetime(2026, 8, 18, 8, 45))
            self.assertTrue(trading)
            self.assertEqual([lv for lv, _, _ in notes], [ew.FAIL])
            self.assertIn("휴장일 파일", notes[0][1])
        finally:
            ew.HOLIDAYS = original


class ReportAccumulationTests(unittest.TestCase):
    """두 번 실행하면 같은 날 보고서에 runs 가 쌓여야 한다."""

    def test_two_runs_accumulate(self) -> None:
        argv = sys.argv
        report_dir, log_path = ew.REPORT_DIR, ew.LOG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            try:
                sys.argv = ["x", "--no-popup"]
                ew.REPORT_DIR = Path(tmp) / "보고서"
                ew.LOG_PATH = Path(tmp) / "LOG" / "sched.log"

                board_ok = ew.check_board(PREOPEN, _board())
                self.assertEqual(ew._emit(PREOPEN, "board", board_ok), 0)

                bad = ew.check_board(LIVE, _board(candidate_count=0))
                self.assertEqual(ew._emit(LIVE, "live", bad), 1)

                report = ew.REPORT_DIR / f"자료원_조기경보_{PREOPEN:%Y%m%d}.json"
                saved = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(len(saved["runs"]), 2)
                self.assertEqual([r["phase"] for r in saved["runs"]],
                                 ["board", "live"])
                self.assertEqual([r["verdict"] for r in saved["runs"]],
                                 [ew.PASS, ew.FAIL])
                self.assertEqual(saved["verified"], ew.UNVERIFIED)

                written = ew.LOG_PATH.read_text(encoding="utf-8")
                self.assertEqual(written.count("자료원 조기 경보"), 2)
            finally:
                sys.argv = argv
                ew.REPORT_DIR, ew.LOG_PATH = report_dir, log_path

    def test_warn_run_exits_zero_and_is_recorded(self) -> None:
        argv = sys.argv
        report_dir, log_path = ew.REPORT_DIR, ew.LOG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            try:
                sys.argv = ["x", "--no-popup"]
                ew.REPORT_DIR = Path(tmp) / "보고서"
                ew.LOG_PATH = Path(tmp) / "LOG" / "sched.log"

                payload = _context()
                payload["source_status"]["captain_money_rank"]["accepted_count"] = 0
                results = ew.check_context(PREOPEN, payload,
                                           realtime_level=ew.WARN)
                self.assertEqual(ew._emit(PREOPEN, "preopen", results), 0)

                report = ew.REPORT_DIR / f"자료원_조기경보_{PREOPEN:%Y%m%d}.json"
                saved = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(saved["runs"][0]["verdict"], ew.WARN)
                self.assertEqual(saved["runs"][0]["warn_count"], 1)
                self.assertEqual(saved["runs"][0]["fail_count"], 0)
            finally:
                sys.argv = argv
                ew.REPORT_DIR, ew.LOG_PATH = report_dir, log_path


if __name__ == "__main__":
    unittest.main()
