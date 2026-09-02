import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


class AtomicStateReplaceRetryTests(unittest.TestCase):
    def test_s01_s02_shared_writer_uses_unique_temp_and_cleans_up(self):
        module = importlib.import_module("strategy_01_rotation_engine_v2")
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            sources = []

            def always_locked(source, target):
                sources.append(Path(source))
                raise PermissionError(5, "locked")

            with patch.object(module.os, "replace", side_effect=always_locked), patch.object(
                module.time, "sleep"
            ) as sleep:
                saved = module.write_json_atomic(destination, {"status": "blocked"})

            self.assertFalse(saved)
            self.assertEqual(len(sources), 20)
            self.assertEqual(sleep.call_count, 19)
            self.assertNotEqual(sources[0], destination.with_suffix(".json.tmp"))
            self.assertTrue(sources[0].name.startswith("state.json."))
            self.assertFalse(sources[0].exists())

    def test_live_engines_retry_transient_windows_lock(self):
        original_replace = os.replace
        module_names = (
            "strategy_06_crash_low_chase_v1",
            "strategy_01_rotation_engine_v2",
            "strategy_01_open_surge_engine_v1",
        )
        for module_name in module_names:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp_dir:
                module = importlib.import_module(module_name)
                destination = Path(temp_dir) / "state.json"
                attempts = 0

                def replace_after_two_locks(source, target):
                    nonlocal attempts
                    attempts += 1
                    if attempts <= 2:
                        raise PermissionError(5, "locked")
                    return original_replace(source, target)

                with patch.object(module.os, "replace", side_effect=replace_after_two_locks), patch.object(
                    module.time, "sleep"
                ) as sleep:
                    saved = module.write_json_atomic(destination, {"status": "saved"})

                self.assertTrue(saved)
                self.assertEqual(attempts, 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"status": "saved"})

    def test_shadow_writer_retries_transient_windows_lock(self):
        module = importlib.import_module("valley_common_exit_shadow_v1")
        original_replace = Path.replace
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            attempts = 0

            def replace_after_two_locks(source, target):
                nonlocal attempts
                attempts += 1
                if attempts <= 2:
                    raise PermissionError(5, "locked")
                return original_replace(source, target)

            with patch.object(Path, "replace", autospec=True, side_effect=replace_after_two_locks), patch.object(
                module.time, "sleep"
            ) as sleep:
                saved = module.write_json_atomic(destination, {"status": "saved"})

            self.assertTrue(saved)
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"status": "saved"})

    def test_s06_unique_temp_retries_then_returns_false(self):
        module = importlib.import_module("strategy_06_crash_low_chase_v1")
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            sources = []

            def always_locked(source, target):
                sources.append(Path(source))
                raise PermissionError(5, "locked")

            with patch.object(module.os, "replace", side_effect=always_locked), patch.object(
                module.time, "sleep"
            ) as sleep:
                saved = module.write_json_atomic(destination, {"status": "blocked"})

            self.assertFalse(saved)
            self.assertEqual(len(sources), 20)
            self.assertEqual(sleep.call_count, 19)
            self.assertNotEqual(sources[0], destination.with_suffix(".json.tmp"))
            self.assertTrue(sources[0].name.startswith("state.json."))
            self.assertFalse(sources[0].exists())

    def test_live_engine_save_exhaustion_fails_closed(self):
        targets = (
            ("strategy_01_rotation_engine_v2", "Strategy01Engine"),
            ("strategy_01_open_surge_engine_v1", "Strategy01Engine"),
            ("strategy_06_crash_low_chase_v1", "Strategy06Engine"),
        )
        for module_name, class_name in targets:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp:
                module = importlib.import_module(module_name)
                engine = object.__new__(getattr(module, class_name))
                engine.state = {}
                state_path = Path(temp) / "locked-state.json"
                engine.config = SimpleNamespace(state_path=state_path)
                engine.log = Mock()
                with patch.object(module, "write_json_atomic", return_value=False):
                    with self.assertRaisesRegex(RuntimeError, "FAIL_CLOSED"):
                        engine._save()
                engine.log.critical.assert_called_once()
                self.assertTrue(
                    state_path.with_suffix(
                        state_path.suffix + ".save_failed.flag").exists()
                )

    def test_save_failure_marker_forces_balance_reconcile_with_empty_local_state(self):
        targets = (
            ("strategy_01_rotation_engine_v2", "Strategy01Engine"),
            ("strategy_06_crash_low_chase_v1", "Strategy06Engine"),
        )
        for module_name, class_name in targets:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp:
                module = importlib.import_module(module_name)
                engine = object.__new__(getattr(module, class_name))
                state_path = Path(temp) / "state.json"
                marker = module.state_save_failure_marker(state_path)
                marker.write_text("STATE_SAVE_FAILED\n", encoding="ascii")
                engine.state_save_failure_paths = (marker,)
                engine.state_save_failure_path = marker
                engine.state = {"positions": {}}
                engine.broker = Mock()
                engine.broker.connect.return_value = True
                engine.broker.holdings.return_value = {"005930": {"qty": 1}}
                engine._save = Mock()

                engine._startup_reconcile()

                engine.broker.holdings.assert_called_once()
                self.assertTrue(engine.state["recovery_blocked"])
                self.assertIn("005930", engine.state["last_error"])
                self.assertTrue(marker.exists())
                engine._save.assert_called_once()

    def test_save_failure_marker_clears_only_after_confirmed_flat_account(self):
        targets = (
            ("strategy_01_rotation_engine_v2", "Strategy01Engine"),
            ("strategy_06_crash_low_chase_v1", "Strategy06Engine"),
        )
        for module_name, class_name in targets:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp:
                module = importlib.import_module(module_name)
                engine = object.__new__(getattr(module, class_name))
                state_path = Path(temp) / "state.json"
                marker = module.state_save_failure_marker(state_path)
                marker.write_text("STATE_SAVE_FAILED\n", encoding="ascii")
                engine.state_save_failure_paths = (marker,)
                engine.state_save_failure_path = marker
                engine.state = {"positions": {}}
                engine.broker = Mock()
                engine.broker.connect.return_value = True
                engine.broker.holdings.return_value = {}
                engine._save = Mock()

                engine._startup_reconcile()

                self.assertFalse(marker.exists())
                self.assertFalse(engine.state["recovery_blocked"])
                self.assertEqual(engine.state["last_error"], "")
                engine._save.assert_called_once()

    def test_save_failure_uses_separate_fallback_marker(self):
        targets = (
            "strategy_01_rotation_engine_v2",
            "strategy_06_crash_low_chase_v1",
        )
        original_write_text = Path.write_text
        for module_name in targets:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp:
                module = importlib.import_module(module_name)
                state_path = Path(temp) / "data" / "state.json"
                primary = module.state_save_failure_marker(state_path)
                fallback_dir = Path(temp) / "fallback"

                def write_except_primary(path, *args, **kwargs):
                    if path == primary:
                        raise PermissionError(5, "primary locked")
                    return original_write_text(path, *args, **kwargs)

                with patch.dict(
                    os.environ,
                    {"STOCK_BOT_RECOVERY_FLAG_DIR": str(fallback_dir)},
                ), patch.object(
                    Path, "write_text", autospec=True, side_effect=write_except_primary
                ):
                    marker = module.mark_state_save_failure(state_path)

                self.assertEqual(
                    marker, fallback_dir / "state.json.save_failed.flag"
                )
                self.assertTrue(marker.exists())

    def test_all_signal_writers_share_the_same_survival_policy(self):
        original_replace = os.replace
        module_names = (
            "strategy_04_pullback_signal_v1",
            "strategy_05_base_breakout_signal_v1",
            "골짜기_급반등",
            "strategy_02_low_buy_signal_v1",
            "strategy_02_low_buy_signal_SHADOWB_v1",
            "strategy_02_low_buy_signal_SHADOWC_v1",
        )
        for module_name in module_names:
            with self.subTest(module=module_name), tempfile.TemporaryDirectory() as temp_dir:
                module = importlib.import_module(module_name)
                destination = Path(temp_dir) / "signal.json"
                attempts = 0

                def replace_after_two_locks(source, target):
                    nonlocal attempts
                    attempts += 1
                    if attempts <= 2:
                        raise PermissionError(5, "locked")
                    return original_replace(source, target)

                with patch.object(module.os, "replace", side_effect=replace_after_two_locks), patch.object(
                    module.time_module, "sleep"
                ) as sleep:
                    saved = module._write_json_atomic(destination, {"status": "saved"})

                self.assertTrue(saved)
                self.assertEqual(attempts, 3)
                self.assertEqual(sleep.call_count, 2)

    def test_signal_writer_exhaustion_returns_false_without_crashing(self):
        module = importlib.import_module("strategy_04_pullback_signal_v1")
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "signal.json"
            with patch.object(module.os, "replace", side_effect=PermissionError(5, "locked")) as replace, patch.object(
                module.time_module, "sleep"
            ) as sleep, patch.object(module.sys, "stderr"):
                saved = module._write_json_atomic(destination, {"status": "blocked"})

            self.assertFalse(saved)
            self.assertEqual(replace.call_count, 6)
            self.assertEqual(sleep.call_count, 5)


if __name__ == "__main__":
    unittest.main()
