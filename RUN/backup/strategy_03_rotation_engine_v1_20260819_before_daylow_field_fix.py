# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 주문0 회전 배선.

매수신호는 S03 독립 계약을 사용한다. 체결 이후 주문복구·슬롯·보유·매도는
기존 공통 엔진을 사용한다. 기존 VALLEY_MORNING_CRASH 매도 수치와 우선순위는
유지하되, 사용자 지시에 따라 이 S03 프로세스에서만 09:30 강제청산을 15:10
최종청산으로 바꾼다. 기존 골짜기 프로필 전역값은 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import capital_config

# ★[MA3-COMMON 2026-08-03] 상승보유 = 3분봉 5/10/20선 + 매수세 우위(전 전략 공통).
from ma3_common_v1 import (
    ma3_rows,
    ma5_broken as ma3_ma5_broken,
    rider_permit as ma3_rider_permit,
)
from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    Strategy01Engine,
    number,
    parse_dt,
    read_json,
)
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_LANE,
    EARLY_LOW_MAX_REBOUND_PCT,
    EARLY_LOW_MIN_REBOUND_PCT,
    EarlyLowAuditChain,
    production_file_sha256,
    # ★[S03-LANE-FIX 2026-08-06 친구님 지시 "가로 해"] 2번 레인 잣대를 새로 가져온다.
    INTRADAY_CRASH_LANE,
    INTRADAY_MAX_REBOUND_PCT,
    INTRADAY_MIN_REBOUND_PCT,
    EXPRESS_NEAR_LOW_PCT,
    OPEN_ARM_DROP_PCT,
    OPEN_HANDOFF_DROP_PCT,
    OPEN_CRASH_LANE,
    OPEN_MAX_REBOUND_PCT,
    OPEN_MIN_REBOUND_PCT,
    select_fresh_signals,
)
from strategy_common_hold_sell_v1 import (
    ExitPolicy,
    HoldSellObservation,
    HoldSellState,
    STRATEGY_PROFILES,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profile_runtime_snapshot,
)
from hold_sell_audit_v1 import HoldSellAuditRecorder
# ★[2026-08-12 보안수리 2번] env 단독 활성화는 해시 커버리지 밖이라 머신 env 로
#   우회할 수 있었다. 실전 스위치를 env AND 명부승인(지문검증)의 두 요소로 만든다.
from approval_manifest_writer_v1 import live_feature_enabled


class Strategy03HoldSellEngine(UnifiedHoldSellEngine):
    """공통 장초반 골짜기 매도에서 S03의 시간청산만 15:10으로 분리."""

    def __init__(self, *, audit_recorder=None) -> None:
        super().__init__(audit_recorder=audit_recorder)
        self.open_profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            hard_stop_pct=Decimal("-2.0"),
            strong_flow_hard_stop_pct=Decimal("-2.0"),
            # ★[S03-EXPRESS 2026-08-06 친구님 지시 "매도 방법은 10:30까지 매도하는 걸로"]
            #   아침 창구 강제청산 09:50 → 10:30. 나머지 공통매도(하드손절 -2%·흐름방어·
            #   꼭지매도)는 그대로. 되돌리기: backup\s03_express_20260806\ 복원.
            force_exit_at=day_time(10, 30),
            early_decision_at=day_time(9, 20),
            exit_policy=ExitPolicy.TREND_REBOUND,
            trail_needs_sell_pressure=True,
        )
        self.profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            # ★[S03-LANE2 2026-08-06 친구님 결정 "-1%로 변경해"] 2레인 손절컷.
            #   처음 지시는 -0.5%였으나 닷새 캡처 검증에서 -0.5%는 바닥의 미세 출렁임에
            #   반등 직전 털려(손절 81.4%·평균 +0.54%) -1%(손절 60.5%·평균 +1.43%)의
            #   절반도 못 벌었다 — 숫자를 보시고 친구님이 -1%로 확정.
            #   되돌리기: backup\s03_lane2_20260806\ 복원.
            hard_stop_pct=Decimal("-1.0"),
            strong_flow_hard_stop_pct=Decimal("-1.0"),
            force_exit_at=day_time(15, 10),
        )

    def evaluate(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ):
        if state.strategy_id is not StrategyId.VALLEY_MORNING_CRASH:
            return super().evaluate(state, observation)
        state_before = state.to_dict()
        decision = self._evaluate_strategy03_once(state, observation)
        self.audit_recorder.record(
            state_before=state_before,
            observation=observation,
            decision=decision,
            state_after=state.to_dict(),
        )
        return decision

    def _evaluate_strategy03_once(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ):
        self._validate_sequence(state, observation)
        if state.sell_latched:
            return self._latched_decision(state)
        self._update_state_metrics(state, observation)
        entry_time = state.entry_at.timetz().replace(tzinfo=None)
        is_open_lane = (
            state.entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not state.entry_lane and entry_time < day_time(9, 20))
        )
        profile = self.open_profile if is_open_lane else self.profile
        return self._evaluate_valley(state, observation, profile)



def make_strategy03_signal_selector(
    snapshot_path: Path,
    snapshot_max_age_sec: float,
    early_low_live_enabled: bool | None = None,
):
    """Recheck the S06-style staircase price band and live flow before ordering."""
    if early_low_live_enabled is None:
        # ★[2026-08-12 보안수리 2번] 두 요소 모두 참이어야 실주문 후보가 된다:
        #   ① env 스위치(운영 편의) ② 명부의 해시/지문 보호된 승인(보안).
        #   env 만 머신 스코프로 우회 설정해도 명부 승인이 없으면 켜지지 않는다.
        early_low_live_enabled = (
            os.environ.get("S03_EARLY_LOW_LIVE", "NO").strip().upper() == "YES"
            and live_feature_enabled("S03_EARLY_LOW")
        )

    # ★[EARLY-LOW-AUDIT 2026-08-12] 장초 레인 신호가 계약·주문 selector 를 어떤
    #   입력으로 통과/탈락했는지 해시 사슬 JSONL 로 남긴다. 같은 (신호, 판정) 조합은
    #   한 번만 기록한다 — selector 는 1초마다 돌므로 그대로 남기면 폭주한다.
    _audit_chains: dict[str, EarlyLowAuditChain] = {}
    # ★[2026-08-12 보안수리 3번 보강] 값은 '기록 성공 당시의 감사 파일 크기'다.
    #   재방문 시 파일이 그보다 작아졌으면(삭제·절단) seen 을 무효화하고 재기록을
    #   요구한다 — 종전엔 set 이라, 한 번 기록되면 이후 파일이 사라져도 같은 신호의
    #   주문이 통과했다(증거 소실 후 주문).
    _audit_seen: dict[tuple[str, str, bool, bool], int] = {}
    _audit_sha = production_file_sha256([
        Path(__file__),
        Path(__file__).with_name("strategy_03_signal_contract_v1.py"),
    ])

    def _audit_early_rows(payload, rows, validated, snapshot, now, max_age_sec,
                          consumed):
        early_rows = [
            row for row in (payload.get("signals") or [])
            if isinstance(row, Mapping)
            and str(row.get("entry_lane") or "") == EARLY_LOW_LANE
            and str(row.get("action") or "") == "BUY_READY"
        ]
        if not early_rows:
            return set()
        day = now.strftime("%Y%m%d")
        chain = _audit_chains.get(day)
        if chain is None:
            chain = EarlyLowAuditChain("engine", day)
            _audit_chains.clear()
            _audit_chains[day] = chain
            _audit_seen.clear()
        contract_keys = {
            (str(row.get("code") or ""), str(row.get("ts") or ""))
            for row in rows
            if str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        }
        selected_keys = {
            (str(row.get("code") or ""), str(row.get("ts") or ""))
            for row in validated
            if str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        }
        codes = snapshot.get("codes") or {}
        # ★[2026-08-12 보안수리 3번] 감사기록에 못 남긴 early_low 주문후보를 모은다.
        #   호출부(selector)가 이 집합에 든 (code, ts) 는 validated 에서 빼서 실주문을
        #   보류한다 = '증거 있는 주문만 실행'. seen 등록은 append 성공 후로 미뤄
        #   실패한 것은 다음 틱에 자연히 재시도된다.
        audit_failed: set[tuple[str, str]] = set()
        for row in early_rows:
            code = str(row.get("code") or "").zfill(6)
            row_ts = str(row.get("ts") or "")
            key = (code, row_ts)
            contract_pass = key in contract_keys
            selector_pass = key in selected_keys
            seen_key = (code, row_ts, contract_pass, selector_pass)
            if seen_key in _audit_seen:
                # 기록 당시 크기 이상이면 증거 온전 - 스킵. 작아졌으면(삭제·절단)
                # seen 무효화하고 아래에서 재기록한다.
                try:
                    cur_size = chain.path.stat().st_size
                except OSError:
                    cur_size = -1
                if cur_size >= _audit_seen[seen_key]:
                    continue
                del _audit_seen[seen_key]
            raw = codes.get(code)
            written = chain.append({
                "event": "ORDER_GATE",
                "code": code,
                "name": str(row.get("name") or ""),
                "hr_rank": row.get("hr_rank"),
                "signal_row": dict(row),
                # 계약의 종목당 1행 중복제거(seen_codes)는 signals 목록 순서를 탄다.
                # 같은 종목의 앞선 행(다른 레인 포함)까지 순서대로 남겨야 재생이 같다.
                "same_code_signals": [
                    dict(item)
                    for item in (payload.get("signals") or [])
                    if isinstance(item, Mapping)
                    and str(item.get("code") or "").zfill(6) == code
                ],
                "payload_meta": {
                    "schema": str(payload.get("schema") or ""),
                    "date": str(payload.get("date") or ""),
                    "updated_at": str(payload.get("updated_at") or ""),
                    "mode": str(payload.get("mode") or ""),
                },
                "snapshot_raw": dict(raw) if isinstance(raw, Mapping) else None,
                "snapshot_ts": (
                    str(raw.get("ts") or "") if isinstance(raw, Mapping) else ""),
                "current_price": (
                    abs(number(raw.get("cur"))) if isinstance(raw, Mapping)
                    else 0.0),
                "broker_day_low": (
                    abs(number(raw.get("day_low"))) if isinstance(raw, Mapping)
                    else 0.0),
                "anchor_low": number(row.get("anchor_low")),
                "anchor_low_ts": str(row.get("anchor_low_ts") or ""),
                "rebound_pct": number(row.get("rebound_pct")),
                "chase_blocked": bool(row.get("chase_blocked")),
                "signal_ts": str(row.get("ts") or ""),
                "signal_price": number(row.get("price")),
                "decision_now": now.isoformat(timespec="milliseconds"),
                "max_age_sec": float(max_age_sec),
                "snapshot_max_age_sec": float(snapshot_max_age_sec),
                "consumed": sorted(str(item) for item in consumed),
                "early_low_live_enabled": bool(early_low_live_enabled),
                "contract_pass": contract_pass,
                "selector_pass": selector_pass,
                "prod_sha": _audit_sha,
            })
            if written is None:
                # 감사 실패 - seen 미등록(다음 틱 재시도). 주문 예정(selector_pass)이면 보류 대상.
                if selector_pass:
                    audit_failed.add(key)
            else:
                # 기록 성공 - 그 시점 파일 크기를 함께 저장(삭제·절단 감지 기준).
                try:
                    _audit_seen[seen_key] = chain.path.stat().st_size
                except OSError:
                    pass  # 크기를 못 재면 등록하지 않아 다음 틱에 재확인한다.
        return audit_failed

    def selector(
        payload,
        *,
        now: datetime,
        max_age_sec: float,
        consumed=(),
    ):
        contract_payload = payload
        if not early_low_live_enabled:
            contract_payload = dict(payload)
            contract_payload["signals"] = [
                row for row in (payload.get("signals") or [])
                if str((row or {}).get("entry_lane") or "") != EARLY_LOW_LANE
            ]
        rows = select_fresh_signals(
            contract_payload,
            now=now,
            max_age_sec=max_age_sec,
            consumed=consumed,
        )
        snapshot = read_json(snapshot_path, {})
        codes = snapshot.get("codes") or {}
        decision_at = parse_dt(now.isoformat(), now)
        validated = []
        for row in rows:
            raw = codes.get(str(row.get("code") or "").zfill(6))
            if not isinstance(raw, dict):
                continue
            point_at = parse_dt(raw.get("ts"), decision_at)
            if abs((decision_at - point_at).total_seconds()) > snapshot_max_age_sec:
                continue

            price = abs(number(raw.get("cur")))
            anchor_low = number(row.get("anchor_low"))
            open_price = number(row.get("open_price"))
            if price <= 0 or anchor_low <= 0:
                continue
            rebound = (price / anchor_low - 1.0) * 100.0
            # ★[S03-LANE-FIX 2026-08-06 친구님 지시 "가로 해"] 레인마다 제 잣대로 검산한다.
            #   종전에는 1번 레인(OPEN_CRASH)의 잣대를 2번 레인 신호에도 들이댔다:
            #     · 가격대를 '시가 대비 -8%~-4%' 로 봤다 → 2번은 '당일 고점' 기준이라 축이 다르다
            #     · 반등을 1.0~1.5% 로 요구했다 → 2번 신호기는 0.5~1.0% 에서만 신호를 낸다
            #       = 1.0% 한 점에서만 스쳐 사실상 절대 통과 못 했다.
            #   이것이 S03 역대 매수 0건의 최종 원인이었다(1차 원인은 open_price 누락).
            #   되돌리기: backup\s03_fix_20260806\ 복원.
            lane = str(row.get("entry_lane") or OPEN_CRASH_LANE)
            if lane == EARLY_LOW_LANE:
                if not early_low_live_enabled:
                    continue
                if not EARLY_LOW_MIN_REBOUND_PCT <= rebound <= EARLY_LOW_MAX_REBOUND_PCT:
                    continue
                validated.append(row)
                continue
            if lane == INTRADAY_CRASH_LANE:
                # 낙폭(당일 고점 대비)은 신호기와 계약이 이미 검산했다.
                # 여기서는 '그 사이 저점에서 너무 멀어지지 않았나'만 다시 본다.
                intraday_high = number(row.get("intraday_high"))
                if intraday_high <= anchor_low:
                    continue
                if not INTRADAY_MIN_REBOUND_PCT <= rebound <= INTRADAY_MAX_REBOUND_PCT:
                    continue
            else:
                if open_price <= 0:
                    continue
                upper_price = open_price * (1.0 + OPEN_ARM_DROP_PCT / 100.0)
                # ★[S03-EXPRESS 2026-08-06] 급행 신호는 제 잣대로 재검산 —
                #   -8% 하한·반등 1.0~1.5% 를 들이대면 급행이 전부 버려진다.
                #   위 -4% 선(S01·S02 영역 구분)과 저점 과열(+1.5%)만 다시 본다.
                if str(row.get("reason") or "").startswith("S03_EXPRESS"):
                    if not 0 < price <= upper_price:
                        continue
                    if not 0.0 <= rebound <= EXPRESS_NEAR_LOW_PCT:
                        continue
                else:
                    lower_price = open_price * (1.0 + OPEN_HANDOFF_DROP_PCT / 100.0)
                    if not lower_price < price <= upper_price:
                        continue
                    if not OPEN_MIN_REBOUND_PCT <= rebound <= OPEN_MAX_REBOUND_PCT:
                        continue

            current_buy = number(raw.get("buy_money_cum"), -1.0)
            current_sell = number(raw.get("sell_money_cum"), -1.0)
            signal_buy = number(row.get("current_buy_money_cum"), -1.0)
            signal_sell = number(row.get("current_sell_money_cum"), -1.0)
            if min(current_buy, current_sell, signal_buy, signal_sell) < 0:
                continue
            if current_buy < signal_buy or current_sell < signal_sell:
                continue
            signal_at = parse_dt(row.get("ts"), decision_at)
            if point_at > signal_at:
                delta_buy = current_buy - signal_buy
                delta_sell = current_sell - signal_sell
                if delta_buy <= delta_sell:
                    continue
            validated.append(row)
        # ★[2026-08-12 보안수리 3번] early_low 는 '감사 성공'이 실주문의 전제다.
        #   종전에는 감사 실패를 무시하고 주문을 냈다(증거 없는 주문 가능). 이제
        #   감사에 못 남긴 early_low 주문후보는 validated 에서 빼 보류한다.
        #   감사 배선 자체가 예외로 터지면 early_low 전부 보류(fail-closed).
        try:
            audit_failed = _audit_early_rows(
                payload, rows, validated, snapshot, decision_at,
                max_age_sec, consumed,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"S03_EARLY_LOW_AUDIT_FAILED error={exc!r}",
                file=sys.stderr, flush=True,
            )
            audit_failed = {
                (str(r.get("code") or "").zfill(6), str(r.get("ts") or ""))
                for r in validated
                if str(r.get("entry_lane") or "") == EARLY_LOW_LANE
            }
        if audit_failed:
            validated = [
                r for r in validated
                if not (
                    str(r.get("entry_lane") or "") == EARLY_LOW_LANE
                    and (str(r.get("code") or "").zfill(6),
                         str(r.get("ts") or "")) in audit_failed
                )
            ]
            print(
                "S03_EARLY_LOW_ORDER_HELD_NO_AUDIT codes="
                f"{sorted({c for c, _ in audit_failed})}",
                file=sys.stderr, flush=True,
            )
        return validated

    return selector


class Strategy03Engine(Strategy01Engine):
    def __init__(self, config: Config, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        audit_recorder = self.exit_engine.audit_recorder
        if self.config.audit_enabled:
            audit_recorder = HoldSellAuditRecorder(
                self.config.audit_root,
                [
                    Path(__file__).with_name("strategy_common_hold_sell_v1.py"),
                    Path(__file__),
                ],
                runtime_profile=strategy_profile_runtime_snapshot(
                    self.config.strategy_id
                ),
            )
        self.exit_engine = Strategy03HoldSellEngine(
            audit_recorder=audit_recorder)
        self._s03_daily_trend: dict[str, dict[str, float]] | None = None

    def _load_s03_daily_trend(self) -> None:
        if self._s03_daily_trend is not None:
            return
        self._s03_daily_trend = {}
        session_day = str(self.state.get("date") or "")
        if len(session_day) != 8 or not session_day.isdigit():
            self.log.warning("S03 daily trend disabled: invalid session date")
            return
        by_code: dict[str, dict[str, float]] = {}
        try:
            with self.config.eod_bars_path.open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    if (
                        len(code) == 6
                        and code.isdigit()
                        and day < session_day
                        and len(day) == 8
                        and day.isdigit()
                        and close > 0
                    ):
                        by_code.setdefault(code, {})[day] = close
        except OSError:
            self.log.warning("S03 daily trend disabled: EOD bars unavailable")
            return

        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma20_prev = sum(closes[-21:-1]) / 20
            self._s03_daily_trend[code] = {
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma20_prev": ma20_prev,
            }

    def _daily_ma_permit(self, code: str, price: float,
                         buy_side=None) -> bool:
        """★[MA3-COMMON 2026-08-03] 3분봉 5/10/20선 + 매수세 우위로 통일(공용코어와 동일).

        종전 S03 판정은 일봉 5선>10선·20선 우상향 + 3분봉 고가≥일봉 5선이었다.
        3분봉 고가를 '일봉' 5선과 비교하는 혼합이라, 일봉 5선이 장중 가격보다
        한참 아래인 종목은 상승보유가 영구 참이 됐다.
        되돌리기: backup\\strategy_03_rotation_engine_v1_20260803_ma3wire.py
        """
        return ma3_rider_permit(code, price, buy_side=buy_side)

    def _position_force_exit_at(
        self,
        position: dict[str, Any],
    ) -> day_time:
        entry_at = parse_dt(position.get("entry_at"))
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        # ★[S03-EXPRESS 2026-08-06] 09:50 → 10:30 (위 open_profile 주석 참조).
        return day_time(10, 30) if is_open_lane else self.config.force_exit

    def _completed_open_ma5_broken(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> bool:
        # ★[MA3-COMMON 2026-08-03] 기준선을 일봉 5선 → 3분봉 5선으로 교체.
        #   이 함수는 daily_ma5_broken(흐름역전 민감도 조절)을 채운다. 일봉 5선은
        #   장중에 안 움직여서 '5선을 깼다'가 사실상 발생하지 않았다.
        code = str(position["code"]).zfill(6)
        price = number(point.get("price"))
        rows = ma3_rows(code)
        if not rows:
            return False
        ma5 = rows["ma5"]
        if price >= ma5:
            position["s03_ma5_seen_above"] = True

        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        previous = ((source or {}).get(position["code"]) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False
        observed_at = point["ts"]
        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]), minute=int(hm[2:]), second=0, microsecond=0
            )
        except ValueError:
            return False
        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        latest_completed_minute = current_minute - timedelta(minutes=1)
        if latest_completed_minute < first_post_entry_minute:
            return False
        latest = previous[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            position.get("s03_ma5_seen_above")
            and latest_close > 0
            and latest_close < ma5
            and number(point.get("price")) < ma5
        )

    def _completed_open_structure(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[bool, str]:
        """Return a new post-entry 3m-support/1m-close break.

        The entry minute is deliberately excluded. The three completed
        one-minute bars immediately before the latest completed one-minute
        bar form the post-entry three-minute support. The latest completed
        one-minute close must finish below that support.
        """
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        code = str(position.get("code") or "").zfill(6)
        previous = ((source or {}).get(code) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False, ""

        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False, ""
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]),
                minute=int(hm[2:]),
                second=0,
                microsecond=0,
            )
        except ValueError:
            return False, ""
        if abs((observed_at - current_minute).total_seconds()) > 90:
            return False, ""

        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        full_post_entry_count = int(
            (current_minute - first_post_entry_minute).total_seconds() // 60
        )
        latest_key = (current_minute - timedelta(minutes=1)).strftime("%Y%m%d%H%M")
        if full_post_entry_count < 4:
            return False, latest_key

        post_entry = previous[-min(full_post_entry_count, len(previous)):]
        if len(post_entry) < 4:
            return False, latest_key
        baseline_lows = [
            number(bar[2]) for bar in post_entry[-4:-1]
            if len(bar) >= 4 and number(bar[2]) > 0
        ]
        latest = post_entry[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            len(baseline_lows) == 3
            and latest_close > 0
            and latest_close < min(baseline_lows)
        ), latest_key

    def _open_structure_break_active(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> bool:
        broken, break_key = self._completed_open_structure(position, observed_at)
        if not break_key:
            return False

        tracked_key = str(position.get("s03_structure_bar_key") or "")
        hold_payload = position.get("hold_state")
        if break_key != tracked_key:
            position["s03_structure_bar_key"] = break_key
            position["s03_structure_watch_started"] = bool(broken)
            if isinstance(hold_payload, dict):
                hold_payload["valley_morning_break_since"] = ""
            return broken

        if not broken:
            position["s03_structure_watch_started"] = False
            return False
        if not position.get("s03_structure_watch_started"):
            return False
        if isinstance(hold_payload, dict) and hold_payload.get(
            "valley_morning_break_since"
        ):
            return True

        # This completed one-minute break already received its single 10s
        # exact-flow confirmation and was cancelled. A new completed bar is
        # required before another structure-break watch may start.
        position["s03_structure_watch_started"] = False
        return False

    def _build_observation(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> HoldSellObservation:
        observation = super()._build_observation(position, point)
        entry_at = parse_dt(position.get("entry_at"), point["ts"])
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        if not is_open_lane:
            return observation

        exact = point["buy_money_cum"] >= 0 and point["sell_money_cum"] >= 0
        rate10 = self.windows.rates(position["code"], 10) if exact else None
        exact_valid = bool(rate10 and rate10[0] + rate10[1] > 0)
        return replace(
            observation,
            daily_ma5_broken=self._completed_open_ma5_broken(position, point),
            structure_broken=self._open_structure_break_active(
                position, point["ts"]
            ),
            valley_exact_flow_valid=exact_valid,
            valley_exact_sell_dominant=bool(
                exact_valid and rate10 and rate10[1] > rate10[0]
            ),
        )


@dataclass(frozen=True)
class Strategy03Config(Config):
    max_cycles_per_code: int = 2

    def __post_init__(self) -> None:
        if self.quantity not in {1, 2}:
            raise ValueError("Strategy 03 requires one or two shares")
        if self.max_slots != 6:
            raise ValueError("Strategy 03 requires exactly six concurrent slots")
        if self.max_daily_codes != 6:
            raise ValueError("Strategy 03 requires exactly six distinct codes per day")
        if self.max_cycles_per_code != 2:
            raise ValueError("Strategy 03 permits exactly two entries per code")
        if self.rotation_capital_krw <= 0:
            raise ValueError("rotation_capital_krw must be positive")
        if self.max_sell_retries < 1:
            raise ValueError("max_sell_retries must be positive")
        if not all((
            self.state_schema,
            self.strategy_slug,
            self.strategy_label,
            self.slot_owner,
            self.broker_order_prefix,
            self.event_prefix,
        )):
            raise ValueError("strategy identity fields must not be empty")


def build_config() -> Strategy03Config:
    return Strategy03Config(
        signal_path=Path(
            r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(
            r"C:\stock_bot\data\strategy_03_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_03_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_03_rotation_v1.log"),
        approval_path=Path(
            r"C:\stock_bot\config\strategy_03_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_03_off.flag"),
        manual_buy_block_path=Path(
            r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_03_rotation_v1.lock"),
        live_requested=(
            os.environ.get("S03_LIVE", "NO").strip().upper() == "YES"),
        quantity=capital_config.get_order_quantity(),
        max_slots=int(os.environ.get("S03_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S03_MAX_DAILY_CODES", "6")),
        max_cycles_per_code=int(os.environ.get("S03_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=capital_config.get_limit("daily_total_max"),
        max_sell_retries=int(os.environ.get("S03_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get(
            "S03_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get(
            "S03_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get(
            "S03_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S03_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S03_LOOP_SEC", "1")),
        entry_start=day_time(9, 0),
        entry_end=day_time(14, 30),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_03_rotation_engine_v1",
        strategy_id=StrategyId.VALLEY_MORNING_CRASH,
        strategy_slug="strategy03",
        strategy_label="Strategy 03 Valley Rapid Rebound",
        slot_owner="STRATEGY03",
        broker_order_prefix="STRATEGY03",
        event_prefix="strategy_03",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 03 is already running.", flush=True)
        return 0
    try:
        selector = make_strategy03_signal_selector(
            config.snapshot_path, config.snapshot_max_age_sec)
        return Strategy03Engine(
            config,
            signal_selector=selector,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
