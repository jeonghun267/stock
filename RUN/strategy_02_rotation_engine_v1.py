# -*- coding: utf-8 -*-
"""새전략 02 독립 회전엔진: 매수만 S02, 보유·매도·주문복구는 공통."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

import capital_config

# ★[DAY-GATE 2026-08-08] 판정 파일 읽기는 캐시로(틱마다 재읽기 방지, 8/5 교훈).
from json_cache_v1 import read_json_cached

# ★[MA3-COMMON 2026-08-03] 상승보유 = 3분봉 5/10/20선 + 매수세 우위(전 전략 공통).
from ma3_common_v1 import (
    buy_side_alive as ma3_buy_side_alive,
    ma3_rows,
    ma5_broken as ma3_ma5_broken,
    rider_permit as ma3_rider_permit,
)
from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    Strategy01Engine,
    as_kst,
    kst_now,
    number,
    read_json,
)
from strategy_02_signal_contract_v1 import select_fresh_signals
from strategy_02_six_second_shadow_v1 import Strategy02SixSecondShadow
from strategy_02_trend_lock_shadow_v1 import Strategy02TrendLockShadow
from strategy_common_hold_sell_v1 import StrategyId
from strategy_common_reentry_gate_v1 import LossReentryGate


# ★[DAY-GATE 2026-08-08 친구님 승인 "화요일부터 ON"] 하락일 게이트 — S02 신규 매수만 차단.
#   판정: SAFEPLUS_DAY_JUDGE(09:32)가 쓰는 data\day_gate\day_judge_YYYYMMDD.json 의
#   suspect(아침 깨진반등률 >= 47%). 스위치 S02_DAYGATE=YES 일 때만 작동(기본 NO = 종전 그대로).
#   근거: 12일 재생 — 게이트 적용 시 건당기대 -0.315% -> +0.016% (하락일 4일 차단).
#   매도·보유·주문복구는 절대 건드리지 않는다. 판정 파일이 없으면 차단 안 함(안전측).
#   롤백: 실전 런처에서 S02_DAYGATE 줄 제거(또는 NO) — 코드 원복 불필요.
_DAY_GATE_DIR = Path(r"C:\stock_bot\data\day_gate")
_DAY_GATE_START = day_time(9, 32)
_S02_PEAK_CANARY_FLAG = Path(
    r"C:\stock_bot\config\s02_peak_5_drop_1p5_flow_3of4_6s_20260811.flag"
)


def day_gate_blocked(now) -> bool:
    """하락일 의심 + 스위치 ON + 09:32 이후면 참 = S02 신규 진입 금지."""
    if os.environ.get("S02_DAYGATE", "NO").strip().upper() != "YES":
        return False
    if now.time() < _DAY_GATE_START:
        return False
    verdict = read_json_cached(
        _DAY_GATE_DIR / ("day_judge_%s.json" % now.strftime("%Y%m%d")), {})
    return bool(isinstance(verdict, dict) and verdict.get("suspect"))


class Strategy02Engine(Strategy01Engine):
    """S02-only market telemetry adapter for the shared hold/sell engine."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # ★[PEAK-SCORE-3 2026-08-19 친구님 "배선해"] 꼭지흐름 매도 문턱 2→3 (S02만).
        #   근거: 8/13 백테심판 — score=2 매도 13건 보류 시 30분 뒤 평균 +2.67%p(상방 10/12).
        #   8/19 재생 실측 — 오늘 S02 이익매도 전부 score=2에서 잘림(019210 +3.14% 등).
        #   ⚠️8/13 심판 경고: 이득의 71%가 강세일(8/10) 집중 — 며칠 실측으로 유지/철회 판단.
        #   하드컷·방어매도·시간청산·S02 전용 약꼭지(1점) 규칙 무변경.
        #   공용 기본값(2)·타 전략 무간섭 — 이 프로세스의 엔진 인스턴스만 바꾼다.
        #   롤백: setx S02_PEAK_SCORE 2  ·  백업 backup\strategy_02_rotation_engine_v1_20260819_before_peak_score3.py
        try:
            _peak_score = int(os.environ.get("S02_PEAK_SCORE", "3"))
        except ValueError:
            _peak_score = 3
        if _peak_score != self.exit_engine.config.common_peak_score:
            self.exit_engine.config = replace(
                self.exit_engine.config, common_peak_score=_peak_score)
        # Owner-approved permanent S02 loss re-entry gate:
        # 15 minutes after the confirmed sell, a lower low than the prior
        # cycle's trough, then three consecutive buy-side confirmations.
        self.loss_reentry_gate = LossReentryGate(
            min_wait_sec=float(os.environ.get(
                "S02_LOSS_REENTRY_WAIT_SEC", "900",
            )),
            require_new_low=True,
            min_stable_bars=0,
            atr_multiplier=0.0,
            buy_confirmations=int(os.environ.get(
                "S02_LOSS_REENTRY_CONFIRMATIONS", "3",
            )),
        )
        self._s02_micro = defaultdict(lambda: deque(maxlen=80))
        self._s02_six_second_shadow = Strategy02SixSecondShadow(self._event)
        self._s02_trend_lock_shadow = Strategy02TrendLockShadow(
            self._event, self.exit_engine.config,
        )

        production_files = {
            "engine": Path(__file__).resolve(),
            "shared_rotation_engine": Path(__file__).with_name(
                "strategy_01_rotation_engine_v2.py"
            ),
            "signal_contract": Path(__file__).with_name(
                "strategy_02_signal_contract_v1.py"
            ),
            "signal_source": Path(__file__).with_name(
                "strategy_02_low_buy_signal_v1.py"
            ),
            "order_adapter": Path(__file__).with_name(
                "strategy_common_order_v1.py"
            ),
        }
        self._order_lifecycle_prod_sha = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in production_files.items()
            if path.is_file()
        }

        self._s02_arrival_max_chase_bps = float(os.environ.get(
            "S02_MAX_ARRIVAL_CHASE_BPS", "25"
        ))
        self._s02_base_signal_selector = self.signal_selector
        self._s02_signal_rows_by_code: dict[str, dict[str, Any]] = {}
        self.signal_selector = self._select_with_arrival_collar

    def _select_with_arrival_collar(self, *args, **kwargs):
        rows = list(self._s02_base_signal_selector(*args, **kwargs))
        self._s02_signal_rows_by_code = {
            str(row.get("code") or "").zfill(6): row
            for row in rows
            if isinstance(row, dict)
        }
        return rows
    def _order_lifecycle(
        self,
        event: str,
        position: Mapping[str, Any],
        *,
        fill_quantity: int = 0,
        fill_price: float = 0.0,
        fill_source: str = "",
        observed_at: Optional[datetime] = None,
    ) -> None:
        """Durable S02-only signal -> order -> fill audit chain."""
        pending = position.get("pending") or {}
        captured_at = as_kst(observed_at or kst_now())
        signal_snapshot = position.get("signal_snapshot") or {}
        emitted_price = number(signal_snapshot.get("signal_emitted_price") or signal_snapshot.get("price"))
        arrival_price = number(position.get("signal_price"))
        fill_slippage_bps = (
            (number(fill_price) / arrival_price - 1.0) * 10000.0
            if number(fill_price) > 0 and arrival_price > 0 else None
        )
        record: dict[str, Any] = {
            "schema": "s02_order_lifecycle_v1",
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "strategy_id": self.config.strategy_id.value,
            "trade_date": str(self.state.get("date") or ""),
            "event": event,
            "code": str(position.get("code") or "").zfill(6),
            "signal_id": str(position.get("signal_id") or ""),
            "signal_ts": str(position.get("signal_ts") or ""),
            "signal_price": number(position.get("signal_price")),
            "signal_reason": str(position.get("signal_reason") or ""),
            "entry_stage": str(
                pending.get("entry_stage") or position.get("entry_stage") or ""
            ),
            "signal_snapshot": position.get("signal_snapshot") or {},
            "signal_emitted_price": emitted_price,
            "arrival_price": arrival_price,
            "arrival_chase_bps": signal_snapshot.get("arrival_chase_bps"),
            "fill_slippage_bps": (
                round(fill_slippage_bps, 4)
                if fill_slippage_bps is not None else None
            ),
            "idempotency_key": str(pending.get("idempotency_key") or ""),
            "order_no": str(pending.get("order_no") or ""),
            "requested_quantity": int(pending.get("requested_qty") or 0),
            "broker_status": str(pending.get("last_status") or ""),
            "fill_quantity": int(fill_quantity),
            "fill_price": number(fill_price),
            "fill_reconciled_at": (
                captured_at.isoformat(timespec="seconds")
                if event == "BUY_FILL_CONFIRMED" else ""
            ),
            "fill_source": fill_source,
            "mode": str(getattr(self.broker, "mode", "UNKNOWN")),
            "production_files": dict(self._order_lifecycle_prod_sha),
        }
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        )
        record["record_sha256"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        path = (
            self.config.order_lifecycle_root
            / str(self.state.get("date") or captured_at.strftime("%Y%m%d"))
            / "s02_order_lifecycle.jsonl"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(
                    json.dumps(record, ensure_ascii=False, default=str) + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self.log.exception("S02_ORDER_LIFECYCLE_AUDIT_WRITE_FAILED")
    def _try_entries(self, now) -> None:
        # ★[DAY-GATE 2026-08-08] 하락일 의심이면 신규 진입만 멈춘다(매도·보유 불변).
        #   알림 이벤트는 날짜당 1회, 이후에는 조용히 건너뛴다.
        if day_gate_blocked(now):
            stamp = now.strftime("%Y%m%d")
            if self.state.get("day_gate_announced") != stamp:
                self.state["day_gate_announced"] = stamp
                self._event("BUY_BLOCKED", reason="DAY_GATE_SUSPECT_DOWN_DAY")
                self._save()
            return
        try:
            super()._try_entries(now)
        finally:
            self._s02_signal_rows_by_code.clear()

    # ★[LEGACY-DAILY-MA 제거 2026-08-05 친구님 지시 "지워"] 여기 있던
    #   _load_daily_ma(일봉 종가에서 5/10/20선 계산)와 _daily_ma_permit_legacy
    #   (그 일봉 선으로 상승보유 판정)를 지웠다.
    #   8/3 에 상승보유를 일봉→3분봉(ma3_common_v1)으로 전면 교체했는데 S05 만
    #   _daily_ma_permit_legacy 를 계속 부르고 있었고, 그 호출을 같은 날 지우면서
    #   두 함수 다 부르는 곳이 없어졌다. 일봉 5일선은 장중에 안 움직이는 고정값이라
    #   되살리면 상승보유가 사실상 영구 참이 된다(8/3 에스피지 사고).
    #   상승보유 판정은 이제 _daily_ma_permit(3분봉) 하나뿐이다.
    #   되돌리기: backup\strategy_02_rotation_engine_v1_20260805_before_legacy_removal.py

    def _bar_row(self, code: str):
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        return (source or {}).get(str(code).zfill(6)) or {}

    def _one_minute_bull_to_bear(self, code: str) -> bool:
        row = self._bar_row(code)
        previous = row.get("prev") or []
        if not previous or len(previous[-1]) < 4:
            return False
        previous_bull = number(previous[-1][3]) > number(previous[-1][0])
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return previous_bull and current_open > 0 and current_close < current_open

    def _one_minute_bearish(self, code: str) -> bool:
        """★[TRAIL-FLOW 2026-08-03] 진행 중 1분봉이 음봉인가(종가 < 시가).

        _one_minute_bull_to_bear 는 직전봉이 양봉이어야 해서 연속 음봉을 놓친다.
        꼭지 판정에는 전환이 아니라 '지금 음봉인가'가 필요하다.
        """
        row = self._bar_row(code)
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return bool(current_open > 0 and current_close > 0
                    and current_close < current_open)

    def _daily_ma_permit(self, code: str, price: float,
                         buy_side=None) -> bool:
        """★[MA3-COMMON 2026-08-03] 3분봉 5/10/20선 + 매수세 우위로 통일(공용코어와 동일).

        종전 S02 판정은 일봉 5선↑·10선↑·20선↑·5선>10선 + (완성봉≥5선 또는 현재가≥10선)
        이었다. 일봉이라 장중에 안 깨져서 상승보유가 사실상 영구 참이었다.
        되돌리기: backup\\strategy_02_rotation_engine_v1_20260803_ma3wire.py
        """
        return ma3_rider_permit(code, price, buy_side=buy_side)

    def _snapshot_point(self, code, now):
        point = super()._snapshot_point(code, now)
        if point is None:
            return None
        snapshot = read_json(self.config.snapshot_path, {})
        raw = (snapshot.get("codes") or {}).get(str(code).zfill(6)) or {}
        point["che_str"] = max(0.0, number(raw.get("che_str")))
        point["buy_vol_cum"] = number(raw.get("buy_vol_cum"), -1.0)
        point["sell_vol_cum"] = number(raw.get("sell_vol_cum"), -1.0)
        row = self._s02_signal_rows_by_code.get(str(code).zfill(6))
        if not row:
            return point
        emitted_price = number(row.get("price"))
        if emitted_price <= 0:
            self._event(
                "BUY_WAIT", code=str(code).zfill(6),
                name=str(row.get("name") or ""),
                price=point["price"], reason="ARRIVAL_SIGNAL_PRICE_MISSING",
            )
            return None
        arrival_chase_bps = (
            point["price"] / emitted_price - 1.0
        ) * 10000.0
        row["signal_emitted_price"] = emitted_price
        row["arrival_price"] = point["price"]
        row["arrival_chase_bps"] = round(arrival_chase_bps, 4)
        if arrival_chase_bps > self._s02_arrival_max_chase_bps:
            self._event(
                "BUY_WAIT", code=str(code).zfill(6),
                name=str(row.get("name") or ""),
                price=point["price"],
                reason=(
                    f"ARRIVAL_PRICE_COLLAR "
                    f"{arrival_chase_bps:.2f}>"
                    f"{self._s02_arrival_max_chase_bps:.2f}bps"
                ),
            )
            return None
        return point

    def _micro_rates(self, code: str, point):
        rows = self._s02_micro[str(code).zfill(6)]
        current = (
            point["ts"],
            number(point.get("buy_vol_cum"), -1.0),
            number(point.get("sell_vol_cum"), -1.0),
            number(point.get("che_str")),
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

        def at_or_before(target):
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

    def _build_observation(self, position, point):
        observation = super()._build_observation(position, point)
        (
            buy_volume_5s,
            sell_volume_5s,
            previous_sell_volume_10s,
            che_str,
            che_change_5s,
        ) = self._micro_rates(position["code"], point)
        # ★[MA3-COMMON 2026-08-03] 종전 일봉 5/10/20선 → 3분봉으로 교체.
        #   ma10_support·ma20_rising 은 S05(베이스 붕괴 방어)도 그대로 읽는다.
        code = str(position["code"]).zfill(6)
        price = point["price"]
        ma3 = ma3_rows(code) or {}
        # 상승보유는 부모(_build_observation)가 거래대금 속도만으로 이미 한 번 판정했다.
        # S02·S05 는 체결량 속도까지 있으니 그 3종으로 다시 정확히 판정해 덮어쓴다.
        buy_side = ma3_buy_side_alive(
            float(observation.buy_money_per_sec_10s),
            float(observation.buy_money_per_sec_30s),
            float(observation.sell_money_per_sec_10s),
            float(observation.sell_money_per_sec_30s),
            sell_volume_5s,
            previous_sell_volume_10s,
        )
        result = replace(
            observation,
            buy_volume_per_sec_5s=buy_volume_5s,
            sell_volume_per_sec_5s=sell_volume_5s,
            sell_volume_per_sec_previous_10s=previous_sell_volume_10s,
            che_str=che_str,
            che_str_change_5s=che_change_5s,
            one_minute_bull_to_bear=self._one_minute_bull_to_bear(
                position["code"]),
            one_minute_bearish=self._one_minute_bearish(position["code"]),
            daily_ma_permit=self._daily_ma_permit(code, price, buy_side=buy_side),
            # ★[MA20-DEFENSE 2026-08-05] 20선 단계까지 인정한 상승보유.
            #   공통 매도엔진이 손실방어 국면에서만 쓴다(꼭지에는 안 쓴다).
            #   위 daily_ma_permit 은 allow_ma20 없이(=20선 단계 제외) 구한 값이라
            #   서로 다르다. 그 차이가 이 배선의 전부다 — S02·S05 는 이제
            #   "손실 중인데 우상향 20선이 받쳐줄 때" 팔지 않고 버틴다.
            ma20_defense_permit=ma3_rider_permit(
                code, price, buy_side=buy_side, allow_ma20=True),
            daily_ma5_broken=ma3_ma5_broken(code, price),
            ma10_support=bool(
                ma3.get("ma10", 0.0) > 0 and price >= ma3["ma10"]
            ),
            ma20_support=bool(
                ma3.get("ma20", 0.0) > 0 and price >= ma3["ma20"]
            ),
            ma20_rising=bool(
                ma3.get("ma20", 0.0) > ma3.get("ma20_prev", 0.0) > 0
            ),
        )
        if os.environ.get(
            "S02_SIX_SECOND_EXIT_SHADOW", "NO"
        ).strip().upper() == "YES":
            try:
                self._s02_six_second_shadow.evaluate(position, result)
            except Exception as exc:
                # Shadow telemetry must never interrupt live hold/sell.
                self.log.warning("S02 six-second shadow skipped: %s", exc)
        if os.environ.get(
            "S02_TREND_LOCK_SHADOW", "NO"
        ).strip().upper() == "YES":
            try:
                self._s02_trend_lock_shadow.evaluate(
                    position,
                    result,
                    above_ma5_ma10_ma20=bool(
                        not result.daily_ma5_broken
                        and result.ma10_support
                        and result.ma20_support
                        and result.ma20_rising
                    ),
                )
            except Exception as exc:
                # Order-zero telemetry must never interrupt live hold/sell.
                self.log.warning("S02 trend-lock shadow skipped: %s", exc)
        return result


def build_config() -> Config:
    return Config(
        signal_path=Path(r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_02_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_02_rotation_v1.log"),
        order_lifecycle_root=Path(r"C:\stock_bot\data\audit\s02_order_lifecycle"),
        post_exit_observation_sec=float(
            os.environ.get("S02_POST_EXIT_OBSERVATION_SEC", "900")
        ),
        approval_path=Path(r"C:\stock_bot\config\strategy_02_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_02_off.flag"),
        manual_buy_block_path=Path(r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_02_rotation_v1.lock"),
        live_requested=os.environ.get("S02_LIVE", "NO").strip().upper() == "YES",
        quantity=capital_config.get_order_quantity(),
        max_slots=int(os.environ.get("S02_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S02_MAX_DAILY_CODES", "12")),
        max_cycles_per_code=int(os.environ.get("S02_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=capital_config.get_limit("daily_total_max"),
        max_sell_retries=int(os.environ.get("S02_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get("S02_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get("S02_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get("S02_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S02_FILL_WAIT_SEC", "8")),
        initial_sell_query_budget_sec=2.0,
        loss_reentry_gate_mode=os.environ.get(
            "S02_LOSS_REENTRY_GATE_MODE", "SHADOW"
        ).strip().upper(),
        reentry_peer_state_paths=(
            Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json"),
        ),
        loop_sec=float(os.environ.get("S02_LOOP_SEC", "1")),
        # 09:00부터 신호기와 주문기를 함께 열어 아침 시가 -3% 조건을 실행한다.
        entry_start=day_time(9, 0),
        entry_end=day_time(14, 20),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_02_rotation_engine_v1",
        strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
        strategy_slug="strategy02",
        strategy_label="Strategy 02 Low Buy Sell Exhaustion",
        slot_owner="STRATEGY02",
        broker_order_prefix="STRATEGY02",
        event_prefix="strategy_02",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 02 is already running.", flush=True)
        return 0
    canary_date = os.environ.get(
        "S02_PEAK_5_DROP_1P5_FLOW_3OF4_6S_DATE", ""
    ).strip()
    if canary_date:
        try:
            _S02_PEAK_CANARY_FLAG.unlink()
        except OSError as exc:
            lock.release()
            print(
                f"S02 canary token was not consumed; live start blocked: {exc}",
                flush=True,
            )
            return 1
    try:
        return Strategy02Engine(
            config,
            signal_selector=select_fresh_signals,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
