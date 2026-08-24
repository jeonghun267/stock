# -*- coding: utf-8 -*-
"""저점 직접반등(DIRECT_REBOUND) 공통 판정 — S02·S06 공용 단일 정책.

★[2026-08-13 친구님 지시 "눌림은 필수조건이 아니라 선택 경로다"]
  S02(계단)와 S06(급락추격)이 서로 복사된 저점 로직을 따로 들고 있어 같은
  차트에서 한쪽만 사는 문제의 해결. 이 모듈은 '판정 정책'만 갖는다:

  - DIRECT_REBOUND: 낙폭 충족 + 신저점 갱신 중단 + 첫 반등 문턱 회복 +
    수급 전환(저점 전 매도우위→저점 후 매수우위, 매수대금 가속, 매수 체결량
    우위, 매도 재강화 없음, 체결강도 상승) + 연속 확인 틱 → 눌림·60초 대기
    없이 진입 허용. 추격상한 초과는 항상 차단.
  - RETEST_REBOUND: 기존 첫 반등→눌림→높은 두 번째 저점→재반등 경로.
    각 전략의 기존 코드가 그대로 담당한다(여기서 재구현하지 않는다).

  전략별 낙폭·기준가격·시간대·문턱은 호출자(전략)가 config 로 넘긴다.
  수급 원시값 계산도 각 전략의 기존 함수를 그대로 쓰고, 여기는 그 결과를
  받아 '허용/차단과 사유'만 돌려준다 — 같은 정책이 두 곳에 복사되지 않게.

  fail-closed: 필요한 관측값이 없으면(None) 절대 통과로 치지 않고
  DATA_MISSING 사유로 차단한다.

  실전 게이트: 환경변수 LOW_REBOUND_DIRECT=YES 일 때만 allow 가 참이 된다.
  기본(미설정)은 판정·기록만 하고 주문은 내지 않는다(ready 로 구분).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

DIRECT_LANE = "DIRECT_REBOUND"
RETEST_LANE = "RETEST_REBOUND"

DIRECT_ENABLED = (
    os.environ.get("LOW_REBOUND_DIRECT", "NO").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)


@dataclass(frozen=True)
class DirectReboundConfig:
    """전략별로 유지되는 값들 — 낙폭 판정은 호출자가 끝내고 drop_ok 로 넘긴다."""
    first_rebound_pct: float          # 전략별 첫 반등 문턱 (S02 1.0 / S06 0.5)
    chase_cap_pct: float              # 전략별 추격상한 (둘 다 2.0)
    confirm_ticks: int = 2            # 연속 확인 틱 (기존 값 유지)
    confirm_max_gap_sec: float = 6.0  # 확인 틱 사이 최대 간격
    min_no_new_low_sec: float = 5.0   # 신저점 갱신 중단으로 인정할 최소 경과
    volume_turn_required: bool = True # S06 은 체결량 매수/매도 분리 원천이 없어 False


def judge_direct_rebound(
    *,
    confirm_hits: int,
    last_confirm_ts: Optional[datetime],
    cfg: DirectReboundConfig,
    ts: datetime,
    price: float,
    low_price: float,
    no_new_low_sec: Optional[float],
    drop_ok: bool,
    flow_flip: Optional[bool],
    flow_accel: Optional[bool],
    money_buy_turn: Optional[bool],
    volume_buy_turn: Optional[bool],
    sell_restrength: Optional[bool],
    che_rising: Optional[bool],
) -> Dict[str, Any]:
    """한 틱의 직접반등 판정. 상태(연속 확인)는 결과로 돌려주고 호출자가 저장한다."""
    fail: list[str] = []

    if low_price is None or low_price <= 0 or price is None or price <= 0:
        fail.append("DATA_MISSING:price_or_low")
        rebound_pct = 0.0
    else:
        rebound_pct = (price / low_price - 1.0) * 100.0

    # 정확한 경계값이 이진 부동소수점 오차로 탈락하지 않게 극소 허용치를 둔다.
    boundary_epsilon = 1e-9
    chase_cap_pass = rebound_pct <= cfg.chase_cap_pct + boundary_epsilon
    if not drop_ok:
        fail.append("DROP_NOT_MET")
    if no_new_low_sec is None:
        fail.append("DATA_MISSING:no_new_low_sec")
    elif no_new_low_sec < cfg.min_no_new_low_sec:
        fail.append("LOW_TOO_FRESH")
    if not fail and rebound_pct < cfg.first_rebound_pct - boundary_epsilon:
        fail.append("REBOUND_BELOW_FLOOR")
    if not chase_cap_pass:
        fail.append("ABOVE_CHASE_CAP")

    def _need(name: str, value: Optional[bool], want: bool = True) -> None:
        if value is None:
            fail.append(f"DATA_MISSING:{name}")
        elif value is not want:
            fail.append(f"{name.upper()}_{'ABSENT' if want else 'PRESENT'}")

    _need("flow_flip", flow_flip)
    _need("flow_accel", flow_accel)
    _need("money_buy_turn", money_buy_turn)
    if cfg.volume_turn_required:
        _need("volume_buy_turn", volume_buy_turn)
    _need("sell_restrength", sell_restrength, want=False)
    _need("che_rising", che_rising)

    passed = not fail
    if passed:
        if (
            last_confirm_ts is None
            or (ts - last_confirm_ts).total_seconds() > cfg.confirm_max_gap_sec
        ):
            new_hits = 1
        else:
            new_hits = confirm_hits + 1
        new_last = ts
        if new_hits < cfg.confirm_ticks:
            fail.append("CONFIRM_TICKS_PENDING")
    else:
        new_hits = 0
        new_last = None

    ready = passed and new_hits >= cfg.confirm_ticks
    return {
        "lane": DIRECT_LANE,
        "ready": ready,                      # 정책상 통과 (게이트 무관)
        "armed": DIRECT_ENABLED,             # 실전 게이트 상태
        "allow": ready and DIRECT_ENABLED,   # 실제 주문 허용
        "low_price": round(float(low_price or 0.0), 4),
        "rebound_pct": round(rebound_pct, 3),
        "no_new_low_sec": (
            round(float(no_new_low_sec), 1) if no_new_low_sec is not None else ""
        ),
        "flow_flip": "" if flow_flip is None else bool(flow_flip),
        "flow_accel": "" if flow_accel is None else bool(flow_accel),
        "money_buy_turn": "" if money_buy_turn is None else bool(money_buy_turn),
        "volume_buy_turn": "" if volume_buy_turn is None else bool(volume_buy_turn),
        "che_rising": "" if che_rising is None else bool(che_rising),
        "confirm_ticks": new_hits,
        "last_confirm_ts": new_last,
        "chase_cap_pass": chase_cap_pass,
        "fail": fail,
    }
