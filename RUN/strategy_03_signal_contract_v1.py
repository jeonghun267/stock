# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 신호 계약. 주문과 브로커 호출은 없다."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any, Iterable, Mapping

STRATEGY_NUMBER = "03"
STRATEGY_ID = "S03_VALLEY_RAPID_REBOUND"
STRATEGY_NAME = "골짜기 급반등"
SIGNAL_SCHEMA = "strategy_03_valley_rapid_rebound_signal_v1"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"
OPEN_CRASH_LANE = "OPEN_CRASH"
INTRADAY_CRASH_LANE = "INTRADAY_CRASH"
OPEN_CRASH_ALGORITHM = "S06_STAIRCASE_RETEST_V1"
INTRADAY_CRASH_ALGORITHM = OPEN_CRASH_ALGORITHM
ALGORITHM = OPEN_CRASH_ALGORITHM
OPEN_ARM_DROP_PCT = -4.0
OPEN_HANDOFF_DROP_PCT = -8.0
OPEN_MIN_REBOUND_PCT = 1.0
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
    if lane not in {OPEN_CRASH_LANE, INTRADAY_CRASH_LANE}:
        return False
    if lane == OPEN_CRASH_LANE:
        in_window = time(9, 2) <= ts.time() < time(9, 20)
    else:
        in_window = time(9, 20) <= ts.time() < time(14, 30)
    open_price = float(raw.get("open_price") or 0)
    drop_from_open = float(raw.get("drop_from_open_pct") or 0)
    rebound = float(raw.get("rebound_pct") or 0)
    return (
        algorithm == ALGORITHM
        and in_window
        and open_price > 0
        and OPEN_HANDOFF_DROP_PCT < drop_from_open <= OPEN_ARM_DROP_PCT
        and OPEN_MIN_REBOUND_PCT <= rebound <= OPEN_MAX_REBOUND_PCT
        and float(raw.get("first_rebound_pct") or 0) >= FIRST_REBOUND_PCT
        and float(raw.get("observe_sec") or 0) >= MIN_OBSERVE_SEC
        and float(raw.get("pullback_depth_pct") or 0) >= MIN_PULLBACK_PCT
        and float(raw.get("higher_low_pct") or 0) >= MIN_HIGHER_LOW_PCT
        and float(raw.get("second_rebound_pct") or 0) >= MIN_SECOND_REBOUND_PCT
        # ★[SPEED-GATE 2026-08-03 친구님 지시] flow_flip·flow_accel 강제 조건 제거.
        #   신호기에서 이 두 관문을 뺐는데 계약서가 그대로면 신호가 나가도 매매엔진이
        #   전부 걸러낸다(테스트가 잡아낸 두 번째 구멍). 둘 다 저점 '전' 자료나 10초
        #   구간 2개가 필요해 8/3 실전에서 99%가 빈 값이었고, 그 때문에 3번은 하루 종일
        #   0건이었다. 값은 계속 기록된다 — 문턱만 없앤다.
        #   판정 근거는 신호기가 이미 확인한 "저점 후 매수속도 > 매도속도"다.
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
            float(row.get("recent_buy_rate_10s") or 0)
            - float(row.get("recent_sell_rate_10s") or 0),
            float(row.get("higher_low_pct") or 0),
            -float(row.get("rebound_pct") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected
