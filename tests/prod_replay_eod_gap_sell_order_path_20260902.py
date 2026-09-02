import hashlib
import importlib.util
import json
from pathlib import Path
from datetime import datetime
from unittest.mock import patch


ROOT = Path(r"C:\stock_bot")
PROD = ROOT / "RUN" / "eod_gap_live_executor_v1.py"
FIXTURE = ROOT / "tests" / "fixtures" / "eod_gap_sell_order_path_20260902.json"
REPORT = ROOT / "reports" / "verified_replay" / "20260902" / "eod_gap_sell_order_path_replay_20260902.json"
COMMAND = "py -3 -B -X utf8 tests/prod_replay_eod_gap_sell_order_path_20260902.py"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prod():
    spec = importlib.util.spec_from_file_location("eod_gap_sell_order_path_replay", PROD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mod = load_prod()
    captured = []

    class CapturingBroker:
        def send_order_real(self, **kwargs):
            captured.append(kwargs)
            return {"status": "OK"}

    replay_times = [datetime(2026, 9, 3, 9, 0, 5)] * 3 + [datetime(2026, 9, 3, 9, 30, 0)]
    plans = []
    with patch.object(mod, "LIVE", True), \
            patch.object(mod, "ACCOUNT", "65020000"), \
            patch.object(mod, "_read_micro", return_value=frozen["quote"]), \
            patch.object(mod, "_log"):
        for attempt, now in zip((0, 1, 2, 2), replay_times):
            plan = mod._sell_order_plan(frozen["code"], attempt, now=now)
            plans.append(plan)
            accepted = mod._order(
                CapturingBroker(), frozen["code"], frozen["quantity"], frozen["side"],
                "PROD_REPLAY", hoga_gb=plan["hoga_gb"], price=plan["price"]
            )
            if not accepted:
                raise AssertionError(f"production order path rejected stage: {plan}")

    if len(captured) != len(frozen["expected_stages"]):
        raise AssertionError(f"production order path was not accepted: {captured}")
    actual = []
    for plan, order in zip(plans, captured):
        actual.append({"stage": plan["stage"], "order_type": order["order_type"],
                       "hoga_gb": order["hoga_gb"], "price": order["price"]})
    if actual != frozen["expected_stages"]:
        raise AssertionError(f"order mismatch: actual={actual} expected={frozen['expected_stages']}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS",
        "date": frozen["date"],
        "performance_scope": "DECISION_ONLY",
        "source_data": str(FIXTURE),
        "production_entry_point": str(PROD) + "::_order",
        "production_code_changed": "CHANGED",
        "command": COMMAND,
        "source_sha256": sha256(FIXTURE),
        "replay_engine_sha256": sha256(PROD),
        "decisions": actual,
        "orders_sent": 0,
        "note": "Production _order path executed with a capturing broker; no real broker order was sent."
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
