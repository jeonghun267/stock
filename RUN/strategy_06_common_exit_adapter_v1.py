# -*- coding: utf-8 -*-
"""S06 전용 공통 매도엔진 어댑터 — 관측값 변환과 매도상태 보관만 한다.

[2026-08-25 친구님 지시] "S06 매도를 규칙 복사가 아니라 S02가 쓰는
strategy_common_hold_sell_v1.py 의 동일 엔진·동일 정책으로 연결하라."

이 파일이 하는 일은 셋뿐이다.
  ① S06 이 이미 읽고 있는 자료(스냅샷 원본·flows·3분봉)를 공통 엔진의
     HoldSellObservation 으로 **옮긴다**.
  ② 체결 시 HoldSellState 를 만들고, S06 상태파일 전용 칸에 저장·복구한다.
  ③ S06 감사기록을 S02 와 섞이지 않는 전략 폴더로 보낸다.

⚠️ 매도 판정식은 이 파일에 한 줄도 없다. 전부 UnifiedHoldSellEngine 이 한다.
   여기에 문턱값(-2%·트레일 폭 따위)을 새로 적는 순간 '규칙 복사'가 되어
   지시를 어긴다. 정책을 바꾸려면 공통 파일의 S06 프로필만 고칠 것.

⚠️ 매도상태를 state["hold_sell_states"] 라는 **최상위 칸**에 둔다.
   positions 안에 넣지 않는 이유 — S06 보존입력 재생기(s06_exact_replay_v1)가
   _chase_tick 전후의 positions 를 통째로 대조한다. 진입 경로 재생 결과를
   한 글자도 바꾸지 않으려고 매도 전용 칸을 따로 쓴다.

⚠️ 자료가 부족하면 값을 지어내지 않는다(None/0 으로 둔다). 공통 엔진은
   common_peak_flow_ready 가 거짓이면 꼭지매도를 판정하지 않는다 = fail-closed.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from hold_sell_audit_v1 import HoldSellAuditRecorder
from json_cache_v1 import read_json_cached
from ma3_common_v1 import (
    buy_side_alive as ma3_buy_side_alive,
    ma3_rows,
    ma5_broken as ma3_ma5_broken,
    rider_permit as ma3_rider_permit,
)
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profile_runtime_snapshot,
)


STRATEGY_ID = StrategyId.S06_CRASH_LOW_CHASE
HOLD_STATES_KEY = "hold_sell_states"
COMMON_ENGINE_PATH = Path(__file__).with_name("strategy_common_hold_sell_v1.py")
# 감사기록 뿌리는 공용이지만, 기록기가 <뿌리>/<날짜>/<전략>/ 로 갈라 쓴다.
# 그래서 S06 행이 S02 파일에 섞이지 않는다(hold_sell_audit_v1.HoldSellAuditRecorder._target).
AUDIT_ROOT = Path(r"C:\stock_bot\data\audit\hold_sell")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flow_rate(
    rows: Any,
    epoch_now: float,
    window_sec: float,
    *,
    min_span: float = 3.0,
) -> Optional[Tuple[float, float]]:
    """(매수 원/초, 매도 원/초). 자료가 모자라면 None — 0 으로 속이지 않는다.

    S06 이 이미 쓰는 self.flows((epoch, 매수누적, 매도누적)) 를 그대로 읽는다.
    창 길이·최소 관측폭은 S06 _morning_buy_side 의 것과 같다.
    """
    window = [row for row in rows if epoch_now - row[0] <= window_sec]
    if len(window) < 2:
        return None
    span = window[-1][0] - window[0][0]
    if span < min_span:
        return None
    return (
        max(0.0, window[-1][1] - window[0][1]) / span,
        max(0.0, window[-1][2] - window[0][2]) / span,
    )


class Strategy06CommonExitAdapter:
    """S06 엔진 옆에 붙어 관측값을 만들고 매도상태를 보관한다."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        # 체결량·체결강도 속도용 이력. 공용코어의 같은 이름 통로와 같은 모양이다.
        self._micro: Dict[str, deque] = defaultdict(lambda: deque(maxlen=80))

    # ── 매도상태 보관 ──────────────────────────────────────────────────
    @staticmethod
    def position_key(position: Mapping[str, Any]) -> str:
        """positions 딕셔너리 열쇠와 같은 규칙(code:entry_no)."""
        code = str(position.get("code") or "").zfill(6)
        return f"{code}:{int(position.get('entry_no') or 1)}"

    def _bucket(self) -> Dict[str, Any]:
        bucket = self.engine.state.get(HOLD_STATES_KEY)
        if not isinstance(bucket, dict):
            bucket = {}
            self.engine.state[HOLD_STATES_KEY] = bucket
        return bucket

    def save(self, position: Mapping[str, Any], hold_state: HoldSellState) -> None:
        self._bucket()[self.position_key(position)] = hold_state.to_dict()

    def drop(self, position: Mapping[str, Any]) -> None:
        self._bucket().pop(self.position_key(position), None)

    def prune(self, live_keys: Any) -> None:
        """장부에서 사라진 포지션의 매도상태를 같이 지운다."""
        bucket = self._bucket()
        for key in [key for key in bucket if key not in set(live_keys)]:
            bucket.pop(key, None)

    def load(self, position: Mapping[str, Any]) -> Optional[HoldSellState]:
        payload = self._bucket().get(self.position_key(position))
        if not isinstance(payload, Mapping):
            return None
        try:
            return HoldSellState.from_dict(payload)
        except Exception:
            # 손상된 매도상태는 버리고 아래 ensure 가 진입정보로 다시 만든다.
            return None

    def create(
        self,
        position: Mapping[str, Any],
        *,
        quantity: int,
        entry_price: float,
        entry_at: datetime,
        order_no: str = "",
    ) -> Optional[HoldSellState]:
        """체결 확정 시 매도상태를 만든다. 입력이 불완전하면 None(매도판정 보류)."""
        if int(quantity) <= 0 or _number(entry_price) <= 0:
            return None
        code = str(position.get("code") or "").zfill(6)
        day = str(self.engine.state.get("date") or "")
        entry_no = int(position.get("entry_no") or 1)
        hold_state = HoldSellState(
            position_id=(
                f"{self.engine.config.strategy_slug}:{day}:{code}:"
                f"e{entry_no}:{order_no or 'shadow'}"
            ),
            strategy_id=STRATEGY_ID,
            code=code,
            quantity=int(quantity),
            entry_price=Decimal(str(_number(entry_price))),
            entry_at=entry_at,
            entry_lane=str(position.get("entry_lane") or ""),
        )
        self.save(position, hold_state)
        return hold_state

    def ensure(self, position: Mapping[str, Any]) -> Optional[HoldSellState]:
        """복구 경로 — 매도상태가 없거나 수량이 어긋나면 장부 기준으로 맞춘다.

        왜 필요한가: 재기동·잔량 재배분(_startup_reconcile)·부분체결로 장부
        수량이 바뀔 수 있고, 이 배선 이전에 만들어진 보유 포지션에는 매도상태가
        아예 없다. 그 경우 진입정보(entry_price/entry_at/qty)로 다시 만든다.
        """
        quantity = int(position.get("qty") or 0)
        entry_price = _number(position.get("entry_price"))
        if quantity <= 0 or entry_price <= 0:
            return None
        hold_state = self.load(position)
        if hold_state is None:
            entry_at = position.get("entry_at")
            try:
                parsed = (
                    datetime.fromisoformat(str(entry_at)) if entry_at else None
                )
            except ValueError:
                parsed = None
            if parsed is None:
                return None
            hold_state = self.create(
                position,
                quantity=quantity,
                entry_price=entry_price,
                entry_at=parsed,
            )
            if hold_state is None:
                return None
            # 장부가 이미 알고 있는 고점을 넘겨준다(재기동으로 꼭지를 잊지 않게).
            peak = _number(position.get("peak_price"))
            if peak > float(hold_state.peak_price):
                hold_state.peak_price = Decimal(str(peak))
                self.save(position, hold_state)
            return hold_state
        if hold_state.quantity != quantity:
            hold_state.quantity = quantity
            self.save(position, hold_state)
        return hold_state

    # ── 관측값 변환 ────────────────────────────────────────────────────
    def _snapshot_raw(self, code: str) -> Mapping[str, Any]:
        """스냅샷 원본 행 — 엔진이 이미 읽은 캐시를 그대로 통과시킨다.

        S06 _snapshot_point 는 체결강도·체결량 누적을 싣지 않는다. 그 값을 쓰려고
        _snapshot_point 를 고치면 진입 경로를 건드리게 되므로, 여기서 같은 캐시를
        직접 읽는다(파일 재읽기 없음).
        """
        raw = (self.engine._snapshot().get("codes") or {}).get(code)
        return raw if isinstance(raw, Mapping) else {}

    def _micro_rates(
        self, code: str, observed_at: datetime, raw: Mapping[str, Any],
    ) -> Tuple[float, float, float, float, float]:
        """체결량 5초 속도·직전 10초 속도·체결강도와 그 5초 변화.

        공용코어(Strategy01Engine._common_exit_micro_rates)가 S02 에 넣어 주는
        값과 같은 통로다. 값이 하나라도 준비되지 않으면 전부 0 으로 돌려
        공통 엔진이 그 항목을 근거로 쓰지 않게 한다.
        """
        rows = self._micro[code]
        current = (
            observed_at,
            _number(raw.get("buy_vol_cum"), -1.0),
            _number(raw.get("sell_vol_cum"), -1.0),
            _number(raw.get("che_str")),
        )
        if min(current[1], current[2]) < 0 or current[3] <= 0:
            rows.clear()
            return 0.0, 0.0, 0.0, 0.0, 0.0
        if rows and (
            current[0] <= rows[-1][0]
            or current[1] < rows[-1][1]
            or current[2] < rows[-1][2]
        ):
            rows.clear()
        rows.append(current)
        while rows and (current[0] - rows[0][0]).total_seconds() > 20:
            rows.popleft()

        def at_or_before(target: datetime):
            for item in reversed(rows):
                if item[0] <= target:
                    return item
            return None

        recent_target = current[0] - timedelta(seconds=5)
        previous_target = current[0] - timedelta(seconds=15)
        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        if recent_start is None or previous_start is None:
            return 0.0, 0.0, 0.0, current[3], 0.0
        if (
            (recent_target - recent_start[0]).total_seconds() > 2
            or (previous_target - previous_start[0]).total_seconds() > 3
        ):
            return 0.0, 0.0, 0.0, current[3], 0.0
        recent_span = (current[0] - recent_start[0]).total_seconds()
        previous_span = (recent_start[0] - previous_start[0]).total_seconds()
        deltas = (
            current[1] - recent_start[1],
            current[2] - recent_start[2],
            recent_start[2] - previous_start[2],
        )
        if recent_span <= 0 or previous_span <= 0 or min(deltas) < 0:
            return 0.0, 0.0, 0.0, current[3], 0.0
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / previous_span,
            current[3],
            current[3] - recent_start[3],
        )

    @staticmethod
    def _structure_low(code: str, bars: Mapping[str, Any]) -> float:
        """완성 1분봉 3개의 최저가. 자료가 3개가 아니면 0(판정 안 함)."""
        source = bars.get("m") if isinstance(bars.get("m"), dict) else bars
        row = (source or {}).get(code) or {}
        previous = row.get("prev") or []
        lows = [
            _number(bar[2]) for bar in previous[-3:]
            if len(bar) >= 3 and _number(bar[2]) > 0
        ]
        return min(lows) if len(lows) == 3 else 0.0

    @staticmethod
    def _one_minute_shape(code: str, bars: Mapping[str, Any]) -> Tuple[bool, bool]:
        """(직전 양봉 -> 현재 음봉, 현재 음봉)."""
        source = bars.get("m") if isinstance(bars.get("m"), dict) else bars
        row = (source or {}).get(code) or {}
        current_open = _number(row.get("o"))
        current_close = _number(row.get("c"))
        bearish = bool(
            current_open > 0 and current_close > 0 and current_close < current_open
        )
        previous = row.get("prev") or []
        if not previous or len(previous[-1]) < 4:
            return False, bearish
        previous_bull = _number(previous[-1][3]) > _number(previous[-1][0])
        return bool(previous_bull and bearish), bearish

    def build_observation(
        self,
        position: Mapping[str, Any],
        point: Mapping[str, Any],
    ) -> Optional[HoldSellObservation]:
        """S06 의 자료를 공통 엔진 관측값으로 옮긴다. 값이 없으면 None."""
        code = str(position.get("code") or "").zfill(6)
        price = _number(point.get("price"))
        if price <= 0:
            return None
        engine = self.engine
        observed_at = point["ts"]
        epoch_now = observed_at.timestamp()
        # S06 이 이미 유지하는 수급 이력에 이번 점을 더한다(종전 매도경로와 같은 호출).
        engine._append_exit_flow(code, point)
        rows = list(engine.flows.get(code) or ())
        rate10 = _flow_rate(rows, epoch_now, 10.0)
        rate30 = _flow_rate(rows, epoch_now, 30.0)
        rate5 = _flow_rate(rows, epoch_now, 5.0, min_span=2.0)
        buy30, sell30 = rate30 or rate10 or (0.0, 0.0)
        buy10, sell10 = rate10 or (buy30, sell30)
        buy5, sell5 = rate5 or (buy10, sell10)
        total30 = buy30 + sell30
        ratio = buy30 / total30 if total30 > 0 else 0.60

        raw = self._snapshot_raw(code)
        buy_cum = _number(point.get("buy_money_cum"), -1.0)
        sell_cum = _number(point.get("sell_money_cum"), -1.0)
        exact = buy_cum >= 0 and sell_cum >= 0
        volume = max(0.0, _number(point.get("cum_vol")))
        vwap = (buy_cum + sell_cum) / volume if exact and volume > 0 else 0.0
        if not (price * 0.5 <= vwap <= price * 2.0):
            vwap = 0.0

        (
            buy_volume_5s,
            sell_volume_5s,
            previous_sell_volume_10s,
            che_str,
            che_change_5s,
        ) = self._micro_rates(code, observed_at, raw)

        bars = read_json_cached(engine.config.bars_path, {})
        ma3 = ma3_rows(code, bars) or {}
        buy_side = ma3_buy_side_alive(
            buy10, buy30, sell10, sell30,
            sell_volume_5s, previous_sell_volume_10s,
        )
        bull_to_bear, bearish = self._one_minute_shape(code, bars)
        structure_low = self._structure_low(code, bars)
        return HoldSellObservation(
            observed_at=observed_at,
            price=Decimal(str(price)),
            vwap=Decimal(str(vwap)),
            buy_ratio_recent=Decimal(str(ratio)),
            money_speed_5s=Decimal(str(buy5 + sell5)),
            money_speed_10s=Decimal(str(buy10 + sell10)),
            money_speed_30s=Decimal(str(total30)),
            buy_money_per_sec_10s=Decimal(str(buy10)),
            sell_money_per_sec_10s=Decimal(str(sell10)),
            buy_money_per_sec_30s=Decimal(str(buy30)),
            sell_money_per_sec_30s=Decimal(str(sell30)),
            buy_volume_per_sec_5s=Decimal(str(buy_volume_5s)),
            sell_volume_per_sec_5s=Decimal(str(sell_volume_5s)),
            sell_volume_per_sec_previous_10s=Decimal(str(previous_sell_volume_10s)),
            che_str=Decimal(str(che_str)),
            che_str_change_5s=Decimal(str(che_change_5s)),
            structure_broken=bool(structure_low > 0 and price < structure_low),
            money_accelerating=bool(
                (buy10 + sell10) > 0 and (buy5 + sell5) >= (buy10 + sell10)
            ),
            recent_buy_money_rising=bool(rate10 and rate30 and buy10 >= buy30),
            one_minute_bull_to_bear=bull_to_bear,
            one_minute_bearish=bearish,
            # 수급 창이 정확히 서 있을 때만 꼭지매도를 판정하게 한다(fail-closed).
            common_peak_flow_ready=bool(
                exact
                and rate10 is not None
                and isinstance(position.get("real"), bool)
            ),
            daily_ma_permit=ma3_rider_permit(
                code, price, payload=bars, buy_side=buy_side),
            # ★[MA20-DEFENSE] 손실방어 국면 전용(꼭지에는 쓰지 않는다). 아침 계약검사가
            #   'ma20_defense_permit= 에 대입되는 호출'만 손실방어용으로 세므로
            #   S01·S02 와 같은 붙여쓰기 형태를 유지한다.
            ma20_defense_permit=ma3_rider_permit(
                code, price, payload=bars, buy_side=buy_side, allow_ma20=True),
            daily_ma5_broken=ma3_ma5_broken(code, price, bars),
            price_above_ma5=bool(
                ma3.get("ma5", 0.0) > 0 and price > ma3["ma5"]
            ),
            ma5_rising=bool(ma3.get("ma5", 0.0) > ma3.get("ma5_prev", 0.0) > 0),
            ma5_value=Decimal(str(ma3.get("ma5", 0.0))),
            ma5_prev_value=Decimal(str(ma3.get("ma5_prev", 0.0))),
            ma10_value=Decimal(str(ma3.get("ma10", 0.0))),
            ma3_source=str(ma3.get("source") or ""),
            ma10_support=bool(
                ma3.get("ma10", 0.0) > 0 and price >= ma3["ma10"]
            ),
            ma20_support=bool(
                ma3.get("ma20", 0.0) > 0 and price >= ma3["ma20"]
            ),
            ma20_rising=bool(ma3.get("ma20", 0.0) > ma3.get("ma20_prev", 0.0) > 0),
        )


def build_exit_engine(*, audit: bool = True) -> UnifiedHoldSellEngine:
    """S06 전용 공통 매도엔진 인스턴스. 감사기록은 S06 폴더로만 간다."""
    engine = UnifiedHoldSellEngine()
    if audit:
        engine.audit_recorder = HoldSellAuditRecorder(
            AUDIT_ROOT,
            [COMMON_ENGINE_PATH, Path(__file__).resolve()],
            runtime_profile=strategy_profile_runtime_snapshot(STRATEGY_ID),
        )
    return engine
