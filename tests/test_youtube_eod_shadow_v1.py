from pathlib import Path
import sys
from datetime import datetime, timedelta
from unittest.mock import patch


BASE = Path(r"C:\stock_bot")
RUN = BASE / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import youtube_eod_shadow_v1 as shadow


def test_lrl_endpoint_matches_linear_sequence():
    assert shadow.lrl_endpoint([float(value) for value in range(1, 21)]) == 20.0


def test_exact_video_gates_pass_together():
    previous = [float(value) for value in range(1, 400)]
    result = shadow.evaluate_video_condition(
        previous_closes=previous,
        current_price=500.0,
        cumulative_volume=1_000_001,
        float_shares=1_000_000,
    )
    assert result["passed"] is True
    assert result["gates"] == {
        "lrl_red": True,
        "above_ma200": True,
        "above_ma400": True,
        "volume_over_float": True,
    }


def test_missing_or_equal_inputs_fail_closed():
    previous = [float(value) for value in range(1, 400)]
    assert shadow.evaluate_video_condition(previous[:-1], 500, 2_000, 1_000)["passed"] is False
    assert shadow.evaluate_video_condition(previous, 500, 1_000, 1_000)["passed"] is False
    assert shadow.evaluate_video_condition(previous, 500, 2_000, 0)["passed"] is False


def test_shadow_has_no_order_api():
    source = (RUN / "youtube_eod_shadow_v1.py").read_text(encoding="utf-8")
    forbidden = ["SendOrder(", "send_order", "SENDORDER_REAL", "SENDORDER_SHADOW"]
    assert all(token not in source for token in forbidden)


def test_read_only_batch_fid_wiring_exists():
    client = (RUN / "broker_client.py").read_text(encoding="utf-8")
    gateway = (RUN / "broker_gateway_v1.py").read_text(encoding="utf-8")
    assert "def batch_get_comm_real_data" in client
    assert 'req_type == "BATCH_GET_COMM_REAL_DATA"' in gateway
    assert "allowed_fids = {10, 13}" in gateway


def test_float_cache_allows_previous_close_but_rejects_stale():
    now = datetime(2026, 8, 12, 15, 0)
    cache = {
        "for_date": "20260811",
        "generated_at": (now - timedelta(hours=18)).isoformat(),
        "codes": {"000001": {"float_shares": 1000}},
    }
    assert shadow.float_cache_is_usable(cache, now) is True
    cache["generated_at"] = (now - timedelta(hours=121)).isoformat()
    assert shadow.float_cache_is_usable(cache, now) is False


def test_realtime_registration_retries_then_succeeds():
    class Broker:
        def __init__(self):
            self.calls = 0

        def setreal_reg(self, *args, **kwargs):
            self.calls += 1
            if self.calls < 3:
                return {"status": "TIMEOUT", "error": "late"}
            return {"status": "OK"}

    broker = Broker()
    with patch.object(shadow.time, "sleep"), patch.object(shadow, "_log"):
        screens = shadow._register_realtime(broker, ["000001"])
    assert broker.calls == 3
    assert screens == {"9600": ["000001"]}
