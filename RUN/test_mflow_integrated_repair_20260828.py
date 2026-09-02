import ast
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath


HERE = Path(__file__).resolve().parent
EXEC = HERE / "money_flow_exec_v1.py"
BOARD = HERE / "money_flow_board_v1.py"
GATEWAY = HERE / "broker_gateway_v1.py"


def function_from(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def test_a_deep_watch_publish_and_gateway_read():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        che = tmp / "che.json"
        che.write_text(json.dumps({
            "111111": {"lo": 94},
            "222222": {"lo": 96},
        }), encoding="utf-8")

        def safe_path(raw):
            if isinstance(raw, Path):
                return raw
            return tmp / PureWindowsPath(str(raw)).name

        ns = {
            "os": os, "json": json, "time": time, "datetime": datetime,
            "Path": safe_path, "CHE_STATE": che, "_MW": {"ts": 0.0, "n": 0},
            "_UNIV": (["111111", "222222"], {}),
            "_prev_top_pool": lambda _today: [("111111", 100, 0), ("222222", 100, 0)],
        }
        publish = function_from(BOARD, "_publish_micro_watch", ns)
        publish({"111111": {"cur": 95}, "222222": {"cur": 97}})
        deep_file = tmp / "micro_watch_moneyflow_deep.json"
        deep = json.loads(deep_file.read_text(encoding="utf-8"))
        assert deep["codes"] == ["111111"]

        gw_file = tmp / "gateway_deep.json"
        gw_file.write_text(json.dumps({
            "for_date": datetime.now().strftime("%Y%m%d"),
            "codes": ["111111", "111111", "222222"],
        }), encoding="utf-8")
        gw_ns = {
            "json": json, "datetime": datetime,
            "MFLOW_MICRO_CAP": 90, "MFLOW_WATCH_FILE": gw_file,
        }
        reader = function_from(GATEWAY, "_read_moneyflow_watch", gw_ns)
        assert reader(object()) == ["111111", "222222"]


def test_b_only_deep_reaches_1330():
    src = EXEC.read_text(encoding="utf-8")
    assert 'DEEP_ENTRY_END = os.environ.get("MF_DEEP_ENTRY_END", "1400")' in src
    assert "if hm > DEEP_ENTRY_END:\n        return False" in src
    assert 'if hm > ENTRY_END and not r.get("_deep"):' in src

    def reaches_candidate(hm, deep):
        if hm > "1400":
            return False
        if hm > "1300" and not deep:
            return False
        return True

    assert reaches_candidate("1330", True) is True
    assert reaches_candidate("1330", False) is False
    assert reaches_candidate("1401", True) is False


def test_c_counterfactual_and_raw_inputs():
    with tempfile.TemporaryDirectory() as raw_tmp:
        audit_dir = Path(raw_tmp)
        ns = {
            "datetime": datetime, "json": json,
            "AUDIT_DIR": audit_dir, "_AUDIT_SEEN": set(),
        }
        audit = function_from(EXEC, "_audit_decision", ns)
        passed = {
            "inflow": True, "imbalance": False, "candle_pos": True,
            "bull_n": True, "dumping": True,
        }
        audit("123456", "BLOCK", "imbalance", passed, {"imb": 0.8})
        files = list(audit_dir.glob("mflow_decision_inputs_*.jsonl"))
        assert len(files) == 1
        row = json.loads(files[0].read_text(encoding="utf-8").strip())
        assert row["would_pass_without_gate"] is True
        assert row["values"]["imb"] == 0.8


if __name__ == "__main__":
    test_a_deep_watch_publish_and_gateway_read()
    test_b_only_deep_reaches_1330()
    test_c_counterfactual_and_raw_inputs()
    print("PASS A=deep-watch B=deep-only-1330 C=audit-counterfactual")
