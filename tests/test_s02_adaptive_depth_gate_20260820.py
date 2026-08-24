# -*- coding: utf-8 -*-
from datetime import datetime
import sys
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
sys.path.insert(0, str(ROOT / "RUN"))

import strategy_02_low_buy_signal_v1 as s02


def test_depth_gate_and_adaptive_boundaries():
    morning = datetime.fromisoformat("2026-08-20T09:10:00")
    daytime = datetime.fromisoformat("2026-08-20T10:10:00")
    assert s02._effective_required_drop_pct(morning, True) == 0.0
    assert s02._effective_required_drop_pct(daytime, True) == 0.0
    assert s02._effective_required_drop_pct(morning, False) == 3.0
    assert s02._effective_required_drop_pct(daytime, False) == 5.0

    fast = s02.adaptive_bottom_decision(
        algorithm="S02_S06_DIRECT_REBOUND_V1", entry_gap_pct=1.5,
        anchor_low=100.0, open_price=100.0, avg_5d_range_pct=10.0,
        regime_band="BULL", u201_pct=2.5, observe_sec=60.0,
    )
    assert fast["adaptive_lane"] == "FAST"

    weak_early = s02.adaptive_bottom_decision(
        algorithm="S02_S06_STAIRCASE_RETEST_V1", entry_gap_pct=2.0,
        anchor_low=95.0, open_price=100.0, avg_5d_range_pct=10.0,
        regime_band="BEAR", u201_pct=-1.0, observe_sec=299.9,
    )
    weak_ready = s02.adaptive_bottom_decision(
        algorithm="S02_S06_STAIRCASE_RETEST_V1", entry_gap_pct=2.0,
        anchor_low=95.0, open_price=100.0, avg_5d_range_pct=10.0,
        regime_band="BEAR", u201_pct=-1.0, observe_sec=300.0,
    )
    assert weak_early["adaptive_lane"] == "BLOCK"
    assert weak_ready["adaptive_lane"] == "RETEST"


def test_today_actual_buys_against_current_adaptive_decision():
    # [HYPOTHETICAL] Inputs are the generated 2026-08-20 shadow-decision rows,
    # not complete decision-boundary tick streams.
    cases = [
        ("310210", "DIRECT_REBOUND", 1.3912, 179700.0, -3.0744, 10.27, "GRAY", 0.00, 0.0, "BLOCK"),
        ("087010", "DIRECT_REBOUND", 1.2372, 185900.0, -2.8736, 9.79, "BULL", 3.16, 0.0, "BLOCK"),
        ("095340", "DIRECT_REBOUND", 1.0545, 170700.0, -3.8310, 8.17, "BULL", 1.75, 0.0, "BLOCK"),
        ("087010", "STAIRCASE_RETEST", 1.1425, 183800.0, -3.9707, 9.79, "LEAN_BULL", 1.49, 313.1, "RETEST"),
        ("064760", "STAIRCASE_RETEST", 1.3245, 226500.0, -3.2051, 12.46, "LEAN_BULL", 1.49, 81.3, "RETEST"),
        ("126730", "DIRECT_REBOUND", 1.2469, 20050.0, -1.2315, 14.62, "LEAN_BULL", 1.40, 0.0, "FAST"),
        ("084370", "STAIRCASE_RETEST", 1.2658, 134300.0, -1.9708, 8.61, "BULL", 1.87, 438.6, "RETEST"),
        ("082920", "STAIRCASE_RETEST", 1.5579, 33700.0, -3.1609, 10.55, "BULL", 1.83, 584.4, "RETEST"),
    ]
    for code, lane, gap, low, low_from_open, avg_range, regime, u201, observe, expected in cases:
        open_price = low / (1.0 + low_from_open / 100.0)
        result = s02.adaptive_bottom_decision(
            algorithm=f"S02_S06_{lane}_V1", entry_gap_pct=gap,
            anchor_low=low, open_price=open_price,
            avg_5d_range_pct=avg_range, regime_band=regime,
            u201_pct=u201, observe_sec=observe,
        )
        assert result["adaptive_lane"] == expected, code
