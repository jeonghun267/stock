from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_03_rotation_engine_v1 as s03_engine
from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_ALGORITHM,
    EARLY_LOW_LANE,
    EarlyLowAuditChain,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)
from 골짜기_급반등 import EarlyLowDetector, MicroPoint, _early_high_range_codes

REPLAY = RUN / "s03_early_low_prod_replay_v1.py"


class Strategy03EarlyLowTests(unittest.TestCase):
    def point(self, second: int, price: float, day_low: float,
              buy: float = 0.0, sell: float = 0.0) -> MicroPoint:
        return MicroPoint(
            ts=datetime(2026, 8, 13, 9, 0, 0) + timedelta(seconds=second),
            price=price,
            buy_money_cum=buy,
            sell_money_cum=sell,
            broker_day_low=day_low,
        )

    def signal(self) -> dict:
        anchor_ts = datetime(2026, 8, 13, 9, 0, 40)
        signal_ts = datetime(2026, 8, 13, 9, 1, 5)
        return {
            "mode": SIGNAL_MODE,
            "algorithm": EARLY_LOW_ALGORITHM,
            "entry_lane": EARLY_LOW_LANE,
            "action": "BUY_READY",
            "reason": "S03_EARLY_LOW_REBOUND+BUY_SPEED_LEAD",
            "ts": signal_ts.isoformat(timespec="milliseconds"),
            "price": 101.2,
            "anchor_low": 100.0,
            "anchor_low_ts": anchor_ts.isoformat(timespec="milliseconds"),
            "anchor_id": f"{anchor_ts.isoformat(timespec='milliseconds')}:100.0000",
            "rebound_pct": 1.2,
            "signal_sequence": 1,
            "code": "000001",
            "name": "TEST",
            "flow_turn_ready": True,
            "flow_recent_buy_rate": 12.0,
            "flow_recent_sell_rate": 2.0,
            "flow_price_responding": True,
        }

    def payload(self) -> dict:
        row = self.signal()
        return {
            "schema": SIGNAL_SCHEMA,
            "date": "20260813",
            "updated_at": row["ts"],
            "mode": SIGNAL_MODE,
            "signals": [row],
        }

    def test_fires_inside_capture_window_on_rebound_and_buy_speed_lead(self):
        detector = EarlyLowDetector()
        armed = detector.feed(self.point(20, 100.0, 100.0), allow_signal=True)
        detector.feed(self.point(40, 100.4, 100.0, 100.0, 100.0), allow_signal=True)
        fired = detector.feed(self.point(65, 101.2, 100.0, 400.0, 150.0), allow_signal=True)
        self.assertEqual(armed["action"], "ARMED")
        self.assertEqual(fired["action"], "BUY_READY")
        self.assertEqual(fired["reason"], "S03_EARLY_LOW_REBOUND+BUY_SPEED_LEAD")
        self.assertEqual(fired["anchor_low"], 100.0)
        self.assertAlmostEqual(fired["rebound_pct"], 1.2)

    def test_blocks_code_for_day_after_crossing_two_percent_first(self):
        detector = EarlyLowDetector()
        detector.feed(self.point(20, 100.0, 100.0), allow_signal=True)
        blocked = detector.feed(self.point(65, 102.1, 100.0), allow_signal=True)
        later = detector.feed(self.point(70, 101.5, 100.0), allow_signal=True)
        self.assertEqual(blocked["reason"], "EARLY_LOW_REBOUND_CHASE_LIMIT")
        self.assertEqual(later["action"], "DONE")

    def test_contract_and_order_selector_require_preserved_flow_fields(self):
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        self.assertEqual(
            len(select_fresh_signals(payload, now=decision_now, max_age_sec=5)),
            1,
        )
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({
                    "codes": {
                        "000001": {
                            "ts": decision_now.isoformat(),
                            "cur": 101.2,
                        }
                    }
                }),
                encoding="utf-8",
            )
            # ★[AUDIT-ISOLATION 2026-08-12 친구님 지시 "테스트 격리 구멍 수리해"]
            #   selector 의 감사 배선은 기본값이 운영 폴더다. 재지정 없이 부르면
            #   운영 감사 사슬에 가짜 기록(000001/TEST)이 남는다 — 8/12 실제 오염.
            previous = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = folder
            try:
                selector = make_strategy03_signal_selector(
                    snapshot_path, 4.0, early_low_live_enabled=True)
                selected = selector(payload, now=decision_now, max_age_sec=5)
            finally:
                if previous is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = previous
        self.assertEqual([row["code"] for row in selected], ["000001"])

    def _run_default_gate(self, *, env_value, feature_ok, release_ok=False):
        """early_low_live_enabled=None(기본 판정 경로)로 selector 를 돌려 선택 코드를 돌려준다.
        명부 의존은 live_feature_enabled monkeypatch 로 격리한다(실제 명부 무접근)."""
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        original_feature = s03_engine.live_feature_enabled
        original_release = s03_engine.release_live_enabled
        prev_env = os.environ.get("S03_EARLY_LOW_LIVE")
        prev_audit = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({"codes": {"000001": {
                    "ts": decision_now.isoformat(), "cur": 101.2}}}),
                encoding="utf-8",
            )
            s03_engine.live_feature_enabled = lambda name: bool(feature_ok)
            s03_engine.release_live_enabled = lambda: bool(release_ok)
            if env_value is None:
                os.environ.pop("S03_EARLY_LOW_LIVE", None)
            else:
                os.environ["S03_EARLY_LOW_LIVE"] = env_value
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = folder
            try:
                selector = make_strategy03_signal_selector(snapshot_path, 4.0)
                selected = selector(payload, now=decision_now, max_age_sec=5)
            finally:
                s03_engine.live_feature_enabled = original_feature
                s03_engine.release_live_enabled = original_release
                if prev_env is None:
                    os.environ.pop("S03_EARLY_LOW_LIVE", None)
                else:
                    os.environ["S03_EARLY_LOW_LIVE"] = prev_env
                if prev_audit is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = prev_audit
        return [row["code"] for row in selected]

    def test_env_only_activation_is_blocked_without_manifest_grant(self):
        # env=YES 로 우회 설정해도 명부 승인이 없으면 실주문 후보가 되면 안 된다.
        self.assertEqual(self._run_default_gate(env_value="YES", feature_ok=False), [])

    def test_manifest_grant_without_env_stays_closed(self):
        # 명부 승인만 있고 env 가 없으면 여전히 닫혀 있어야 한다(둘 다 필요).
        self.assertEqual(self._run_default_gate(env_value=None, feature_ok=True), [])

    def test_both_env_and_manifest_grant_open_the_lane(self):
        self.assertEqual(
            self._run_default_gate(
                env_value="AUTO", feature_ok=True, release_ok=True), ["000001"])

    def test_early_low_order_is_held_when_audit_write_fails(self):
        # ★보안수리 3번: 감사기록에 못 남긴 early_low 신호는 실주문 후보가 되면 안 된다.
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        original_append = EarlyLowAuditChain.append
        prev_audit = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({"codes": {"000001": {
                    "ts": decision_now.isoformat(), "cur": 101.2}}}),
                encoding="utf-8",
            )
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = folder
            EarlyLowAuditChain.append = lambda self, record: None  # 감사 실패 주입
            try:
                selector = make_strategy03_signal_selector(
                    snapshot_path, 4.0, early_low_live_enabled=True)
                selected = selector(payload, now=decision_now, max_age_sec=5)
            finally:
                EarlyLowAuditChain.append = original_append
                if prev_audit is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = prev_audit
        self.assertEqual(selected, [])

    def test_append_rolls_back_partial_write_on_fsync_error(self):
        # ★보안수리 3번 보강: 쓰기 도중 실패해도 부분 줄이 남아 사슬을 손상시키면 안 된다.
        import os as _os
        with tempfile.TemporaryDirectory() as name:
            chain = EarlyLowAuditChain("signal", "20260813", directory=Path(name))
            self.assertIsNotNone(chain.append({"event": "A", "broker_day_low": 1.0}))
            size_after_first = chain.path.stat().st_size
            original_fsync = _os.fsync
            _os.fsync = lambda fd: (_ for _ in ()).throw(OSError("no fsync"))
            try:
                second = chain.append({"event": "B", "broker_day_low": 2.0})
            finally:
                _os.fsync = original_fsync
            self.assertIsNone(second)  # 끝까지 실패 -> None(주문 보류 신호)
            # 파일은 첫 줄만 남고 사슬은 온전해야 한다(부분 줄 롤백됨).
            self.assertEqual(chain.path.stat().st_size, size_after_first)
            ok, reason, records = EarlyLowAuditChain.verify_file(chain.path)
            self.assertTrue(ok, reason)
            self.assertEqual([r["seq"] for r in records], [1])

    def test_append_retries_then_succeeds_after_transient_lock(self):
        import os as _os
        with tempfile.TemporaryDirectory() as name:
            chain = EarlyLowAuditChain("signal", "20260813", directory=Path(name))
            real_fsync = _os.fsync
            state = {"n": 0}

            def flaky(fd):
                state["n"] += 1
                if state["n"] <= 2:  # 처음 2회 실패 후 성공
                    raise OSError("transient lock")
                return real_fsync(fd)

            _os.fsync = flaky
            try:
                written = chain.append({"event": "A", "broker_day_low": 1.0})
            finally:
                _os.fsync = real_fsync
            self.assertIsNotNone(written)  # 재시도 끝에 성공
            ok, reason, records = EarlyLowAuditChain.verify_file(chain.path)
            self.assertTrue(ok, reason)
            self.assertEqual([r["seq"] for r in records], [1])  # 중복 줄 없음

    def test_deleted_audit_file_forces_reappend_before_order(self):
        # ★보안수리 3번 보강: 한 번 기록됐어도 감사 파일이 사라지면 재기록 전엔 주문 통과 금지.
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        prev_audit = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({"codes": {"000001": {
                    "ts": decision_now.isoformat(), "cur": 101.2}}}),
                encoding="utf-8",
            )
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = folder
            engine_file = Path(folder) / "s03_early_low_engine_20260813.jsonl"
            try:
                selector = make_strategy03_signal_selector(
                    snapshot_path, 4.0, early_low_live_enabled=True)
                first = selector(payload, now=decision_now, max_age_sec=5)
                self.assertTrue(engine_file.exists())
                engine_file.unlink()  # 감사 파일 삭제(증거 소실)
                selector(payload, now=decision_now, max_age_sec=5)
            finally:
                if prev_audit is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = prev_audit
            self.assertEqual([r["code"] for r in first], ["000001"])
            # seen 무효화로 재기록됐어야 한다(증거 복원).
            self.assertTrue(engine_file.exists())

    def test_live_order_path_defaults_closed_until_production_replay(self):
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({
                    "codes": {
                        "000001": {
                            "ts": decision_now.isoformat(),
                            "cur": 101.2,
                        }
                    }
                }),
                encoding="utf-8",
            )
            # ★[AUDIT-ISOLATION 2026-08-12] 위와 같은 이유 — 운영 감사 폴더 오염 방지.
            previous = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = folder
            try:
                selector = make_strategy03_signal_selector(
                    snapshot_path, 4.0, early_low_live_enabled=False,
                    flow_turn_live_enabled=False)
                selected = selector(payload, now=decision_now, max_age_sec=5)
            finally:
                if previous is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = previous
            engine_file = Path(folder) / "s03_early_low_engine_20260813.jsonl"
            ok, reason, records = EarlyLowAuditChain.verify_file(engine_file)
            self.assertTrue(ok, reason)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["contract_pass"])
            self.assertFalse(records[0]["selector_pass"])
            self.assertTrue(records[0]["candidate_selector_pass"])
            self.assertEqual(
                records[0]["order_mode"], "SHADOW_ORDER_ZERO")
            self.assertFalse(records[0]["early_low_live_enabled"])
            self.assertFalse(records[0]["flow_turn_live_enabled"])
        self.assertEqual(selected, [])

    def _signal_audit_record(
        self,
        detector: EarlyLowDetector,
        point: MicroPoint,
        *,
        allow_signal: bool = True,
    ) -> dict:
        """생산(골짜기_급반등.run)과 같은 방식으로 판정 전후를 뜬 기록."""
        state = detector.state
        pre_state = {
            "anchor_low": state.anchor_low,
            "anchor_low_ts": (
                state.anchor_low_ts.isoformat(timespec="milliseconds")
                if state.anchor_low_ts else ""),
            "chase_blocked": bool(state.chase_blocked),
            "emitted": bool(state.emitted),
            "flow_points": [
                {
                    "ts": flow_point.ts.isoformat(timespec="milliseconds"),
                    "price": flow_point.price,
                    "buy_money_cum": flow_point.buy_money_cum,
                    "sell_money_cum": flow_point.sell_money_cum,
                }
                for flow_point in detector.flow_points
            ],
        }
        row = detector.feed(point, allow_signal=allow_signal)
        fired = row["action"] == "BUY_READY"
        return {
            "event": "DECISION",
            "code": "000001",
            "name": "TEST",
            "hr_rank": 1,
            "snapshot_ts": point.ts.isoformat(timespec="milliseconds"),
            "current_price": point.price,
            "broker_day_low": point.broker_day_low,
            "buy_money_cum": point.buy_money_cum,
            "sell_money_cum": point.sell_money_cum,
            "allow_signal": allow_signal,
            "pre_state": pre_state,
            "anchor_low": state.anchor_low,
            "anchor_low_ts": (
                state.anchor_low_ts.isoformat(timespec="milliseconds")
                if state.anchor_low_ts else ""),
            "chase_blocked": bool(state.chase_blocked),
            "emitted": bool(state.emitted),
            "rebound_pct": float(row.get("rebound_pct") or 0.0),
            "action": str(row.get("action") or ""),
            "reason": str(row.get("reason") or ""),
            "flow_turn_ready": bool(row.get("flow_turn_ready")),
            "flow_recent_buy_rate": float(row.get("flow_recent_buy_rate") or 0.0),
            "flow_recent_sell_rate": float(row.get("flow_recent_sell_rate") or 0.0),
            "flow_price_responding": bool(row.get("flow_price_responding")),
            "signal_ts": str(row.get("ts") or "") if fired else "",
            "signal_price": float(row.get("price") or 0.0) if fired else 0.0,
            "prod_sha": {"test": "0" * 64},
        }

    def _write_signal_chain(self, folder: Path) -> None:
        chain = EarlyLowAuditChain("signal", "20260813", directory=folder)
        detector = EarlyLowDetector()
        first = chain.append(self._signal_audit_record(
            detector, self.point(20, 100.0, 100.0)))
        second = chain.append(self._signal_audit_record(
            detector, self.point(40, 100.4, 100.0, 100.0, 100.0)))
        third = chain.append(self._signal_audit_record(
            detector, self.point(65, 101.2, 100.0, 400.0, 150.0)))
        assert first is not None and second is not None and third is not None
        assert third["action"] == "BUY_READY"

    def _run_replay(self, folder: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPLAY),
             "--date", "20260813", "--audit-dir", str(folder)],
            capture_output=True, text=True, timeout=120,
        )

    def test_audit_chain_verifies_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            self._write_signal_chain(folder)
            path = folder / "s03_early_low_signal_20260813.jsonl"
            ok, reason, records = EarlyLowAuditChain.verify_file(path)
            self.assertTrue(ok, reason)
            self.assertEqual([r["seq"] for r in records], [1, 2, 3])
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace('"broker_day_low": 100.0',
                                        '"broker_day_low": 99.0')
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok, reason, _ = EarlyLowAuditChain.verify_file(path)
            self.assertFalse(ok)
            self.assertIn("HASH_MISMATCH", reason)

    def test_prod_replay_passes_on_recorded_production_decisions(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            self._write_signal_chain(folder)
            # 엔진 기록은 생산 selector 의 감사 배선이 직접 쓰게 한다.
            payload = self.payload()
            decision_now = datetime(2026, 8, 13, 9, 1, 6)
            snapshot_path = folder / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({"codes": {"000001": {
                    "ts": decision_now.isoformat(), "cur": 101.2,
                }}}),
                encoding="utf-8",
            )
            previous = os.environ.get("S03_EARLY_LOW_AUDIT_DIR")
            os.environ["S03_EARLY_LOW_AUDIT_DIR"] = str(folder)
            try:
                selector = make_strategy03_signal_selector(
                    snapshot_path, 4.0, early_low_live_enabled=True)
                selected = selector(payload, now=decision_now, max_age_sec=5)
            finally:
                if previous is None:
                    os.environ.pop("S03_EARLY_LOW_AUDIT_DIR", None)
                else:
                    os.environ["S03_EARLY_LOW_AUDIT_DIR"] = previous
            self.assertEqual([row["code"] for row in selected], ["000001"])
            engine_path = folder / "s03_early_low_engine_20260813.jsonl"
            self.assertTrue(engine_path.exists())
            result = self._run_replay(folder)
            self.assertIn("[PROD_REPLAY] PASS", result.stdout, result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_prod_replay_unverified_when_field_missing(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            chain = EarlyLowAuditChain("signal", "20260813", directory=folder)
            detector = EarlyLowDetector()
            record = self._signal_audit_record(
                detector, self.point(20, 100.0, 100.0))
            record.pop("broker_day_low")
            self.assertIsNotNone(chain.append(record))
            result = self._run_replay(folder)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("UNVERIFIED", result.stdout)
            self.assertIn("broker_day_low", result.stdout)

    def test_prod_replay_unverified_without_audit_data(self):
        with tempfile.TemporaryDirectory() as name:
            result = self._run_replay(Path(name))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("NO_AUDIT_DATA", result.stdout)

    def test_uses_exactly_first_forty_ranked_high_range_codes(self):
        payload = {
            "schema_version": 2,
            "for_date": "20260813",
            "source_stale": False,
            "candidates": [
                {"rank": rank, "code": f"{rank:06d}"}
                for rank in range(45, 0, -1)
            ],
        }
        codes = _early_high_range_codes(payload, "20260813")
        self.assertEqual(len(codes), 40)
        self.assertIn("000001", codes)
        self.assertIn("000040", codes)
        self.assertNotIn("000041", codes)


if __name__ == "__main__":
    unittest.main()
