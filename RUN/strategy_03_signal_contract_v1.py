# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 신호 계약. 주문과 브로커 호출은 없다."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time as time_module
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping

STRATEGY_NUMBER = "03"
STRATEGY_ID = "S03_VALLEY_RAPID_REBOUND"
STRATEGY_NAME = "골짜기 급반등"
SIGNAL_SCHEMA = "strategy_03_valley_rapid_rebound_signal_v1"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"
OPEN_CRASH_LANE = "OPEN_CRASH"
INTRADAY_CRASH_LANE = "INTRADAY_CRASH"
EARLY_LOW_LANE = "EARLY_LOW"
OPEN_CRASH_ALGORITHM = "S06_STAIRCASE_RETEST_V1"
INTRADAY_CRASH_ALGORITHM = "S03_INTRADAY_CRASH_REBOUND_V1"
EARLY_LOW_ALGORITHM = "S03_EARLY_60S_REBOUND_V1"
ALGORITHM = OPEN_CRASH_ALGORITHM
OPEN_ARM_DROP_PCT = -4.0
OPEN_HANDOFF_DROP_PCT = -8.0
# ★[S03-EXPRESS 2026-08-06 친구님 지시 "-7% 이하로 해 / 배선해"] 급행 매수 경로 상수.
#   깊은 급락(당일 고점 대비 -7%↓)에서 '매도 감속 + 매수 가속 + 매수 우위'(flow_accel)가
#   나오면 눌림·2차반등을 기다리지 않고 즉시 산다 — 3번의 정체(급락 후 급반등 즉시 타기).
#   근거: 8/6 닷새 캡처 전수 — 얕은 구간(-6~-8%)은 -0.90%, -8%↓ +0.74%, -10%↓ +1.67%.
#   친구님이 -6(지시값)과 -8(실측값) 사이 -7 로 결정. 매수창은 09:02~09:20(레인 그대로),
#   강제청산은 09:50 → 10:30(친구님 지시). 흘러내리는 날 대조(049080)는 급락속도 관문이 거른다.
EXPRESS_DEPTH_PCT = -7.0        # 당일 고점 대비 이만큼 깊어야 급행 자격
EXPRESS_FAST_WINDOW_SEC = 600.0  # 직전 10분 안에
EXPRESS_FAST_DROP_PCT = -3.0     # -3% 이상 빠진 '빠른 낙하' 직후여야 함(흘러내림 배제)
EXPRESS_NEAR_LOW_PCT = 1.5       # 저점 +1.5% 안에서만(멀어지면 이미 늦음)
OPEN_MIN_REBOUND_PCT = 1.0
# ★[2026-08-06 친구님 지시 "두번째 저점도 -5% 이하 아니니 / 셋 다 고쳐"] 1.5 -> 5.0.
#   1.5 는 너무 얕았다 - 8/6 코스텍시스가 -2.008% 에서 신호가 났다.
#   같은 날 '장중 고점'을 10분 창 최대값에서 당일 고점으로 바꿨으므로(낙폭이 실제대로
#   깊게 잡힌다) 문턱을 함께 올려야 뜻이 맞는다. 두 변경은 짝이다.
#   비교: 1번 레인(OPEN_CRASH)은 시가 대비 감시 -4.0% / 인계 -8.0%.
#   되돌리기: backup\s03_fix_20260806\ 의 파일 복원(고점 변경과 같이 되돌릴 것).
INTRADAY_MIN_DRAWDOWN_PCT = 5.0
INTRADAY_MIN_REBOUND_PCT = 1.0
INTRADAY_MAX_REBOUND_PCT = 1.5
# ★[SPEED-GATE 2026-08-03 친구님 지시] 매수 허용 상한 2.0 -> 1.5.
#   저점 +1.0~+1.5% 구간이 곧 감시창이다. 시간(60초) 대신 이 가격 구간 안에서
#   저점 후 매수속도가 매도속도를 넘는지로 판단한다.
#   S06 은 자기 상수(S06_CHASE_CAP_PCT=2.0)를 써서 이 변경에 영향받지 않는다.
#   소비 3곳 모두 S03 전용: 골짜기_급반등.py:86 / 이 파일 71줄 / strategy_03_rotation_engine_v1.py:126
#   롤백: 2.0 으로 되돌리고 신호기·매매엔진 재기동
OPEN_MAX_REBOUND_PCT = 1.5
# ★[SPEED-GATE 2026-08-03 친구님 지시] 1차 반등 문턱 1.5 -> 1.0.
#   매수구간을 저점 +1.0~+1.5% 로 좁히면서도 계단 재테스트 4단계를 전부 살리기 위한 값이다.
#   저점 100 기준: 1차반등 101.0 -> 눌림 100.6(더높은저점 100.3 초과) -> 2차반등 101.1
#   -> 매수구간 101.0~101.5 안에 들어온다. 4단계 중 하나도 버리지 않았다.
#   ⚠️이 값을 1.5 로 되돌리면 매수 상한 1.5 와 충돌해 검증기가 기동을 거부한다
#     ("chase cap must exceed first rebound"). 상한과 함께 되돌릴 것.
FIRST_REBOUND_PCT = 1.0
# ★[SPEED-GATE 2026-08-03 친구님 지시] 60.0 -> 0.0.
#   신호기(골짜기_급반등)에서 시간 관찰을 걷어내고 저점 후 매수속도 우위로 바꿨는데
#   이 계약 검사가 60초를 계속 요구하면, 신호가 나가도 매매엔진이 전부 걸러낸다
#   (테스트가 이 구멍을 잡아냈다 — 안 고쳤으면 3번은 내일도 0건이었다).
#   observe_sec 은 계속 기록된다. 문턱만 없앤다.
#   되돌릴 때는 신호기의 시간 관찰과 함께 되돌릴 것.
MIN_OBSERVE_SEC = 0.0
MIN_PULLBACK_PCT = 0.4
MIN_HIGHER_LOW_PCT = 0.3
MIN_SECOND_REBOUND_PCT = 0.5
EARLY_LOW_CAPTURE_START = time(9, 0, 0)
# ★[CAPTURE-WINDOW-0910 2026-08-19 친구님 승인 "확장 승인"] 저점 포착 창 60초 → 10분.
#   09:00~09:10 동안 신저점을 계속 갱신하며, 저점 +1.0~+2.0%와 매수속도 우위가
#   함께 확인되면 창 종료를 기다리지 않고 신호를 낸다. 신저점이면 수급창도 다시 시작한다.
#   알고리즘 이름과 EARLY_LOW_60S_* 사유는 감사·계약 대조용 역사적 명칭이라 유지한다.
#   실전 스위치와 주문 수량·매도 조건은 이 계약 변경에서 건드리지 않는다.
#   되돌리기: 창 확장만 되돌리려면 위 8/19 백업, 상한까지 되돌리려면
#             backup\strategy_03_signal_contract_v1_20260823_before_cap_2p0.py
EARLY_LOW_CAPTURE_END = time(9, 10, 0)
EARLY_LOW_MIN_REBOUND_PCT = 1.0
# ★[CAP-2P0 2026-08-23 친구님 승인 "B로 하라"] 상한 1.5 → 2.0 복귀.
#   상한을 넘으면 CHASE_LIMIT로 차단되며, chase_blocked는 09:00~09:10 안에
#   새 당일저가가 나올 때만 해제된다.
#   condition_id는 S03_EARLY_LOW_0900_0910_NEW_LOW_RESET_REBOUND_1P0_2P0_FLOW_TURN으로
#   동기화돼 있다. 이 값을 다시 바꾸면 release_states도 함께 바꿔야 승격이 성립한다.
#   되돌리기: backup\strategy_03_signal_contract_v1_20260823_before_cap_2p0.py
#             + s03_early_low_release_v1.py의 CONDITION_ID
#             + config\live_approved_hashes_v1.json의 release_states
EARLY_LOW_MAX_REBOUND_PCT = 2.0

# ★[EARLY-LOW-AUDIT 2026-08-12 친구님 승인 "영구 실전 연결"] 장초 레인 생산 감사.
#   실전 활성화(S03_EARLY_LOW_LIVE=YES)는 이 감사 기록을 실제 생산 코드로 재생해
#   통과한 뒤에만 허용한다(재생기: RUN\s03_early_low_prod_replay_v1.py).
#   신호기(골짜기_급반등)와 매매엔진(strategy_03_rotation_engine_v1)이 각자의 파일에
#   기록한다 — 두 프로세스가 한 파일을 쓰면 해시 사슬이 끊어진다.
EARLY_LOW_AUDIT_SCHEMA = "s03_early_low_audit_v1"
EARLY_LOW_AUDIT_DEFAULT_DIR = r"C:\stock_bot\data\audit\s03_early_low"


def early_low_audit_dir() -> Path:
    return Path(os.environ.get(
        "S03_EARLY_LOW_AUDIT_DIR", EARLY_LOW_AUDIT_DEFAULT_DIR))


def production_file_sha256(paths: Iterable[Path]) -> dict[str, str]:
    """의사결정에 쓰인 생산 파일의 SHA-256. 읽기 실패는 값 대신 사유를 남긴다."""
    output: dict[str, str] = {}
    for path in paths:
        path = Path(path)
        try:
            output[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            output[path.name] = f"UNREADABLE:{exc.__class__.__name__}"
    return output


class EarlyLowAuditChain:
    """append 전용 JSONL + 해시 사슬. 검증은 verify_file 로 한다.

    사슬 규칙: record_hash = sha256(정규화 JSON(레코드 - record_hash)).
    정규화 = sort_keys + ensure_ascii + 공백 없는 구분자. prev_hash 는 직전
    레코드의 record_hash(첫 레코드는 "GENESIS"). 프로세스 재시작 시 기존 파일의
    마지막 정상 레코드에 이어붙인다 — 중간에 손상 줄이 있으면 그대로 남겨
    verify_file 이 잡아내게 한다(몰래 잇지 않는다).
    """

    def __init__(self, stream: str, day: str, *, directory: Path | None = None) -> None:
        directory = Path(directory) if directory else early_low_audit_dir()
        self.path = directory / f"s03_early_low_{stream}_{day}.jsonl"
        self.stream = stream
        self.day = day
        self._seq = 0
        self._prev_hash = "GENESIS"
        try:
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        self._seq = int(record["seq"])
                        self._prev_hash = str(record["record_hash"])
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass

    @staticmethod
    def canonical(record: Mapping[str, Any]) -> bytes:
        body = {k: v for k, v in record.items() if k != "record_hash"}
        return json.dumps(
            body, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("ascii")

    def append(self, record: Mapping[str, Any]) -> dict[str, Any] | None:
        """기록 실패는 신호·주문 흐름을 죽이지 않는다(stderr 보고 후 계속)."""
        row = dict(record)
        row["schema"] = EARLY_LOW_AUDIT_SCHEMA
        row["stream"] = self.stream
        row["trade_day"] = self.day
        row["seq"] = self._seq + 1
        row["prev_hash"] = self._prev_hash
        row["record_hash"] = hashlib.sha256(self.canonical(row)).hexdigest()
        # ★[2026-08-12 보안수리 3번 보강] '증거 있는 주문'을 위해 세 가지를 지킨다:
        #   ① binary append + os.fsync 로 디스크에 확정된 뒤에만 성공을 반환한다
        #      (flush 만으로는 OS 버퍼까지라 크래시 시 증거가 유실될 수 있다).
        #   ② 쓰기가 도중에 실패하면, 이번 시도로 늘어난 부분 바이트를 원래 크기로
        #      truncate 해 되돌린다(부분 줄이 남아 사슬이 손상된 채 다음 줄이 붙는
        #      것을 막는다 — 종전엔 롤백이 없어 손상 사슬 위에 주문이 허용됐다).
        #   ③ 순간 파일잠금(WinError 5) 대비 최초 1회 + 0.1초 간격 3회 재시도.
        #   끝까지 실패하면 None → 호출부(selector)가 그 신호의 실주문을 보류한다.
        line = (json.dumps(row, ensure_ascii=True) + "\n").encode("ascii")
        last_exc: OSError | None = None
        for attempt in range(4):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                start = self.path.stat().st_size if self.path.exists() else 0
            except OSError as exc:
                last_exc = exc
                if attempt < 3:
                    time_module.sleep(0.1)
                continue
            try:
                with self.path.open("ab") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._seq = row["seq"]
                self._prev_hash = row["record_hash"]
                return row
            except OSError as exc:
                last_exc = exc
                self._rollback_partial(start)
                if attempt < 3:
                    time_module.sleep(0.1)
        print(
            f"S03_EARLY_LOW_AUDIT_WRITE_FAILED path={self.path} error={last_exc}",
            file=sys.stderr, flush=True,
        )
        return None

    def _rollback_partial(self, size: int) -> None:
        """이번 append 시도로 파일이 size 보다 커졌으면 그 부분을 잘라 되돌린다."""
        try:
            if self.path.exists() and self.path.stat().st_size > size:
                with self.path.open("r+b") as handle:
                    handle.truncate(size)
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError:
            pass

    @staticmethod
    def verify_file(path: Path) -> tuple[bool, str, list[dict[str, Any]]]:
        """(정상여부, 사유, 레코드들). 줄 손상·순번 단절·해시 불일치 전부 실패."""
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return False, f"UNREADABLE:{exc.__class__.__name__}", []
        records: list[dict[str, Any]] = []
        prev_hash = "GENESIS"
        for index, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                return False, f"BLANK_LINE:{index}", records
            try:
                record = json.loads(line)
            except ValueError:
                return False, f"CORRUPT_LINE:{index}", records
            if not isinstance(record, dict):
                return False, f"NOT_OBJECT:{index}", records
            expected = hashlib.sha256(
                EarlyLowAuditChain.canonical(record)).hexdigest()
            if str(record.get("record_hash")) != expected:
                return False, f"HASH_MISMATCH:seq={record.get('seq')}", records
            if str(record.get("prev_hash")) != prev_hash:
                return False, f"CHAIN_BROKEN:seq={record.get('seq')}", records
            if int(record.get("seq") or 0) != len(records) + 1:
                return False, f"SEQ_GAP:seq={record.get('seq')}", records
            prev_hash = str(record["record_hash"])
            records.append(record)
        return True, "OK", records


def _parse_local(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _fresh(ts: datetime | None, now: datetime, max_age_sec: float) -> bool:
    if ts is None:
        return False
    age = (now - ts).total_seconds()
    return -2.0 <= age <= max_age_sec


def _signal_id(day: str, row: Mapping[str, Any]) -> str:
    base = (
        f"{day}:{str(row.get('code') or '').zfill(6)}:"
        f"{int(float(row.get('signal_sequence') or 0))}:"
        f"{row.get('anchor_id')}:{row.get('ts')}"
    )
    lane = str(row.get("entry_lane") or OPEN_CRASH_LANE)
    return base if lane == OPEN_CRASH_LANE else f"{base}:{lane}"


def _lane_valid(raw: Mapping[str, Any], ts: datetime) -> bool:
    lane = str(raw.get("entry_lane") or OPEN_CRASH_LANE)
    algorithm = str(raw.get("algorithm") or "")
    if lane not in {EARLY_LOW_LANE, OPEN_CRASH_LANE, INTRADAY_CRASH_LANE}:
        return False
    if lane == EARLY_LOW_LANE:
        in_window = EARLY_LOW_CAPTURE_START <= ts.time() < time(14, 30)
    elif lane == OPEN_CRASH_LANE:
        in_window = time(9, 2) <= ts.time() < time(9, 20)
    else:
        in_window = time(9, 20) <= ts.time() < time(14, 30)
    rebound = float(raw.get("rebound_pct") or 0)
    if lane == EARLY_LOW_LANE:
        anchor_low = float(raw.get("anchor_low") or 0)
        anchor_ts = _parse_local(raw.get("anchor_low_ts"))
        return (
            algorithm == EARLY_LOW_ALGORITHM
            and in_window
            and anchor_low > 0
            and anchor_ts is not None
            and EARLY_LOW_CAPTURE_START
            <= anchor_ts.time() <= EARLY_LOW_CAPTURE_END
            and EARLY_LOW_MIN_REBOUND_PCT
            <= rebound <= EARLY_LOW_MAX_REBOUND_PCT
            and bool(raw.get("flow_turn_ready"))
            and float(raw.get("flow_recent_buy_rate") or 0.0)
            > float(raw.get("flow_recent_sell_rate") or 0.0)
            and bool(raw.get("flow_price_responding"))
        )
    if lane == INTRADAY_CRASH_LANE:
        intraday_high = float(raw.get("intraday_high") or 0)
        anchor_low = float(raw.get("anchor_low") or 0)
        drawdown = float(raw.get("intraday_drawdown_pct") or 0)
        return (
            algorithm == INTRADAY_CRASH_ALGORITHM
            and in_window
            and intraday_high > anchor_low > 0
            and drawdown <= -INTRADAY_MIN_DRAWDOWN_PCT
            and INTRADAY_MIN_REBOUND_PCT
            <= rebound <= INTRADAY_MAX_REBOUND_PCT
        )

    open_price = float(raw.get("open_price") or 0)
    drop_from_open = float(raw.get("drop_from_open_pct") or 0)
    # ★[S03-EXPRESS 2026-08-06] 급행 신호는 제 잣대로 검산한다 — 4단계 잣대(눌림·2차반등·
    #   반등 1.0~1.5%)를 들이대면 급행이 전부 버려진다(급행은 저점 +0~1.5% 어디서든 산다).
    if str(raw.get("reason") or "").startswith("S03_EXPRESS"):
        return (
            algorithm == OPEN_CRASH_ALGORITHM
            and in_window
            and open_price > 0
            and float(raw.get("express_depth_pct") or 0) <= EXPRESS_DEPTH_PCT
            and 0.0 <= rebound <= EXPRESS_NEAR_LOW_PCT
        )
    return (
        algorithm == OPEN_CRASH_ALGORITHM
        and in_window
        and open_price > 0
        and OPEN_HANDOFF_DROP_PCT < drop_from_open <= OPEN_ARM_DROP_PCT
        and OPEN_MIN_REBOUND_PCT <= rebound <= OPEN_MAX_REBOUND_PCT
        and float(raw.get("first_rebound_pct") or 0) >= FIRST_REBOUND_PCT
        and float(raw.get("observe_sec") or 0) >= MIN_OBSERVE_SEC
        and float(raw.get("pullback_depth_pct") or 0) >= MIN_PULLBACK_PCT
        and float(raw.get("higher_low_pct") or 0) >= MIN_HIGHER_LOW_PCT
        and float(raw.get("second_rebound_pct") or 0) >= MIN_SECOND_REBOUND_PCT
        # 저점 뒤 매수속도가 매도속도를 넘은 신호만 주문엔진으로 넘긴다.
        and float(raw.get("post_buy_rate") or 0)
        > float(raw.get("post_sell_rate") or 0)
    )


def select_fresh_signals(
    payload: Mapping[str, Any],
    *,
    now: datetime,
    max_age_sec: float,
    consumed: Iterable[str] = (),
) -> list[dict[str, Any]]:
    local_now = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    day = local_now.strftime("%Y%m%d")
    if str(payload.get("schema") or "") != SIGNAL_SCHEMA:
        return []
    if str(payload.get("mode") or "") != SIGNAL_MODE:
        return []
    if str(payload.get("date") or "") != day:
        return []
    if not _fresh(_parse_local(payload.get("updated_at")), local_now, max_age_sec):
        return []

    used = set(consumed)
    selected = []
    seen_codes: set[str] = set()
    for raw in payload.get("signals") or []:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").zfill(6)
        if len(code) != 6 or not code.isdigit() or code in seen_codes:
            continue
        if str(raw.get("action") or "") != "BUY_READY":
            continue
        if str(raw.get("mode") or "") != SIGNAL_MODE:
            continue
        if int(float(raw.get("signal_sequence") or 0)) not in {1, 2}:
            continue
        signal_ts = _parse_local(raw.get("ts"))
        if (
            not _fresh(signal_ts, local_now, max_age_sec)
            or signal_ts is None
            or not _lane_valid(raw, signal_ts)
        ):
            continue
        signal_id = _signal_id(day, raw)
        if signal_id in used:
            continue
        row = dict(raw)
        row.update({
            "code": code,
            "entry_lane": str(raw.get("entry_lane") or OPEN_CRASH_LANE),
            "signal_id": signal_id,
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
        })
        selected.append(row)
        seen_codes.add(code)
    selected.sort(
        key=lambda row: (
            int(float(row.get("listed_turnover_bonus") or 0)),
            float(row.get("recent_buy_rate_10s") or 0)
            - float(row.get("recent_sell_rate_10s") or 0),
            float(row.get("higher_low_pct") or 0),
            -float(row.get("rebound_pct") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected
