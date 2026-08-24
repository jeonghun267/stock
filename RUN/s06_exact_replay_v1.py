"""S06 1회 재생기 — 저장 입력을 현재 엔진의 실제 메서드에 그대로 넣는다.

[2026-08-20 친구님 지시] "저장 입력을 현재 Strategy06Engine 실제 메서드에 그대로 넣는
재생기를 만들고 재구성·프록시 계산은 금지한다."

재구성을 피하는 방법:
  저장해 둔 snapshot/hr 원본 raw 를 임시 파일로 되살리고 Config 의 경로를 그쪽으로 돌린다.
  그러면 `_snapshot()` · `_snapshot_point()` · `_hr_row()` · `day_anchor()` 가 전부
  **실제 코드 그대로** 실행된다. 판정식을 베껴 쓴 곳이 한 줄도 없다.
  호출하는 판정 진입점도 실제 `Strategy06Engine._chase_tick(code, now)` 하나뿐이다.

시계 정렬(재구성 아님):
  `_entry_wait_epoch` · `_observe_log_epoch` 는 `time.time()` 절대값과 비교된다.
  저장 시점 `wall_epoch` 과 재생 시각의 차이만큼 평행이동해, 원본과 **같은 경과시간**이
  되도록 맞춘다. 값을 지어내는 것이 아니라 기준선을 옮기는 것이다.

판정: 저장된 chase_after 와 재생 결과가 전건 일치하면 [PROD_REPLAY] PASS.

사용:
    python s06_exact_replay_v1.py                     # 최신 날짜 파일 전건
    python s06_exact_replay_v1.py --date 20260821
    python s06_exact_replay_v1.py --file <경로> --limit 50
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
import time
from dataclasses import fields, replace
from datetime import datetime, time as datetime_time
from pathlib import Path
from typing import Any, Dict, List, Optional

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

RECORD_DIR = Path(os.environ.get(
    "S06_EXACT_RECORD_DIR", r"C:\stock_bot\data\s06_exact_replay"))

PROVENANCE = "[PROD_REPLAY]"
UNVERIFIED = "[UNVERIFIED]"
EXPECTED_SCHEMA = "s06_exact_input_v2"

# 재생 중에는 기록기가 다시 돌면 안 된다(무한 누적 방지).
os.environ["S06_EXACT_RECORD"] = "NO"
os.environ["S06_LIVE"] = "NO"


class _NoOrderBroker:
    real_session = False
    buy_allowed = False
    mode = "REPLAY"
    last_error = "REPLAY_NO_BROKER"

    def connect(self) -> bool:
        return False

    def holdings(self):
        return {}

    def open_orders(self, code=None, buy=None):
        return {}

    def submit(self, **kwargs) -> str:
        return "SHADOW"

    def cancel(self, **kwargs) -> str:
        return "SHADOW"


class _NoSlots:
    def __init__(self) -> None:
        self._codes: set[str] = set()

    def acquire(self, code, tag, day) -> bool:
        code6 = str(code).zfill(6)
        if code6 in self._codes:
            return True
        if len(self._codes) >= 6:
            return False
        self._codes.add(code6)
        return True

    def release(self, code, day) -> None:
        self._codes.discard(str(code).zfill(6))


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return str(value)


def _apply_saved_config(config: Any, saved: Dict[str, Any]):
    """Frozen Config를 replace하여 저장 당시 실효값을 복원한다."""
    applied: List[str] = []
    updates: Dict[str, Any] = {}
    for descriptor in fields(config):
        field = descriptor.name
        if field not in (saved or {}) or not hasattr(config, field):
            continue
        current = getattr(config, field)
        value = saved[field]
        if isinstance(current, Path):
            continue
        if field == "live_requested":
            continue
        if isinstance(current, bool):
            converted = bool(value)
        elif isinstance(current, int) and isinstance(value, (int, float)):
            converted = int(value)
        elif isinstance(current, float) and isinstance(value, (int, float)):
            converted = float(value)
        elif isinstance(current, str):
            converted = str(value)
        elif isinstance(current, datetime_time) and isinstance(value, str):
            converted = datetime_time.fromisoformat(value)
        else:
            continue
        updates[field] = converted
        if current != converted:
            applied.append(field)
    return replace(config, **updates), applied


def replay_one(record: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
    from strategy_06_exact_input_recorder_v1 import _state_for_tick
    from strategy_06_crash_low_chase_v1 import (
        ChaseState, Config, Strategy06Engine, VolumeWindow,
    )

    code = str(record.get("code") or "").zfill(6)
    now = datetime.fromisoformat(str(record["now_iso"]))

    # ── 저장한 원본 raw 를 파일로 되살린다 (엔진이 실제로 읽게) ──────────────
    snap_path = workdir / "snapshot.json"
    hr_path = workdir / "hr_state.json"
    _write_json(snap_path, {"codes": {code: record.get("snapshot_rec") or {}}})
    _write_json(hr_path, {"codes": {code: record.get("hr_rec") or {}}})

    state_path = workdir / "state.json"
    saved_state = record.get("state_before")
    if not isinstance(saved_state, dict):
        raise ValueError("record is missing full state_before")
    _write_json(state_path, saved_state)

    config = Config(
        live_requested=False,
        snapshot_path=snap_path,
        hr_state_path=hr_path,
        state_path=state_path,
        lock_path=workdir / "replay.lock",
        event_dir=workdir / "events",
        fills_dir=workdir / "fills",
        log_path=workdir / "replay.log",
        approval_path=workdir / "never_approved.flag",
        off_flag_path=workdir / "never_off.flag",
        manual_buy_block_path=workdir / "never_block.flag",
    )
    config, applied = _apply_saved_config(config, record.get("config") or {})

    engine = Strategy06Engine(config, broker=_NoOrderBroker(), slots=_NoSlots())

    # ── 종목별 런타임 상태 복원 ────────────────────────────────────────────
    engine.names[code] = record.get("name") or code
    engine.state = json.loads(json.dumps(saved_state, ensure_ascii=False))

    engine.flows[code].clear()
    for row in record.get("flows") or []:
        engine.flows[code].append(tuple(row))

    window = VolumeWindow()
    for observed_at, cum_vol in record.get("volumes") or []:
        window.rows.append((datetime.fromisoformat(str(observed_at)), float(cum_vol)))
    engine.volumes[code] = window

    # 시계 정렬: 저장 시점과 재생 시점의 차이만큼 평행이동
    offset = time.time() - float(record.get("wall_epoch") or time.time())
    engine._entry_wait_epoch[code] = float(
        record.get("entry_wait_epoch") or 0.0) + offset
    engine._observe_log_epoch[code] = float(
        record.get("observe_log_epoch") or 0.0) + offset
    direct_before = record.get("direct_confirm_before")
    if isinstance(direct_before, list) and len(direct_before) == 3:
        last_ts = direct_before[1]
        if isinstance(last_ts, str) and last_ts:
            last_ts = datetime.fromisoformat(last_ts)
        engine._direct_confirm = {
            code: (int(direct_before[0]), last_ts, bool(direct_before[2]))
        }

    # 스냅샷 캐시를 비워 임시 파일을 실제로 읽게 한다
    engine._snapshot_cache = (0.0, {})
    engine._hr_cache = (0.0, {})

    # ── 실제 판정 메서드 호출 ──────────────────────────────────────────────
    error = ""
    try:
        engine._chase_tick(code, now)
    except Exception as exc:  # 재생 중 예외도 결과의 일부다
        error = "%s: %s" % (type(exc).__name__, exc)

    produced = _state_for_tick(engine, code)
    expected = record.get("state_after")
    if not isinstance(expected, dict):
        raise ValueError("record is missing full state_after")

    diffs = []
    for key in sorted(set(expected) | set(produced)):
        want, got = expected.get(key), produced.get(key)
        if isinstance(want, float) or isinstance(got, float):
            try:
                if abs(float(want or 0) - float(got or 0)) <= 1e-9:
                    continue
            except (TypeError, ValueError):
                pass
        if want != got:
            diffs.append({"field": key, "expected": want, "produced": got})

    produced_flows = _plain(list(engine.flows.get(code, [])))
    expected_flows = record.get("flows_after") or []
    if produced_flows != expected_flows:
        diffs.append({
            "field": "runtime.flows",
            "expected": expected_flows,
            "produced": produced_flows,
        })
    produced_volumes = _plain(list(getattr(engine.volumes.get(code), "rows", [])))
    expected_volumes = record.get("volumes_after") or []
    if produced_volumes != expected_volumes:
        diffs.append({
            "field": "runtime.volumes",
            "expected": expected_volumes,
            "produced": produced_volumes,
        })
    produced_direct = _plain(
        getattr(engine, "_direct_confirm", {}).get(code))
    expected_direct = record.get("direct_confirm_after")
    if produced_direct != expected_direct:
        diffs.append({
            "field": "runtime.direct_confirm",
            "expected": expected_direct,
            "produced": produced_direct,
        })

    # 로그 파일 핸들을 놓아준다 — 안 놓으면 임시 폴더 정리가 Windows 에서 막힌다.
    for handler in list(getattr(engine.log, "handlers", [])):
        try:
            handler.close()
            engine.log.removeHandler(handler)
        except Exception:
            pass

    return {
        "code": code,
        "now_iso": record.get("now_iso"),
        "match": not diffs and not error,
        "diffs": diffs,
        "error": error,
        "config_overrides": applied,
        "phase_expected": ((expected.get("chase") or {}).get(code) or {}).get("phase"),
        "phase_produced": ((produced.get("chase") or {}).get(code) or {}).get("phase"),
        "entry_decision": bool(record.get("entry_decision")),
    }


def load_records(path: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit and len(rows) >= limit:
                break
    return rows


def pick_file(args) -> Optional[Path]:
    if args.file:
        path = Path(args.file)
        return path if path.exists() else None
    if args.date:
        path = RECORD_DIR / ("s06_exact_input_%s.jsonl" % args.date)
        return path if path.exists() else None
    if not RECORD_DIR.exists():
        return None
    found = sorted(RECORD_DIR.glob("s06_exact_input_*.jsonl"))
    return found[-1] if found else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--file")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    path = pick_file(args)
    if path is None:
        print("%s BLOCKED reason=NO_SAVED_INPUT dir=%s" % (UNVERIFIED, RECORD_DIR))
        print("  capture-only 기동이 한 번도 입력을 남기지 않았다. 재생할 소재가 없다.")
        return 3

    records = load_records(path, args.limit or None)
    if not records:
        print("%s BLOCKED reason=EMPTY_INPUT file=%s" % (UNVERIFIED, path))
        return 3
    invalid_schema = [
        row for row in records if row.get("schema") != EXPECTED_SCHEMA
    ]
    if invalid_schema:
        print("%s BLOCKED reason=INCOMPLETE_SCHEMA file=%s expected=%s invalid=%d"
              % (UNVERIFIED, path, EXPECTED_SCHEMA, len(invalid_schema)))
        return 3

    results = []
    with tempfile.TemporaryDirectory(
            prefix="s06_replay_", ignore_cleanup_errors=True) as tmp:
        for index, record in enumerate(records):
            workdir = Path(tmp) / ("t%05d" % index)
            workdir.mkdir(parents=True, exist_ok=True)
            try:
                results.append(replay_one(record, workdir))
            except Exception as exc:
                results.append({
                    "code": record.get("code"),
                    "now_iso": record.get("now_iso"),
                    "match": False,
                    "diffs": [],
                    "error": "REPLAY_HARNESS: %s: %s" % (type(exc).__name__, exc),
                })

    matched = sum(1 for r in results if r["match"])
    total = len(results)
    decision_cases = sum(1 for r in results if r.get("entry_decision"))
    if matched != total:
        status = "FAIL"
        label = PROVENANCE
        exit_code = 1
    elif decision_cases < 1:
        status = "BLOCKED"
        label = UNVERIFIED
        exit_code = 3
    else:
        status = "PASS"
        label = PROVENANCE
        exit_code = 0

    engine_path = RUN_DIR / "strategy_06_crash_low_chase_v1.py"
    replay_path = Path(__file__).resolve()
    print("%s %s file=%s" % (label, status, path.name))
    print("  entry_point=Strategy06Engine._chase_tick  (실제 메서드 직접 호출)")
    print("  대조 %d/%d 일치, 불일치 %d건, 진입판정 %d건"
          % (matched, total, total - matched, decision_cases))
    print("  source_data=%s" % path)
    print("  source_sha256=%s" % _sha256(path))
    print("  engine_sha256=%s" % _sha256(engine_path))
    print("  replay_sha256=%s" % _sha256(replay_path))
    print("  command=%s" % shlex.join([sys.executable, str(replay_path)] + sys.argv[1:]))
    if status == "BLOCKED":
        print("  reason=NO_ENTRY_DECISION_CASE")

    for result in results:
        if result["match"]:
            continue
        print("  ── 불일치 code=%s ts=%s" % (result["code"], result["now_iso"]))
        if result.get("error"):
            print("     오류: %s" % result["error"])
        for diff in result.get("diffs") or []:
            print("     %s: 저장=%r 재생=%r"
                  % (diff["field"], diff["expected"], diff["produced"]))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
