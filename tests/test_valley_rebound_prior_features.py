# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "analysis" / "골짜기_급반등_사전특징_분석.py"
SPEC = importlib.util.spec_from_file_location("valley_prior_features", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValleyReboundPriorFeaturesTest(unittest.TestCase):
    def test_average_rank_handles_ties(self):
        ranks = MODULE.average_rank([(0, 1.0), (1, 1.0), (2, 3.0)])
        self.assertAlmostEqual(ranks[0], ranks[1])
        self.assertLess(ranks[0], ranks[2])

    def test_same_day_effect_does_not_cross_dates(self):
        quick = [
            {"day": "20260723", "x": 10.0},
            {"day": "20260724", "x": 1.0},
        ]
        control = [
            {"day": "20260723", "x": 5.0},
            {"day": "20260724", "x": 2.0},
        ]
        effect, pairs = MODULE.common_language_effect(quick, control, "x")
        self.assertEqual(pairs, 2)
        self.assertEqual(effect, 0.0)

    def test_screen_rules_requires_both_days(self):
        rows = []
        for day in ("20260723", "20260724"):
            for idx in range(10):
                row = {
                    "day": day,
                    "quick_v": idx == 9,
                }
                for feature in MODULE.FEATURES:
                    row[f"{feature}__day_pct"] = (idx + 0.5) / 10
                rows.append(row)
        rules = MODULE.screen_rules(rows)
        self.assertTrue(rules)
        self.assertTrue(all(rule["quick_days"] == 2 for rule in rules))


if __name__ == "__main__":
    unittest.main()
