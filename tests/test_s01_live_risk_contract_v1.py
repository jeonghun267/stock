# -*- coding: utf-8 -*-
"""Production wiring lock for S01 capital, quantity, and trusted-price gates."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import capital_config
from live_owner_approval_guard_v1 import verify_live_hashes
from strategy_01_rotation_engine_v2 import Config


def test_s01_uses_two_million_won_and_one_share_ssot():
    raw = json.loads((ROOT / "config" / "capital.json").read_text(encoding="utf-8-sig"))
    assert raw["capital_krw"] == 2_000_000
    assert raw["order_quantity"] == 1
    assert capital_config.get_capital() == 2_000_000
    assert capital_config.get_order_quantity() == 1
    assert capital_config.get_limit("daily_total_max") == 2_000_000
    config = Config()
    assert config.quantity == 1
    assert config.rotation_capital_krw == 2_000_000


def test_s01_live_launcher_requires_trusted_price_floor():
    launcher = (RUN / "hidden" / "SAFEPLUS_STRATEGY01_LIVE.cmd").read_text(
        encoding="utf-8-sig"
    )
    assert "set S01_LIVE=YES" in launcher
    assert "set SAFEPLUS_MIN_PRICE=10000" in launcher
    assert "strategy_all_live_gate_launcher_v1.py --strategy S01" in launcher


def test_final_broker_rechecks_quantity_order_value_and_total_budget():
    source = (RUN / "broker_gateway_v1.py").read_text(encoding="utf-8-sig")
    assert 'capital_config.get_order_quantity()' in source
    assert 'capital_config.get_limit("order_max")' in source
    assert 'position_budget.can_open_krw(qty * current_price)' in source
    assert "PRICE_UNAVAILABLE" in source


def test_s01_live_hash_boundary_is_intact():
    assert verify_live_hashes("S01") == (True, [])
