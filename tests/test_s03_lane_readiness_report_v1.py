import csv, sys
from pathlib import Path
RUN = Path(__file__).resolve().parents[1] / "RUN"
sys.path.insert(0, str(RUN))
from s03_lane_readiness_report_v1 import SPECS, build_report


def write_csv(path, headers, lane):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow({field: lane if field == "entry_lane" else "1" for field in headers})


def test_three_lane_readiness_passes_without_live_change(tmp_path):
    day = "20260823"
    for lane, (pattern, required, _) in SPECS.items():
        write_csv(tmp_path / pattern.format(day=day), sorted(required), lane)
    report = build_report(tmp_path, day)
    assert report["status"] == "PASS"
    assert report["entry_lanes_expected"] == ["EARLY_LOW","OPEN_CRASH","INTRADAY_CRASH"]
    assert report["live_behavior_changed"] is False


def test_missing_execution_field_fails_closed(tmp_path):
    day = "20260823"
    for lane, (pattern, required, _) in SPECS.items():
        headers = set(required)
        if lane == "OPEN_CRASH":
            headers.remove("spread_bps")
        write_csv(tmp_path / pattern.format(day=day), sorted(headers), lane)
    report = build_report(tmp_path, day)
    assert report["status"] == "UNVERIFIED"
    assert report["lanes"]["OPEN_CRASH"]["missing_columns"] == ["spread_bps"]
