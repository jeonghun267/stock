# -*- coding: utf-8 -*-
"""S02_SIX_FLOW_RECOVERY_V1 — 장중 재기동 six 레인 수급 복원 검증.

검증 기준(친구님 승인 5항 + 재검토 추가분):
  ① 재기동 후 중복 주문 0건        → emitted_anchors/emission_count 가 살아있다
  ② 낡은 pending 복원 0건          → pending·확인횟수·눌림 상태는 복원되지 않는다
  ③ 손상·전일 상태 복원 0건        → 날짜·스키마·단조성 가드가 각각 막는다
  ④ 저장 누적값 > 현재 누적값이면 그 종목 복원 거부
  ⑤ 기존 매수조건·설정값 불변      → SIGNAL_SCHEMA·문턱 상수가 그대로다
  ⑥ 복원본이 내는 신호는 미재기동본의 부분집합 → 항상 CHASE 로 낮춰 복원한다

대상 파일을 S02_TARGET 환경변수로 바꿔 지정할 수 있다(작업본 검증용).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

TARGET = Path(
    os.environ.get(
        "S02_TARGET", r"C:\stock_bot\RUN\strategy_02_low_buy_signal_v1.py")
)


def _load_module():
    run_dir = Path(r"C:\stock_bot\RUN")
    if str(run_dir) not in sys.path:
        sys.path.insert(0, str(run_dir))
    spec = importlib.util.spec_from_file_location("s02_under_test", TARGET)
    module = importlib.util.module_from_spec(spec)
    # dataclass 가 해석 중 sys.modules 를 찾는다 — 등록 후 실행해야 한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _load_module()

# 패치 반영 전(장중)에는 이 파일 전체를 건너뛴다 — 아직 없는 기능을 실패로
# 세면 pytest 기준선에 가짜 회귀 20여 건이 생긴다. 15:30 반영 후 자동으로 켜진다.
if not hasattr(M, "SIX_RECOVERY_ENABLED"):
    pytest.skip(
        f"S02_SIX_FLOW_RECOVERY_V1 미반영 대상: {TARGET}",
        allow_module_level=True,
    )

TODAY = datetime.now().replace(microsecond=0)
LOW_TS = TODAY.replace(hour=10, minute=24, second=0)
NOW_TS = TODAY.replace(hour=11, minute=55, second=31)


def _point(module, *, price, buy_cum, sell_cum, ts=NOW_TS):
    """판정에 쓰이는 필드만 채운 최소 MarketPoint."""
    return module.MarketPoint(
        ts=ts,
        price=float(price),
        cum_vol=1000.0,
        che_str=100.0,
        ask_tot=100.0,
        bid_tot=100.0,
        buy_money_cum=float(buy_cum),
        sell_money_cum=float(sell_cum),
        buy_vol_cum=500.0,
        sell_vol_cum=500.0,
        best_ask_px=price + 10,
        best_bid_px=price - 10,
        best_ask_qty=100.0,
        best_bid_qty=100.0,
        broker_day_low=float(price),
        broker_day_high=float(price),
    )


def _row(**over):
    """정상 복원행 — 09:30 이후 요구낙폭 5% 를 넉넉히 넘긴다."""
    row = {
        "code": "007390",
        "six_phase": "OBSERVE",
        "six_episode_high": 25800.0,
        "six_low": 24450.0,
        "six_low_ts": LOW_TS.isoformat(timespec="seconds"),
        "six_low_buy_money": 1_000_000.0,
        "six_low_sell_money": 2_000_000.0,
        "six_low_buy_vol": 400.0,
        "six_low_sell_vol": 900.0,
        "six_low_che_str": 88.0,
        "six_pre_buy_rate": 1000.0,
        "six_pre_sell_rate": 3000.0,
        "six_reset_steps": 3,
        "six_dead_low": 0.0,
    }
    row.update(over)
    return row


def _monitor(module):
    return module.LowBuySignalMonitor(
        max_signals_per_code=2,
        confirm_sec=2.0,
        confirm_points=3,
        max_spread_bps=30.0,
    )


def _restore(module, monitor, rows, date_text=None):
    payload = {
        "schema": module.SIGNAL_SCHEMA,
        "date": date_text or TODAY.strftime("%Y%m%d"),
        "signals": [],
        "six_recovery": rows,
    }
    monitor.restore(payload, TODAY.strftime("%Y%m%d"))
    return payload


def _apply(module, monitor, rows, *, price=24700.0, buy_cum=9_000_000.0,
           sell_cum=9_000_000.0, reference_price=25800.0, ts=NOW_TS):
    _restore(module, monitor, rows)
    state = monitor.states.setdefault("007390", module.CodeState())
    point = _point(module, price=price, buy_cum=buy_cum, sell_cum=sell_cum, ts=ts)
    verdict = monitor._apply_six_recovery("007390", state, point, reference_price)
    return state, verdict


# ── ⑤ 기존 조건·설정값 불변 ───────────────────────────────────────────────

def test_signal_schema_unchanged():
    """스키마 문자열을 바꾸면 이 파일을 읽는 11개 모듈과 날짜가드가 깨진다."""
    assert M.SIGNAL_SCHEMA == "strategy_02_low_buy_sell_exhaustion_signal_v1"


def test_entry_thresholds_unchanged():
    assert M.MORNING_DIP_DROP_PCT == 3.0
    assert M.INTRADAY_DIP_DROP_PCT == 5.0
    assert M.SIX_CHASE_CAP_PCT == 2.0
    assert M.SIX_FIRST_REBOUND_PCT == 1.0
    assert M.DAY_LOW_MAX_GAP_PCT == 2.0


# ── 정상 복원 ────────────────────────────────────────────────────────────

def test_recovery_restores_low_flow():
    state, verdict = _apply(M, _monitor(M), [_row()])
    assert verdict.startswith("OK:"), verdict
    assert state.six_low == 24450.0
    assert state.six_episode_high == 25800.0
    assert state.six_low_ts == LOW_TS
    assert state.six_low_buy_money == 1_000_000.0
    assert state.six_low_sell_money == 2_000_000.0
    assert state.six_pre_buy_rate == 1000.0
    assert state.six_pre_sell_rate == 3000.0
    assert state.six_reset_steps == 3


def test_recovered_state_makes_flow_flip_measurable():
    """복원의 유일한 목적 — 저점 수급이 살아나 flow_flip 이 계산된다."""
    fresh = _monitor(M)
    blank = M.CodeState()
    point = _point(M, price=24700.0, buy_cum=9_000_000.0, sell_cum=9_000_000.0)
    assert M.LowBuySignalMonitor._six_flow_flip(blank, point) == ""

    state, verdict = _apply(M, fresh, [_row()])
    assert verdict.startswith("OK:")
    # 저점 전 매도우위(1000<3000) · 저점 후 매수우위 → 역전 "O"
    after = _point(M, price=24700.0, buy_cum=9_000_000.0, sell_cum=3_000_000.0)
    assert M.LowBuySignalMonitor._six_flow_flip(state, after) == "O"


# ── ⑥ 부분집합 보장: 항상 CHASE 로 낮춰 복원 ──────────────────────────────

def test_recovery_always_downgrades_to_chase():
    state, _ = _apply(M, _monitor(M), [_row(six_phase="OBSERVE")])
    assert state.six_phase == "CHASE"


# ── ② 낡은 pending·확인상태는 복원되지 않는다 ────────────────────────────

def test_recovery_never_restores_pending_or_confirm_state():
    state, verdict = _apply(M, _monitor(M), [_row(
        pending_anchor_id="STALE", pending_hits=3, six_first_rebound_peak=25000.0,
        six_pullback_low=24600.0, six_observe_since=LOW_TS.isoformat(),
        direct_confirm_hits=5,
    )])
    assert verdict.startswith("OK:")
    assert state.pending_anchor_id == ""
    assert state.pending_hits == 0
    assert state.pending_since is None
    assert state.six_observe_since is None
    assert state.six_first_rebound_peak == 0.0
    assert state.six_pullback_seen is False
    assert state.six_pullback_low == 0.0
    assert state.six_micro_confirm_hits == 0
    assert state.direct_confirm_hits == 0
    assert state.direct_last_confirm_ts is None


# ── ③④ 거부 가드 ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "over, kwargs, expected",
    [
        ({}, {"buy_cum": 10.0}, "SKIP:CUM_REGRESSED"),          # ④ 매수누적 역행
        ({}, {"sell_cum": 10.0}, "SKIP:CUM_REGRESSED"),         # ④ 매도누적 역행
        ({}, {"price": 24000.0}, "SKIP:NEW_LOW"),               # 저점 아래
        ({}, {"reference_price": 26500.0}, "SKIP:HIGH_ADVANCED"),
        # 낙폭 1.0% — 기준고점을 같이 낮춰야 ④가 아닌 ⑤에서 걸린다.
        ({"six_episode_high": 24700.0},
         {"reference_price": 24700.0}, "SKIP:DROP_SHORT"),
        ({"six_pre_buy_rate": -1.0}, {}, "SKIP:NO_PRE_RATE"),
        ({"six_pre_sell_rate": -1.0}, {}, "SKIP:NO_PRE_RATE"),
        ({"six_low": 0.0}, {}, "SKIP:INCOMPLETE"),
        ({"six_episode_high": 0.0}, {}, "SKIP:INCOMPLETE"),
        ({"six_low_ts": ""}, {}, "SKIP:INCOMPLETE"),
        ({"six_low": "글자"}, {}, "SKIP:MALFORMED"),
    ],
)
def test_recovery_rejects(over, kwargs, expected):
    state, verdict = _apply(M, _monitor(M), [_row(**over)], **kwargs)
    assert verdict == expected, verdict
    assert state.six_phase == "IDLE"      # 거부되면 상태를 건드리지 않는다
    assert state.six_low == 0.0


def test_recovery_rejects_yesterday_low_ts():
    state, verdict = _apply(M, _monitor(M), [_row(
        six_low_ts=(LOW_TS - timedelta(days=1)).isoformat(timespec="seconds"))])
    assert verdict == "SKIP:NOT_TODAY"
    assert state.six_phase == "IDLE"


def test_recovery_rejects_future_low_ts():
    state, verdict = _apply(M, _monitor(M), [_row(
        six_low_ts=(NOW_TS + timedelta(minutes=5)).isoformat(timespec="seconds"))])
    assert verdict == "SKIP:NOT_TODAY"


# ── ③ 전일 payload 는 restore() 단계에서 통째로 막힌다 ────────────────────

def test_previous_day_payload_is_not_loaded_at_all():
    monitor = _monitor(M)
    yesterday = (TODAY - timedelta(days=1)).strftime("%Y%m%d")
    _restore(M, monitor, [_row()], date_text=yesterday)
    assert monitor._six_recovery_pending == {}


def test_wrong_schema_payload_is_not_loaded_at_all():
    monitor = _monitor(M)
    monitor.restore(
        {"schema": "something_else", "date": TODAY.strftime("%Y%m%d"),
         "six_recovery": [_row()]},
        TODAY.strftime("%Y%m%d"),
    )
    assert monitor._six_recovery_pending == {}


# ── 한 종목 손상이 전체를 멈추지 않는다 ──────────────────────────────────

def test_broken_row_does_not_block_other_codes():
    monitor = _monitor(M)
    _restore(M, monitor, [
        {"code": None},
        {"code": "ABCDEF"},
        {"code": "12"},
        _row(),
    ])
    assert set(monitor._six_recovery_pending) == {"007390"}


# ── ① 중복 주문 방지: 기존 dedup 복원이 그대로 산다 ──────────────────────

def test_existing_signal_dedup_still_restored():
    monitor = _monitor(M)
    monitor.restore(
        {
            "schema": M.SIGNAL_SCHEMA,
            "date": TODAY.strftime("%Y%m%d"),
            "signals": [{
                "code": "007390", "signal_sequence": 2,
                "anchor_id": "ANCHOR-1", "anchor_low": 24450.0,
            }],
            "six_recovery": [_row()],
        },
        TODAY.strftime("%Y%m%d"),
    )
    state = monitor.states["007390"]
    assert state.emission_count == 2
    assert "ANCHOR-1" in state.emitted_anchors


# ── 복원은 종목당 1회만 ──────────────────────────────────────────────────

def test_recovery_applies_only_once_per_code():
    monitor = _monitor(M)
    state, first = _apply(M, monitor, [_row()])
    assert first.startswith("OK:")
    point = _point(M, price=24700.0, buy_cum=9_000_000.0, sell_cum=9_000_000.0)
    assert monitor._apply_six_recovery("007390", state, point, 25800.0) == ""


# ── 저장 왕복 ────────────────────────────────────────────────────────────

def test_six_recovery_rows_roundtrip():
    writer = _monitor(M)
    state = writer.states.setdefault("007390", M.CodeState())
    state.six_phase = "CHASE"
    state.six_episode_high = 25800.0
    state.six_low = 24450.0
    state.six_low_ts = LOW_TS
    state.six_low_buy_money = 1_000_000.0
    state.six_low_sell_money = 2_000_000.0
    state.six_pre_buy_rate = 1000.0
    state.six_pre_sell_rate = 3000.0
    state.six_reset_steps = 3
    rows = writer.six_recovery_rows()
    assert len(rows) == 1 and rows[0]["code"] == "007390"

    reader_state, verdict = _apply(M, _monitor(M), rows)
    assert verdict.startswith("OK:")
    assert reader_state.six_low == 24450.0
    assert reader_state.six_pre_sell_rate == 3000.0


def test_idle_codes_are_not_saved():
    writer = _monitor(M)
    writer.states.setdefault("007390", M.CodeState())    # IDLE 기본값
    assert writer.six_recovery_rows() == []


def test_unapplied_pending_is_carried_forward():
    """복원 후보가 아직 체결을 못 봤으면 다음 기동으로 넘어가야 한다."""
    monitor = _monitor(M)
    _restore(M, monitor, [_row()])
    rows = monitor.six_recovery_rows()
    assert [r["code"] for r in rows] == ["007390"]
