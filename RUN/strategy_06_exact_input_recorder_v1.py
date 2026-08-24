"""S06 생산경로 exact-input recorder — 판정 직전 입력을 누락 없이 저장한다.

[2026-08-20 친구님 지시] "S06 생산경로의 실제 입력값을 누락 없이 저장하는
exact-input recorder와 1회 재생기를 먼저 만들어라."

저장 대상은 `Strategy06Engine._chase_tick(code, now)` 이 소비하는 입력 전부다.
그 메서드가 읽는 것을 코드에서 전수 확인해 아래로 확정했다:

  ① state["chase"][code]            → ChaseState.from_dict 의 원본
  ② snapshot_path 의 codes[code]    → _snapshot_point / day_anchor 가 읽는 원본 raw
  ③ hr_state_path 의 codes[code]    → _hr_row / day_anchor 가 읽는 원본 raw
  ④ self.flows[code]                → (epoch, 매수누적, 매도누적) 이력
  ⑤ self.volumes[code].rows         → (관측시각, 누적체결량) 이력
  ⑥ self._entry_wait_epoch[code]    → time.time() 기반 재시도 간격
  ⑦ self._observe_log_epoch[code]   → time.time() 기반 로그 간격
  ⑧ config 실효값 전부              → 문턱·경로
  ⑨ now, names[code], state["date"]

②③을 "계산 결과"가 아니라 **파일 원본 그대로** 저장하는 것이 핵심이다.
그래야 재생기가 _snapshot_point·_hr_row·day_anchor 의 실제 코드를 그대로 돌릴 수 있고,
프록시 계산이 끼어들지 않는다.

⚠️ ⑥⑦은 `time.time()` 절대값이라 재생 시각과 어긋난다. 그래서 저장 시점의
`wall_epoch` 도 함께 남긴다. 재생기가 이 값으로 시계를 정렬한다(재구성이 아니라 시계 보정).

설계 원칙:
  - **non-blocking**: 어떤 실패도 매매를 막지 않는다. 전 구간 예외 격리.
  - **실전 파일 무접촉**: 전용 폴더에만 쓴다.
  - 끄기: setx S06_EXACT_RECORD NO
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

SCHEMA = "s06_exact_input_v2"

OUT_DIR = Path(os.environ.get(
    "S06_EXACT_RECORD_DIR", r"C:\stock_bot\data\s06_exact_replay"))


def enabled() -> bool:
    # Live engines must never inherit per-tick disk I/O accidentally.  The
    # capture-only launcher opts in explicitly with S06_EXACT_RECORD=YES.
    return os.environ.get("S06_EXACT_RECORD", "NO").strip().upper() in {
        "YES", "Y", "1", "TRUE", "ON"}


def _plain(value: Any) -> Any:
    """JSON 으로 안전하게 떨어뜨린다. 실패해도 예외를 내지 않는다."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    return str(value)


def _config_snapshot(config: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for field in getattr(config, "__dataclass_fields__", {}):
        try:
            out[field] = _plain(getattr(config, field))
        except Exception:
            out[field] = "<unreadable>"
    return out


def _raw_from(payload: Any, code: str) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    codes = payload.get("codes")
    if not isinstance(codes, Mapping):
        return {}
    row = codes.get(str(code).zfill(6))
    return dict(row) if isinstance(row, Mapping) else {}


def _state_for_tick(engine: Any, code: str) -> Dict[str, Any]:
    """State fields actually consumed by _chase_tick/_try_entry."""
    state = engine.state
    chase = state.get("chase") or {}
    return _plain({
        "date": state.get("date"),
        "chase": {code: chase.get(code) or {}},
        "positions": state.get("positions") or {},
        "entered_codes": state.get("entered_codes") or [],
        "order_attempts_total": state.get("order_attempts_total") or 0,
        "recovery_blocked": bool(state.get("recovery_blocked")),
        "last_error": state.get("last_error") or "",
    })


def capture_before(engine: Any, code: str, now: datetime) -> Optional[Dict[str, Any]]:
    """_chase_tick 직전 입력 일체를 담아 돌려준다. 실패하면 None."""
    if not enabled():
        return None
    try:
        code6 = str(code).zfill(6)
        config = engine.config

        # 스냅샷·고저폭판은 엔진이 실제로 쓰는 캐시 경로를 그대로 통과시켜
        # 판정이 본 것과 동일한 원본을 잡는다.
        snapshot_payload = engine._snapshot()
        # _hr_row itself owns the one-second cache expiry rule.  Calling it
        # here guarantees that the row saved is the same cached payload that
        # the immediately following _chase_tick consumes.
        try:
            engine._hr_row(code6)
            hr_payload = engine._hr_cache[1]
        except Exception:
            hr_payload = {}

        volumes = []
        window = engine.volumes.get(code6) if hasattr(engine.volumes, "get") else None
        if window is not None:
            for observed_at, cum_vol in list(getattr(window, "rows", []) or []):
                volumes.append([_plain(observed_at), _plain(cum_vol)])

        return {
            "schema": SCHEMA,
            "captured_at": datetime.now().isoformat(timespec="microseconds"),
            "wall_epoch": time.time(),
            "code": code6,
            "name": engine.names.get(code6, code6),
            "now_iso": now.isoformat(),
            "state_date": str(engine.state.get("date") or ""),
            "state_before": _state_for_tick(engine, code6),
            "config": _config_snapshot(config),
            "runtime_flags": {
                "LOW_REBOUND_DIRECT": os.environ.get(
                    "LOW_REBOUND_DIRECT", "NO").strip().upper(),
            },
            "chase_before": _plain(
                (engine.state.get("chase") or {}).get(code6) or {}),
            "snapshot_rec": _plain(_raw_from(snapshot_payload, code6)),
            "hr_rec": _plain(_raw_from(hr_payload, code6)),
            "flows": [_plain(list(row)) for row in list(engine.flows.get(code6, []))]
            if hasattr(engine.flows, "get") else [],
            "volumes": volumes,
            "entry_wait_epoch": float(engine._entry_wait_epoch.get(code6, 0.0)),
            "observe_log_epoch": float(engine._observe_log_epoch.get(code6, 0.0)),
            "direct_confirm_before": _plain(
                getattr(engine, "_direct_confirm", {}).get(code6)),
        }
    except Exception:
        return None


def capture_after(
    engine: Any,
    code: str,
    pending: Optional[Dict[str, Any]],
    error: str = "",
) -> None:
    """_chase_tick 직후 결과를 붙여 JSONL 로 떨군다. 실패해도 조용히 넘어간다."""
    if not pending:
        return
    try:
        code6 = str(code).zfill(6)
        pending["chase_after"] = _plain(
            (engine.state.get("chase") or {}).get(code6) or {})
        positions = engine.state.get("positions") or {}
        pending["positions_after"] = _plain({
            key: value for key, value in positions.items()
            if str(value.get("code") or "").zfill(6) == code6
        })
        pending["state_after"] = _state_for_tick(engine, code6)
        pending["flows_after"] = [
            _plain(list(row)) for row in list(engine.flows.get(code6, []))
        ] if hasattr(engine.flows, "get") else []
        window = engine.volumes.get(code6) if hasattr(engine.volumes, "get") else None
        pending["volumes_after"] = [
            [_plain(observed_at), _plain(cum_vol)]
            for observed_at, cum_vol in list(getattr(window, "rows", []) or [])
        ]
        pending["last_error_after"] = str(engine.state.get("last_error") or "")
        pending["decision_error"] = str(error or "")
        pending["direct_confirm_after"] = _plain(
            getattr(engine, "_direct_confirm", {}).get(code6))
        before_state = pending.get("state_before") or {}
        before_entered = list(before_state.get("entered_codes") or [])
        after_entered = list(engine.state.get("entered_codes") or [])
        before_positions = before_state.get("positions") or {}
        pending["entry_decision"] = (
            before_entered != after_entered
            or set(before_positions) != set(positions)
        )

        day = str(engine.state.get("date") or datetime.now().strftime("%Y%m%d"))
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / ("s06_exact_input_%s.jsonl" % day)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(pending, ensure_ascii=False, default=str))
            handle.write("\n")
    except Exception:
        return
