# -*- coding: utf-8 -*-
"""★[S06-DAILY-APPROVE 2026-08-04] S06 승인 날짜 갱신.

지켜야 할 두 가지가 정반대 방향이라 양쪽 다 시험한다.
  - 상시 결정이 있으면 매일 아침 오늘 날짜로 밀어줘야 한다(안 그러면 하루 종일 그림자).
  - 없는 승인을 만들어내면 안 된다(그건 갱신이 아니라 무단 승인).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from approval_settings_guard import KST, legacy_daily_approval_valid  # noqa: E402
from strategy_06_daily_approve_v1 import renew  # noqa: E402


class Strategy06DailyApproveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.approval = self.root / "strategy_06_live_approved.flag"
        self.off = self.root / "strategy_06_off.flag"
        self.holidays = self.root / "holidays_kr.txt"
        self.now = datetime(2026, 8, 5, 8, 55)

    def call(self, **overrides):
        values = {
            "now": self.now,
            "approval_path": self.approval,
            "off_path": self.off,
            "holidays_path": self.holidays,
        }
        values.update(overrides)
        return renew(**values)

    # ── 갱신해야 하는 경우 ────────────────────────────────────────────────

    def test_yesterday_approval_is_pushed_to_today(self):
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260804 S06_LIVE\n", encoding="ascii")

        renewed, reason = self.call()

        self.assertTrue(renewed)
        self.assertEqual("RENEWED", reason)
        self.assertEqual(
            "APPROVED_BY_OWNER 20260805 S06_LIVE\n",
            self.approval.read_text(encoding="ascii"),
        )

    def test_renewed_flag_passes_the_order_gate(self):
        """갱신 결과가 주문 관문이 실제로 인정하는 값이어야 한다."""
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260804 S06_LIVE\n", encoding="ascii")
        self.call()

        self.assertTrue(legacy_daily_approval_valid(
            self.approval.read_text(encoding="ascii"),
            self.now.replace(tzinfo=KST),
        ))

    def test_already_today_is_a_no_op(self):
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260805 S06_LIVE\n", encoding="ascii")

        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("ALREADY_TODAY", reason)

    # ── 절대 만들면 안 되는 경우 ─────────────────────────────────────────

    def test_missing_flag_is_never_created(self):
        """깃발 삭제 = 문서화된 '전면 그림자' 스위치. 되살리면 안 된다."""
        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("NO_STANDING_APPROVAL", reason)
        self.assertFalse(self.approval.exists(), "없는 승인을 만들어냈다")

    def test_off_flag_blocks_renewal(self):
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260804 S06_LIVE\n", encoding="ascii")
        self.off.write_text("OFF\n", encoding="ascii")

        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("OFF_FLAG", reason)
        self.assertIn("20260804", self.approval.read_text(encoding="ascii"))

    def test_holiday_blocks_renewal(self):
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260804 S06_LIVE\n", encoding="ascii")
        self.holidays.write_text(
            "# comment\n20260805  # test holiday\n", encoding="utf-8")

        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("HOLIDAY", reason)

    def test_malformed_or_foreign_flag_is_left_alone(self):
        cases = {
            "APPROVED\n": "MALFORMED_APPROVAL",
            "auto-approved 2026-08-04T08:59:42\n": "MALFORMED_APPROVAL",
            "APPROVED_BY_OWNER 20260804 09:57:00\n": "MALFORMED_APPROVAL",
            "": "MALFORMED_APPROVAL",
        }
        for text, expected in cases.items():
            with self.subTest(flag=text.strip() or "(empty)"):
                self.approval.write_text(text, encoding="ascii")
                renewed, reason = self.call()
                self.assertFalse(renewed)
                self.assertEqual(expected, reason)
                self.assertEqual(text, self.approval.read_text(encoding="ascii"))

    def test_bom_flag_is_not_touched(self):
        """PowerShell 로 쓰면 BOM 이 붙는다 - 관문도 못 읽는 값이니 갱신도 안 한다."""
        self.approval.write_bytes(
            b"\xef\xbb\xbf" + b"APPROVED_BY_OWNER 20260804 S06_LIVE\n")

        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("UNREADABLE_APPROVAL", reason)

    def test_future_dated_flag_is_not_touched(self):
        """시계가 뒤로 갔을 때 미래 승인을 과거로 끌어내리지 않는다."""
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260806 S06_LIVE\n", encoding="ascii")

        renewed, reason = self.call()

        self.assertFalse(renewed)
        self.assertEqual("FUTURE_APPROVAL", reason)

    def test_no_temp_file_is_left_behind(self):
        self.approval.write_text(
            "APPROVED_BY_OWNER 20260804 S06_LIVE\n", encoding="ascii")
        self.call()

        self.assertEqual(
            [], list(self.root.glob("*.tmp")), "임시 파일이 남았다")


if __name__ == "__main__":
    unittest.main()
