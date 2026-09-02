from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "CORE"
    / "COLLECT"
    / "reconcile_positions_from_broker_v1.py"
)

def load_module():
    spec = importlib.util.spec_from_file_location("position_reconcile_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

class PositionReconcileSafetyTests(unittest.TestCase):
    def test_empty_broker_requires_two_confirmed_snapshots(self) -> None:
        module = load_module()
        safe, _ = module._safe_to_write({}, {"007390"})
        self.assertFalse(safe)
        safe, why = module._safe_to_write(
            {}, {"007390"}, confirmed_empty=True,
        )
        self.assertTrue(safe)
        self.assertEqual(why, "")

if __name__ == "__main__":
    unittest.main()