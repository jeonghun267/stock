from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from hold_sell_audit_v1 import (
    AuditError,
    HoldSellAuditRecorder,
    PostExitObservationAuditRecorder,
    json_value,
    load_verified_rows,
    sha256_file,
)
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profile_runtime_snapshot,
    strategy_profiles_from_runtime_snapshot,
)
from verified_hold_sell_replay_v1 import ENGINE_PATH, main, replay_audit
from verified_replay_gate_v1 import APPROVAL_SCHEMA, validate_approval


KST = timezone(timedelta(hours=9))


class _ForgedDecisionRecorder(HoldSellAuditRecorder):
    """실전 판정과 사유가 다른 감사 스트림을 만든다.

    ★[REPLAY-STATUS 2026-08-04] 감사 파일은 해시 체인으로 잠겨 있어 사후 변조가
    불가능하다(test_tampered_audit_fails_closed). 그래서 '기록 시점부터 다른 판정'
    으로 재생 불일치를 만든다 = 운영 엔진이 바뀌어 과거 판정을 재현 못 하는 상황.
    """

    def record(self, *, state_before, observation, decision, state_after):
        forged = json_value(decision)
        forged["reason"] = f"{forged.get('reason') or ''}_FORGED"
        return super().record(
            state_before=state_before,
            observation=observation,
            decision=forged,
            state_after=state_after,
        )


class VerifiedReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.start = datetime(2026, 8, 5, 10, 0, tzinfo=KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _capture(self, recorder_cls=HoldSellAuditRecorder) -> Path:
        recorder = recorder_cls(
            self.root / "audit",
            ENGINE_PATH,
            strict=True,
        )
        engine = UnifiedHoldSellEngine(audit_recorder=recorder)
        state = HoldSellState(
            position_id="verified-test",
            strategy_id=StrategyId.S01_OPEN_SURGE,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )

        def observation(seconds: int, price: str) -> HoldSellObservation:
            return HoldSellObservation(
                observed_at=self.start + timedelta(seconds=seconds),
                price=Decimal(price),
                buy_money_per_sec_10s=Decimal("100"),
                sell_money_per_sec_10s=Decimal("200"),
                buy_money_per_sec_30s=Decimal("200"),
                sell_money_per_sec_30s=Decimal("100"),
                buy_volume_per_sec_5s=Decimal("100"),
                sell_volume_per_sec_5s=Decimal("200"),
                sell_volume_per_sec_previous_10s=Decimal("100"),
                che_str=Decimal("100"),
                che_str_change_5s=Decimal("-3"),
                common_peak_flow_ready=True,
            )

        engine.evaluate(state, observation(0, "104"))
        engine.evaluate(state, observation(1, "102.7"))
        sold = engine.evaluate(state, observation(3, "102.7"))
        self.assertTrue(sold.should_sell)
        files = list((self.root / "audit").rglob("*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_capture_replay_and_user_approval_gate(self) -> None:
        audit = self._capture()
        rows = load_verified_rows(audit)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["prev_hash"], "0" * 64)
        self.assertEqual(rows[1]["prev_hash"], rows[0]["row_hash"])

        report_path, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="verified-test-command",
        )
        self.assertEqual(report["provenance"], "[PROD_REPLAY]")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["sell"]["price"], "102.7")
        self.assertEqual(report["observations_replayed"], 3)
        self.assertTrue(report["audit_rows_verified"])
        self.assertEqual(report["capture_replay_mismatches"], [])
        self.assertEqual(report["action_mismatch_count"], 0)
        self.assertEqual(report["reason_mismatch_count"], 0)

        approval = self.root / "approval.json"
        approval.write_text(json.dumps({
            "schema": APPROVAL_SCHEMA,
            "approved_by_user": True,
            "report_path": str(report_path),
            "report_sha256": sha256_file(report_path),
            "engine_sha256": sha256_file(ENGINE_PATH),
        }), encoding="utf-8")
        validated = validate_approval(approval)
        self.assertEqual(validated["status"], "PASS")

    def test_s02_canary_runtime_profile_replays_without_environment(self) -> None:
        snapshot = strategy_profile_runtime_snapshot(
            StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
        )
        snapshot.update({
            "supported_weak_peak_confirm_sec": 6,
            "supported_weak_peak_active_date": "20260805",
            "supported_weak_peak_arm_return_pct": "5",
            "supported_weak_peak_drop_pct": "1.5",
            "supported_weak_peak_score": 3,
        })
        recorder = HoldSellAuditRecorder(
            self.root / "audit",
            ENGINE_PATH,
            strict=True,
            runtime_profile=snapshot,
        )
        engine = UnifiedHoldSellEngine(
            audit_recorder=recorder,
            profiles=strategy_profiles_from_runtime_snapshot(snapshot),
        )
        state = HoldSellState(
            position_id="s02-canary-runtime",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )

        def observation(seconds: int, price: str) -> HoldSellObservation:
            return HoldSellObservation(
                observed_at=self.start + timedelta(seconds=seconds),
                price=Decimal(price),
                buy_money_per_sec_10s=Decimal("100"),
                sell_money_per_sec_10s=Decimal("200"),
                buy_money_per_sec_30s=Decimal("200"),
                sell_money_per_sec_30s=Decimal("100"),
                buy_volume_per_sec_5s=Decimal("100"),
                sell_volume_per_sec_5s=Decimal("200"),
                sell_volume_per_sec_previous_10s=Decimal("100"),
                common_peak_flow_ready=True,
                ma10_support=True,
                ma20_rising=True,
            )

        engine.evaluate(state, observation(0, "106"))
        engine.evaluate(state, observation(1, "104.3"))
        engine.evaluate(state, observation(3, "104.3"))
        sold = engine.evaluate(state, observation(7, "104.3"))
        self.assertTrue(sold.should_sell)
        audit = next((self.root / "audit").rglob("*.jsonl"))

        _, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="s02-canary-runtime-test",
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["runtime_profile"], snapshot)
        self.assertEqual(report["capture_replay_mismatches"], [])

    def test_replay_continues_with_verified_post_exit_observation(self) -> None:
        recorder = HoldSellAuditRecorder(
            self.root / "audit", ENGINE_PATH, strict=True,
        )
        engine = UnifiedHoldSellEngine(audit_recorder=recorder)
        state = HoldSellState(
            position_id="post-exit-test",
            strategy_id=StrategyId.S01_OPEN_SURGE,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )
        first = HoldSellObservation(
            observed_at=self.start,
            price=Decimal("100"),
        )
        decision = engine.evaluate(state, first)
        self.assertFalse(decision.should_sell)
        audit = next((self.root / "audit").rglob("*.jsonl"))

        post_recorder = PostExitObservationAuditRecorder(
            self.root / "post_exit", ENGINE_PATH, strict=True,
        )
        post_path = post_recorder.record(
            position={
                "strategy_id": StrategyId.S01_OPEN_SURGE.value,
                "code": "119850",
                "position_id": "post-exit-test",
                "entry_at": self.start.isoformat(),
                "entry_price": "100",
            },
            observation=HoldSellObservation(
                observed_at=self.start + timedelta(seconds=2),
                price=Decimal("100.1"),
            ),
            exit_at=self.start + timedelta(seconds=1),
        )
        self.assertIsNotNone(post_path)

        _, report = replay_audit(
            audit,
            post_exit_audit_path=post_path,
            report_root=self.root / "reports",
            command="post-exit-continuation-test",
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["observations_total"], 2)
        self.assertEqual(report["observations_replayed"], 2)
        self.assertEqual(report["post_exit_observations_replayed"], 1)

    def test_tampered_audit_fails_closed(self) -> None:
        audit = self._capture()
        text = audit.read_text(encoding="utf-8")
        audit.write_text(text.replace('"price":"102.7"', '"price":"999"', 1),
                         encoding="utf-8")
        with self.assertRaises(AuditError):
            load_verified_rows(audit)

    def test_mid_position_capture_is_unverified(self) -> None:
        recorder = HoldSellAuditRecorder(
            self.root / "audit",
            ENGINE_PATH,
            strict=True,
        )
        engine = UnifiedHoldSellEngine(audit_recorder=recorder)
        state = HoldSellState(
            position_id="mid-position",
            strategy_id=StrategyId.S01_OPEN_SURGE,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
            last_observed_at=self.start,
        )
        engine.evaluate(state, HoldSellObservation(
            observed_at=self.start + timedelta(seconds=1),
            price=Decimal("100"),
        ))
        audit = next((self.root / "audit").rglob("*.jsonl"))
        with self.assertRaisesRegex(AuditError, "mid-position"):
            load_verified_rows(audit)

    def test_strategy03_replay_uses_its_production_adapter(self) -> None:
        from strategy_03_rotation_engine_v1 import Strategy03HoldSellEngine
        from verified_hold_sell_replay_v1 import STRATEGY03_ENGINE_PATH

        recorder = HoldSellAuditRecorder(
            self.root / "audit",
            [ENGINE_PATH, STRATEGY03_ENGINE_PATH],
            strict=True,
        )
        engine = Strategy03HoldSellEngine(audit_recorder=recorder)
        state = HoldSellState(
            position_id="strategy03-test",
            strategy_id=StrategyId.VALLEY_MORNING_CRASH,
            code="319400",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
            entry_lane="INTRADAY_CRASH",
        )
        engine.evaluate(state, HoldSellObservation(
            observed_at=self.start + timedelta(seconds=1),
            price=Decimal("100"),
        ))
        audit = next((self.root / "audit").rglob("*.jsonl"))

        _, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="strategy03-adapter-test",
        )

        self.assertEqual(len(report["replay_engine_paths"]), 2)
        self.assertEqual(report["capture_replay_mismatches"], [])

    # ── ★[REPLAY-STATUS 2026-08-04] status 하드코딩 회귀 ──────────────────

    def _approve(self, report_path: Path) -> Path:
        approval = self.root / "approval.json"
        approval.write_text(json.dumps({
            "schema": APPROVAL_SCHEMA,
            "approved_by_user": True,
            "report_path": str(report_path),
            "report_sha256": sha256_file(report_path),
            "engine_sha256": sha256_file(ENGINE_PATH),
        }), encoding="utf-8")
        return approval

    def _run_main(self, audit: Path) -> int:
        saved = sys.argv
        sys.argv = [
            "verified_hold_sell_replay_v1.py",
            "--audit", str(audit),
            "--report-root", str(self.root / "reports"),
        ]
        try:
            return main()
        finally:
            sys.argv = saved

    def test_replay_mismatch_is_not_pass(self) -> None:
        """재생이 실제 판정과 어긋나면 PASS 라고 쓰면 안 된다."""
        audit = self._capture(_ForgedDecisionRecorder)
        _, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="mismatch-test",
        )
        self.assertTrue(
            report["capture_replay_mismatches"], "불일치가 잡혀야 시험이 성립한다")
        self.assertEqual("FAIL", report["status"])
        self.assertEqual(0, report["action_mismatch_count"])
        self.assertGreater(report["reason_mismatch_count"], 0)
        self.assertTrue(all(
            item["kind"] == "REASON"
            for item in report["capture_replay_mismatches"]
        ))

    def test_gate_rejects_mismatched_report(self) -> None:
        """게이트가 실제로 거부해야 한다 - 리포트에만 적히고 끝나면 의미 없다."""
        audit = self._capture(_ForgedDecisionRecorder)
        report_path, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="mismatch-gate-test",
        )
        self.assertEqual("FAIL", report["status"])
        approval = self._approve(report_path)
        with self.assertRaisesRegex(AuditError, "passing production replay"):
            validate_approval(approval)

    def test_matching_report_still_passes_the_gate(self) -> None:
        """반대 방향 - 정상 재생까지 막아 버리면 고친 게 아니다."""
        audit = self._capture()
        report_path, report = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="match-gate-test",
        )
        self.assertEqual("PASS", report["status"])
        self.assertEqual([], report["capture_replay_mismatches"])
        self.assertEqual(
            "PASS", validate_approval(self._approve(report_path))["status"])

    def test_gate_rejects_hand_edited_pass_status(self) -> None:
        """옛 판(status 하드코딩)이 뽑았거나 손으로 고친 리포트도 막아야 한다."""
        audit = self._capture(_ForgedDecisionRecorder)
        report_path, _ = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="hand-edited-test",
        )
        forged = json.loads(report_path.read_text(encoding="utf-8"))
        forged["status"] = "PASS"          # 옛 판이 쓰던 값 그대로
        report_path.write_text(
            json.dumps(forged, ensure_ascii=False, indent=2), encoding="utf-8")

        approval = self._approve(report_path)   # 해시는 다시 맞춰서 승인
        with self.assertRaisesRegex(AuditError, "mismatch record"):
            validate_approval(approval)

    def test_gate_rejects_report_without_mismatch_record(self) -> None:
        """불일치 기록이 아예 없으면 '없었다'를 증명 못 한 것이므로 거부한다."""
        audit = self._capture()
        report_path, _ = replay_audit(
            audit,
            report_root=self.root / "reports",
            command="missing-record-test",
        )
        stripped = json.loads(report_path.read_text(encoding="utf-8"))
        del stripped["capture_replay_mismatches"]
        report_path.write_text(
            json.dumps(stripped, ensure_ascii=False, indent=2), encoding="utf-8")

        approval = self._approve(report_path)
        with self.assertRaisesRegex(AuditError, "mismatch record"):
            validate_approval(approval)

    def test_main_exit_code_follows_status(self) -> None:
        """예약작업·배치는 화면이 아니라 종료코드를 본다."""
        self.assertEqual(0, self._run_main(self._capture()))
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assertNotEqual(
            0, self._run_main(self._capture(_ForgedDecisionRecorder)))


if __name__ == "__main__":
    unittest.main()
