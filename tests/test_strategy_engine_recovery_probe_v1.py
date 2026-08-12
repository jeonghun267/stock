import json
import logging
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_engine_recovery_probe_v1 as recovery
from strategy_05_rotation_engine_v1 import Strategy05Engine, build_config
from strategy_06_crash_low_chase_v1 import Config as S06Config
from strategy_06_crash_low_chase_v1 import Strategy06Engine


def state(schema, positions):
    return {"schema": schema, "date": "20260810", "positions": positions}


class RecoveryProbeTests(unittest.TestCase):
    def test_probe_is_fail_closed_and_requires_real_active_position(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = recovery.RecoveryTarget(
                root / "state.json", root / "engine.lock", "schema-v1")
            with patch.dict(recovery.TARGETS, {"S05": target}, clear=False):
                self.assertEqual(recovery.probe("S05"), 12)

                target.state_path.write_text(
                    json.dumps(state("schema-v1", {})), encoding="utf-8")
                self.assertEqual(recovery.probe("S05"), 11)

                target.state_path.write_text(json.dumps(state("schema-v1", {
                    "shadow": {"code": "111111", "phase": "HOLD", "real": False},
                    "closed": {"code": "222222", "phase": "CLOSED", "real": True},
                    "live": {"code": "333333", "phase": "HOLD", "real": True},
                })), encoding="utf-8")
                self.assertEqual(recovery.probe("S05"), 0)

                target.lock_path.write_text(str(os.getpid()), encoding="ascii")
                self.assertEqual(recovery.probe("S05"), 10)

    def test_recovery_environment_forces_s05_exit_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ, {"STRATEGY_RECOVERY_EXIT_ONLY": "YES"}, clear=False
        ):
            root = Path(folder)
            config = replace(
                build_config(),
                state_path=root / "state.json",
                names_path=root / "names.json",
                approval_path=root / "approval.flag",
                off_flag_path=root / "off.flag",
                manual_buy_block_path=root / "manual.flag",
                log_path=root / "engine.log",
                event_dir=root / "events",
                live_requested=True,
            )
            engine = Strategy05Engine(
                config, logger=logging.getLogger("test-recovery-s05"))
            self.assertTrue(engine.broker.force_exit_only)
            self.assertTrue(engine.broker.real_session)
            self.assertFalse(engine.broker.buy_allowed)

    def test_recovery_environment_forces_s06_exit_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ, {"STRATEGY_RECOVERY_EXIT_ONLY": "YES"}, clear=False
        ):
            root = Path(folder)
            config = replace(
                S06Config(),
                state_path=root / "state.json",
                names_path=root / "names.json",
                approval_path=root / "approval.flag",
                off_flag_path=root / "off.flag",
                manual_buy_block_path=root / "manual.flag",
                log_path=root / "engine.log",
                event_dir=root / "events",
                live_requested=True,
            )
            engine = Strategy06Engine(
                config, logger=logging.getLogger("test-recovery-s06"))
            self.assertTrue(engine.broker.force_exit_only)
            self.assertTrue(engine.broker.real_session)
            self.assertFalse(engine.broker.buy_allowed)


if __name__ == "__main__":
    unittest.main()
