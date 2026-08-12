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
INTRADAY_MIN_REBOUND_PCT = 0.5
INTRADAY_MAX_REBOUND_PCT = 1.0
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
EARLY_LOW_CAPTURE_END = time(9, 1, 0)
EARLY_LOW_MIN_REBOUND_PCT = 1.0
EARLY_LOW_MAX_REBOUND_PCT = 2.0


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
        in_window = EARLY_LOW_CAPTURE_END < ts.time() < time(14, 30)
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
            float(row.get("recent_buy_rate_10s") or 0)
            - float(row.get("recent_sell_rate_10s") or 0),
            float(row.get("higher_low_pct") or 0),
            -float(row.get("rebound_pct") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected
