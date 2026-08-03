# -*- coding: utf-8 -*-
"""
CAPTAIN 2.0 — RESET 기반 Money Flow Trading Engine

목적
----
가격 위치(바닥/눌림/횡보/돌파/신고가)와 무관하게 거래대금이 강하게 유입되는
순간을 감지하고, 실제 저점 시점으로 소급 RESET한 뒤 RESET 이후의 매수/매도
우위와 가격 반응을 초 단위로 측정한다.

중요 안전 원칙
--------------
1) 기본값은 SHADOW(주문 0)이다. CAPTAIN2_LIVE=YES를 명시해야만 주문 경로가 열린다.
2) 5일선·10일선은 매수/매도 하드 조건으로 사용하지 않는다.
3) 새 TR 및 새 SetRealReg를 호출하지 않는다. 기존 JSON 스냅샷만 읽는다.
4) ★[2026-07-22 실체결 수술] 매수/매도 체결량은 틱룰 실측만 쓴다 — 폴링 간
   누적거래량 증가분(실제 체결량)을 가격 방향(↑매수/↓매도/보합=직전방향)으로 분류.
   누적 체결강도 역산 '추정'은 친구님 지시로 완전히 제거됐다(재도입 금지).
5) 실전 전환 전 최소 수 거래일 SHADOW 검증이 필요하다.

입력
----
C:\\stock_bot\\IPC\\live_micro_snapshot.json
C:\\stock_bot\\data\\micro_rank_board.json
C:\\stock_bot\\data\\_code_name_cache.json (선택)

출력
----
C:\\stock_bot\\data\\captain2_state.json
C:\\stock_bot\\data\\shadow\\captain2_events_YYYYMMDD.csv
C:\\stock_bot\\LOG\\captain2_moneyflow.log
"""
from __future__ import annotations

import csv
import faulthandler
import json
from collections import deque
import logging
import math
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# ★[2026-07-22] 공용 슬롯 장부 — 계좌는 1개, 모든 전략 합쳐 최대 6종목.
#   캡틴1·골짜기가 이미 쓰는 바로 그 파일(data\shared_slots.json)을 그대로 공유한다.
sys.path.insert(0, r"C:\stock_bot\RUN")
import shared_slots as shared      # noqa: E402
from captain2_common_hold_sell_v1 import (  # noqa: E402
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)
from captain2_strategy_01_live_bridge_v1 import (  # noqa: E402
    STRATEGY_NAME as C2_01_STRATEGY_NAME,
    select_fresh_signals,
)
from valley_common_exit_shadow_v1 import SideWindows, build_observation  # noqa: E402


# =============================================================================
# 설정
# =============================================================================

@dataclass(frozen=True)
class Config:
    snapshot_path: Path = Path(os.environ.get(
        "CAPTAIN2_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    micro_board_path: Path = Path(os.environ.get(
        "CAPTAIN2_MICRO_BOARD", r"C:\stock_bot\data\micro_rank_board.json"))
    selector_board_path: Path = Path(os.environ.get(
        "CAPTAIN2_SELECTOR_BOARD", r"C:\stock_bot\data\돈흐름_선별판.json"))
    selector_gate_on: bool = os.environ.get(
        "CAPTAIN2_SELECTOR_GATE_ON", "1").strip() == "1"
    selector_refresh_sec: float = float(os.environ.get("CAPTAIN2_SELECTOR_REFRESH_SEC", "5"))
    early_watch_path: Path = Path(os.environ.get(
        "CAPTAIN2_EARLY_WATCH", r"C:\stock_bot\IPC\micro_watch_captain2.json"))
    name_cache_path: Path = Path(os.environ.get(
        "CAPTAIN2_NAME_CACHE", r"C:\stock_bot\data\_code_name_cache.json"))
    state_path: Path = Path(os.environ.get(
        "CAPTAIN2_STATE", r"C:\stock_bot\data\captain2_state.json"))
    event_dir: Path = Path(os.environ.get(
        "CAPTAIN2_EVENT_DIR", r"C:\stock_bot\data\shadow"))
    log_path: Path = Path(os.environ.get(
        "CAPTAIN2_LOG", r"C:\stock_bot\LOG\captain2_moneyflow.log"))
    manual_block_path: Path = Path(os.environ.get(
        "CAPTAIN2_MANUAL_BLOCK", r"C:\stock_bot\config\manual_buy_block.flag"))
    off_flag_path: Path = Path(os.environ.get(
        "CAPTAIN2_OFF_FLAG", r"C:\stock_bot\config\captain2_off.flag"))

    live: bool = os.environ.get("CAPTAIN2_LIVE", "NO").strip().upper() == "YES"
    qty_fixed: int = int(os.environ.get("CAPTAIN2_QTY_FIX", "1"))
    loop_sec: float = float(os.environ.get("CAPTAIN2_LOOP_SEC", "1.0"))
    entry_start: str = os.environ.get("CAPTAIN2_ENTRY_START", "0930")
    entry_end: str = os.environ.get("CAPTAIN2_ENTRY_END", "1520")
    force_exit: str = os.environ.get("CAPTAIN2_FORCE_EXIT", "1525")
    program_end: str = os.environ.get("CAPTAIN2_END", "1530")

    # FLOW 감지. 기존 micro_rank_engine의 money_start_raw/START를 우선 사용한다.
    min_burst_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BURST", "3.0"))
    min_money_add_5s: float = float(os.environ.get("CAPTAIN2_MIN_ADD5S", "0"))

    # 저점 탐색/확정
    low_search_max_sec: float = float(os.environ.get("CAPTAIN2_LOW_SEARCH_MAX", "5.0"))
    low_no_new_sec: float = float(os.environ.get("CAPTAIN2_LOW_NO_NEW_SEC", "2.0"))
    low_confirm_ticks: int = int(os.environ.get("CAPTAIN2_LOW_CONFIRM_TICKS", "1"))

    # RESET 후 초기 진입 확인. 절대 체결강도보다 RESET 이후 상대 매수 우위를 주축으로 둔다.
    buy_min_elapsed_sec: float = float(os.environ.get("CAPTAIN2_BUY_MIN_SEC", "2.0"))
    buy_max_elapsed_sec: float = float(os.environ.get("CAPTAIN2_BUY_MAX_SEC", "6.0"))
    min_reset_exec_volume: float = float(os.environ.get("CAPTAIN2_MIN_RESET_VOL", "1"))
    min_buy_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BUY_RATIO", "0.58"))
    min_buy_sell_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BS_RATIO", "1.35"))
    buy_confirm_sec: float = float(os.environ.get("CAPTAIN2_BUY_CONFIRM_SEC", "2.0"))
    min_price_ticks: int = int(os.environ.get("CAPTAIN2_MIN_PRICE_TICKS", "1"))

    # 보유/경계/청산

    hard_stop_bottom_pct: float = float(os.environ.get("CAPTAIN2_STOP_BOTTOM_PCT", "-2.0"))
    hard_stop_pull_pct: float = float(os.environ.get("CAPTAIN2_STOP_PULL_PCT", "-3.0"))
    hard_stop_pull_buy_pct: float = float(os.environ.get("CAPTAIN2_STOP_PULL_BUY_PCT", "-4.0"))
    watch_buy_ratio: float = float(os.environ.get("CAPTAIN2_WATCH_BUY_RATIO", "0.52"))
    sell_buy_ratio: float = float(os.environ.get("CAPTAIN2_SELL_BUY_RATIO", "0.48"))
    watch_confirm_sec: float = float(os.environ.get("CAPTAIN2_WATCH_CONFIRM_SEC", "2.0"))
    # ★[2026-07-22 매도수술] 전략매도 조건(매도우위+구조붕괴)이 이 시간 '연속 유지'돼야 매도.
    #   첫날 실측(키움 분봉): 매도 후 +15분에 76%가 매도가보다 위(평균 +0.41%) = 문턱 노이즈 조기매도.
    #   구조붕괴가 '직전 5초 저가 하회'라 하락틱 1개에도 참이 되므로, 지속 요구가 노이즈 교차를 차단한다.
    sell_confirm_sec: float = float(os.environ.get("CAPTAIN2_SELL_CONFIRM_SEC", "15"))
    # ★[ROLL-LIVE 2026-07-22 친구님 "지금 연결"] 회전과다 근본수술 2종.
    #   ①매도 흐름판정을 'RESET 이후 누적'(분모가 계속 자라 50%로 평균회귀 → 48% 하회가 시간문제
    #     = 회전기계)에서 '최근 flow_window_sec초 구간'으로 교체. 임계값(52/48%·지속15초·구조붕괴)은
    #     무변경 — 재는 대상만 '현재 흐름'으로 바로잡는다(스펙 10항: 매도세가 "우위로 바뀌면").
    #     60초 근거 = 오늘 실측 노이즈 dip 4~24초를 덮는 최소 구간.
    flow_window_sec: float = float(os.environ.get("CAPTAIN2_FLOW_WINDOW_SEC", "60"))
    #   ②진입 신뢰도 — RESET 이후 실제 유입대금 하한. 오늘 실측: 0.1억 미만 '먼지' 진입이
    #     37건 중 22건 = 회전과다의 몸통. 스펙 운영원칙("대금 규모·속도는 신뢰도에 사용")의 실구현.
    min_entry_money_krw: float = float(os.environ.get("CAPTAIN2_MIN_ENTRY_MONEY_KRW", "10000000"))

    # ★[보완3종 2026-07-22] ㉮이익 보호 트레일 → ★[설계8단계 2026-07-22 친구님 "지금 배선해"]
    #   단계식으로 승격 — 친구님 명시값: 고점수익 +2%↑→되돌림 0.8% / +4%↑→1.0% / +7%↑→1.5%.
    #   도달한 최고 구간의 폭을 적용(수익이 클수록 넓게 = 큰 상승을 끝까지 탄다). 형식 "무장:폭,..."
    trail_steps_raw: str = os.environ.get("CAPTAIN2_TRAIL_STEPS", "2:0.8,4:1.0,7:1.5")
    # ★[설계8단계] ⑤이평 보유 허가증 — 캡틴1 검증 소스(eod_daily_bars.csv·매일 저녁 갱신) 재사용.
    #   새 TR 0. 267MB라 백그라운드 스레드 로드(이평은 보조라 수십 초 늦게 켜져도 무해).
    eod_bars_path: Path = Path(os.environ.get(
        "CAPTAIN2_EOD_BARS", r"C:\stock_bot\data\eod_daily_bars.csv"))
    # ★[수익성 진단 2026-07-24] 일봉 5·20선이 모두 60선 아래인 역배열은 신규매수 금지.
    #   돈흐름 공용 캐시를 재사용해 새 TR·대용량 CSV 재로딩 없이 세 진입 레인에 동일 적용한다.
    reverse_ma_gate_on: bool = os.environ.get(
        "CAPTAIN2_REVERSE_MA_GATE_ON", "1").strip() == "1"
    ma60_cache_path: Path = Path(os.environ.get(
        "CAPTAIN2_MA60_CACHE", r"C:\stock_bot\data\돈흐름_ma60.json"))
    #   허가증 효과 = "조금 더 끌고 간다" — 흐름매도 지속확인 시간 배수(돈이 살아있을 때만 발동).
    ma_permit_confirm_mult: float = float(os.environ.get("CAPTAIN2_MA_PERMIT_CONFIRM_MULT", "2.0"))
    # ★[3분봉 상승보유 2026-07-24] RAID 보유 중 5·10선이 상향으로 만나고 20선이
    #   우상향하면 20선 이탈 전까지 일반 전략매도를 유예한다. 하드컷·강제청산은 항상 우선한다.
    ma3_rider_on: bool = os.environ.get("CAPTAIN2_MA3_RIDER_ON", "1").strip() == "1"
    ma3_converge_pct: float = float(os.environ.get("CAPTAIN2_MA3_CONVERGE_PCT", "0.5"))
    ma3_bars_path: Path = Path(os.environ.get(
        "CAPTAIN2_MA3_BARS", r"C:\stock_bot\data\prices_3m.csv"))
    # ㉯돈 마름(속도 소멸) 매도 — "돈이 빠질 때까지 보유"의 대우: 유입속도가 보유 중 피크의
    #   20% 아래로 30초 지속 붕괴하면 돈이 빠진 것. 보유 60초·피크 0.01억/초 미만이면 판정 안 함.
    dryup_frac: float = float(os.environ.get("CAPTAIN2_DRYUP_FRAC", "0.2"))
    dryup_confirm_sec: float = float(os.environ.get("CAPTAIN2_DRYUP_CONFIRM_SEC", "30"))
    dryup_min_hold_sec: float = float(os.environ.get("CAPTAIN2_DRYUP_MIN_HOLD_SEC", "60"))
    dryup_min_peak_mps: float = float(os.environ.get("CAPTAIN2_DRYUP_MIN_PEAK_MPS", "1000000"))
    # ㉰큰돈 감지 문턱 — 오늘 FLOW 감지 619종목·전부 SMALL 진입. 감지 시 5초 유입속도가
    #   분당 1억(캡틴1 검증 안전핀)=1,666,667원/초 미만이면 급증으로 보지 않는다(오늘 감지의 58% 차단).
    surge_min_mps: float = float(os.environ.get("CAPTAIN2_SURGE_MIN_MPS", "1666667"))
    # ㉱우위 지속성 — 진입 직전 최근10초 유입속도가 최근30초의 절반 미만이면 '한 방 반짝'으로
    #   보고 진입 보류(오늘 실측: 2~6초 순간 매수비율은 승자 변별력 0 — 지속성이 유력 가설).
    persist_min_frac: float = float(os.environ.get("CAPTAIN2_PERSIST_MIN_FRAC", "0.5"))
    structure_lookback_sec: float = float(os.environ.get("CAPTAIN2_STRUCTURE_SEC", "5.0"))
    max_positions: int = int(os.environ.get("CAPTAIN2_MAX_POSITIONS", "6"))
    # ★[2026-07-22] 0 = 하루 진입 횟수 무제한(로테이션이 하루 3회에서 끊기던 제한 해제)
    max_entries_day: int = int(os.environ.get("CAPTAIN2_MAX_ENTRIES", "0"))
    # 하루 누적 매수액이 아니라 현재 보유+매수대기 원금만 제한한다. 매도 체결 뒤 즉시 재사용.
    max_active_capital_krw: float = float(os.environ.get(
        "CAPTAIN2_MAX_ACTIVE_CAPITAL_KRW",
        os.environ.get("CAPTAIN2_MAX_DAILY_BUY_KRW", "2000000")))
    # 표본 확보용: 0이면 일손실/연속손실에 따른 신규진입 중단을 사용하지 않는다.
    max_daily_loss_krw: float = float(os.environ.get("CAPTAIN2_MAX_DAILY_LOSS_KRW", "0"))
    max_consecutive_losses: int = int(os.environ.get("CAPTAIN2_MAX_CONSECUTIVE_LOSSES", "0"))
    # ★[2026-07-22] 전역 쿨다운 → '종목별' 쿨다운으로 의미 변경. 같은 루프에서 서로 다른 종목이
    #   빈 슬롯만큼 동시에 진입할 수 있어야 하므로, 이 값은 동일 종목 재진입만 막는 데 쓴다.
    #   (동일 종목 재진입은 CLOSED/FAILED 재무장 로직에서도 같은 값으로 한 번 더 걸린다)
    cooldown_sec: float = float(os.environ.get("CAPTAIN2_COOLDOWN_SEC", "20"))

    # ★[눌림레인 2026-07-22 친구님 "오늘 자료로 수치 나오면 바로 배선"] 두 레인 분리.
    #   급습(RAID)=현행 5초/6초 유지. 눌림(PULL)=아래 값 전부 7/22 전체시장 1초 캡처의
    #   눌림 3,556사례 분포에서 도출(추측 0):
    #   저점탐색 180초(p90 157 커버·현행 5초는 61% 놓침) · 무갱신 확정 15초(신저점→매수우위
    #   전환 중앙 11~p80 21초 어간) · 진입확인창 60초(전환 p90 32 + 재가속 p90 41 완결) ·
    #   지속확인 5초 · 분리 기준 = 직전 에피소드 고점 대비 -0.8%(사례 정의 하한) ·
    #   직전 에피소드 유효기간 30분. 권장창 진입 시 추격화(저점+1.5% 초과)는 실측 9%.
    pull_low_search_max_sec: float = float(os.environ.get("CAPTAIN2_PULL_LOW_SEARCH_MAX", "180"))
    pull_low_no_new_sec: float = float(os.environ.get("CAPTAIN2_PULL_LOW_NO_NEW_SEC", "15"))
    pull_buy_max_sec: float = float(os.environ.get("CAPTAIN2_PULL_BUY_MAX_SEC", "60"))
    pull_buy_confirm_sec: float = float(os.environ.get("CAPTAIN2_PULL_BUY_CONFIRM_SEC", "5"))
    pull_split_drop_pct: float = float(os.environ.get("CAPTAIN2_PULL_SPLIT_DROP_PCT", "0.8"))
    # ★[PULL 고점차단 2026-07-24] 0.8%는 관찰 시작 기준일 뿐 매수 허용 깊이가 아니다.
    #   실제 매수는 고점→L2 저점 깊이 2% 이상이며, 저점에서 고점으로 60% 넘게 회복하기 전만 허용한다.
    pull_min_depth_pct: float = float(os.environ.get("CAPTAIN2_PULL_MIN_DEPTH_PCT", "2.0"))
    pull_max_recovery_pct: float = float(os.environ.get("CAPTAIN2_PULL_MAX_RECOVERY_PCT", "60"))
    pull_prev_max_age_sec: float = float(os.environ.get("CAPTAIN2_PULL_PREV_MAX_AGE_SEC", "1800"))

    # ★[BASE 횡보돌파 2026-07-24 친구님 승인] 응집폭발의 검증된 완성 1분봉 조건을
    #   캡틴2 독립 레인으로 이식한다. 5배 그림자는 비용 전 본전이었고, 실전값 6배는
    #   7건 중 5승(+3.64%p, 비용 전)이어서 6배만 사용한다. 돌파 추격은 금지하고
    #   10분 안 돌파선 리테스트 뒤 기존 실제 저점·매수우위 관문으로 진입한다.
    base_on: bool = os.environ.get("CAPTAIN2_BASE_ON", "1").strip() == "1"
    base_bars_path: Path = Path(os.environ.get(
        "CAPTAIN2_BASE_BARS", r"C:\stock_bot\data\돈맥_1분봉.json"))
    base_seed_ledger_path: Path = Path(os.environ.get(
        "CAPTAIN2_BASE_SEED_LEDGER", r"C:\stock_bot\data\base_breakout_shadow_ledger.json"))
    base_n: int = int(os.environ.get("CAPTAIN2_BASE_N", "30"))
    base_tight_pct: float = float(os.environ.get("CAPTAIN2_BASE_TIGHT_PCT", "3.0"))
    base_volx: float = float(os.environ.get("CAPTAIN2_BASE_VOLX", "6.0"))
    base_wait_bars: int = int(os.environ.get("CAPTAIN2_BASE_WAIT_BARS", "10"))
    # 7/23 6배 이상 리테스트 4건 실측: 실제 저점 0.1~66.9초, 저점 뒤 매수관문 최대 57초.
    # BASE만 90/60초로 분리한다. RAID 5/6초·PULL 180/60초는 그대로다.
    base_low_search_max_sec: float = float(os.environ.get("CAPTAIN2_BASE_LOW_SEARCH_MAX", "90"))
    base_buy_max_sec: float = float(os.environ.get("CAPTAIN2_BASE_BUY_MAX_SEC", "60"))
    base_entry_start: str = os.environ.get("CAPTAIN2_BASE_ENTRY_START", "0930")
    base_entry_end: str = os.environ.get("CAPTAIN2_BASE_ENTRY_END", "1430")

    # ★[재가속 재돌파 2026-07-24] 완성 3분봉 재돌파 뒤 돌파선 유지·추격상한·
    #   VWAP·정확 FID15 매수우위를 모두 통과하면 기존 후보 풀로 보내 1주 주문체계를 재사용한다.
    reaccel_shadow_on: bool = os.environ.get(
        "CAPTAIN2_REACCEL_SHADOW_ON", "1").strip() == "1"
    reaccel_live_on: bool = os.environ.get(
        "CAPTAIN2_REACCEL_LIVE_ON", "0").strip() == "1"
    reaccel_start: str = os.environ.get("CAPTAIN2_REACCEL_START", "0930")
    reaccel_end: str = os.environ.get("CAPTAIN2_REACCEL_END", "1420")
    reaccel_min_day_gain_pct: float = float(os.environ.get(
        "CAPTAIN2_REACCEL_MIN_DAY_GAIN_PCT", "3.0"))
    reaccel_min_age_bars: int = int(os.environ.get("CAPTAIN2_REACCEL_MIN_AGE_BARS", "5"))
    reaccel_max_ext_pct: float = float(os.environ.get("CAPTAIN2_REACCEL_MAX_EXT_PCT", "1.5"))
    reaccel_min_volx: float = float(os.environ.get("CAPTAIN2_REACCEL_MIN_VOLX", "1.2"))
    reaccel_max_surge5_pct: float = float(os.environ.get(
        "CAPTAIN2_REACCEL_MAX_SURGE5_PCT", "5.0"))
    reaccel_gate_max_sec: float = float(os.environ.get(
        "CAPTAIN2_REACCEL_GATE_MAX_SEC", "60"))

    # ★[EARLY 초입레인 2026-07-23 친구님 확정] "돈이 처음 몰리는 초입"을 RESET 저점확정 없이 잡는
    #   별도 레인. 수치 전부 7/23 1초캡처 실측(발화81·성공50·승률62%·비용후 +0.24%)에서 도출 — 추측 0.
    #   EARLY는 장전 전일대금 상위 감시풀과 현재 유입속도로 초입을 잡는다.
    #   일반·재가속 레인은 당일 누적대금 100억원 공통관문을 그대로 유지한다.
    #   증가배율은 개장 첫 30초 면제(30초창 미형성 — 실측 규칙에 포함), 매수대금비율은 첫 10초
    #   개장누적 폴백(10초 전 데이터 부재 — 실측과 동일). FID15 4필드 없으면 발화 안 함(fail-closed).
    early_on: bool = os.environ.get("CAPTAIN2_EARLY_ON", "1").strip() == "1"
    early_start: str = os.environ.get("CAPTAIN2_EARLY_START", "0900")
    early_end: str = os.environ.get("CAPTAIN2_EARLY_END", "0919")
    early_min_speed: float = float(os.environ.get("CAPTAIN2_EARLY_MIN_SPEED", "1666667"))
    early_min_burst: float = float(os.environ.get("CAPTAIN2_EARLY_MIN_BURST", "3.0"))
    early_burst_waive_sec: float = float(os.environ.get("CAPTAIN2_EARLY_BURST_WAIVE_SEC", "30"))
    early_min_buy_ratio: float = float(os.environ.get("CAPTAIN2_EARLY_MIN_BUY_RATIO", "0.70"))
    early_persist_sec: int = int(os.environ.get("CAPTAIN2_EARLY_PERSIST_SEC", "3"))
    early_max_above_open_pct: float = float(os.environ.get("CAPTAIN2_EARLY_MAX_ABOVE_OPEN_PCT", "3.0"))
    early_gap_min_pct: float = float(os.environ.get("CAPTAIN2_EARLY_GAP_MIN_PCT", "3.0"))
    early_dip_no_new_sec: float = float(os.environ.get("CAPTAIN2_EARLY_DIP_NO_NEW_SEC", "2"))
    early_decision_hm: str = os.environ.get("CAPTAIN2_EARLY_DECISION_HM", "0920")
    early_force_exit_hm: str = os.environ.get("CAPTAIN2_EARLY_FORCE_EXIT_HM", "0930")
    early_trend_min_buy_ratio: float = float(os.environ.get("CAPTAIN2_EARLY_TREND_MIN_BUY_RATIO", "0.52"))
    early_trend_speed_frac: float = float(os.environ.get("CAPTAIN2_EARLY_TREND_SPEED_FRAC", "0.5"))
    # 시가 폴백(엔진이 09:01 이후 재시작한 경우): 돈맥_1분봉.json의 op(당일 시가). 없으면 그 종목 EARLY 금지.
    early_m1_path: Path = Path(os.environ.get("CAPTAIN2_EARLY_M1", r"C:\stock_bot\data\돈맥_1분봉.json"))

    # ★[VWAP 3종 2026-07-23 친구님 확정 — 7/23 매도감사 근거] VWAP=(FID15 매수+매도대금)÷누적거래량.
    #   감사 실측: 손실 2건(주성·제주) 모두 매수 순간부터 VWAP 아래(꼭지 자리) — VWAP 진입관문이면 원천 차단.
    #   지엔씨는 5/10일선·VWAP 위 + 직전10초 매수비 97% 폭주 중 트레일 조기매도(반납 2.21%p+재매수 왕복).
    #   원칙: VWAP '하나만'으로 매매하지 않는다 — 진입은 기존 조건에 관문 추가, 매도는 3중 동시확인.
    #   VWAP 무효(FID15 부재·누적량 리셋 글리치=현재가의 0.5~2배 밖) 시 관문 통과(fail-open — 전면중단 방지).
    # C2-01 장초반 급상승 초입. 주문0 감시기가 확정한 신선한 신호만 기존 주문 경로에 전달한다.
    c2_01_on: bool = os.environ.get("CAPTAIN2_C2_01_ON", "0").strip() == "1"
    c2_01_signal_path: Path = Path(os.environ.get(
        "CAPTAIN2_C2_01_SIGNAL", r"C:\stock_bot\data\captain2_c2_01_shadow.json"))
    c2_01_signal_max_age_sec: float = float(os.environ.get(
        "CAPTAIN2_C2_01_SIGNAL_MAX_AGE_SEC", "5"))
    c2_01_max_order_attempts: int = int(os.environ.get(
        "CAPTAIN2_C2_01_MAX_ORDER_ATTEMPTS", "1"))

    vwap_gate_on: bool = os.environ.get("CAPTAIN2_VWAP_GATE_ON", "1").strip() == "1"
    #   보유 중 VWAP 이탈 = 즉시매도 아님 → 조기경보. 경보 중 '매도대금 우위(기존 48% 임계 재사용)
    #   + 돈 속도 약화(기존 persist_min_frac 0.5 재사용) + 가속 아님'이 함께 확인될 때만 매도.
    vwap_warn_exit_on: bool = os.environ.get("CAPTAIN2_VWAP_WARN_EXIT_ON", "1").strip() == "1"
    #   PROFIT_TRAIL 유예: 최근 10초 실제 매수대금비율 ≥ 90%(친구님 명시) + 속도 유지(약화 아님)면
    #   트레일 보류. 돈이 약해지거나 매도우위로 바뀌면 즉시 해제(다음 루프 트레일 정상 발동).
    trail_money_guard_on: bool = os.environ.get("CAPTAIN2_TRAIL_MONEY_GUARD_ON", "1").strip() == "1"
    trail_guard_buy_ratio: float = float(os.environ.get("CAPTAIN2_TRAIL_GUARD_BUY_RATIO", "0.90"))

    # ★[돈 중심 매도 점수 엔진 2026-07-23 친구님 확정 구조] NORMAL(0~24)→WATCH(25~)→WARNING(50~)
    #   →SELL READY(75~)→[최근5초 매수대금 증가? YES=HOLD 유예(최대10초) / NO=SELL]→강제SELL.
    #   HARD_STOP -3%는 최후 보험으로 그대로(대부분 그 전에 점수매도로 끝나는 구조).
    #   근거(7/23 재감사): 손실 2건 모두 매수 후 48초 안에 3신호(VWAP·속도·역전) 완성 — 실제 매도는
    #   3.5분·18분 뒤 -3%에서. 3신호 완성 시점 탈출 시 +1.8/+2.4%p 절감, 지엔씨 익절은 안 망침.
    #   배점: ⓐVWAP 이탈 +25 ⓑ속도 피크50%↓ +25(20%↓ +40) ⓒ30초 매수<매도 +25(매수비35%↓ +35)
    #   ⓓ가속 중 총점 ×0.5. 단일 신호=노이즈(지엔씨 ③이 매수4초 발화 후 +2.8% 상승) — 75+는
    #   3계열 동시일 때만 도달 가능한 배점. ON이면 기존 VWAP_WARN_EXIT(부분집합)를 대체한다.
    score_sell_on: bool = os.environ.get("CAPTAIN2_SCORE_SELL_ON", "1").strip() == "1"
    score_sell_ready: float = float(os.environ.get("CAPTAIN2_SCORE_SELL_READY", "75"))
    score_warning: float = float(os.environ.get("CAPTAIN2_SCORE_WARNING", "50"))
    score_watch: float = float(os.environ.get("CAPTAIN2_SCORE_WATCH", "25"))

    score_dry_confirm_sec: float = float(os.environ.get("CAPTAIN2_SCORE_DRY_CONFIRM_SEC", "5"))
    score_min_hold_sec: float = float(os.environ.get("CAPTAIN2_SCORE_MIN_HOLD_SEC", "30"))
    score_bottom_min_hold_sec: float = float(os.environ.get("CAPTAIN2_SCORE_BOTTOM_MIN_HOLD_SEC", "60"))
    score_peak_min_mps: float = float(os.environ.get("CAPTAIN2_SCORE_PEAK_MIN_MPS", "1000000"))

    # ★[재진입 가드 2026-07-23 친구님 확정 — 진입검증 2단계] 같은 종목 재진입은 '직전 회차보다
    #   신호가 강할 때만' 허용(시간 쿨다운 아님). 7/23 지엔씨 3회전 실측: 유입 1.6→0.8→0.2억·
    #   속도 0.33→0.14→0.03억/초·매수비 97→88→82%로 세 지표 전부 단조 약화 → 2·3차가 손실.
    #   1차 매수 후 보유했으면 +11.78%인데 3회전으로 -1.40%(기회비용 13.18%p). 유입대금·유입속도가
    #   모두 직전 진입 이상이어야 재진입(매수비는 오차단 위험 때문에 제외 — _reentry_ok 참조).
    #   (유입대금 '하한 상향'은 구간별 비용후 전부 마이너스로 데이터 근거 없어 미적용)
    reentry_guard_on: bool = os.environ.get("CAPTAIN2_REENTRY_GUARD_ON", "1").strip() == "1"
    max_entries_per_code: int = int(os.environ.get("CAPTAIN2_MAX_ENTRIES_PER_CODE", "2"))
    reentry_strength_mult: float = float(os.environ.get("CAPTAIN2_REENTRY_STRENGTH_MULT", "1.3"))
    reentry_buy_ratio_add: float = float(os.environ.get("CAPTAIN2_REENTRY_BUY_RATIO_ADD", "0.05"))

    # ★[VI 거부 대응 2026-07-23 친구님 확정] VI 거부→해제 확인→1~2초 대기→동일수량 재주문→최대 3회
    #   (max_sell_retry=3 재사용)→실패 시 로그 후 종료. 7/23 지엔씨 실측: VI 단일가 2분간 최유리
    #   매도 11발 전부 거부 — 거부는 fills·미체결조회 어디에도 안 남아 엔진이 인지 불가했다.
    #   → VI를 데이터로 감지(누적거래량 50%↓ 급감 리셋=예상체결 전환, 복귀=해제. 새 TR 0).
    #   VI 중엔 매도 발사 보류(맹목 재주문 중단), 해제 후 vi_reorder_wait_sec 대기 뒤 재주문.
    #   상한 도달 후에도 HARD_STOP·TIME_EXIT(최후 보험)는 통과한다(친구님 "하드스톱 유지" 원칙).
    vi_reorder_wait_sec: float = float(os.environ.get("CAPTAIN2_VI_REORDER_WAIT_SEC", "1.5"))

    stale_snapshot_sec: float = float(os.environ.get("CAPTAIN2_STALE_SNAPSHOT_SEC", "3"))
    stale_board_sec: float = float(os.environ.get("CAPTAIN2_STALE_BOARD_SEC", "5"))
    stale_recovery_sec: float = float(os.environ.get("CAPTAIN2_STALE_RECOVERY_SEC", "5"))

    # ★[구조판정 SHADOW 2026-07-24 친구님 승인] 계층 B(장중 대장주 구조판정)를 '그림자'로 병렬 기록.
    #   검증(1분봉 30일·대장244): 구조 3/3(종가<VWAP & 직전5완성분봉 저점이탈 & 최근60초 순매도)이
    #   정상눌림 조기매도 12%(고정트레일 1.5%=41%)·터미널 포착 78%. 실매도는 일절 바꾸지 않고,
    #   기존 엔진의 실제 매도와 구조엔진 판정을 같은 시각에 나란히 기록만 한다(전부 try/except).
    #   끄기: CAPTAIN2_STRUCT_SHADOW_ON=0. min_bars=직전 완성분봉 최소 개수(그 미만이면 UNKNOWN).
    struct_shadow_on: bool = os.environ.get("CAPTAIN2_STRUCT_SHADOW_ON", "1").strip() == "1"
    struct_shadow_min_bars: int = int(os.environ.get("CAPTAIN2_STRUCT_SHADOW_MIN_BARS", "3"))
    # ★[수급 가점 2026-07-23 친구님 승인 "고"] D-2(2거래일 전) 기관/외인 매집 종목을 슬롯 경합 시
    #   같은 우위 버킷 안에서 우선. 관문 아님 — 매수 차단 0·순서만 변경. 백테(12일·691신호):
    #   매집 그룹 전 축 우위·D-2 외인 비용후 +0.18% vs 비매집 -0.93%. EARLY 정렬은 확정 스펙이라 무적용.
    supply_boost_on: bool = os.environ.get("CAPTAIN2_SUPPLY_BOOST_ON", "1").strip() == "1"
    theme_leader_bonus_on: bool = os.environ.get("CAPTAIN2_THEME_LEADER_BONUS_ON", "1").strip() == "1"
    theme_leader_max_age_min: float = float(os.environ.get("CAPTAIN2_THEME_LEADER_MAX_AGE_MIN", "30"))

    # ★[2026-07-22] 시장 필터 — 잡주 제거. 기존 RESET/매수우위/WATCH/SELL 임계값과 무관한 별도 관문.
    #   현재가 1만원 미만 또는 당일 거래대금 100억원 미만이면 LOW_SEARCH/RESET/BUY_READY/BUY 전부 금지.
    #   단 이미 HOLD·WATCH 중인 종목의 매도 추적에는 적용하지 않는다(가격이 내려갔다고 매도하지 않음).
    min_price: float = float(os.environ.get("CAPTAIN2_MIN_PRICE", "10000"))
    min_today_value_krw: float = float(os.environ.get("CAPTAIN2_MIN_TODAY_VALUE_KRW", "10000000000"))

    # ★[2026-07-22 체결층 이식] 접수 ≠ 체결. 이 시간 안에 전량 체결 못 하면 잔량 취소 후 확정.
    #   기본 8초 = 캡틴1 실전값(MC_FILL_WAIT 코드 기본값, cmd 미지정)과 동일. 변수만 분리한다.
    fill_wait_sec: float = float(os.environ.get("CAPTAIN2_FILL_WAIT_SEC", "8"))
    fills_dir: Path = Path(os.environ.get("CAPTAIN2_FILLS_DIR", r"C:\stock_bot\LOG"))
    rt_open_path: Path = Path(os.environ.get(
        "CAPTAIN2_RT_OPEN", r"C:\stock_bot\data\rt_open_positions.json"))
    # rt_open_positions.json 허용 나이(초). 이 파일의 주인은 reconcile(--write)이고 08:50·15:35
    #   하루 2회만 쓴다. 08:50에 쓰인 파일이 장 마감(15:30)까지 유효해야 하므로 기본 8시간.
    #   이보다 오래됐거나 오늘 안 쓰였으면 계좌 진실을 못 믿는 것으로 보고 LIVE 신규매수를 막는다.
    rt_open_max_age_sec: float = float(os.environ.get("CAPTAIN2_RT_OPEN_MAX_AGE_SEC", "28800"))
    max_sell_retry: int = int(os.environ.get("CAPTAIN2_MAX_SELL_RETRY", "3"))

    # ★[2026-07-22 관찰전용] 초단위 재생 로그 — CAPTAIN2가 추적 중인 종목만 기록(전체시장 캡처 아님).
    #   판정에는 일절 쓰지 않는다. 기록 실패가 전략 루프를 멈추지 않는다.
    replay_dir: Path = Path(os.environ.get(
        "CAPTAIN2_REPLAY_DIR", r"C:\stock_bot\data\shadow\captain2_replay"))
    replay_enabled: bool = os.environ.get("CAPTAIN2_REPLAY", "YES").strip().upper() == "YES"
    replay_flush_rows: int = int(os.environ.get("CAPTAIN2_REPLAY_FLUSH_ROWS", "100"))
    replay_flush_sec: float = float(os.environ.get("CAPTAIN2_REPLAY_FLUSH_SEC", "5"))


# =============================================================================
# 모델
# =============================================================================

class Phase(str, Enum):
    IDLE = "IDLE"
    LOW_SEARCH = "LOW_SEARCH"
    RESET = "RESET"
    BUY_READY = "BUY_READY"
    # ★[2026-07-22 체결층 이식] 접수 ≠ 체결. 주문 응답 OK/TIMEOUT만으로 HOLD/CLOSED로 가지 않는다.
    BUY_PENDING = "BUY_PENDING"      # 매수 주문 접수됨 — 실체결 확인 전
    SELL_PENDING = "SELL_PENDING"    # 매도 주문 접수됨 — 실체결 확인 전
    HOLD = "HOLD"
    WATCH = "WATCH"
    # ★[2026-07-22] 재시작 복구에서 RESET 맥락(reset_ts·누적기준·recent_prices 등)을 완전히
    #   되살리지 못한 보유 종목. 전략매도(FLOW_WEAK+STRUCTURE_BREAK)는 근거가 없으므로 쓰지 않고
    #   HARD_STOP과 TIME_EXIT만 작동시킨다.
    RECOVERY_HOLD = "RECOVERY_HOLD"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass
class MarketPoint:
    ts: datetime
    code: str
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float = 0.0
    bid_tot: float = 0.0
    imb: float = 0.0
    money_add_5s: float = 0.0
    money_speed_5s: float = 0.0
    money_speed_10s: float = 0.0
    money_speed_30s: float = 0.0
    money_start: bool = False
    money_start_raw: bool = False
    theme_leader: bool = False
    theme_signal: str = ""
    # ★[2026-07-22] 당일 거래대금(원). 실측 결과 입력 JSON 두 개 어디에도 '누적' 당일거래대금 필드가
    #   없다(board의 money_* 는 전부 5s~180s 롤링 윈도우, snapshot은 cur/cum_vol/che_str/호가뿐).
    #   → 새 TR 없이 현재 데이터만으로 만드는 근사값: 현재가 × 당일누적거래량.
    #   정확한 체결가중 거래대금이 아니므로 로그·CSV에 source=EST_PRICE_X_CUMVOL 로 명시한다.
    today_value_krw: float = 0.0
    # ★[REAL-SIDE 2026-07-22] 브로커가 부호체결(FID15)로 쌓은 '실제' 방향별 누계(스냅샷 4필드).
    #   -1.0 = 필드 없음(구스냅샷/브로커 수술 전) — 이때만 틱룰 근사로 폴백한다.
    buy_vol_cum: float = -1.0
    sell_vol_cum: float = -1.0
    buy_money_cum: float = -1.0
    sell_money_cum: float = -1.0


@dataclass
class CandidateLow:
    ts: datetime
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float
    bid_tot: float
    imb: float
    # ★[2026-07-22 실체결 수술] 저점 관측 시점의 '실체결' 누계(추정 아님) — RESET 기준선이 된다
    buy_cum: float
    sell_cum: float
    # ★[REAL-SIDE 2026-07-22] 방향별 실거래대금 누계도 같은 시점에 동결(대금 기준선)
    buy_money: float = 0.0
    sell_money: float = 0.0


@dataclass
class EarlyState:
    """★[EARLY 초입레인 2026-07-23] 종목별 초입 판정 추적 — FlowState(에피소드 단위)와 분리.
    발화는 종목당 하루 1회(fired). hist는 최근 20초의 (초epoch, FID15매수누계, 매도누계, 가격)."""
    bm0: float = -1.0                  # 개장 후 첫 관측 FID15 누계(첫 10초 비율 폴백 기준선)
    sm0: float = -1.0
    bm0_ts: float = 0.0
    hist: deque = field(default_factory=lambda: deque(maxlen=20))
    streak: int = 0                    # 조건 연속 초(무장가 이상 유지 = 지속)
    last_sec: float = 0.0
    arm_px: float = 0.0                # 무장가 — 이 아래로 밀리면 지속 끊김
    high_px: float = 0.0               # 시가 +3% 선을 먼저 넘긴 추격 이력 차단
    below_open_seen: bool = False
    dip_low: float = 0.0
    dip_low_ts: float = 0.0
    dip_low_speed: float = 0.0
    streak_kind: str = ""
    entry_kind: str = ""
    fired: bool = False
    sort_key: Tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass
class BasePatternState:
    """완성 1분봉 응집돌파 추적. 매수판정은 FlowState(BASE)가 담당한다."""
    hist: deque = field(default_factory=lambda: deque(maxlen=45))
    cap_hm: str = ""
    armed: bool = False
    breakout_hm: str = ""
    limit: float = 0.0
    wait_left: int = 0
    range_pct: float = 0.0
    volx: float = 0.0
    breakout_close: float = 0.0
    retest_started: bool = False


@dataclass
class ReaccelShadowState:
    """완성 3분봉 재돌파와 이후 60초 관문을 추적하는 주문0 전용 상태."""
    bars: deque = field(default_factory=lambda: deque(maxlen=130))
    bucket: int = -1
    bar_hm: str = ""
    bar_open: float = 0.0
    bar_high: float = 0.0
    bar_low: float = 0.0
    bar_close: float = 0.0
    bar_start_cum: float = 0.0
    bar_last_cum: float = 0.0
    status: str = "IDLE"
    arm_ts: Optional[datetime] = None
    signal_price: float = 0.0
    line: float = 0.0
    age: int = 0
    ext_pct: float = 0.0
    volx: float = 0.0
    surge5_pct: float = 0.0
    base_buy_cum: float = 0.0
    base_sell_cum: float = 0.0
    base_buy_money: float = 0.0
    base_sell_money: float = 0.0
    dominance_since: Optional[datetime] = None


@dataclass
class FlowState:
    code: str
    name: str = ""
    phase: Phase = Phase.IDLE
    flow_detect_ts: Optional[datetime] = None
    candidate_low: Optional[CandidateLow] = None
    last_low_update_ts: Optional[datetime] = None
    reset_id: str = ""
    reset_ts: Optional[datetime] = None
    reset_price: float = 0.0
    reset_buy_cum: float = 0.0
    reset_sell_cum: float = 0.0
    # ★[REAL-SIDE 2026-07-22] RESET 시점 방향별 실거래대금 기준선(원)
    reset_buy_money: float = 0.0
    reset_sell_money: float = 0.0
    reset_cum_vol: float = 0.0
    reset_che_str: float = 0.0
    reset_ask_tot: float = 0.0
    reset_bid_tot: float = 0.0
    reset_imb: float = 0.0
    reset_high: float = 0.0
    reset_low: float = 0.0
    structure_low: float = 0.0
    buy_exec_vol: float = 0.0
    sell_exec_vol: float = 0.0
    # ★[REAL-SIDE 2026-07-22] RESET 이후 방향별 실거래대금(원)·대금 비율 — 측정·기록용
    #   (기존 관문 임계값은 무변경 — 친구님 지시: 데이터 완성 먼저, 임계값 임의 변경 금지)
    buy_exec_money: float = 0.0
    sell_exec_money: float = 0.0
    buy_money_ratio: float = 0.5
    side_exact: bool = False          # True=브로커 부호체결(정확) / False=틱룰 근사
    # ★[ROLL-LIVE 2026-07-22] 매도 흐름판정에 실제로 쓰는 '최근 구간' 매수비율(+실측 구간초).
    #   구간 데이터 부족 시 RESET 이후 비율로 폴백(추적 초기엔 그게 곧 최근이다).
    flow_ratio_recent: float = 0.5
    flow_span_recent: float = 0.0
    # ★[ROLL 2026-07-22 관찰전용] 윈도우 길이 튜닝용 실측 3종(판정 미사용)
    roll10_ratio: float = 0.5
    roll30_ratio: float = 0.5
    roll60_ratio: float = 0.5
    roll10_money_ps: float = 0.0
    roll30_money_ps: float = 0.0
    roll60_money_ps: float = 0.0
    # ★[보완3종 2026-07-22] 돈 마름 매도용 — 보유 중 30초 유입속도 피크·붕괴 시작 시각
    hold_peak_money_ps: float = 0.0
    dryup_since: Optional[datetime] = None
    # ★[VWAP 3종 2026-07-23] 보유 중 VWAP 이탈 조기경보 시각(회복 시 None으로 해제)
    vwap_warn_since: Optional[datetime] = None
    # ★[점수 엔진 2026-07-23] 5초 유입속도(money_speed_5s) 보유 중 피크 · SELL READY 진입 시각 ·
    #   현재 상태 문자열(전이 이벤트 기록용 — 상태가 바뀔 때만 이벤트를 남긴다)
    hold_peak_spd5: float = 0.0
    sell_ready_since: Optional[datetime] = None
    score_state: str = "NORMAL"
    # ★[VI 거부 대응 2026-07-23] VI 감지 상태 — 누적거래량 급감(예상체결 전환)=발동 의심,
    #   정상 누적 복귀=해제. VI 중엔 vi_prev_cum_vol을 갱신하지 않는다(예상체결량 오염 방지).
    vi_suspect: bool = False
    vi_prev_cum_vol: float = 0.0
    vi_normal_cum_vol: float = 0.0
    vi_release_epoch: float = 0.0
    vi_hold_logged: bool = False
    sell_exhaust_logged: bool = False
    # ★[설계8단계 2026-07-22] ③가속(매수대금 속도 10>30>60초 서열) ⑤이평 허가증 ①평상시 배율
    money_accel: bool = False
    ma_permit: bool = False
    # ★[3분봉 상승보유] 일봉 허가증과 분리. RAID에서만 일반 전략매도를 잠근다.
    ma3_rider_permit: bool = False
    ma3_ma5: float = 0.0
    ma3_ma10: float = 0.0
    ma3_ma20: float = 0.0
    ma3_hold_logged: bool = False
    morning_hold_logged: bool = False
    money_mult_dayavg: float = 0.0
    # ★[눌림레인 2026-07-22] 레인(RAID=급습/PULL=눌림 반등) + 직전 에피소드 고점(레인 판정용)
    lane: str = "RAID"
    # C2-01만 사용하는 공통 상승보유·매도 엔진 상태. 재시작 뒤에도 같은 판단 순서를 잇는다.
    common_exit_state: Dict[str, Any] = field(default_factory=dict)
    prev_episode_high: float = 0.0
    prev_episode_end_ts: Optional[datetime] = None
    # ★[눌림레인 점검1 수정] 이번 에피소드에서 관측한 최고가 — 감지 시점부터 추적.
    #   저점탐색 단계 실패(어제 17,822건 = 최대 경로)는 reset_high·peak_price가 0이라
    #   이 필드 없이는 "매수 전 눌림 시작" 종목이 PULL로 영영 못 넘어간다(친구님 적중).
    #   한계: 감지가 다리 중간에 발화하므로 진짜 급등 고점보다 약간 낮게 잡힐 수 있음(보수적).
    episode_high: float = 0.0
    # ★[PULL 5조건 2026-07-22 친구님] Higher Low용 — PULL 저점탐색의 1차 확정 저점(L1).
    #   0이면 아직 1차 저점 전. 2차 저점(L2)이 L1보다 높게 확정될 때만 RESET(앵커=L2).
    pull_l1_price: float = 0.0
    # ★[PULL 실제 재눌림 2026-07-24] L1 뒤 반등 고점에서 최소 1틱 다시 내려온 뒤에만
    #   L2 후보 탐색을 시작한다. 단순 상승·횡보를 가짜 L2로 확정하지 않기 위한 상태다.
    pull_rebound_high: float = 0.0
    pull_repull_seen: bool = False
    pull_reference_high: float = 0.0       # PULL 위치 판정용 실제 직전/현재 에피소드 고점
    buy_ratio: float = 0.5
    buy_sell_ratio: float = 1.0
    price_response_pct: float = 0.0
    # ★[2026-07-22] RESET 이후 '실제 신규 유입대금'의 크기와 속도(관찰·정렬용. BUY 하드조건 아님)
    reset_delta_volume: float = 0.0        # 현재 누적거래량 - RESET 누적거래량
    reset_money_add_krw: float = 0.0       # 신규 체결량 × 대표가격
    reset_money_per_sec_krw: float = 0.0   # 신규 거래대금 ÷ RESET 이후 경과초
    money_size_grade: str = "NONE"
    dominance_since: Optional[datetime] = None
    watch_since: Optional[datetime] = None
    # ★[2026-07-22 매도수술] 매도조건(매도우위+구조붕괴)이 연속 유지되기 시작한 시각. 끊기면 None.
    sell_cond_since: Optional[datetime] = None
    entry_ts: Optional[datetime] = None
    entry_price: float = 0.0
    qty: int = 0
    peak_price: float = 0.0
    exit_ts: Optional[datetime] = None
    exit_price: float = 0.0
    exit_reason: str = ""
    last_update_ts: Optional[datetime] = None
    anomaly_count: int = 0
    terminal_ts: Optional[datetime] = None
    rearm_ready: bool = False
    recent_prices: list[Tuple[float, float]] = field(default_factory=list)

    # ★[2026-07-22 체결층 이식] 주문·체결 추적(전략값 아님 — 전부 주문 인프라)
    buy_order_no: str = ""
    sell_order_no: str = ""
    buy_requested_ts: Optional[datetime] = None
    sell_requested_ts: Optional[datetime] = None
    buy_requested_qty: int = 0
    sell_requested_qty: int = 0
    buy_reserved_krw: float = 0.0
    buy_filled_qty: int = 0
    sell_filled_qty: int = 0
    buy_avg_fill_price: float = 0.0
    sell_avg_fill_price: float = 0.0
    buy_cancel_requested: bool = False
    sell_cancel_requested: bool = False
    buy_slot_reserved: bool = False
    buy_pending_reason: str = ""
    sell_pending_reason: str = ""
    last_order_check_ts: Optional[datetime] = None
    # 주문번호 확정을 위한 발주 직전 스냅샷·기준시각(캡틴1 pending dict의 known/since와 동일 역할)
    buy_known_onos: list = field(default_factory=list)
    sell_known_onos: list = field(default_factory=list)
    buy_since_hms: str = "00:00:00"
    sell_since_hms: str = "00:00:00"
    buy_sent_epoch: float = 0.0
    sell_sent_epoch: float = 0.0
    buy_cancel_epoch: float = 0.0
    sell_cancel_epoch: float = 0.0
    buy_cancel_check_epoch: float = 0.0
    sell_cancel_check_epoch: float = 0.0
    sell_retry_count: int = 0
    ono_ambiguous_logged: bool = False

    # ★[2026-07-22 관찰전용] 재생 로그가 읽어갈 '이번 루프 계산 원시값'.
    #   판정에는 절대 쓰지 않는다 — clamp 전 원본을 버리지 않고 남기기 위한 필드일 뿐이다.
    obs_raw_buy_delta: float = 0.0
    obs_raw_sell_delta: float = 0.0
    obs_delta_cum_vol: float = 0.0
    obs_prev_structure_low: float = 0.0
    obs_structure_broken: bool = False
    obs_buy_signal_reason: str = ""

    # ★[구조판정 SHADOW 2026-07-24] 직전 완성 1분봉 저가 누적(로그전용·판정 미사용).
    sh_entry_ref: Optional[datetime] = None      # 이 추적이 시작된 진입 시각(진입 바뀌면 초기화)
    sh_bar_min: int = -1                          # 현재 진행 중인 분(완성봉 경계 감지)
    sh_bar_low: float = 0.0                       # 현재 분의 진행 저가
    sh_lows: deque = field(default_factory=lambda: deque(maxlen=5))   # 직전 5 완성분봉 저가
    sh_last_state: str = ""                       # 직전 shadow 상태(구조붕괴 '전이' 감지)


# =============================================================================
# 유틸리티
# =============================================================================

def setup_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("captain2")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(cfg.log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def parse_ts(value: Any, fallback: Optional[datetime] = None) -> datetime:
    """★[2026-07-22 보강] ISO 'T' 구분자 포맷 추가.
    실측: live_micro_snapshot.json의 종목별 ts는 '2026-07-22T10:54:40.681488'(T 구분자)이고
    micro_rank_board.json의 ts는 '2026-07-22 11:01:05'(공백 구분자)다. 원본은 공백 포맷만
    시도해서 스냅샷 ts가 항상 파싱 실패 → fallback(now) 반환 → read_points()의 종목별
    신선도 검사(stale_snapshot_sec)가 무력화되고, MarketPoint.ts도 실제 체결시각이 아닌
    현재시각이 됐다. 판정 임계값·전략 조건은 무변경(파싱 포맷만 추가)."""
    fallback = fallback or datetime.now()
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%H:%M:%S.%f", "%H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt.startswith("%H"):
                return fallback.replace(hour=dt.hour, minute=dt.minute, second=dt.second, microsecond=dt.microsecond)
            return dt
        except ValueError:
            continue
    return fallback


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def stable_json_read(path: Path, retries: int = 3, delay: float = 0.03) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for _ in range(retries):
        try:
            raw1 = path.read_bytes()
            time.sleep(0.005)
            raw2 = path.read_bytes()
            if raw1 != raw2:
                time.sleep(delay)
                continue
            return json.loads(raw2.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"JSON 읽기 실패: {path}: {last_error}")


def krx_tick_size(price: float) -> float:
    """국내 주식 일반 호가단위 근사. 시장/ETF 예외는 추후 메타데이터 연동 필요."""
    if price < 2_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 20_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 200_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


class TickSideAggregator:
    """★[2026-07-22 실체결 수술 — 친구님 지시 '누적 역산 사용 금지'] 틱룰 실체결 집계.

    기존 estimate_cumulative_sides(누적 체결강도 역산)를 완전히 대체한다.
    폴링 간 누적거래량 증가분 = 그 구간에 '실제 발생한 체결량'이다. 이것을 가격 방향
    (↑=매수 / ↓=매도 / 보합=직전방향 유지)으로 분류해 종목별 매수/매도 실체결 누계를 쌓는다.
    crash_lowflow_shadow_v1(7/16 검증)의 틱룰과 동일 규약. 추정·역산 없음.

    누계의 원점은 프로세스 기동 시점이다 — RESET 기준선과 현재값이 같은 원점을 쓰므로
    차이(구간 체결량)는 원점과 무관하게 정확하다. 재시작 시 보유 종목 누계는 상태파일로
    승계하되(seed), 공백 구간 체결량은 방향을 알 수 없으므로 버린다(양쪽 모두 미집계)."""

    # ★[ROLL 2026-07-22 관찰전용] 최근 구간 흐름 측정용 이력 보존 시간(초).
    #   60초 윈도우 + 여유. 판정에 쓰지 않는다 — 회전과다 근본수술의 임계값 산정 재료.
    HIST_KEEP_SEC = 90.0

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._m: Dict[str, Dict[str, Any]] = {}
        self._hist: Dict[str, deque] = {}   # code -> deque[(epoch, buy, sell, bm, sm)]
        self._log = logger

    def _hist_push(self, code: str, epoch: float) -> None:
        s = self._m.get(code)
        if s is None:
            return
        h = self._hist.get(code)
        if h is None:
            h = deque()
            self._hist[code] = h
        h.append((epoch, s["buy"], s["sell"], s.get("bm", 0.0), s.get("sm", 0.0)))
        cutoff = epoch - self.HIST_KEEP_SEC
        while h and h[0][0] < cutoff:
            h.popleft()

    def roll(self, code: str, window_sec: float, now_epoch: float):
        """최근 window_sec 구간의 (매수량, 매도량, 매수대금, 매도대금, 실측구간초). 부족하면 None."""
        h = self._hist.get(code)
        if not h or len(h) < 2:
            return None
        cutoff = now_epoch - window_sec
        base = None
        for e in h:
            if e[0] <= cutoff:
                base = e
            else:
                break
        if base is None:
            base = h[0]
        last = h[-1]
        span = last[0] - base[0]
        if span <= 0:
            return None
        return (last[1] - base[1], last[2] - base[2],
                last[3] - base[3], last[4] - base[4], span)

    def update(self, points: Iterable[MarketPoint]) -> None:
        for p in points:
            self._update_one(p)
            # ★[ROLL 2026-07-22 관찰전용] 어떤 분기로 끝났든 이번 초의 누계를 이력에 적재
            self._hist_push(p.code, p.ts.timestamp())

    def _update_one(self, p: MarketPoint) -> None:
        s = self._m.get(p.code)
        # ★[REAL-SIDE 2026-07-22] 정확모드 — 브로커가 부호체결(FID15)로 쌓은 실제 누계가 오면
        #   그 값을 그대로 쓴다(원점=브로커 08:35 기동, 캡틴2 재시작과 무관하게 하루 내내 일관).
        if p.buy_vol_cum >= 0 and p.sell_vol_cum >= 0:
            if s is not None and not s.get("exact") and (s["buy"] > 0 or s["sell"] > 0):
                if self._log:
                    self._log.warning("실체결 모드 전환(틱룰→정확) %s — 진행 중 기준선은 재정박 필요", p.code)
            self._m[p.code] = {"last_p": p.price, "last_v": p.cum_vol, "last_dir": 0.0,
                               "buy": p.buy_vol_cum, "sell": p.sell_vol_cum,
                               "bm": max(0.0, p.buy_money_cum), "sm": max(0.0, p.sell_money_cum),
                               "exact": True}
            return
        # ── 틱룰 폴백(브로커 필드 없음) ──────────────────────────────
        if s is None:
            self._m[p.code] = {"last_p": p.price, "last_v": p.cum_vol,
                               "last_dir": 0.0, "buy": 0.0, "sell": 0.0,
                               "bm": 0.0, "sm": 0.0, "exact": False}
            return
        if s.get("exact"):
            # 정확모드였는데 필드가 사라짐(브로커 이상) — 브로커 원점 숫자에 틱룰을 섞으면
            # 오염되므로 동결 유지. 필드가 돌아오면 위 정확모드가 다시 덮어쓴다.
            return
        if s["last_v"] is None or s["last_p"] is None:
            # 재시작 승계 직후 첫 관측 — 공백 구간 체결량은 버리고 기준만 잡는다
            s["last_p"], s["last_v"] = p.price, p.cum_vol
            return
        dv = p.cum_vol - s["last_v"]
        if dv < 0:
            # 누적거래량 역행(스냅샷 리셋 등) — 집계하지 않고 기준만 갱신
            s["last_p"], s["last_v"] = p.price, p.cum_vol
            return
        d = s["last_dir"]
        if p.price > s["last_p"]:
            d = 1.0
        elif p.price < s["last_p"]:
            d = -1.0
        if d > 0:
            s["buy"] += dv
            s["bm"] += dv * p.price
        elif d < 0:
            s["sell"] += dv
            s["sm"] += dv * p.price
        s["last_dir"] = d
        s["last_p"], s["last_v"] = p.price, p.cum_vol

    def cum_now(self, code: str) -> Tuple[float, float]:
        s = self._m.get(code)
        return (s["buy"], s["sell"]) if s else (0.0, 0.0)

    def money_now(self, code: str) -> Tuple[float, float]:
        """방향별 실거래대금 누계(원). 정확모드=브로커 체결가중, 틱룰=체결량×당시가 근사."""
        s = self._m.get(code)
        return (s.get("bm", 0.0), s.get("sm", 0.0)) if s else (0.0, 0.0)

    def is_exact(self, code: str) -> bool:
        s = self._m.get(code)
        return bool(s and s.get("exact"))

    def snapshot(self, code: str) -> Optional[Dict[str, float]]:
        s = self._m.get(code)
        if s is None:
            return None
        return {"buy": s["buy"], "sell": s["sell"], "last_dir": s["last_dir"],
                "bm": s.get("bm", 0.0), "sm": s.get("sm", 0.0),
                "exact": 1.0 if s.get("exact") else 0.0}

    def seed(self, code: str, snap: Mapping[str, Any]) -> None:
        # 정확모드는 승계 불필요(브로커 원점이 유지됨) — 다음 관측이 어차피 덮어쓴다.
        # 틱룰 모드 승계용으로만 의미가 있다.
        self._m[code] = {"last_p": None, "last_v": None,
                         "last_dir": float(snap.get("last_dir") or 0.0),
                         "buy": float(snap.get("buy") or 0.0),
                         "sell": float(snap.get("sell") or 0.0),
                         "bm": float(snap.get("bm") or 0.0),
                         "sm": float(snap.get("sm") or 0.0),
                         "exact": bool(float(snap.get("exact") or 0.0))}


class ThreeMinuteMARider:
    """실시간 가격으로 3분봉 5·10·20선을 이어 붙이는 RAID 보유 허가증.

    전일 시드는 intraday_ma의 검증된 CSV 로더만 재사용한다. bars3()/broker fallback은
    호출하지 않으므로 보유 중 추가 TR은 0이다. 상향 만남에서 무장한 뒤에는 5·10선이
    벌어져도 상승을 계속 타며, 20선 이탈 또는 완성봉 20선 비상승에서 해제한다.
    """

    KEEP_COMPLETED = 20

    def __init__(self, cfg: Config, logger: logging.Logger) -> None:
        self.enabled = cfg.ma3_rider_on
        self.converge_pct = max(0.0, cfg.ma3_converge_pct)
        self.bars_path = cfg.ma3_bars_path
        self.log = logger
        self._seed: Dict[str, List[float]] = {}
        self._today: Dict[str, deque] = {}
        self._bucket: Dict[str, int] = {}
        self._current_close: Dict[str, float] = {}
        self._active: set = set()
        self._last: Dict[str, Tuple[float, float, float]] = {}
        self._loaded = False

    @staticmethod
    def _metrics(series: List[float]) -> Optional[Tuple[float, float, float, bool, bool]]:
        if len(series) < 21:
            return None
        m5 = sum(series[-5:]) / 5.0
        m10 = sum(series[-10:]) / 10.0
        m20 = sum(series[-20:]) / 20.0
        prev = series[:-1]
        p5 = sum(prev[-5:]) / 5.0
        p10 = sum(prev[-10:]) / 10.0
        p20 = sum(prev[-20:]) / 20.0
        return m5, m10, m20, p5 <= p10 and m5 >= m10, m20 > p20

    def load_seed(self) -> None:
        if not self.enabled:
            self._loaded = True
            self.log.info("3분봉 상승보유 OFF")
            return
        try:
            # 검증된 전일 풀데이·신선도 필터만 사용. bars3/브로커 함수는 호출하지 않는다.
            os.environ.setdefault("PRIOR_3M_CSV", str(self.bars_path))
            from intraday_ma import _prior_map
            raw = _prior_map()
            seed: Dict[str, List[float]] = {}
            for code, values in raw.items():
                closes = []
                for value in values[-self.KEEP_COMPLETED:]:
                    try:
                        price = float(value)
                    except (TypeError, ValueError):
                        continue
                    if price > 0:
                        closes.append(price)
                if len(closes) >= self.KEEP_COMPLETED:
                    seed[str(code).zfill(6)] = closes
            self._seed = seed
            self._loaded = True
            self.log.info("3분봉 상승보유 전일시드 완료 %d종목 (추가 TR 0)", len(seed))
        except Exception:
            self._loaded = True
            self.log.exception("3분봉 상승보유 시드 실패 — 허가증 미발동(fail-closed)")

    def _series(self, code: str, current: Optional[float] = None) -> List[float]:
        out = list(self._seed.get(code) or [])
        out.extend(self._today.get(code) or [])
        if current is not None and current > 0:
            out.append(current)
        return out[-21:]

    def update(self, points: Iterable[MarketPoint]) -> None:
        if not self.enabled:
            return
        for point in points:
            code = point.code
            price = float(point.price)
            bucket = int(point.ts.timestamp() // 180)
            previous_bucket = self._bucket.get(code)
            new_bar = previous_bucket is not None and bucket != previous_bucket
            if previous_bucket is None:
                self._bucket[code] = bucket
            elif new_bar:
                previous_close = self._current_close.get(code, 0.0)
                # 중단 뒤 여러 봉을 건너뛴 경우 마지막 관측가를 가짜 종가로 채우지 않는다.
                if bucket - previous_bucket == 1 and previous_close > 0:
                    bars = self._today.setdefault(code, deque(maxlen=self.KEEP_COMPLETED))
                    bars.append(previous_close)
                self._bucket[code] = bucket
            self._current_close[code] = price
            if not self._loaded:
                continue

            forming = self._metrics(self._series(code, price))
            if forming is None:
                self._last.pop(code, None)
                self._active.discard(code)
                continue
            m5, m10, m20, cross_up, rising20 = forming
            self._last[code] = (m5, m10, m20)

            if code in self._active and new_bar:
                completed = self._metrics(self._series(code))
                if completed is not None and not completed[4]:
                    self._active.discard(code)
            if code in self._active and price < m20:
                self._active.discard(code)

            gap_pct = abs(m5 / m10 - 1.0) * 100.0 if m10 > 0 else 999.0
            meet_up = m5 >= m10 and (cross_up or gap_pct <= self.converge_pct)
            if code not in self._active and meet_up and rising20 and price >= m20:
                self._active.add(code)

    def status(self, code: str) -> Tuple[bool, float, float, float]:
        code = str(code).zfill(6)
        m5, m10, m20 = self._last.get(code, (0.0, 0.0, 0.0))
        return self.enabled and code in self._active, m5, m10, m20

    def snapshot(self) -> Dict[str, Any]:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "today": {code: list(values) for code, values in self._today.items()},
            "bucket": self._bucket,
            "current_close": self._current_close,
            "active": sorted(self._active),
        }

    def restore(self, payload: Mapping[str, Any]) -> None:
        if not self.enabled or str(payload.get("date") or "") != datetime.now().strftime("%Y-%m-%d"):
            return
        try:
            self._today = {
                str(code).zfill(6): deque((float(x) for x in values), maxlen=self.KEEP_COMPLETED)
                for code, values in (payload.get("today") or {}).items()
            }
            self._bucket = {str(code).zfill(6): int(value)
                            for code, value in (payload.get("bucket") or {}).items()}
            self._current_close = {str(code).zfill(6): float(value)
                                   for code, value in (payload.get("current_close") or {}).items()}
            self._active = {str(code).zfill(6) for code in (payload.get("active") or [])}
        except Exception:
            self.log.exception("3분봉 상승보유 상태 복원 실패 — 새 관측부터 재구성")

# =============================================================================
# ★[2026-07-22] 체결 확인 — 캡틴1(morning_captain_live_v1.py)의 주문번호 기반 구조 이식.
#   원본: _fills_onos(297행) / _ono_discover(335행) / _known_onos(352행).
#   전략 로직은 하나도 가져오지 않았다 — 주문번호·체결량·평균가 집계뿐이다.
# =============================================================================

def fills_by_ono(fills_dir: Path, code: str, side: str = "매수",
                 since_hms: str = "00:00:00") -> Dict[str, Tuple[int, float]]:
    """fills_YYYYMMDD.csv를 '주문번호별' {ono: (누적체결량, 가중평균체결가)}로 집계.
    fill_qty는 주문별 누적치라 행 간 증가분(inc)에 fill_px를 가중한다.
    ★종목코드만으로 귀속하지 않는다 — 다른 엔진의 주문(다른 주문번호)과 절대 안 섞인다."""
    fp = fills_dir / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return {}
    code = str(code).zfill(6)
    prev: Dict[str, int] = {}
    out: Dict[str, Tuple[int, float]] = {}
    try:
        with fp.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    if str(r.get("code", "")).strip().zfill(6) != code:
                        continue
                    if side not in str(r.get("otype", "")):
                        continue
                    if "체결" not in str(r.get("state", "")):
                        continue
                    ts = str(r.get("ts", ""))
                    if len(ts) >= 19 and ts[11:19] < since_hms:
                        continue
                    ono = str(r.get("order_no", "")).strip()
                    if not ono:
                        continue
                    q = int(float(r.get("fill_qty") or 0))
                    px = float(r.get("fill_px") or 0)
                    inc = q - prev.get(ono, 0)
                    if inc > 0:
                        prev[ono] = q
                        tq, wsum = out.get(ono, (0, 0.0))
                        out[ono] = (tq + inc, wsum + inc * px)
                except Exception:
                    continue
    except Exception:
        return {}
    return {o: (q, (w / q if q > 0 else 0.0)) for o, (q, w) in out.items()}


def parse_trail_steps(raw: str) -> List[Tuple[float, float]]:
    """★[설계8단계] "무장:폭,무장:폭" → [(무장%, 되돌림폭%)] 오름차순. 파싱 실패 시 빈 리스트(트레일 꺼짐)."""
    out: List[Tuple[float, float]] = []
    try:
        for part in str(raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            arm_s, drop_s = part.split(":")
            arm_v, drop_v = float(arm_s), float(drop_s)
            if arm_v > 0 and drop_v > 0:
                out.append((arm_v, drop_v))
    except Exception:
        return []
    return sorted(out)


def _parse_saved_dt(value: Any) -> Optional[datetime]:
    """state_json이 저장한 '%Y-%m-%d %H:%M:%S.%f'[:−3] 형식을 되읽는다. 못 읽으면 None."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _reset_context_ok(state: FlowState) -> Tuple[bool, list]:
    """★[2026-07-22] 전략매도(FLOW_WEAK+STRUCTURE_BREAK)를 이어가려면 RESET 맥락이 온전해야 한다.
    하나라도 없으면 그 종목은 RECOVERY_HOLD로 내려 HARD_STOP·TIME_EXIT만 적용한다.
    (근거 없는 상태로 buy_ratio를 다시 계산하면 엉뚱한 시점에 팔거나 못 판다)"""
    missing = []
    if state.reset_ts is None:
        missing.append("reset_ts")
    if state.reset_cum_vol <= 0:
        missing.append("reset_cum_vol")
    if state.reset_buy_cum <= 0 and state.reset_sell_cum <= 0:
        missing.append("reset_buy_cum/sell_cum")
    if state.reset_price <= 0:
        missing.append("reset_price")
    if state.entry_price <= 0:
        missing.append("entry_price")
    return (not missing), missing


def state_json(state: FlowState) -> Dict[str, Any]:
    data = asdict(state)
    data["phase"] = state.phase.value
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if state.candidate_low:
        cl = asdict(state.candidate_low)
        cl["ts"] = state.candidate_low.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        data["candidate_low"] = cl
    return data


# =============================================================================
# 입력 어댑터
# =============================================================================

class DataFeed:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.log = logger
        self.names = self._load_names()

    def _load_names(self) -> Dict[str, str]:
        try:
            data = stable_json_read(self.cfg.name_cache_path)
            raw = data.get("map", data)
            return {str(k).zfill(6): str(v) for k, v in raw.items()}
        except Exception:
            return {}

    def read_points(self, allow_stale_board: bool = False) -> Dict[str, MarketPoint]:
        snap = stable_json_read(self.cfg.snapshot_path)
        board = stable_json_read(self.cfg.micro_board_path)
        now = datetime.now()

        board_ts = parse_ts(board.get("ts"), now)
        board_stale = abs((now - board_ts).total_seconds()) > self.cfg.stale_board_sec
        if board_stale and not allow_stale_board:
            raise RuntimeError(f"micro board stale: {(now - board_ts).total_seconds():.1f}s")

        board_items = {} if board_stale else {
            str(x.get("code") or "").zfill(6): x
            for x in (board.get("all_items") or [])
            if x.get("code")
        }
        theme_leaders = {}
        if self.cfg.theme_leader_bonus_on:
            try:
                import theme_leader as theme_leader_feed
                theme_leaders = theme_leader_feed.get_leaders(
                    max_age_min=self.cfg.theme_leader_max_age_min)
            except Exception:
                theme_leaders = {}
        points: Dict[str, MarketPoint] = {}
        for raw_code, item in (snap.get("codes") or {}).items():
            code = str(raw_code).zfill(6)
            # ★[2026-07-24 특수코드 차단 친구님 "문제 수정"] 6자리 숫자 정규코드만 취급.
            #   0156T0류(신주인수권 계열 의심) 특수코드를 이름도 못 푼 채 매수한 사고
            #   (7/24 2왕복 -3.04%·-1.08%) 재발 방지 — 감지 단계부터 원천 차단.
            if len(code) != 6 or not code.isdigit():
                continue
            price = safe_float(item.get("cur"))
            cum_vol = safe_float(item.get("cum_vol"))
            che_str = safe_float(item.get("che_str"))
            if price <= 0 or cum_vol < 0:
                continue
            ts = parse_ts(item.get("ts"), now)
            if abs((now - ts).total_seconds()) > self.cfg.stale_snapshot_sec:
                continue
            b = board_items.get(code, {})
            theme_info = theme_leaders.get(code) or {}
            points[code] = MarketPoint(
                ts=ts,
                code=code,
                price=price,
                cum_vol=cum_vol,
                che_str=che_str,
                ask_tot=safe_float(item.get("ask_tot")),
                bid_tot=safe_float(item.get("bid_tot")),
                imb=safe_float(item.get("imb")),
                money_add_5s=safe_float(b.get("money_add_5s")),
                money_speed_5s=safe_float(b.get("money_speed_5s")),
                money_speed_10s=safe_float(b.get("money_speed_10s")),
                money_speed_30s=safe_float(b.get("money_speed_30s")),
                money_start=bool(b.get("money_start")),
                money_start_raw=bool(b.get("money_start_raw")),
                theme_leader=bool(theme_info),
                theme_signal=str(theme_info.get("signal") or ""),
                # ★[2026-07-22] 당일 거래대금 근사(EST_PRICE_X_CUMVOL) — 입력에 누적 거래대금 필드 없음
                today_value_krw=price * cum_vol,
                # ★[REAL-SIDE 2026-07-22] 브로커 부호체결 누계 4필드 — 없으면 -1.0(틱룰 폴백 신호)
                buy_vol_cum=safe_float(item.get("buy_vol_cum", -1.0), -1.0),
                sell_vol_cum=safe_float(item.get("sell_vol_cum", -1.0), -1.0),
                buy_money_cum=safe_float(item.get("buy_money_cum", -1.0), -1.0),
                sell_money_cum=safe_float(item.get("sell_money_cum", -1.0), -1.0),
            )
        return points


# =============================================================================
# 주문 어댑터 — 기본 SHADOW
# =============================================================================

class ExecutionAdapter:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.log = logger
        self.client = None
        self.account = ""
        self.last_error_detail = ""

    def connect(self) -> bool:
        if not self.cfg.live:
            self.log.info("SHADOW 모드: 주문 0")
            return True
        # ★[2026-07-22] manual_buy_block은 '신규 매수 차단' 스위치일 뿐 매도 엔진 중단 스위치가 아니다.
        #   기존 구조는 flag가 있으면 브로커 연결 자체를 거부해서, 보유분 매도 관리까지 죽었다.
        #   → 연결·계좌조회·매도는 항상 허용하고, 차단은 buy()에서만 한다.
        if self.cfg.manual_block_path.exists():
            self.log.warning("manual_buy_block.flag 존재 — 신규 매수만 차단(연결·계좌조회·매도는 정상)")
        try:
            from broker_client import BrokerClient, is_broker_alive  # type: ignore
            if not is_broker_alive():
                self.log.error("broker gateway 비정상")
                return False
            self.client = BrokerClient()
            info = self.client.account_info("ACCNO")
            accounts = (info.get("data") or {}).get("accounts") or []
            if isinstance(accounts, str):
                accounts = [x for x in accounts.split(";") if x]
            self.account = accounts[0] if accounts else os.environ.get("SAFEPLUS_ACCOUNT", "")
            if not self.account:
                self.log.error("계좌번호 없음")
                return False
            return True
        except Exception:
            self.log.exception("브로커 연결 실패")
            return False

    def buy(self, code: str, qty: int) -> str:
        self.last_error_detail = ""
        if self.cfg.live and self.cfg.off_flag_path.exists():
            self.last_error_detail = "captain2_off.flag"
            self.log.warning("BUY 킬스위치 차단: %s", code)
            return "BLOCKED"
        if self.cfg.live and self.cfg.manual_block_path.exists():
            self.log.warning("BUY 차단 플래그: %s", code)
            return "BLOCKED"
        if not self.cfg.live:
            self.log.info("[SHADOW] BUY %s x%d", code, qty)
            return "SHADOW"
        try:
            result = self.client.send_order_real(
                idempotency_key=f"captain2_buy_{code}_{uuid.uuid4()}",
                account=self.account,
                code=code,
                qty=int(qty),
                order_type=1,
                price=0,
                hoga_gb="06",
                rqname=f"CAPTAIN2_BUY_{code}",
                screen_no="9750",
            )
            status = str((result or {}).get("status") or "NONE").upper()
            self.last_error_detail = str(
                (result or {}).get("message") or (result or {}).get("error") or "")
            if status not in ("OK", "TIMEOUT"):
                self.log.warning("BUY 주문 거부 %s status=%s detail=%s",
                                 code, status, self.last_error_detail or "-")
            return status
        except Exception as exc:
            self.last_error_detail = f"{type(exc).__name__}: {exc}"
            self.log.exception("BUY 주문 실패 %s", code)
            return "ERROR"

    def sell(self, code: str, qty: int) -> str:
        self.last_error_detail = ""
        if not self.cfg.live:
            self.log.info("[SHADOW] SELL %s x%d", code, qty)
            return "SHADOW"
        try:
            result = self.client.send_order_real(
                idempotency_key=f"captain2_sell_{code}_{uuid.uuid4()}",
                account=self.account,
                code=code,
                qty=int(qty),
                order_type=2,
                price=0,
                hoga_gb="06",
                rqname=f"CAPTAIN2_SELL_{code}",
                screen_no="9750",
            )
            status = str((result or {}).get("status") or "NONE").upper()
            self.last_error_detail = str(
                (result or {}).get("message") or (result or {}).get("error") or "")
            if status not in ("OK", "TIMEOUT"):
                self.log.warning("SELL 주문 거부 %s status=%s detail=%s",
                                 code, status, self.last_error_detail or "-")
            return status
        except Exception as exc:
            self.last_error_detail = f"{type(exc).__name__}: {exc}"
            self.log.exception("SELL 주문 실패 %s", code)
            return "ERROR"

    # ── ★[2026-07-22] 주문번호 단위 조회·지정취소 (캡틴1 open_onos/cancel_order 이식) ──
    #    다른 엔진의 주문은 절대 건드리지 않는다. 종목단위 전량취소는 쓰지 않는다.

    def open_onos(self, code: str, buy: bool = True) -> Optional[Dict[str, int]]:
        """이 종목의 미체결 {주문번호: 미체결수량} (opt10075). 실패 시 None(판단불가)."""
        if not self.cfg.live or not self.client:
            return {}
        try:
            r = self.client.tr(
                "opt10075",
                inputs={"계좌번호": self.account, "전체종목구분": "1",
                        "매매구분": "2" if buy else "1",
                        "종목코드": str(code).zfill(6), "체결구분": "1"},
                output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                               "미체결수량", "주문상태"],
                rqname=f"CAPTAIN2_ONO_{code}", screen_no="9750", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as exc:
            self.log.warning("미체결 조회 실패 %s: %s", code, exc)
            return None
        out: Dict[str, int] = {}
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if ono and rem > 0:
                    out[ono] = rem
            except Exception:
                continue
        return out

    def cancel_order(self, code: str, ono: str, rem: int, buy: bool = True) -> str:
        """내 주문번호만 지정 취소. ono가 없으면 취소하지 않는다(교차취소 금지)."""
        if not self.cfg.live or not self.client or not ono:
            self.log.info("CANCEL_REQUEST %s 주문번호=%s x%d (그림자/번호없음 — 실취소 생략)",
                          code, ono or "?", rem)
            return "SKIP"
        try:
            cr = self.client.send_order_real(
                idempotency_key=f"captain2_cxl_{code}_{uuid.uuid4()}",
                account=self.account, code=str(code).zfill(6), qty=int(rem),
                order_type=(3 if buy else 4), price=0, hoga_gb="00",
                rqname=f"CAPTAIN2_CXL_{code}", screen_no="9750", origin_order_no=str(ono))
            st = str((cr or {}).get("status", "")).upper()
            self.log.info("CANCEL_REQUEST %s 주문번호=%s x%d → %s", code, ono, rem, st)
            return st
        except Exception as exc:
            self.log.warning("지정취소 실패 %s 주문번호=%s: %s", code, ono, exc)
            return "ERROR"


# =============================================================================
# 엔진
# =============================================================================

class Captain2Engine:
    EVENT_COLUMNS = [
        "ts", "code", "name", "event", "phase", "price", "reset_price",
        "elapsed_sec", "money_add_5s", "money_speed_5s", "money_speed_10s",
        "money_speed_30s", "burst_ratio", "buy_exec_vol", "sell_exec_vol",
        "buy_ratio", "buy_sell_ratio", "price_response_pct", "structure_low",
        "che_str", "ask_tot", "bid_tot", "imb", "reason",
        # ★[2026-07-22] 시장필터·큰돈 측정 컬럼
        "today_value_krw", "reset_delta_volume", "reset_money_add_krw",
        "reset_money_per_sec_krw", "money_size_grade",
        # ★[REAL-SIDE 2026-07-22] 방향별 실거래대금·출처(1=브로커 부호체결 정확, 0=틱룰 근사)
        "buy_exec_money", "sell_exec_money", "buy_money_ratio", "side_exact",
        # ★[ROLL-LIVE 2026-07-22] 매도판정용 최근구간 비율 + 윈도우 튜닝용 관찰 3종
        "flow_ratio_recent", "flow_span_recent",
        "roll10_ratio", "roll30_ratio", "roll60_ratio",
        "roll10_money_ps", "roll30_money_ps", "roll60_money_ps",
        # ★[설계8단계 2026-07-22] 가속·이평허가·평상시배율 + ★[눌림레인] 레인
        "money_accel", "ma_permit", "money_mult_dayavg", "lane",
    ]

    # ★[구조판정 SHADOW 2026-07-24] 계층 B 병렬기록 컬럼(별도 CSV·로그전용)
    STRUCT_SHADOW_COLUMNS = [
        "ts", "code", "name", "entry_ts", "entry_price", "price", "pnl_pct",
        "peak_price", "peak_dd_pct", "vwap", "cond_vwap",
        "structure_low_5", "n_bars", "cond_structlow",
        "net_krw_60s", "cond_netsell", "score_count",
        "shadow_state", "live_action", "live_reason", "data_quality",
    ]
    REACCEL_SHADOW_COLUMNS = [
        "ts", "code", "name", "event", "price", "signal_price", "line",
        "elapsed_sec", "day_gain_pct", "age_bars", "ext_pct", "volx",
        "surge5_pct", "buy_exec_vol", "sell_exec_vol", "buy_ratio",
        "buy_sell_ratio", "buy_exec_money", "sell_exec_money",
        "money_total_krw", "persist_ok", "dominance_sec", "side_exact",
        "reason",
    ]

    def __init__(self, cfg: Config, feed: DataFeed, execution: ExecutionAdapter, logger: logging.Logger):
        self.cfg = cfg
        self.feed = feed
        self.execution = execution
        self.log = logger
        self.states: Dict[str, FlowState] = {}
        # ★[2026-07-22 실체결 수술] 실체결 누계 — 모든 판정의 유일한 매수/매도 체결량 원천
        #   (브로커 부호체결 4필드가 오면 정확모드, 없으면 틱룰 폴백)
        self.agg = TickSideAggregator(logger)
        self.ma3_rider = ThreeMinuteMARider(cfg, logger)
        self.entries_today = 0
        self.last_entry_time = 0.0
        self.last_entry_by_code: Dict[str, float] = {}   # ★[2026-07-22] 종목별 마지막 진입시각(종목 쿨다운용)
        # ★[재진입 가드 2026-07-23] 종목별 직전 진입 신호강도 (유입대금, 유입속도, 매수비). 재시작 시 초기화(=당일).
        self.last_entry_signal: Dict[str, Tuple[float, float, float]] = {}
        self.entry_count_by_code: Dict[str, int] = {}
        self.daily_buy_krw = 0.0
        self.daily_realized_pnl_krw = 0.0
        self.consecutive_losses = 0
        self.kill_switch_latched = False
        self.feed_stale_latched = False
        self.feed_fresh_since = 0.0
        self.recovery_blocked = False                    # ★[2026-07-22] 복구 실패 시 LIVE 신규매수 금지
        self._replay_buf: List[Dict[str, Any]] = []      # ★[2026-07-22] 재생로그 버퍼(배치 flush)
        self._replay_last_flush = time.time()
        self._replay_rows_written = 0
        self.running = True
        self.event_path = cfg.event_dir / f"captain2_events_{datetime.now():%Y%m%d}.csv"
        # ★[구조판정 SHADOW 2026-07-24] 계층 B 병렬기록 CSV(실매도와 분리·로그전용)
        self.struct_shadow_path = cfg.event_dir / f"captain2_structure_shadow_{datetime.now():%Y%m%d}.csv"
        # ★[설계8단계 2026-07-22] ⑦단계식 트레일 테이블 + ⑤이평(5·10일선) 캐시.
        #   이평 파일이 267MB라 백그라운드 로드 — 로드 전엔 ma_permit=False(보조 기능이라 무해).
        self._trail_steps = parse_trail_steps(cfg.trail_steps_raw)
        self._ma5: Dict[str, float] = {}
        self._ma10: Dict[str, float] = {}
        self._ma10_prev: Dict[str, float] = {}
        self._ma_loaded = False
        self._reverse_ma_codes: set = set()
        self._selector_codes: set = set()
        self._selector_date = ""
        self._selector_ready = False
        self._selector_last_try = 0.0
        self._selector_last_warning = ""
        self._reverse_ma_date = ""
        self._reverse_ma_last_try = 0.0
        self._reverse_ma_last_warning = ""
        # ★[EARLY 초입레인 2026-07-23] 종목별 초입 추적 + 당일 시가(09:00 이후 첫 관측가) 캐시
        self.early: Dict[str, EarlyState] = {}
        self.day_open: Dict[str, float] = {}
        self._m1_open: Optional[Dict[str, float]] = None   # 재시작 폴백(돈맥_1분봉 op) — lazy 1회 로드
        self._early_watch_meta: Dict[str, Dict[str, float]] = {}
        self._early_watch_date = ""
        self._early_watch_ready = False
        self._early_watch_last_try = 0.0
        self._early_watch_last_warning = ""
        # C2-01은 감시 신호 1개를 기존 1주 주문 인프라에 전달하고 공통 매도 엔진을 사용한다.
        self.c2_01_consumed_signals: set[str] = set()
        self.c2_01_order_attempts = 0
        self._c2_01_common_engine = UnifiedHoldSellEngine()
        self._c2_01_common_windows = SideWindows()
        self._c2_01_bars: Dict[str, Any] = {}
        self._c2_01_bars_mtime_ns = -1
        self._c2_01_exit_error = ""
        # ★[BASE 횡보돌파] 1분봉 추적은 매수 상태와 분리. 재시작 시 기존 그림자 장부의
        #   완성봉 이력만 시드로 읽고 이후 돈맥_1분봉.json을 직접 이어 붙인다(TR0).
        self.base: Dict[str, BasePatternState] = {}
        self._base_last_hm = ""
        self._base_last_error = ""
        self._base_seed_from_shadow_ledger()
        # ★[재가속 SHADOW] BASE/RAID 상태와 완전히 분리된 주문0 관찰기.
        self.reaccel_shadow: Dict[str, ReaccelShadowState] = {}
        self.reaccel_shadow_path = (
            cfg.event_dir / f"captain2_reaccel_shadow_{datetime.now():%Y%m%d}.csv")
        # ★[수급 가점 2026-07-23] D-2 본선·D-1 차선 매집 배지 — 0.2MB 파일이라 동기 로드(부팅 무지연)
        self._supply_badge_d1: set = set()                 # 차선(로더가 채움·실패 시 빈 집합)
        self._supply_badge: set = self._load_supply_badges()
        threading.Thread(target=self._load_daily_ma, daemon=True).start()
        threading.Thread(target=self.ma3_rider.load_seed, daemon=True).start()

    def _load_supply_badges(self) -> set:
        """★[수급 가점 2026-07-23 친구님 승인] D-2(2거래일 전) 기관 또는 외인 순매수(+) 종목 집합.
        소스=investor_daily.csv(opt10059·종가매수 supply_signal과 공유·새 TR 0).
        실패·데이터 부족 시 빈 집합 = 가점 없음, 기존 정렬 그대로(fail-open)."""
        try:
            by: Dict[Tuple[str, str], Tuple[int, int]] = {}
            dates = set()
            with open(r"C:\stock_bot\data\investor_daily.csv", encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    c = str(r.get("code", "")).zfill(6)
                    d = str(r.get("date", "")).strip()
                    if not c or not d:
                        continue
                    dates.add(d)
                    try:
                        inst = int(float(str(r.get("inst_net") or 0).replace(",", "")))
                    except (ValueError, TypeError):
                        inst = 0
                    try:
                        frgn = int(float(str(r.get("foreign_net") or 0).replace(",", "")))
                    except (ValueError, TypeError):
                        frgn = 0
                    by[(c, d)] = (inst, frgn)
            today = datetime.now().strftime("%Y%m%d")
            allsess = sorted(dates | {today})
            i = allsess.index(today)
            if i < 2:
                return set()
            d1, d2 = allsess[i - 1], allsess[i - 2]
            out = {c for (c, d), (inst, frgn) in by.items()
                   if d == d2 and (inst > 0 or frgn > 0)}
            # ★[2026-07-24 친구님 지시] D-1 차선 배지 — D-2가 적어도 "안 쓰는 것보다 낫다".
            #   백테 근거: D-1 기관 +0.39%p·D-1 외인 +0.59%p(8/11일 최다 일관).
            self._supply_badge_d1 = {c for (c, d), (inst, frgn) in by.items()
                                     if d == d1 and (inst > 0 or frgn > 0)}
            self.log.info("수급 가점 로드: D-2=%s %d종목(본선) · D-1=%s %d종목(차선)",
                          d2, len(out), d1, len(self._supply_badge_d1))
            return out
        except Exception as exc:
            self.log.warning("수급 가점 로드 실패(가점 없이 진행): %s", exc)
            return set()

    def _load_daily_ma(self) -> None:
        """캡틴1 _ma_daily(240행) 패턴 재사용 — 직전 n거래일 종가평균 + 10일선 상승판정용 전일값."""
        try:
            byd: Dict[str, Dict[str, float]] = {}
            with self.cfg.eod_bars_path.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    try:
                        byd.setdefault(str(r["code"]).zfill(6), {})[r["date"]] = float(r.get("close") or 0)
                    except Exception:
                        continue
            for c, m in byd.items():
                ks = sorted(m)
                if len(ks) >= 5:
                    self._ma5[c] = sum(m[d] for d in ks[-5:]) / 5
                if len(ks) >= 10:
                    self._ma10[c] = sum(m[d] for d in ks[-10:]) / 10
                if len(ks) >= 11:
                    self._ma10_prev[c] = sum(m[d] for d in ks[-11:-1]) / 10
                elif len(ks) >= 10:
                    self._ma10_prev[c] = self._ma10[c]      # 이력 10일뿐이면 상승판정 불가→동률(허가 안 남)
            self._ma_loaded = True
            self.log.info("이평 캐시 로드 완료 — 5일선 %d·10일선 %d종목", len(self._ma5), len(self._ma10))
        except FileNotFoundError:
            self.log.warning("이평 파일 없음(%s) — 허가증 비활성(전략 본질 무영향)", self.cfg.eod_bars_path)
        except Exception:
            self.log.exception("이평 캐시 로드 실패 — 허가증 비활성으로 계속")

    def stop(self, *_: Any) -> None:
        self.running = False

    def _event(self, point: MarketPoint, state: FlowState, event: str, reason: str = "") -> None:
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.event_path.exists()
        elapsed = (point.ts - state.reset_ts).total_seconds() if state.reset_ts else 0.0
        burst = point.money_speed_5s / max(point.money_speed_30s, 1e-9) if point.money_speed_30s > 0 else 0.0
        row = {
            "ts": point.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "code": point.code,
            "name": state.name,
            "event": event,
            "phase": state.phase.value,
            "price": point.price,
            "reset_price": state.reset_price,
            "elapsed_sec": round(elapsed, 3),
            "money_add_5s": point.money_add_5s,
            "money_speed_5s": point.money_speed_5s,
            "money_speed_10s": point.money_speed_10s,
            "money_speed_30s": point.money_speed_30s,
            "burst_ratio": round(burst, 4),
            "buy_exec_vol": round(state.buy_exec_vol, 3),
            "sell_exec_vol": round(state.sell_exec_vol, 3),
            "buy_ratio": round(state.buy_ratio, 4),
            "buy_sell_ratio": round(state.buy_sell_ratio, 4),
            "price_response_pct": round(state.price_response_pct, 4),
            "structure_low": state.structure_low,
            "che_str": point.che_str,
            "ask_tot": point.ask_tot,
            "bid_tot": point.bid_tot,
            "imb": point.imb,
            "reason": reason,
            "today_value_krw": round(point.today_value_krw),
            "reset_delta_volume": round(state.reset_delta_volume, 3),
            "reset_money_add_krw": round(state.reset_money_add_krw),
            "reset_money_per_sec_krw": round(state.reset_money_per_sec_krw),
            "money_size_grade": state.money_size_grade,
            "buy_exec_money": round(state.buy_exec_money),
            "sell_exec_money": round(state.sell_exec_money),
            "buy_money_ratio": round(state.buy_money_ratio, 4),
            "side_exact": 1 if state.side_exact else 0,
            "lane": state.lane,
            "flow_ratio_recent": round(state.flow_ratio_recent, 4),
            "flow_span_recent": round(state.flow_span_recent, 1),
            "roll10_ratio": round(state.roll10_ratio, 4),
            "roll30_ratio": round(state.roll30_ratio, 4),
            "roll60_ratio": round(state.roll60_ratio, 4),
            "roll10_money_ps": round(state.roll10_money_ps),
            "roll30_money_ps": round(state.roll30_money_ps),
            "roll60_money_ps": round(state.roll60_money_ps),
            "money_accel": 1 if state.money_accel else 0,
            "ma_permit": 1 if state.ma_permit else 0,
            "money_mult_dayavg": round(state.money_mult_dayavg, 2),
        }
        # ★[2026-07-22] 헤더 불일치 방어 — 컬럼이 추가된 날 기존 파일에 이어쓰면 헤더는 옛 컬럼인데
        #   데이터 행만 새 컬럼 수로 길어져 CSV 전체가 어긋난다(분석 시 값이 엉뚱한 열로 읽힘).
        #   기존 파일의 헤더가 현재 EVENT_COLUMNS와 다르면 .old-N 으로 물러두고 새 헤더로 다시 시작한다.
        if not new:
            try:
                with self.event_path.open("r", encoding="utf-8-sig", newline="") as fh:
                    first = (fh.readline() or "").strip()
                if first and [c.strip() for c in first.split(",")] != self.EVENT_COLUMNS:
                    for i in range(1, 100):
                        alt = self.event_path.with_suffix(f".old{i}.csv")
                        if not alt.exists():
                            os.replace(self.event_path, alt)
                            self.log.warning("이벤트 CSV 컬럼 변경 감지 → 기존 파일 보존: %s", alt.name)
                            break
                    new = True
            except Exception:
                self.log.exception("이벤트 CSV 헤더 확인 실패")
        try:
            with self.event_path.open("a", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.EVENT_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            self.log.exception("이벤트 CSV 기록 실패")

    # ── ★[구조판정 SHADOW 2026-07-24 친구님 승인] 계층 B 병렬기록 (판정 미사용·실매도 무변경) ──
    #    구조 3/3 = [종가<VWAP] & [직전 struct_shadow_min_bars 완성분봉 저점 이탈] & [최근60초 순매도].
    #    매 보유루프 계산해 구조붕괴 '전이' 또는 실제 매도(_close) 순간에만 1줄 기록. 전부 try/except.
    def _sh_update_bars(self, p: "MarketPoint", state: "FlowState") -> None:
        """직전 완성 1분봉의 저가만 누적(미완성 봉 미사용). 진입이 바뀌면 초기화."""
        if state.sh_entry_ref != state.entry_ts:
            state.sh_entry_ref = state.entry_ts
            state.sh_bar_min = -1
            state.sh_bar_low = 0.0
            state.sh_lows.clear()
            state.sh_last_state = ""
        now_min = p.ts.hour * 60 + p.ts.minute
        if state.sh_bar_min < 0:
            state.sh_bar_min = now_min
            state.sh_bar_low = p.price
        elif now_min != state.sh_bar_min:
            state.sh_lows.append(state.sh_bar_low)   # 방금 끝난 분봉의 저가 확정
            state.sh_bar_min = now_min
            state.sh_bar_low = p.price
        else:
            state.sh_bar_low = min(state.sh_bar_low, p.price)

    def _sh_compute(self, p: "MarketPoint", state: "FlowState") -> Optional[Dict[str, Any]]:
        """구조 3/3 조건을 라이브 입력으로 계산. 데이터 부족=UNKNOWN. 판정에는 절대 미사용."""
        if state.entry_price <= 0:
            return None
        vw = self._vwap_of(p)                                   # ① VWAP(FID15 기반·무효시 0)
        vwap_ok = vw > 0
        cond_vwap = 1 if (vwap_ok and p.price < vw) else 0
        n_bars = len(state.sh_lows)                             # ② 직전 완성분봉 구조저점 이탈
        struct_ok = n_bars >= self.cfg.struct_shadow_min_bars
        slow5 = min(state.sh_lows) if state.sh_lows else 0.0
        cond_structlow = 1 if (struct_ok and p.price < slow5) else 0
        r60 = self.agg.roll(p.code, 60.0, p.ts.timestamp())     # ③ 최근60초 순매도([2]매수대금-[3]매도대금)
        net_ok = r60 is not None and r60[4] > 0
        net60 = (r60[2] - r60[3]) if net_ok else 0.0
        cond_netsell = 1 if (net_ok and net60 < 0) else 0
        if not (vwap_ok and struct_ok and net_ok):
            shadow_state, score = "STRUCTURE_UNKNOWN", -1
        else:
            score = cond_vwap + cond_structlow + cond_netsell
            shadow_state = "STRUCTURE_BREAK" if score >= 3 else "STRUCTURE_ALIVE"
        peak = state.peak_price or p.price
        return {
            "ts": p.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "code": p.code, "name": state.name,
            "entry_ts": state.entry_ts.strftime("%H:%M:%S") if state.entry_ts else "",
            "entry_price": state.entry_price, "price": p.price,
            "pnl_pct": round((p.price / state.entry_price - 1) * 100, 3),
            "peak_price": peak,
            "peak_dd_pct": round((peak - p.price) / peak * 100, 3) if peak > 0 else 0.0,
            "vwap": round(vw) if vwap_ok else "", "cond_vwap": cond_vwap,
            "structure_low_5": round(slow5) if struct_ok else "", "n_bars": n_bars,
            "cond_structlow": cond_structlow,
            "net_krw_60s": round(net60) if net_ok else "", "cond_netsell": cond_netsell,
            "score_count": score, "shadow_state": shadow_state,
            "data_quality": 1 if (vwap_ok and struct_ok and net_ok) else 0,
        }

    def _sh_log(self, snap: Dict[str, Any], live_action: str, live_reason: str) -> None:
        snap = dict(snap)
        snap["live_action"] = live_action
        snap["live_reason"] = live_reason
        try:
            self.struct_shadow_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.struct_shadow_path.exists()
            with self.struct_shadow_path.open("a", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.STRUCT_SHADOW_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerow({k: snap.get(k, "") for k in self.STRUCT_SHADOW_COLUMNS})
        except Exception:
            self.log.exception("구조 SHADOW 기록 실패")

    def _sh_step(self, p: "MarketPoint", state: "FlowState") -> None:
        """매 보유루프 — 분봉 갱신 + 구조붕괴 '전이' 시 1줄 기록(기존 매도 없이 구조가 먼저 잡은 경우)."""
        try:
            self._sh_update_bars(p, state)
            snap = self._sh_compute(p, state)
            if snap is None:
                return
            st = snap["shadow_state"]
            if st == "STRUCTURE_BREAK" and state.sh_last_state != "STRUCTURE_BREAK":
                self._sh_log(snap, "HOLD", "SHADOW_BREAK_3OF3")
            state.sh_last_state = st
        except Exception:
            self.log.exception("구조 SHADOW step 실패")

    def _sh_on_close(self, p: "MarketPoint", state: "FlowState", reason: str) -> None:
        """실제 매도(_close) 순간 — 같은 시각 구조 판정을 나란히 기록(live_action=SELL)."""
        try:
            self._sh_update_bars(p, state)
            snap = self._sh_compute(p, state)
            if snap is not None:
                self._sh_log(snap, "SELL", reason)
        except Exception:
            self.log.exception("구조 SHADOW close 실패")

    # ── ★[2026-07-22] 공용 계좌 슬롯 / 중복 방지 / 주문번호 확정 ──────────────────────

    def _today(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _account_held_codes(self) -> Tuple[set, str]:
        """계좌 실보유 종목코드(rt_open_positions.json)와 상태.
        반환 (codes, why) — why가 빈 문자열이면 정상, 아니면 신뢰 불가 사유.
        ★파일의 주인은 reconcile_positions_from_broker_v1.py(--write, 08:50·15:35 하루 2회)다.
          장중 실시간 갱신이 아니므로 '오늘 쓰였는가'를 신선도 기준으로 삼는다."""
        p = self.cfg.rt_open_path
        try:
            if not p.exists():
                return set(), "RT_OPEN_MISSING"
            mtime = p.stat().st_mtime
            if datetime.fromtimestamp(mtime).date() != datetime.now().date():
                return set(), "RT_OPEN_STALE_NOT_TODAY"
            age = time.time() - mtime
            if age > self.cfg.rt_open_max_age_sec:
                return set(), f"RT_OPEN_STALE_{age:.0f}s"
            d = stable_json_read(p)
            if not isinstance(d, dict):
                return set(), "RT_OPEN_BROKEN"
            return ({str(c).zfill(6) for c, v in d.items()
                     if int(float((v or {}).get("qty") or 0)) > 0}, "")
        except Exception:
            return set(), "RT_OPEN_BROKEN"

    def _own_busy_codes(self) -> set:
        """CAPTAIN2가 점유 중인 종목 — 보유(HOLD/WATCH/RECOVERY_HOLD) + 주문 진행중.
        ★코드는 zfill(6)로 정규화한다 — shared_slots는 저장 시 zfill하므로, 정규화하지 않으면
          같은 종목이 두 번 세어져 빈 슬롯을 과소평가한다(합집합 이중 차감)."""
        return {str(c).zfill(6) for c, s in self.states.items()
                if s.phase in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                               Phase.BUY_PENDING, Phase.SELL_PENDING)}

    def _used_codes(self) -> set:
        """계좌 전체에서 이미 쓰이고 있는 '고유 종목코드'.
        LIVE = shared_slots 예약 ∪ rt_open_positions 실보유 ∪ CAPTAIN2 자체 진행분.
        (합집합이라 같은 종목이 양쪽에 있어도 1개로만 센다 — 슬롯 이중 차감 방지)"""
        if not self.cfg.live:
            return self._own_busy_codes()
        used = set(self._own_busy_codes())
        try:
            d = shared._load(self._today())          # 예약 종목코드 집합
            used |= {str(c).zfill(6) for c in (d.get("slots") or {})}
        except Exception:
            pass
        held, _why = self._account_held_codes()
        used |= held
        return used

    def _used_codes_count(self) -> int:
        return len(self._used_codes())

    def _available_slots(self) -> int:
        """빈 슬롯 수 = 상한 - 계좌 전체 사용 고유 종목 수.
        SHADOW는 골짜기 선례(_shadow_slot_count 909행)대로 공용 풀을 건드리지 않고 자체 카운터만 쓴다."""
        cap = min(self.cfg.max_positions, shared.MAX) if self.cfg.live else self.cfg.max_positions
        return max(0, cap - self._used_codes_count())

    def _duplicate_reason(self, code: str) -> str:
        """동일 종목 중복 진입 사유. 통과면 빈 문자열."""
        st = self.states.get(code)
        if st and st.phase in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD):
            return "ALREADY_HOLDING"
        if st and st.phase in (Phase.BUY_PENDING, Phase.SELL_PENDING):
            return "ORDER_IN_FLIGHT"
        if self.cfg.live:
            held, _why = self._account_held_codes()
            if code in held:
                return "ACCOUNT_HELD"
        return ""

    def _discover_ono(self, state: FlowState, code: str, side: str) -> str:
        """내 주문번호 확정 — 발주 직전 스냅샷(known)에 없던 '신규' 번호를 fills에서 찾는다.
        정확히 1개면 확정. 2개 이상이면 모호(타 엔진 동시주문) — 합산하지 않고 대기한다.
        캡틴1 _ono_discover(335행)와 동일 계약."""
        buy = (side == "매수")
        cur = state.buy_order_no if buy else state.sell_order_no
        if cur:
            return cur
        known = set(state.buy_known_onos if buy else state.sell_known_onos)
        since = state.buy_since_hms if buy else state.sell_since_hms
        news = [o for o in fills_by_ono(self.cfg.fills_dir, code, side, since) if o not in known]
        if len(news) == 1:
            if buy:
                state.buy_order_no = news[0]
            else:
                state.sell_order_no = news[0]
            self.log.info("ORDER_NO %s %s 주문번호=%s 확정", code, side, news[0])
            return news[0]
        if len(news) > 1 and not state.ono_ambiguous_logged:
            state.ono_ambiguous_logged = True
            self.log.warning("주문번호 모호 %s %s 신규 %d개(%s) — 동시주문 의심·확정 대기(합산 금지)",
                             code, side, len(news), ",".join(news))
        return ""

    def _known_onos(self, code: str, side: str) -> list:
        """발주 직전 스냅샷 — 이 종목의 기존 주문번호 전부(체결분 + 미체결 잔량)."""
        ks = set(fills_by_ono(self.cfg.fills_dir, code, side, "00:00:00").keys())
        try:
            ks |= set((self.execution.open_onos(code, buy=(side == "매수")) or {}).keys())
        except Exception:
            pass
        return sorted(ks)

    def _release_slot(self, code: str, state: FlowState, why: str) -> None:
        """공용 슬롯 반환 — 실제로 예약했던 경우에만(그림자는 애초에 예약 안 함)."""
        state.buy_reserved_krw = 0.0
        if not state.buy_slot_reserved:
            return
        try:
            shared.release(code, self._today())
        except Exception:
            self.log.exception("슬롯 반환 실패 %s", code)
        state.buy_slot_reserved = False
        self.log.info("SLOT_RELEASE %s (%s)", code, why)

    def _refresh_selector_codes(self) -> None:
        """돈맥 코스닥 선별기 정원(univ_codes)과 아침대장(captain)을 신규진입 허용목록으로 갱신."""
        if not self.cfg.selector_gate_on:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if self._selector_date and self._selector_date != today:
            self._selector_codes.clear()
            self._selector_ready = False
            self._selector_date = ""
        now_mono = time.monotonic()
        if now_mono - self._selector_last_try < self.cfg.selector_refresh_sec:
            return
        self._selector_last_try = now_mono
        try:
            data = stable_json_read(self.cfg.selector_board_path)
            board_date = str(data.get("ts") or "")[:10]
            if board_date != today:
                raise ValueError(f"STALE_{board_date or 'EMPTY'}")
            codes = {
                str(code).strip().zfill(6)
                for code in (data.get("univ_codes") or [])
                if str(code).strip()
            }
            captain = data.get("captain") or {}
            if isinstance(captain, dict):
                codes.update(str(code).strip().zfill(6) for code in captain if str(code).strip())
            elif isinstance(captain, list):
                codes.update(
                    str(row.get("code") or "").strip().zfill(6)
                    for row in captain
                    if isinstance(row, dict) and str(row.get("code") or "").strip()
                )
            if not codes:
                raise ValueError("EMPTY_SELECTOR")
            first_ready = not self._selector_ready
            self._selector_codes = codes
            self._selector_date = board_date
            self._selector_ready = True
            self._selector_last_warning = ""
            if first_ready:
                self.log.info("코스닥 선별기 진입관문 로드: %s %d종목", board_date, len(codes))
        except Exception as exc:
            warning = f"{type(exc).__name__}:{exc}"
            if warning != self._selector_last_warning:
                self.log.warning("코스닥 선별기 진입관문 대기 — 신규매수 차단: %s", exc)
                self._selector_last_warning = warning

    def _refresh_early_watch(self) -> None:
        """오늘 장전 압축목록만 EARLY 진입에 사용한다. 누락·구버전·날짜 불일치는 차단."""
        today = datetime.now().strftime("%Y%m%d")
        if self._early_watch_date and self._early_watch_date != today:
            self._early_watch_meta.clear()
            self._early_watch_ready = False
            self._early_watch_date = ""
        now_mono = time.monotonic()
        if now_mono - self._early_watch_last_try < self.cfg.selector_refresh_sec:
            return
        self._early_watch_last_try = now_mono
        try:
            data = stable_json_read(self.cfg.early_watch_path)
            watch_date = str(data.get("for_date") or "")
            if watch_date != today:
                raise ValueError(f"STALE_{watch_date or 'EMPTY'}")
            qualified = {
                str(code).strip().zfill(6)
                for code in (data.get("qualified_codes") or [])
                if str(code).strip()
            }
            raw_meta = data.get("meta") or {}
            meta: Dict[str, Dict[str, float]] = {}
            for code in qualified:
                row = raw_meta.get(code) or raw_meta.get(str(code).lstrip("0")) or {}
                prev_close = safe_float(row.get("prev_close")) if isinstance(row, dict) else 0.0
                if prev_close > 0:
                    meta[code] = {
                        "prev_close": prev_close,
                        "ret_5d_pct": safe_float(row.get("ret_5d_pct")),
                        "high_close_pct": safe_float(row.get("high_close_pct")),
                        "value_ratio_20d": safe_float(row.get("value_ratio_20d")),
                    }
            if not meta:
                raise ValueError("EMPTY_QUALIFIED")
            first_ready = not self._early_watch_ready
            self._early_watch_meta = meta
            self._early_watch_date = watch_date
            self._early_watch_ready = True
            self._early_watch_last_warning = ""
            if first_ready:
                self.log.info("EARLY 장전 압축목록 로드: %s %d종목", watch_date, len(meta))
        except Exception as exc:
            self._early_watch_meta.clear()
            self._early_watch_ready = False
            warning = f"{type(exc).__name__}:{exc}"
            if warning != self._early_watch_last_warning:
                self.log.warning("EARLY 장전 압축목록 대기 — 초입매수 차단: %s", exc)
                self._early_watch_last_warning = warning

    def _early_prev_close(self, code: str) -> float:
        self._refresh_early_watch()
        if not self._early_watch_ready:
            return 0.0
        return safe_float((self._early_watch_meta.get(str(code).zfill(6)) or {}).get("prev_close"))

    def _market_filter(self, p: MarketPoint) -> Tuple[bool, str]:
        """★[2026-07-22] 잡주 제거 관문 — 신규 진입 경로에만 적용(HOLD·WATCH 매도추적에는 미적용)."""
        if p.price < self.cfg.min_price:
            return False, f"PRICE_LT_{self.cfg.min_price:.0f}"
        if p.today_value_krw < self.cfg.min_today_value_krw:
            return False, f"TODAY_VALUE_LT_{self.cfg.min_today_value_krw:.0f}"
        return True, "OK"

    def _refresh_reverse_ma(self) -> None:
        """당일 돈흐름 MA 캐시의 역배열 목록을 짧게 재시도해 로드한다."""
        if not self.cfg.reverse_ma_gate_on:
            return
        today = datetime.now().strftime("%Y%m%d")
        if self._reverse_ma_date == today:
            return
        now_mono = time.monotonic()
        if now_mono - self._reverse_ma_last_try < 10.0:
            return
        self._reverse_ma_last_try = now_mono
        try:
            data = stable_json_read(self.cfg.ma60_cache_path)
            data_date = str(data.get("date") or "")
            if data_date != today:
                warning = f"STALE_{data_date or 'EMPTY'}"
                if warning != self._reverse_ma_last_warning:
                    self.log.warning("역배열 캐시 당일 자료 대기: %s", warning)
                    self._reverse_ma_last_warning = warning
                return
            reval = data.get("reval") or {}
            self._reverse_ma_codes = {
                str(code).zfill(6) for code, blocked in reval.items() if blocked
            }
            self._reverse_ma_date = data_date
            self._reverse_ma_last_warning = ""
            self.log.info("역배열 진입차단 로드: %s %d종목",
                          data_date, len(self._reverse_ma_codes))
        except Exception as exc:
            warning = f"{type(exc).__name__}:{exc}"
            if warning != self._reverse_ma_last_warning:
                self.log.warning("역배열 캐시 로드 실패 — 기존 관문만 적용: %s", exc)
                self._reverse_ma_last_warning = warning

    def _entry_filter(self, p: MarketPoint, require_today_value: bool = True) -> Tuple[bool, str]:
        """세 진입 레인 공통 관문: 가격·거래대금·역배열."""
        if require_today_value:
            ok, why = self._market_filter(p)
        else:
            ok, why = (p.price >= self.cfg.min_price,
                       "OK" if p.price >= self.cfg.min_price else f"PRICE_LT_{self.cfg.min_price:.0f}")
        if not ok:
            return False, why
        if self.cfg.selector_gate_on:
            self._refresh_selector_codes()
            if not self._selector_ready:
                return False, "KOSDAQ_SELECTOR_NOT_READY"
            if str(p.code).strip().zfill(6) not in self._selector_codes:
                return False, "NOT_IN_KOSDAQ_SELECTOR"
        if self.cfg.reverse_ma_gate_on:
            self._refresh_reverse_ma()
            if str(p.code).zfill(6) in self._reverse_ma_codes:
                return False, "REVERSE_MA_5_20_LT_60"
        return True, "OK"

    @staticmethod
    def _base_detect(hist: Iterable, base_n: int, tight_pct: float,
                     min_volx: float) -> Optional[Tuple[float, float, float]]:
        """완성 1분봉만 사용: 직전 N봉 응집 → 마지막 양봉 상단돌파·거래량 폭발."""
        rows = list(hist)
        if len(rows) < base_n + 1:
            return None
        base = rows[-(base_n + 1):-1]
        _hm, op, _hi, _lo, close, vol = rows[-1]
        base_hi = max(float(b[2]) for b in base)
        base_lo = min(float(b[3]) for b in base)
        if base_lo <= 0:
            return None
        range_pct = (base_hi / base_lo - 1.0) * 100.0
        avg_vol = sum(float(b[5]) for b in base) / len(base)
        if (range_pct > tight_pct or avg_vol <= 0 or close <= op
                or close <= base_hi or vol < avg_vol * min_volx):
            return None
        return base_hi, range_pct, vol / avg_vol

    def _base_seed_from_shadow_ledger(self) -> None:
        """재시작 때 09:00 이후 모은 완성봉을 잃지 않도록 기존 주문0 장부만 시드로 재사용."""
        if not self.cfg.base_on:
            return
        try:
            data = stable_json_read(self.cfg.base_seed_ledger_path)
            if str(data.get("date") or "") != datetime.now().strftime("%Y%m%d"):
                return
            for raw_code, saved in (data.get("codes") or {}).items():
                code = str(raw_code).zfill(6)
                st = BasePatternState()
                for row in (saved.get("hist") or [])[-45:]:
                    if isinstance(row, list) and len(row) >= 6:
                        st.hist.append(tuple(row[:6]))
                st.cap_hm = str(saved.get("cap_hm") or "")
                # WAIT만 승계한다. POS는 이미 과거 리테스트에서 체결된 신호라 재시작 추격 금지.
                if (str(saved.get("state") or "") == "WAIT"
                        and float(saved.get("bo_vx") or 0) >= self.cfg.base_volx):
                    st.armed = True
                    st.breakout_hm = str(saved.get("bo_hm") or "")
                    st.limit = float(saved.get("limit") or 0)
                    st.wait_left = max(0, int(saved.get("wait_left") or 0))
                    st.range_pct = float(saved.get("bo_rng") or 0)
                    st.volx = float(saved.get("bo_vx") or 0)
                self.base[code] = st
            if self.base:
                self.log.info("BASE 1분봉 재시작 시드 %d종목(주문0 장부·TR0)", len(self.base))
        except Exception as exc:
            self.log.warning("BASE 시드 없음 — 현재 기동 후 완성봉부터 수집: %s", exc)

    def _start_base_retest(self, p: MarketPoint, pattern: BasePatternState) -> None:
        """돌파선 리테스트에서 즉시 매수하지 않고 실제 저점 탐색을 시작한다."""
        old = self.states.get(p.code)
        if old and old.phase in (
                Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                Phase.BUY_PENDING, Phase.SELL_PENDING):
            return
        ok, _why = self._entry_filter(p)
        if not ok:
            return
        buy_cum, sell_cum = self.agg.cum_now(p.code)
        buy_money, sell_money = self.agg.money_now(p.code)
        state = FlowState(code=p.code, name=self.feed.names.get(p.code, p.code))
        state.lane = "BASE"
        state.phase = Phase.LOW_SEARCH
        state.flow_detect_ts = p.ts
        state.candidate_low = CandidateLow(
            ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
            ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
            buy_cum=buy_cum, sell_cum=sell_cum,
            buy_money=buy_money, sell_money=sell_money)
        state.last_low_update_ts = p.ts
        state.last_update_ts = p.ts
        state.episode_high = max(pattern.breakout_close, p.price)
        self.states[p.code] = state
        pattern.armed = False
        pattern.retest_started = True
        replaced = f" · 기존 {old.lane}/{old.phase.value} 대체" if old else ""
        self._event(
            p, state, "BASE_RETEST",
            f"돌파선 {pattern.limit:.0f} 리테스트·즉시매수 금지 → 실제저점/매수우위 대기 "
            f"(응집 {pattern.range_pct:.2f}%·거래량 {pattern.volx:.1f}배){replaced}")

    def _base_step(self, points: Mapping[str, MarketPoint]) -> None:
        """완성 1분봉으로 BASE를 무장하고, 실시간 리테스트에서 BASE 저점탐색을 연다."""
        if not self.cfg.base_on or not points:
            return
        hm = datetime.now().strftime("%H%M")
        if hm != self._base_last_hm:
            try:
                bars = stable_json_read(self.cfg.base_bars_path)
                if str(bars.get("hm") or "") != hm:
                    raise ValueError(f"STALE_HM_{bars.get('hm')}")
                minute_map = bars.get("m") or {}
                for code in points:
                    item = minute_map.get(code) or {}
                    prev = item.get("prev") or []
                    pv = item.get("pv") or []
                    st = self.base.setdefault(code, BasePatternState())
                    if st.cap_hm == hm or not prev or not pv:
                        continue
                    vals = [float(x) for x in prev[-1][:4]]
                    minute = int(hm[:2]) * 60 + int(hm[2:]) - 1
                    bar_hm = f"{minute // 60:02d}{minute % 60:02d}"
                    if not st.hist or str(st.hist[-1][0]) != bar_hm:
                        st.hist.append((bar_hm, vals[0], vals[1], vals[2],
                                        vals[3], float(pv[-1])))
                        if st.armed:
                            st.wait_left -= 1
                            if st.wait_left <= 0:
                                self.log.info("[BASE EXPIRE] %s(%s) 돌파선 %.0f 리테스트 미도달",
                                              self.feed.names.get(code, code), code, st.limit)
                                st.armed = False
                        elif self.cfg.base_entry_start <= hm <= self.cfg.base_entry_end:
                            det = self._base_detect(
                                st.hist, self.cfg.base_n,
                                self.cfg.base_tight_pct, self.cfg.base_volx)
                            if det:
                                line, range_pct, volx = det
                                st.armed = True
                                st.retest_started = False
                                st.breakout_hm = hm
                                st.limit = line
                                st.wait_left = self.cfg.base_wait_bars
                                st.range_pct = range_pct
                                st.volx = volx
                                st.breakout_close = vals[3]
                                self.log.info(
                                    "[BASE ARMED] %s(%s) 선=%.0f 응집=%.2f%% 거래량=%.1f배 "
                                    "→ %d분 리테스트 대기",
                                    self.feed.names.get(code, code), code, line,
                                    range_pct, volx, self.cfg.base_wait_bars)
                    st.cap_hm = hm
                self._base_last_hm = hm
                self._base_last_error = ""
            except Exception as exc:
                msg = f"{type(exc).__name__}:{exc}"
                if msg != self._base_last_error:
                    self.log.warning("BASE 1분봉 대기 — 판정 보류: %s", msg)
                    self._base_last_error = msg

        # 돌파선 이하는 관찰 시작일 뿐 매수가 아니다. 기존 저점·실체결 관문이 뒤에서 확정한다.
        for code, st in list(self.base.items()):
            if not st.armed or st.retest_started or st.wait_left <= 0:
                continue
            p = points.get(code)
            if p is not None and st.limit > 0 and p.price <= st.limit:
                self._start_base_retest(p, st)


    @staticmethod
    def _reaccel_detect(
            bars: Iterable, day_open: float, min_day_gain_pct: float,
            min_age_bars: int, max_ext_pct: float, min_volx: float,
            max_surge5_pct: float) -> Optional[Dict[str, float]]:
        """과거 신고가재돌파 조건을 완성 3분봉으로 재현한다(진행봉 추정·주문 없음)."""
        rows = list(bars)
        if day_open <= 0 or len(rows) < min_age_bars + 2:
            return None
        current = rows[-1]
        _hm, op, _hi, _lo, close, volume = current
        if close < day_open * (1.0 + min_day_gain_pct / 100.0) or close <= op:
            return None
        prior = rows[:-1]
        prior_high = max(float(bar[2]) for bar in prior)
        hi_idx = max(i for i, bar in enumerate(prior)
                     if float(bar[2]) >= prior_high)
        age = (len(rows) - 1) - hi_idx
        if age < min_age_bars or close <= prior_high:
            return None
        ext_pct = (close / prior_high - 1.0) * 100.0
        if ext_pct > max_ext_pct:
            return None
        surge5_pct = 0.0
        if len(rows) >= 6 and float(rows[-6][4]) > 0:
            surge5_pct = (close / float(rows[-6][4]) - 1.0) * 100.0
            if max_surge5_pct > 0 and surge5_pct > max_surge5_pct:
                return None
        window = rows[-(min_age_bars + 1):-1]
        avg_volume = (sum(float(bar[5]) for bar in window) / len(window)
                      if window else 0.0)
        volx = volume / avg_volume if avg_volume > 0 else 0.0
        if min_volx > 0 and (avg_volume <= 0 or volx < min_volx):
            return None
        return {
            "line": prior_high,
            "age": float(age),
            "ext_pct": ext_pct,
            "volx": volx,
            "surge5_pct": surge5_pct,
            "signal_price": float(close),
        }

    def _reaccel_shadow_log(
            self, p: MarketPoint, state: ReaccelShadowState, event: str,
            day_open: float, buy_vol: float = 0.0, sell_vol: float = 0.0,
            buy_money: float = 0.0, sell_money: float = 0.0,
            persist_ok: bool = False, reason: str = "") -> None:
        """재가속 관찰 CSV만 기록한다. 주문·FlowState·공용 슬롯에는 접근하지 않는다."""
        try:
            total_vol = buy_vol + sell_vol
            buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5
            buy_sell_ratio = buy_vol / max(sell_vol, 1e-9) if total_vol > 0 else 1.0
            elapsed = ((p.ts - state.arm_ts).total_seconds()
                       if state.arm_ts is not None else 0.0)
            dominance_sec = ((p.ts - state.dominance_since).total_seconds()
                             if state.dominance_since is not None else 0.0)
            row = {
                "ts": p.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "code": p.code,
                "name": self.feed.names.get(p.code, p.code),
                "event": event,
                "price": p.price,
                "signal_price": state.signal_price,
                "line": state.line,
                "elapsed_sec": round(elapsed, 3),
                "day_gain_pct": round(
                    (state.signal_price / day_open - 1.0) * 100.0, 3)
                if day_open > 0 else "",
                "age_bars": state.age,
                "ext_pct": round(state.ext_pct, 3),
                "volx": round(state.volx, 3),
                "surge5_pct": round(state.surge5_pct, 3),
                "buy_exec_vol": round(buy_vol, 3),
                "sell_exec_vol": round(sell_vol, 3),
                "buy_ratio": round(buy_ratio, 4),
                "buy_sell_ratio": round(buy_sell_ratio, 4),
                "buy_exec_money": round(buy_money),
                "sell_exec_money": round(sell_money),
                "money_total_krw": round(buy_money + sell_money),
                "persist_ok": 1 if persist_ok else 0,
                "dominance_sec": round(dominance_sec, 3),
                "side_exact": 1 if self.agg.is_exact(p.code) else 0,
                "reason": reason,
            }
            self.reaccel_shadow_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.reaccel_shadow_path.exists()
            with self.reaccel_shadow_path.open(
                    "a", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.REACCEL_SHADOW_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            self.log.exception("재가속 SHADOW 기록 실패 %s", p.code)

    def _reaccel_shadow_gate(
            self, p: MarketPoint, state: ReaccelShadowState,
            day_open: float, allow_live: bool = False
            ) -> Optional[Tuple[MarketPoint, FlowState, str]]:
        if state.status != "WATCH" or state.arm_ts is None:
            return None
        elapsed = (p.ts - state.arm_ts).total_seconds()
        buy_now, sell_now = self.agg.cum_now(p.code)
        buy_money_now, sell_money_now = self.agg.money_now(p.code)
        buy_vol = max(0.0, buy_now - state.base_buy_cum)
        sell_vol = max(0.0, sell_now - state.base_sell_cum)
        buy_money = max(0.0, buy_money_now - state.base_buy_money)
        sell_money = max(0.0, sell_money_now - state.base_sell_money)
        if p.price < state.line:
            self._reaccel_shadow_log(
                p, state, "FAILED_LINE", day_open, buy_vol, sell_vol,
                buy_money, sell_money, reason="돌파선 이탈")
            state.status = "DONE"
            return None
        if p.price > state.line * (1.0 + self.cfg.reaccel_max_ext_pct / 100.0):
            self._reaccel_shadow_log(
                p, state, "FAILED_CHASE", day_open, buy_vol, sell_vol,
                buy_money, sell_money, reason="돌파선 대비 추격상한 초과")
            state.status = "DONE"
            return None
        if elapsed > self.cfg.reaccel_gate_max_sec:
            self._reaccel_shadow_log(
                p, state, "EXPIRED", day_open, buy_vol, sell_vol,
                buy_money, sell_money, reason="60초 관문 미완성")
            state.status = "DONE"
            return None
        total_vol = buy_vol + sell_vol
        buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5
        buy_sell_ratio = buy_vol / max(sell_vol, 1e-9) if total_vol > 0 else 1.0
        r10 = self.agg.roll(p.code, 10.0, p.ts.timestamp())
        r30 = self.agg.roll(p.code, 30.0, p.ts.timestamp())
        speed10 = ((max(0.0, r10[2]) + max(0.0, r10[3])) / r10[4]
                   if r10 is not None and r10[4] > 0 else 0.0)
        speed30 = ((max(0.0, r30[2]) + max(0.0, r30[3])) / r30[4]
                   if r30 is not None and r30[4] > 0 else 0.0)
        persist_ok = not (
            speed30 > 0 and speed10 < self.cfg.persist_min_frac * speed30)
        dominance_ok = (
            self.agg.is_exact(p.code)
            and buy_money + sell_money >= self.cfg.min_entry_money_krw
            and total_vol >= self.cfg.min_reset_exec_volume
            and buy_ratio >= self.cfg.min_buy_ratio
            and buy_sell_ratio >= self.cfg.min_buy_sell_ratio
            and persist_ok
        )
        if dominance_ok:
            if state.dominance_since is None:
                state.dominance_since = p.ts
        else:
            state.dominance_since = None
        dominance_sec = ((p.ts - state.dominance_since).total_seconds()
                         if state.dominance_since is not None else 0.0)
        if dominance_ok and dominance_sec >= self.cfg.buy_confirm_sec:
            self._reaccel_shadow_log(
                p, state, "READY_SHADOW", day_open, buy_vol, sell_vol,
                buy_money, sell_money, persist_ok,
                "돌파선 유지·실체결 매수우위 2초")
            candidate = None
            if self.cfg.reaccel_live_on and allow_live:
                candidate = self._reaccel_live_candidate(
                    p, state, day_open, buy_vol, sell_vol,
                    buy_money, sell_money, persist_ok)
            state.status = "DONE"
            return candidate
        return None

    def _reaccel_live_candidate(
            self, p: MarketPoint, state: ReaccelShadowState, day_open: float,
            buy_vol: float, sell_vol: float, buy_money: float,
            sell_money: float, persist_ok: bool
            ) -> Optional[Tuple[MarketPoint, FlowState, str]]:
        """재가속 READY를 공통 후보 풀로 보내 테마대장 가점·슬롯·주문 관문을 재사용한다."""
        entry_ok, entry_reason = self._entry_filter(p)
        vw = self._vwap_of(p) if self.cfg.vwap_gate_on else 0.0
        if not entry_ok or (vw > 0 and p.price <= vw):
            reason = entry_reason if not entry_ok else f"VWAP_GATE {p.price:.0f}<=VWAP{vw:.0f}"
            self._reaccel_shadow_log(
                p, state, "LIVE_BLOCKED", day_open, buy_vol, sell_vol,
                buy_money, sell_money, persist_ok, reason)
            return None
        previous = self.states.get(p.code)
        if previous is not None and previous.phase not in (
                Phase.IDLE, Phase.FAILED, Phase.CLOSED):
            self._reaccel_shadow_log(
                p, state, "LIVE_BLOCKED", day_open, buy_vol, sell_vol,
                buy_money, sell_money, persist_ok,
                f"기존상태 {previous.phase.value}")
            return None

        elapsed = max((p.ts - state.arm_ts).total_seconds(), 1.0)
        total_vol = buy_vol + sell_vol
        total_money = buy_money + sell_money
        flow = FlowState(code=p.code, name=self.feed.names.get(p.code, p.code))
        flow.lane = "REACCEL"
        flow.phase = Phase.BUY_READY
        flow.reset_id = uuid.uuid4().hex[:12]
        flow.reset_ts = state.arm_ts
        flow.reset_price = state.line
        flow.reset_buy_cum = state.base_buy_cum
        flow.reset_sell_cum = state.base_sell_cum
        flow.reset_buy_money = state.base_buy_money
        flow.reset_sell_money = state.base_sell_money
        flow.reset_cum_vol = max(0.0, p.cum_vol - total_vol)
        flow.reset_che_str = p.che_str
        flow.reset_ask_tot = p.ask_tot
        flow.reset_bid_tot = p.bid_tot
        flow.reset_imb = p.imb
        flow.reset_high = max(state.signal_price, p.price)
        flow.reset_low = state.line
        flow.structure_low = state.line
        flow.buy_exec_vol = buy_vol
        flow.sell_exec_vol = sell_vol
        flow.buy_exec_money = buy_money
        flow.sell_exec_money = sell_money
        flow.buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5
        flow.buy_sell_ratio = buy_vol / max(sell_vol, 1e-9) if total_vol > 0 else 1.0
        flow.buy_money_ratio = buy_money / total_money if total_money > 0 else 0.5
        flow.side_exact = self.agg.is_exact(p.code)
        flow.price_response_pct = (
            (p.price / state.line - 1.0) * 100.0 if state.line > 0 else 0.0)
        flow.reset_delta_volume = total_vol
        flow.reset_money_add_krw = total_money
        flow.reset_money_per_sec_krw = total_money / elapsed
        flow.money_size_grade = self._money_size_grade(total_money)
        self.states[p.code] = flow
        reason = (
            f"REACCEL line={state.line:.0f} ext={state.ext_pct:.2f}% "
            f"volx={state.volx:.2f} buy={flow.buy_ratio:.1%} "
            f"money={total_money / 1e8:.2f}억 theme={p.theme_signal or '-'}")
        self._event(p, flow, "REACCEL_READY", reason)
        return p, flow, reason

    def _reaccel_shadow_step(
            self, points: Mapping[str, MarketPoint],
            allow_live: bool = False) -> list:
        """실시간 3분봉 재돌파를 관찰하고 LIVE READY는 공통 후보 풀로 반환한다."""
        if not (self.cfg.reaccel_shadow_on or self.cfg.reaccel_live_on):
            return []
        candidates = []
        for p in points.values():
            if p.ts.strftime("%H%M") < "0900":
                continue
            state = self.reaccel_shadow.setdefault(p.code, ReaccelShadowState())
            day_open = self._day_open_of(p)
            bucket = int(p.ts.timestamp() // 180)
            if state.bucket < 0:
                state.bucket = bucket
                state.bar_hm = p.ts.strftime("%H%M")
                state.bar_open = state.bar_high = state.bar_low = state.bar_close = p.price
                state.bar_start_cum = state.bar_last_cum = p.cum_vol
            elif bucket == state.bucket:
                state.bar_high = max(state.bar_high, p.price)
                state.bar_low = min(state.bar_low, p.price)
                state.bar_close = p.price
                state.bar_last_cum = p.cum_vol
            else:
                consecutive_bucket = bucket - state.bucket == 1
                new_bar_start_cum = state.bar_last_cum if consecutive_bucket else p.cum_vol
                if consecutive_bucket and state.bar_open > 0:
                    volume = max(0.0, state.bar_last_cum - state.bar_start_cum)
                    state.bars.append((
                        state.bar_hm, state.bar_open, state.bar_high,
                        state.bar_low, state.bar_close, volume))
                    signal_hm = state.bar_hm
                    if (state.status != "WATCH"
                            and self.cfg.reaccel_start <= signal_hm <= self.cfg.reaccel_end):
                        hit = self._reaccel_detect(
                            state.bars, day_open,
                            self.cfg.reaccel_min_day_gain_pct,
                            self.cfg.reaccel_min_age_bars,
                            self.cfg.reaccel_max_ext_pct,
                            self.cfg.reaccel_min_volx,
                            self.cfg.reaccel_max_surge5_pct)
                        if hit is not None:
                            entry_ok, _entry_reason = self._entry_filter(p)
                            if entry_ok:
                                state.status = "WATCH"
                                state.arm_ts = p.ts
                                state.signal_price = hit["signal_price"]
                                state.line = hit["line"]
                                state.age = int(hit["age"])
                                state.ext_pct = hit["ext_pct"]
                                state.volx = hit["volx"]
                                state.surge5_pct = hit["surge5_pct"]
                                state.base_buy_cum, state.base_sell_cum = (
                                    self.agg.cum_now(p.code))
                                state.base_buy_money, state.base_sell_money = (
                                    self.agg.money_now(p.code))
                                state.dominance_since = None
                                self._reaccel_shadow_log(
                                    p, state, "ARMED", day_open,
                                    reason="완성3분봉 재돌파·60초 실체결 관문 시작")
                state.bucket = bucket
                state.bar_hm = p.ts.strftime("%H%M")
                state.bar_open = state.bar_high = state.bar_low = state.bar_close = p.price
                state.bar_start_cum = new_bar_start_cum
                state.bar_last_cum = p.cum_vol
            candidate = self._reaccel_shadow_gate(p, state, day_open, allow_live)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    @staticmethod
    def _money_size_grade(money_krw: float) -> str:
        """★[2026-07-22] RESET 이후 신규 유입대금 규모 등급 — 관찰·로그용. BUY 차단에 쓰지 않는다
        (SMALL이라고 매수를 막지 않음). 잡주 제거는 _market_filter가 이미 처리한다."""
        if money_krw >= 1_000_000_000:
            return "VERY_LARGE"
        if money_krw >= 500_000_000:
            return "LARGE"
        if money_krw >= 100_000_000:
            return "MEDIUM"
        return "SMALL"

    def _is_surge(self, p: MarketPoint) -> bool:
        # ★[보완3종 2026-07-22] 큰돈 문턱 — 5초 유입속도가 분당 1억 미만이면 어떤 신호든 급증 아님.
        #   상대 배율만 보던 원본은 하루 619종목에 발화(잔파도 경보)·진입 전원 SMALL이었다.
        if p.money_speed_5s < self.cfg.surge_min_mps:
            return False
        if p.money_start or p.money_start_raw:
            return True
        if p.money_add_5s <= self.cfg.min_money_add_5s:
            return False
        if p.money_speed_30s <= 0:
            return False
        burst = p.money_speed_5s / max(p.money_speed_30s, 1e-9)
        return burst >= self.cfg.min_burst_ratio and p.money_speed_5s >= p.money_speed_10s

    def _lane_windows(self, state: FlowState) -> Tuple[float, float, float, float]:
        """레인별 (저점탐색 상한, 무갱신 확정, 진입확인창 상한, 지속확인). 실측 도출값은 Config 참조."""
        if state.lane == "PULL":
            return (self.cfg.pull_low_search_max_sec, self.cfg.pull_low_no_new_sec,
                    self.cfg.pull_buy_max_sec, self.cfg.pull_buy_confirm_sec)
        if state.lane == "BASE":
            return (self.cfg.base_low_search_max_sec, self.cfg.low_no_new_sec,
                    self.cfg.base_buy_max_sec, self.cfg.buy_confirm_sec)
        return (self.cfg.low_search_max_sec, self.cfg.low_no_new_sec,
                self.cfg.buy_max_elapsed_sec, self.cfg.buy_confirm_sec)

    def _pull_zone_ok(self, p: MarketPoint, state: FlowState) -> Tuple[bool, str]:
        """PULL 매수 위치: 의미 있는 눌림이며 저점→고점 회복 구간의 중·하단인지 확인."""
        high = state.pull_reference_high
        low = state.reset_price
        if high <= low or low <= 0:
            return False, "PULL 위치기준 없음"
        depth_pct = (1.0 - low / high) * 100.0
        recovery_pct = (p.price - low) / (high - low) * 100.0
        if depth_pct < self.cfg.pull_min_depth_pct:
            return False, (f"PULL 고점구간 차단: 눌림깊이 {depth_pct:.2f}%"
                           f"<{self.cfg.pull_min_depth_pct:.2f}%")
        if recovery_pct > self.cfg.pull_max_recovery_pct:
            return False, (f"PULL 고점추격 차단: 저점→고점 회복위치 {recovery_pct:.1f}%"
                           f">{self.cfg.pull_max_recovery_pct:.1f}%")
        return True, (f"PULL 중·저점구간: 깊이 {depth_pct:.2f}%·"
                      f"회복위치 {recovery_pct:.1f}%")

    def _start_low_search(self, p: MarketPoint, state: FlowState) -> None:
        # ★[눌림레인 2026-07-22] 직전 에피소드 고점 대비 -0.8% 이상 아래에서 시작하는 새 탐색 =
        #   눌림 반등 국면 → PULL 레인(느린 창). 그 외 = RAID(급습·현행 창 그대로).
        state.lane = "RAID"
        state.pull_reference_high = 0.0
        if (state.prev_episode_high > 0 and state.prev_episode_end_ts is not None
                and (p.ts - state.prev_episode_end_ts).total_seconds() <= self.cfg.pull_prev_max_age_sec
                and p.price <= state.prev_episode_high * (1 - self.cfg.pull_split_drop_pct / 100)):
            state.lane = "PULL"
            state.pull_reference_high = state.prev_episode_high
        buy_cum, sell_cum = self.agg.cum_now(p.code)      # ★실체결 누계(역산 아님)
        buy_money, sell_money = self.agg.money_now(p.code)
        low = CandidateLow(
            ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
            ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
            buy_cum=buy_cum, sell_cum=sell_cum,
            buy_money=buy_money, sell_money=sell_money,
        )
        state.phase = Phase.LOW_SEARCH
        state.flow_detect_ts = p.ts
        state.candidate_low = low
        state.last_low_update_ts = p.ts
        state.last_update_ts = p.ts
        state.episode_high = p.price          # ★[눌림레인 점검1] 에피소드 고점 추적 시작
        self._event(p, state, "FLOW_DETECTED")

    def _update_low_search(self, p: MarketPoint, state: FlowState) -> None:
        assert state.candidate_low is not None
        if p.price > state.episode_high:      # ★[눌림레인 점검1] 매수 전 구간에서도 고점 추적
            state.episode_high = p.price
            if state.lane == "PULL":
                state.pull_reference_high = max(state.pull_reference_high, state.episode_high)
        # ★[수익성 진단 2026-07-24] 같은 급등 에피소드 안의 '상승 후 눌림'도 PULL로 전환.
        #   종전에는 이전 에피소드가 끝난 뒤 새 급증이 와야만 PULL이 되어 실제 PULL 체결이 0건이었다.
        split = self.cfg.pull_split_drop_pct / 100.0
        rose_enough = state.episode_high >= state.candidate_low.price * (1 + split)
        pulled_back = p.price <= state.episode_high * (1 - split)
        if state.lane == "RAID" and rose_enough and pulled_back:
            state.lane = "PULL"
            state.pull_l1_price = 0.0
            state.pull_rebound_high = 0.0
            state.pull_repull_seen = False
            state.pull_reference_high = state.episode_high
            self._event(
                p, state, "PULL_LANE_SWITCH",
                f"에피소드고점 {state.episode_high:.0f} 대비 "
                f"{(p.price / state.episode_high - 1) * 100:.2f}% 눌림")
        # ★[2026-07-22 보강] 탐색시간 상한을 신저점 갱신 경로에서도 검사한다.
        #   원본은 이 검사가 '신저점이 아닐 때'(아래 else 경로)에만 있어서, 계속 신저점을 만들며
        #   떨어지는 종목은 매 루프 early return 되어 low_search_max_sec에 영원히 도달하지 못하고
        #   LOW_SEARCH에 무한 체류했다(지침서 3항 "계속 하락 시 FAILED" 위반).
        #   새 임계값·새 조건 추가 아님 — 이미 있는 low_search_max_sec을 도달 가능하게 만든 것.
        search_max, no_new_sec, _bmax, _bconf = self._lane_windows(state)   # ★[눌림레인] 레인별 창
        if (p.ts - (state.flow_detect_ts or p.ts)).total_seconds() >= search_max:
            state.phase = Phase.FAILED
            state.terminal_ts = p.ts
            state.rearm_ready = False
            self._event(p, state, "LOW_SEARCH_FAILED",
                        f"저점 상승전환 미확인(탐색시간 초과·{state.lane})")
            return
        # ★[PULL 실제 재눌림] L1 확인 뒤에는 반등 고점을 먼저 추적하고, 그 고점에서 최소
        #   1틱 다시 내려와야 L2 후보를 연다. 종전에는 L1 확인 시 현재가를 후보로 넣어
        #   재눌림 없이 15초 상승·횡보만 해도 L2로 오인할 수 있었다.
        if (state.lane == "PULL" and state.pull_l1_price > 0
                and not state.pull_repull_seen):
            state.pull_rebound_high = max(state.pull_rebound_high, p.price)
            repull_tick = krx_tick_size(state.pull_rebound_high)
            if p.price <= state.pull_rebound_high - repull_tick:
                buy_cum, sell_cum = self.agg.cum_now(p.code)
                buy_money, sell_money = self.agg.money_now(p.code)
                state.candidate_low = CandidateLow(
                    ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
                    ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
                    buy_cum=buy_cum, sell_cum=sell_cum,
                    buy_money=buy_money, sell_money=sell_money,
                )
                state.last_low_update_ts = p.ts
                state.pull_repull_seen = True
                self._event(
                    p, state, "PULL_REPULL_ARMED",
                    f"반등고점 {state.pull_rebound_high:.0f}에서 1틱 재하락 — L2 탐색 시작")
            return
        if p.price < state.candidate_low.price:
            buy_cum, sell_cum = self.agg.cum_now(p.code)  # ★실체결 누계(역산 아님)
            buy_money, sell_money = self.agg.money_now(p.code)
            state.candidate_low = CandidateLow(
                ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
                ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
                buy_cum=buy_cum, sell_cum=sell_cum,
                buy_money=buy_money, sell_money=sell_money,
            )
            state.last_low_update_ts = p.ts
            self._event(p, state, "LOW_UPDATED")
            return

        search_age = (p.ts - (state.flow_detect_ts or p.ts)).total_seconds()
        no_new_age = (p.ts - (state.last_low_update_ts or p.ts)).total_seconds()
        tick = krx_tick_size(state.candidate_low.price)
        price_confirmed = p.price >= state.candidate_low.price + self.cfg.low_confirm_ticks * tick

        if price_confirmed and no_new_age >= no_new_sec:
            # ★[PULL 5조건 2026-07-22 친구님] Higher Low 구조 — PULL은 1차 저점(L1) 확정만으로
            #   RESET하지 않는다. 반등 후 재눌림의 2차 저점(L2)이 L1보다 '높게' 확정될 때만 RESET.
            #   L2 ≤ L1이면 그 저점을 새 L1로 삼고 다시 기다린다(더 낮은 저점 = Higher Low 실패).
            #   양봉 개수 조건은 쓰지 않는다. RAID는 기존 단일 저점 확정 그대로.
            if state.lane == "PULL":
                if state.pull_l1_price <= 0 or state.candidate_low.price <= state.pull_l1_price:
                    tag = ("1차 저점" if state.pull_l1_price <= 0
                           else f"Higher Low 실패(L2 {state.candidate_low.price:.0f}≤L1 {state.pull_l1_price:.0f}) — 새 L1로")
                    state.pull_l1_price = state.candidate_low.price
                    state.pull_rebound_high = p.price
                    state.pull_repull_seen = False
                    buy_cum, sell_cum = self.agg.cum_now(p.code)
                    buy_money, sell_money = self.agg.money_now(p.code)
                    state.candidate_low = CandidateLow(
                        ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
                        ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
                        buy_cum=buy_cum, sell_cum=sell_cum,
                        buy_money=buy_money, sell_money=sell_money)
                    state.last_low_update_ts = p.ts
                    self._event(p, state, "PULL_L1_CONFIRMED",
                                f"{tag} {state.pull_l1_price:.0f} — 재눌림 L2 대기")
                    return
                # L2 > L1 확정 → RESET(앵커 = L2 = candidate_low)
            self._confirm_reset(p, state)
            return
        if search_age >= search_max:
            state.phase = Phase.FAILED
            state.terminal_ts = p.ts
            state.rearm_ready = False
            self._event(p, state, "LOW_SEARCH_FAILED", "저점 상승전환 미확인")

    def _confirm_reset(self, p: MarketPoint, state: FlowState) -> None:
        low = state.candidate_low
        assert low is not None
        state.phase = Phase.RESET
        state.reset_id = uuid.uuid4().hex[:12]
        state.reset_ts = low.ts
        state.reset_price = low.price
        state.reset_buy_cum = low.buy_cum        # ★저점 관측 시점의 실체결 누계 = RESET 기준선
        state.reset_sell_cum = low.sell_cum
        state.reset_buy_money = low.buy_money    # ★대금 기준선도 같은 시점에 동결
        state.reset_sell_money = low.sell_money
        state.reset_cum_vol = low.cum_vol
        state.reset_che_str = low.che_str
        state.reset_ask_tot = low.ask_tot
        state.reset_bid_tot = low.bid_tot
        state.reset_imb = low.imb
        state.reset_high = max(low.price, p.price)
        state.reset_low = low.price
        state.structure_low = low.price
        state.dominance_since = None
        state.watch_since = None
        state.recent_prices.clear()
        self._update_reset_metrics(p, state)
        self._event(p, state, "RESET_CONFIRMED", "실제 저점 시점으로 소급")

    def _update_reset_metrics(self, p: MarketPoint, state: FlowState) -> None:
        # ★[2026-07-22 실체결 수술] RESET 이후 우위 = 실체결 누계 차이만 사용. 역산 제거.
        buy_cum, sell_cum = self.agg.cum_now(p.code)
        buy_delta = buy_cum - state.reset_buy_cum
        sell_delta = sell_cum - state.reset_sell_cum
        # ★[2026-07-22 관찰전용] clamp 전 원시값 보존 — 아래 판정 로직은 전혀 바뀌지 않는다.
        state.obs_raw_buy_delta = buy_delta
        state.obs_raw_sell_delta = sell_delta
        state.obs_delta_cum_vol = p.cum_vol - state.reset_cum_vol
        if buy_delta < -1e-6 or sell_delta < -1e-6:
            state.anomaly_count += 1
            buy_delta = max(0.0, buy_delta)
            sell_delta = max(0.0, sell_delta)
        state.buy_exec_vol = buy_delta
        state.sell_exec_vol = sell_delta
        total = buy_delta + sell_delta
        state.buy_ratio = buy_delta / total if total > 0 else 0.5
        state.buy_sell_ratio = buy_delta / max(sell_delta, 1e-9) if total > 0 else 1.0
        # ★[REAL-SIDE 2026-07-22] RESET 이후 방향별 실거래대금 델타 — 측정·기록(관문 임계 무변경)
        bm_now, sm_now = self.agg.money_now(p.code)
        state.buy_exec_money = max(0.0, bm_now - state.reset_buy_money)
        state.sell_exec_money = max(0.0, sm_now - state.reset_sell_money)
        m_total = state.buy_exec_money + state.sell_exec_money
        state.buy_money_ratio = state.buy_exec_money / m_total if m_total > 0 else 0.5
        state.side_exact = self.agg.is_exact(p.code)

        # ★[ROLL-LIVE 2026-07-22] 매도 흐름판정용 '최근 구간' 매수비율.
        #   구간 실측이 최소 10초 안 되면 RESET 이후 비율로 폴백(초기엔 그게 곧 최근).
        now_ep = p.ts.timestamp()
        rw = self.agg.roll(p.code, self.cfg.flow_window_sec, now_ep)
        if rw is not None and rw[4] >= min(10.0, self.cfg.flow_window_sec * 0.5):
            rb, rs = max(0.0, rw[0]), max(0.0, rw[1])
            rt = rb + rs
            state.flow_ratio_recent = rb / rt if rt > 0 else 0.5
            state.flow_span_recent = rw[4]
        else:
            state.flow_ratio_recent = state.buy_ratio
            state.flow_span_recent = 0.0
        # ★[ROLL 2026-07-22 관찰전용] 윈도우 길이 튜닝용 10/30/60초 실측(판정 미사용)
        buy_speeds = []
        for w_, rf_, mf_ in ((10.0, "roll10_ratio", "roll10_money_ps"),
                             (30.0, "roll30_ratio", "roll30_money_ps"),
                             (60.0, "roll60_ratio", "roll60_money_ps")):
            r_ = self.agg.roll(p.code, w_, now_ep)
            if r_ is None:
                setattr(state, rf_, 0.5)
                setattr(state, mf_, 0.0)
                buy_speeds.append(0.0)
                continue
            b_, s_ = max(0.0, r_[0]), max(0.0, r_[1])
            t_ = b_ + s_
            setattr(state, rf_, b_ / t_ if t_ > 0 else 0.5)
            setattr(state, mf_, (max(0.0, r_[2]) + max(0.0, r_[3])) / r_[4])
            buy_speeds.append(max(0.0, r_[2]) / r_[4])

        # ★[설계8단계 2026-07-22] ③가속 = '매수대금' 속도가 10>30>60초 서열로 계속 증가
        #   (총대금이 아니라 매수대금 — 투매 폭주를 '유입'으로 오인하지 않기 위해). 하한은 기존
        #   dryup_min_peak_mps 재사용(새 임계값 발명 금지). 가속 중엔 흐름매도·돈마름을 보류한다
        #   — "계속 증가하면 절대 안 판다"(친구님 3순위). 트레일·하드손절은 그대로 산다.
        state.money_accel = (len(buy_speeds) == 3
                             and buy_speeds[0] > buy_speeds[1] > buy_speeds[2]
                             and buy_speeds[0] >= self.cfg.dryup_min_peak_mps)
        # ★[설계8단계] ①평상시 대비 배율(관찰) — 당일 평균 유입속도 대비 최근 10초 배수
        day_sec = max((p.ts - p.ts.replace(hour=9, minute=0, second=0, microsecond=0)).total_seconds(), 1.0)
        day_avg = (bm_now + sm_now) / day_sec
        state.money_mult_dayavg = (state.roll10_money_ps / day_avg) if day_avg > 0 else 0.0
        # ★[설계8단계] ⑤이평 보유 허가증 — "돈이 살아있는데 5일선 위·10일선이 상승하며 받칠 때"만.
        #   돈이 마르기 시작(dryup_since 진행 중)이면 이평 위라도 허가 없음(친구님: 그건 반대).
        m5 = self._ma5.get(p.code)
        m10 = self._ma10.get(p.code)
        m10p = self._ma10_prev.get(p.code)
        state.ma_permit = bool(state.dryup_since is None
                               and m5 is not None and m10 is not None and m10p is not None
                               and p.price > m5 and m10 > m10p)
        state.reset_high = max(state.reset_high, p.price)
        state.reset_low = min(state.reset_low, p.price)
        if p.price > state.episode_high:      # ★[눌림레인 점검1] RESET 이후 구간도 계속 추적
            state.episode_high = p.price
        state.price_response_pct = (p.price / state.reset_price - 1.0) * 100 if state.reset_price > 0 else 0.0
        state.last_update_ts = p.ts

        # ★[2026-07-22] RESET 이후 신규 유입대금 크기·속도 — 새 TR·새 틱데이터 없이 보유 값만 사용.
        elapsed_sec = max((p.ts - state.reset_ts).total_seconds(), 0.001) if state.reset_ts else 0.001
        delta_volume = p.cum_vol - state.reset_cum_vol
        if delta_volume < 0:                      # 누적거래량 역행(스냅샷 리셋 등) 방어
            state.anomaly_count += 1
            delta_volume = 0.0
        representative_price = (state.reset_price + p.price) / 2.0
        state.reset_delta_volume = delta_volume
        state.reset_money_add_krw = delta_volume * representative_price
        state.reset_money_per_sec_krw = state.reset_money_add_krw / elapsed_sec
        state.money_size_grade = self._money_size_grade(state.reset_money_add_krw)

        elapsed_epoch = p.ts.timestamp()
        state.recent_prices.append((elapsed_epoch, p.price))
        cutoff = elapsed_epoch - self.cfg.structure_lookback_sec
        state.recent_prices = [(t, px) for t, px in state.recent_prices if t >= cutoff]
        if state.recent_prices:
            state.structure_low = min(px for _, px in state.recent_prices)

    def _buy_signal(self, p: MarketPoint, state: FlowState) -> Tuple[bool, str]:
        if not state.reset_ts:
            return False, "RESET 없음"
        _smax, _nn, buy_max, buy_confirm = self._lane_windows(state)   # ★[눌림레인] 레인별 창
        elapsed = (p.ts - state.reset_ts).total_seconds()
        if elapsed < self.cfg.buy_min_elapsed_sec:
            return False, "최소 관찰시간 미달"
        if elapsed > buy_max:
            return False, f"진입 확인창 초과({state.lane})"
        if state.lane == "PULL":
            zone_ok, zone_reason = self._pull_zone_ok(p, state)
            if not zone_ok:
                state.dominance_since = None
                return False, zone_reason
        # ★[PULL 5조건] 재가속 조기반환 제거 — PULL 조건은 아래 통합 타이머에서 한 번에 판정
        #   (조기반환 방식은 재가속이 끊겨도 지속 타이머가 리셋되지 않던 결함이 있었음)
        # ★[ROLL-LIVE 2026-07-22] 진입 신뢰도 — RESET 이후 '실제' 유입대금 하한(먼지 진입 차단).
        #   오늘 실측: 0.1억 미만 진입 22/37건이 회전과다의 몸통. 방향별 실거래대금 합으로 잰다.
        money_in = state.buy_exec_money + state.sell_exec_money
        if money_in < self.cfg.min_entry_money_krw:
            return False, f"유입대금 미달 {money_in / 1e8:.2f}억"
        # ★[보완3종 2026-07-22] 우위 지속성 — 최근10초 속도가 최근30초의 절반 미만 = 유입이 이미
        #   식는 '한 방 반짝'. 진입 보류(진입창 안에서 유입이 살아나면 다음 루프에 재평가).
        if (state.roll30_money_ps > 0
                and state.roll10_money_ps < self.cfg.persist_min_frac * state.roll30_money_ps):
            return False, (f"유입 지속성 미달 10초 {state.roll10_money_ps / 1e4:.0f}만/초"
                           f"<30초 {state.roll30_money_ps / 1e4:.0f}만/초의 절반")
        total = state.buy_exec_vol + state.sell_exec_vol
        tick = krx_tick_size(state.reset_price)
        price_ok = p.price >= state.reset_price + self.cfg.min_price_ticks * tick
        dominance_ok = (
            total >= self.cfg.min_reset_exec_volume
            and state.buy_ratio >= self.cfg.min_buy_ratio
            and state.buy_sell_ratio >= self.cfg.min_buy_sell_ratio
        )
        if state.lane == "PULL":
            # ★[PULL 5조건 2026-07-22 친구님 확정 — 전부 만족이 '연속' 유지될 때만 발사]
            #   ①매도대금 속도 실제 감소(최근10초 < 최근30초, 매도 실종은 통과)
            #   ②매수대금 증가(10초 > 30초)  ③재가속(10>30>60초 서열+하한)
            #   ④Higher Low 유지(가격이 L2 위 — 저점탐색이 L2>L1을 이미 강제)
            #   ⑤위 전부+매수우위가 pull_buy_confirm_sec(5초) 연속 — 하나라도 끊기면 타이머 즉시 0
            now_ep = p.ts.timestamp()
            r10 = self.agg.roll(p.code, 10.0, now_ep)
            r30 = self.agg.roll(p.code, 30.0, now_ep)
            b10 = s10 = b30 = s30 = 0.0
            if r10 and r10[4] > 0:
                b10 = max(0.0, r10[2]) / r10[4]
                s10 = max(0.0, r10[3]) / r10[4]
            if r30 and r30[4] > 0:
                b30 = max(0.0, r30[2]) / r30[4]
                s30 = max(0.0, r30[3]) / r30[4]
            sell_decel = (s10 < s30) or s10 == 0.0
            buy_incr = b10 > b30
            hl_intact = p.price > state.reset_price
            cond = (dominance_ok and sell_decel and buy_incr
                    and state.money_accel and hl_intact)
            if cond:
                if state.dominance_since is None:
                    state.dominance_since = p.ts
                duration = (p.ts - state.dominance_since).total_seconds()
            else:
                state.dominance_since = None      # ★끊기면 즉시 0으로 초기화(친구님 3번)
                duration = 0.0
            if cond and price_ok and duration >= buy_confirm:
                return True, (f"PULL 5조건 {duration:.1f}초 연속(우위 {state.buy_ratio:.0%}·"
                              f"매도감속·매수증가·재가속·HL유지·{zone_reason})")
            fails = []
            if not dominance_ok:
                fails.append("매수우위")
            if not sell_decel:
                fails.append("매도감소")
            if not buy_incr:
                fails.append("매수증가")
            if not state.money_accel:
                fails.append("재가속")
            if not hl_intact:
                fails.append("HL이탈")
            return False, "PULL 미충족:" + (",".join(fails) if fails else "지속대기")

        if dominance_ok:
            if state.dominance_since is None:
                state.dominance_since = p.ts
            duration = (p.ts - state.dominance_since).total_seconds()
        else:
            state.dominance_since = None
            duration = 0.0
        if dominance_ok and price_ok and duration >= buy_confirm:
            return True, (f"매수우위 {state.buy_ratio:.1%}/{state.buy_sell_ratio:.2f}배 "
                          f"{duration:.1f}초·{state.lane}")
        return False, "매수우위 또는 가격반응 미확인"

    def _capital_in_use_krw(self) -> float:
        """현재 보유·매도대기·매수대기 원금. 누적 회전액은 포함하지 않는다."""
        total = 0.0
        held = (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD, Phase.SELL_PENDING)
        for state in self.states.values():
            if state.phase == Phase.BUY_PENDING:
                total += max(0.0, state.buy_reserved_krw)
            elif state.phase in held:
                total += max(0.0, state.entry_price) * max(0, int(state.qty or 0))
        return total

    def _can_open(self, code: str = "") -> Tuple[bool, str]:
        if self.cfg.live and self.cfg.off_flag_path.exists():
            return False, "CAPTAIN2_OFF_FLAG"
        if self.cfg.live and self.cfg.manual_block_path.exists():
            return False, "manual_buy_block"
        if self.cfg.live and self.recovery_blocked:
            return False, "RECOVERY_BLOCK"
        # ★[2026-07-22] 계좌 실보유를 못 믿으면 신규매수 금지 — 슬롯 계산이 과소평가돼
        #   계좌 전체 6종목을 넘길 수 있기 때문(매도 관리는 계속된다).
        if self.cfg.live:
            _held, why_rt = self._account_held_codes()
            if why_rt:
                return False, why_rt
        if self._available_slots() <= 0:
            return False, "ACCOUNT_SLOTS_FULL"
        if code:
            dup = self._duplicate_reason(code)
            if dup:
                return False, dup
            if (self.cfg.max_entries_per_code > 0
                    and self.entry_count_by_code.get(code, 0) >= self.cfg.max_entries_per_code):
                return False, f"종목 최대 {self.cfg.max_entries_per_code}회 진입"
        # ★[2026-07-22] 0 = 무제한(로테이션 무중단). >0일 때만 하루 진입 횟수를 제한한다.
        if self.cfg.max_entries_day > 0 and self.entries_today >= self.cfg.max_entries_day:
            return False, "일 최대 진입수"
        if (self.cfg.max_active_capital_krw > 0
                and self._capital_in_use_krw() >= self.cfg.max_active_capital_krw):
            return False, "회전원금 한도"
        if self.cfg.max_daily_loss_krw > 0 and self.daily_realized_pnl_krw <= -self.cfg.max_daily_loss_krw:
            return False, "일 손실 한도"
        if (self.cfg.max_consecutive_losses > 0
                and self.consecutive_losses >= self.cfg.max_consecutive_losses):
            return False, "연속 손절 한도"
        # ★[2026-07-22] 전역 쿨다운 폐지 → 종목별 쿨다운. 전역이면 한 종목을 사는 순간 같은 루프의
        #   다른 후보가 전부 막혀 빈 슬롯을 못 채웠다. 서로 다른 종목은 즉시 진입 가능해야 하고,
        #   동일 종목 재진입만 이 쿨다운으로 막는다.
        if code and self.cfg.cooldown_sec > 0:
            last = self.last_entry_by_code.get(code, 0.0)
            if last > 0 and (time.time() - last) < self.cfg.cooldown_sec:
                return False, "종목 쿨다운"
        return True, "OK"

    def _confirm_entry(self, p: MarketPoint, state: FlowState, qty: int,
                       avg_price: float, reason: str, shadow: bool = False) -> None:
        """실체결이 확인된 뒤에만 호출 — 여기서만 HOLD로 전환한다."""
        state.phase = Phase.HOLD
        state.entry_ts = state.entry_ts or p.ts
        state.entry_price = avg_price
        state.qty = int(qty)
        state.peak_price = max(avg_price, p.price)
        state.watch_since = None
        # ★[점수 엔진 2026-07-23] 새 보유마다 점수 상태 초기화(피크·SELL READY·상태)
        state.hold_peak_spd5 = 0.0
        state.sell_ready_since = None
        state.score_state = "NORMAL"
        state.buy_filled_qty = int(qty)
        state.buy_avg_fill_price = avg_price
        state.buy_reserved_krw = 0.0
        state.morning_hold_logged = False
        self.entries_today += 1
        self.entry_count_by_code[p.code] = self.entry_count_by_code.get(p.code, 0) + 1
        self.daily_buy_krw += avg_price * int(qty)
        self.last_entry_time = time.time()
        self.last_entry_by_code[p.code] = time.time()   # ★종목별 쿨다운 기준
        # ★[재진입 가드 2026-07-23] 이 진입의 신호강도 기록 — 다음 재진입은 이보다 강해야 허용.
        self.last_entry_signal[p.code] = (
            state.reset_money_add_krw, state.reset_money_per_sec_krw, state.buy_ratio)
        self._event(p, state, "SHADOW_FILL" if shadow else "BUY", reason)
        # ★[2026-07-22] 진입 근거를 한 줄로 전부 남긴다(당일거래대금은 근사값이라 source 명시).
        self.log.info(
            "[%s BUY] code=%s name=%s price=%.0f today_value=%.1f억원(EST_PRICE_X_CUMVOL) "
            "reset_price=%.0f reset_money=%.1f억원 reset_money_per_sec=%.2f억원/초 money_grade=%s "
            "buy_vol=%.0f sell_vol=%.0f buy_ratio=%.1f%% buy_sell_ratio=%.2f "
            "매수대금=%.2f억 매도대금=%.2f억 대금비율=%.1f%% 출처=%s "
            "price_response=%+.2f%% reason=%s",
            "SHADOW" if not self.cfg.live else "LIVE",
            p.code, state.name, p.price, p.today_value_krw / 1e8,
            state.reset_price, state.reset_money_add_krw / 1e8,
            state.reset_money_per_sec_krw / 1e8, state.money_size_grade,
            state.buy_exec_vol, state.sell_exec_vol, state.buy_ratio * 100,
            state.buy_sell_ratio,
            state.buy_exec_money / 1e8, state.sell_exec_money / 1e8,
            state.buy_money_ratio * 100, "정확" if state.side_exact else "틱룰",
            state.price_response_pct, reason)

    def _reentry_ok(self, p: MarketPoint, state: FlowState) -> Tuple[bool, str]:
        """★[재진입 가드 2026-07-23] 같은 종목 재진입은 '돈이 직전보다 강할 때만'.
        판정 = 유입대금 AND 유입속도 둘 다 직전 진입 이상(하나라도 약하면 차단). 첫 진입은 통과.
        ★매수비는 게이트에서 제외(2026-07-23 친구님 지적·리플레이 검증): 오늘 지엔씨 3회전은 유입·속도만으로
        이미 정당 차단되고, 매수비를 넣으면 '유입·속도는 급증했는데 매수비만 2~3%p 낮은 강한 재진입'을
        오차단할 위험만 생긴다(보호력 0·리스크만↑). 돈 중심 원칙대로 유입대금·속도만 본다."""
        if not self.cfg.reentry_guard_on:
            return True, ""
        prev = self.last_entry_signal.get(p.code)
        if not prev:
            return True, ""
        pm, ps, pr = prev
        cm, cs = state.reset_money_add_krw, state.reset_money_per_sec_krw
        need_m = pm * self.cfg.reentry_strength_mult
        need_s = ps * self.cfg.reentry_strength_mult
        need_r = min(1.0, pr + self.cfg.reentry_buy_ratio_add)
        if cm >= need_m and cs >= need_s and state.buy_ratio >= need_r:
            return True, ""
        weak = []
        if cm < need_m: weak.append(f"유입 {cm / 1e8:.1f}<{need_m / 1e8:.1f}억")
        if cs < need_s: weak.append(f"속도 {cs / 1e8:.2f}<{need_s / 1e8:.2f}")
        if state.buy_ratio < need_r: weak.append(f"매수비 {state.buy_ratio:.1%}<{need_r:.1%}")
        return False, "REENTRY_WEAK " + ",".join(weak)

    def _open(self, p: MarketPoint, state: FlowState, reason: str) -> None:
        """★[2026-07-22 체결층 이식] 주문 접수 ≠ 체결.
        SHADOW : 기존대로 가상 체결(이벤트명 SHADOW_FILL) — 공용 슬롯은 건드리지 않는다.
        LIVE   : 공용 슬롯 예약 → 1주 주문 → BUY_PENDING. HOLD 전환은 체결확인 후에만."""
        if state.lane in ("EARLY", "C2_01_OPEN_SURGE"):
            no_execution_data = (
                (p.buy_vol_cum <= 0 and p.sell_vol_cum <= 0)
                or (p.buy_money_cum <= 0 and p.sell_money_cum <= 0)
            )
        else:
            no_execution_data = (
                (state.buy_exec_vol <= 0 and state.sell_exec_vol <= 0)
                or (state.buy_exec_money <= 0 and state.sell_exec_money <= 0)
            )
        if no_execution_data:
            self._event(p, state, "BUY_BLOCKED", "NO_EXECUTION_DATA_0_0")
            return
        projected_buy = self._capital_in_use_krw() + p.price * self.cfg.qty_fixed
        if (self.cfg.max_active_capital_krw > 0
                and projected_buy > self.cfg.max_active_capital_krw):
            self._event(p, state, "BUY_BLOCKED", "회전원금 한도 초과")
            return
        ok, why = self._can_open(p.code)
        if not ok:
            self._event(p, state, "BUY_BLOCKED", why)
            return
        # ★[재진입 가드 2026-07-23] 직전보다 약한 재진입 차단(BUY_READY는 유지 — 신호가 강해지면 재참여)
        rok, rwhy = self._reentry_ok(p, state)
        if not rok:
            self._event(p, state, "BUY_BLOCKED", rwhy)
            return

        if not self.cfg.live:
            status = self.execution.buy(p.code, self.cfg.qty_fixed)
            if status != "SHADOW":
                detail = self.execution.last_error_detail or "-"
                self._event(p, state, "BUY_ERROR", f"{status}: {detail}")
                self.log.warning("BUY_ERROR %s(%s) status=%s detail=%s",
                state.name, p.code, status, detail)
                return
            self._confirm_entry(p, state, self.cfg.qty_fixed, p.price, reason, shadow=True)
            return

        # ── LIVE ──────────────────────────────────────────────────────────────
        today = self._today()
        # ① 공용 슬롯 원자적 예약 — 캡틴1·골짜기가 이미 잡은 종목이면 여기서 실패한다.
        if not shared.acquire(p.code, "CAPTAIN2", today):
            self._event(p, state, "BUY_BLOCKED", "SHARED_SLOT_OR_DUPLICATE")
            return
        state.buy_slot_reserved = True
        state.buy_reserved_krw = p.price * self.cfg.qty_fixed
        # ② 발주 직전 주문번호 스냅샷(이 시점 이후 새로 생기는 번호가 내 주문)
        state.buy_known_onos = self._known_onos(p.code, "매수")
        state.buy_since_hms = datetime.now().strftime("%H:%M:%S")
        state.buy_order_no = ""
        state.buy_filled_qty = 0
        state.buy_avg_fill_price = 0.0
        state.buy_cancel_requested = False
        state.buy_cancel_epoch = 0.0
        state.buy_cancel_check_epoch = 0.0
        state.ono_ambiguous_logged = False
        state.buy_requested_qty = int(self.cfg.qty_fixed)
        state.buy_requested_ts = p.ts
        state.buy_sent_epoch = time.time()

        status = self.execution.buy(p.code, self.cfg.qty_fixed)
        if status in ("OK", "TIMEOUT"):
            # TIMEOUT도 체결 여부 불명이므로 절대 HOLD로 가지 않는다 — BUY_PENDING으로 확인 대기.
            state.phase = Phase.BUY_PENDING
            state.buy_pending_reason = reason
            self._event(p, state, "BUY_PENDING", f"{status} — 실체결 확인 대기")
            self.log.info("BUY_PENDING %s(%s) x%d status=%s — 체결확인 대기",
                          state.name, p.code, state.buy_requested_qty, status)
            return
        # ERROR / REJECTED / BLOCKED → 슬롯 반환, 주문 없었던 것으로
        self._release_slot(p.code, state, f"BUY_{status}")
        state.buy_requested_qty = 0
        state.buy_sent_epoch = 0.0
        detail = self.execution.last_error_detail or "-"
        self._event(p, state, "BUY_ERROR", f"{status}: {detail}")
        self.log.warning("BUY_ERROR %s(%s) status=%s detail=%s",
                         state.name, p.code, status, detail)

    # ── ★[2026-07-22] 매수 체결확인 1스텝 (캡틴1 _pend_buy_step 556행 이식) ──
    def _buy_pending_step(self, p: MarketPoint, state: FlowState) -> None:
        code = p.code
        need = int(state.buy_requested_qty or 0)
        state.last_order_check_ts = p.ts
        ono = self._discover_ono(state, code, "매수")
        fills = fills_by_ono(self.cfg.fills_dir, code, "매수", state.buy_since_hms)
        filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)

        # 취소 진행 중 — 취소 완료 확인 후에만 최종 확정
        if state.buy_cancel_requested:
            if time.time() - state.buy_cancel_check_epoch < 2.0:
                return
            state.buy_cancel_check_epoch = time.time()
            op = self.execution.open_onos(code, buy=True)
            confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
            timed_out = time.time() - state.buy_cancel_epoch >= 10.0
            if not (confirmed or timed_out):
                return
            self.log.info("%s %s(%s) 주문번호=%s",
                          "CANCEL_CONFIRMED" if confirmed else "취소확인 시간초과",
                          state.name, code, ono or "?")
            fills = fills_by_ono(self.cfg.fills_dir, code, "매수", state.buy_since_hms)
            filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
            self.log.info("FINAL_FILL_QTY %s(%s) 주문번호=%s %d/%d주 · FINAL_AVG_PRICE %.0f",
                          state.name, code, ono or "?", filled, need, favg)
            if filled >= 1:
                # 부분체결이라도 '실제 체결분만' 보유로 확정(슬롯은 계속 점유)
                self._confirm_entry(p, state, filled, favg, state.buy_pending_reason)
                self._event(p, state, "BUY_PARTIAL_CONFIRMED" if filled < need else "BUY_CONFIRMED",
                            f"{filled}/{need}주 avg={favg:.0f}")
            else:
                self._release_slot(code, state, "BUY_FILL_ZERO")
                state.phase = Phase.FAILED
                state.terminal_ts = p.ts
                state.rearm_ready = False
                self._event(p, state, "BUY_FILL_ZERO", "취소완료·체결 0 — 유령 방지")
            return

        # 전량 체결 → 즉시 확정(취소 불필요)
        if ono and need > 0 and filled >= need:
            self.log.info("FINAL_FILL_QTY %s(%s) 주문번호=%s %d/%d주 · FINAL_AVG_PRICE %.0f",
                          state.name, code, ono, filled, need, favg)
            self._confirm_entry(p, state, filled, favg, state.buy_pending_reason)
            self._event(p, state, "BUY_CONFIRMED", f"{filled}/{need}주 avg={favg:.0f}")
            return

        # 부분체결 확인 또는 시간초과 → 잔량 취소 요청(확정은 취소완료 후)
        if (ono and 1 <= filled < need) or \
           (time.time() - state.buy_sent_epoch) >= self.cfg.fill_wait_sec:
            op = None
            if not ono:
                op = self.execution.open_onos(code, buy=True)
                news = [o for o in (op or {}) if o not in set(state.buy_known_onos)]
                if len(news) == 1:
                    state.buy_order_no = ono = news[0]
                    self.log.info("ORDER_NO %s 매수 주문번호=%s 확정(미체결조회)", code, ono)
                    filled = fills_by_ono(self.cfg.fills_dir, code, "매수",
                                          state.buy_since_hms).get(ono, (0, 0.0))[0]
            if ono:
                rem = (op or {}).get(ono) or max(1, need - filled)
                self.execution.cancel_order(code, ono, rem, buy=True)
                state.buy_cancel_requested = True
                state.buy_cancel_epoch = time.time()
                state.buy_cancel_check_epoch = 0.0
            else:
                # 주문번호를 못 찾았다 = 접수 자체가 안 됐을 가능성. 종목단위 전량취소는 하지 않는다
                # (타 엔진 주문 교차취소 위험). 체결 0으로 판정하고 슬롯만 반환한다.
                self.log.warning("주문번호 미확정 %s(%s) — 교차취소 금지·체결0 판정", state.name, code)
                self._release_slot(code, state, "BUY_ONO_UNRESOLVED")
                state.phase = Phase.FAILED
                state.terminal_ts = p.ts
                state.rearm_ready = False
                self._event(p, state, "BUY_ONO_UNRESOLVED", "주문번호 미확정 — 체결0 판정")

    def _c2_01_signal_step(self, points: Mapping[str, MarketPoint]) -> None:
        """Consume at most one fresh C2-01 signal and pass it to the existing order path."""
        if self.c2_01_order_attempts >= max(0, self.cfg.c2_01_max_order_attempts):
            return
        try:
            payload = stable_json_read(self.cfg.c2_01_signal_path)
        except Exception:
            return
        rows = select_fresh_signals(
            payload,
            now=datetime.now(),
            max_age_sec=self.cfg.c2_01_signal_max_age_sec,
            consumed=self.c2_01_consumed_signals,
        )
        for row in rows:
            code = str(row["code"])
            point = points.get(code)
            if point is None:
                continue
            current = self.states.get(code)
            if current and current.phase in (
                    Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                    Phase.BUY_PENDING, Phase.SELL_PENDING):
                self.c2_01_consumed_signals.add(str(row["signal_id"]))
                continue

            state = FlowState(code=code, name=self.feed.names.get(code, code))
            state.phase = Phase.BUY_READY
            state.lane = "C2_01_OPEN_SURGE"
            state.reset_id = f"C2_01_{uuid.uuid4().hex[:8]}"
            state.reset_ts = point.ts
            state.reset_price = point.price
            state.reset_buy_cum = max(0.0, point.buy_vol_cum)
            state.reset_sell_cum = max(0.0, point.sell_vol_cum)
            state.reset_buy_money = max(0.0, point.buy_money_cum)
            state.reset_sell_money = max(0.0, point.sell_money_cum)
            state.reset_cum_vol = max(0.0, point.cum_vol)
            state.reset_high = point.price
            state.reset_low = point.price
            state.structure_low = point.price
            state.buy_ratio = safe_float(row.get("buy_ratio"), 0.5)
            state.buy_money_ratio = state.buy_ratio
            state.reset_money_per_sec_krw = safe_float(row.get("money_speed_5s"))
            state.reset_money_add_krw = state.reset_money_per_sec_krw * 5.0
            state.money_size_grade = "C2_01"
            state.side_exact = True
            state.obs_buy_signal_reason = str(row.get("reason") or "")
            self.states[code] = state
            self.c2_01_consumed_signals.add(str(row["signal_id"]))
            self.c2_01_order_attempts += 1
            order_reason = (
                f"{C2_01_STRATEGY_NAME} | {row.get('reason') or 'BUY_READY'} "
                f"| signal={row['signal_id']}"
            )
            self._event(point, state, "C2_01_SIGNAL", order_reason)
            self._open(point, state, order_reason)
            if state.phase not in (Phase.HOLD, Phase.BUY_PENDING):
                state.phase = Phase.FAILED
                state.terminal_ts = point.ts
                state.rearm_ready = False
                self._event(point, state, "C2_01_ATTEMPT_CLOSED", "하루 1회 주문시도 종료")
            return

    def _c2_01_bars_payload(self) -> Dict[str, Any]:
        try:
            mtime_ns = self.cfg.base_bars_path.stat().st_mtime_ns
            if mtime_ns != self._c2_01_bars_mtime_ns:
                self._c2_01_bars = stable_json_read(self.cfg.base_bars_path)
                self._c2_01_bars_mtime_ns = mtime_ns
        except Exception:
            pass
        return self._c2_01_bars

    def _c2_01_common_exit(
            self, p: MarketPoint, state: FlowState) -> Tuple[Optional[str], str]:
        """Evaluate the prebuilt common hold/sell engine without changing its rules."""
        try:
            point_row = {
                "ts": p.ts.isoformat(timespec="seconds"),
                "cur": p.price,
                "buy_vol_cum": p.buy_vol_cum,
                "sell_vol_cum": p.sell_vol_cum,
                "buy_money_cum": p.buy_money_cum,
                "sell_money_cum": p.sell_money_cum,
            }
            board_row = {
                "money_speed_5s": p.money_speed_5s,
                "money_speed_10s": p.money_speed_10s,
                "money_speed_30s": p.money_speed_30s,
            }
            observation, quality = build_observation(
                p.code,
                point_row,
                board_row,
                self._c2_01_bars_payload(),
                self._c2_01_common_windows,
            )
            entry_at = state.entry_ts or p.ts
            if entry_at.tzinfo is None:
                entry_at = entry_at.replace(tzinfo=observation.observed_at.tzinfo)
            else:
                entry_at = entry_at.astimezone(observation.observed_at.tzinfo)
            if state.common_exit_state:
                common_state = HoldSellState.from_dict(state.common_exit_state)
            else:
                common_state = HoldSellState(
                    position_id=f"c2-01:{p.code}:{entry_at.strftime('%Y%m%d%H%M%S')}",
                    strategy_id=StrategyId.C2_01_OPEN_SURGE,
                    code=p.code,
                    quantity=int(state.qty),
                    entry_price=state.entry_price,
                    entry_at=entry_at,
                )
            if (common_state.last_observed_at
                    and observation.observed_at < common_state.last_observed_at):
                return None, "OUT_OF_ORDER_SKIPPED"
            decision = self._c2_01_common_engine.evaluate(common_state, observation)
            state.common_exit_state = common_state.to_dict()
            self._c2_01_exit_error = ""
            return (decision.reason if decision.should_sell else None), quality
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if message != self._c2_01_exit_error:
                self._c2_01_exit_error = message
                self.log.warning("C2_01 common exit adapter error: %s", message)
            return None, f"ERROR:{message}"

    def _hold_or_sell(self, p: MarketPoint, state: FlowState) -> None:
        self._vi_track(p, state)      # ★[VI 거부 대응 2026-07-23] 보유 전 구간 VI 감지
        if state.lane == "C2_01_OPEN_SURGE":
            reason, quality = self._c2_01_common_exit(p, state)
            if reason:
                self._event(p, state, "C2_01_COMMON_EXIT", f"{quality} | {reason}")
                self._close(p, state, reason)
            elif quality.startswith("ERROR:"):
                # 공통 관측 어댑터 장애 때도 공통 프로필과 같은 -2%·15:10 안전선은 유지한다.
                ret_pct = (
                    (p.price / state.entry_price - 1.0) * 100
                    if state.entry_price > 0 else 0.0
                )
                if ret_pct <= -2.0:
                    self._close(p, state, f"HARD_STOP_C2_01_FALLBACK {ret_pct:.2f}%")
                elif p.ts.strftime("%H%M") >= self.cfg.force_exit:
                    self._close(p, state, "TIME_EXIT_C2_01_FALLBACK")
            return
        # ★[2026-07-22] RECOVERY_HOLD = RESET 맥락 복원 실패분.
        # ★[2026-07-22 재정박수술] 원본은 여기가 막다른 길이었다 — 맥락을 영영 못 되살려
        #   HARD_STOP(-3%)·TIME_EXIT(15:25)까지 슬롯을 잠근 채 방치됐다(첫날 3종목이 2시간 고착).
        #   수술: 위험청산 검사를 먼저 통과하면, 현재 시점을 새 RESET 기준선으로 '재정박'하고
        #   HOLD로 복귀시켜 전략매도 추적을 재개한다(RESET 상대측정이라는 엔진 철학 그대로,
        #   기준점만 지금으로). entry_price가 없으면 손절 계산이 불가능하므로 재정박하지 않는다.
        if state.phase == Phase.RECOVERY_HOLD:
            if p.price > state.peak_price:
                state.peak_price = p.price
            ret_pct = (p.price / state.entry_price - 1.0) * 100 if state.entry_price > 0 else 0.0
            hard_stop_pct = self.cfg.hard_stop_bottom_pct
            if state.lane == "PULL":
                hard_stop_pct = (self.cfg.hard_stop_pull_buy_pct
                                 if state.flow_ratio_recent > 0.5
                                 else self.cfg.hard_stop_pull_pct)
            if ret_pct <= hard_stop_pct:
                self._close(p, state, f"HARD_STOP {ret_pct:.2f}% (RECOVERY_HOLD)")
            elif (state.lane == "EARLY"
                  and p.ts.strftime("%H%M") >= self.cfg.early_force_exit_hm):
                self._close(p, state, "EARLY_TIME_EXIT_0930 (RECOVERY_HOLD)")
            elif p.ts.strftime("%H%M") >= self.cfg.force_exit:
                self._close(p, state, "TIME_EXIT (RECOVERY_HOLD)")
            elif state.entry_price > 0:
                buy_cum, sell_cum = self.agg.cum_now(p.code)   # ★실체결 누계(역산 아님)
                buy_money, sell_money = self.agg.money_now(p.code)
                state.reset_id = f"REANCHOR_{uuid.uuid4().hex[:8]}"
                state.reset_ts = p.ts
                state.reset_price = p.price
                state.reset_buy_cum = buy_cum
                state.reset_sell_cum = sell_cum
                state.reset_buy_money = buy_money
                state.reset_sell_money = sell_money
                state.reset_cum_vol = p.cum_vol
                state.reset_che_str = p.che_str
                state.reset_high = p.price
                state.reset_low = p.price
                state.structure_low = p.price
                state.recent_prices.clear()
                state.watch_since = None
                state.sell_cond_since = None
                state.phase = Phase.HOLD
                self._event(p, state, "RECOVERY_REANCHOR", "RESET 기준선 재정박 — 전략매도 재개")
                self.log.info("RECOVERY_REANCHOR %s(%s) — 기준선 재정박, HOLD 복귀", state.name, p.code)
            return

        previous_structure_low = state.structure_low
        self._update_reset_metrics(p, state)
        if p.price > state.peak_price:
            state.peak_price = p.price

        if self.cfg.struct_shadow_on:          # ★[구조판정 SHADOW] 로그전용 — 실매도 로직 무변경
            self._sh_step(p, state)

        ret_pct = (p.price / state.entry_price - 1.0) * 100 if state.entry_price > 0 else 0.0
        hm = p.ts.strftime("%H%M")
        hard_stop_pct = self.cfg.hard_stop_bottom_pct
        if state.lane == "PULL":
            hard_stop_pct = (self.cfg.hard_stop_pull_buy_pct
                             if state.flow_ratio_recent > 0.5
                             else self.cfg.hard_stop_pull_pct)
        if ret_pct <= hard_stop_pct:
            self._close(p, state, f"HARD_STOP {ret_pct:.2f}%")
            return
        if state.lane == "EARLY" and hm >= self.cfg.early_force_exit_hm:
            self._close(p, state, "EARLY_TIME_EXIT_0930")
            return
        if hm >= self.cfg.force_exit:
            self._close(p, state, "TIME_EXIT")
            return
        if (state.lane == "EARLY"
                and self.cfg.early_decision_hm <= hm < self.cfg.early_force_exit_hm):
            vw = self._vwap_of(p)
            ma3_permit, _m5, _m10, _m20 = self.ma3_rider.status(p.code)
            score, score_parts = self._sell_score(p, state)
            trend_ok, trend_why = self._early_trend_contract(
                p.price, vw, ma3_permit, state.flow_ratio_recent,
                p.money_speed_10s, p.money_speed_30s, previous_structure_low, score,
                self.cfg.early_trend_min_buy_ratio,
                self.cfg.early_trend_speed_frac,
                self.cfg.score_sell_ready)
            if not trend_ok:
                self._close(p, state,
                            f"EARLY_TREND_EXIT {trend_why} score={score:.0f}[{score_parts}]")
                return
            if not state.morning_hold_logged:
                self._event(p, state, "MORNING_TREND_HOLD",
                            f"VWAP={vw:.0f} flow={state.flow_ratio_recent:.1%} "
                            f"speed10/30={p.money_speed_10s:.0f}/{p.money_speed_30s:.0f} score={score:.0f}")
                state.morning_hold_logged = True
        # ★[3분봉 상승보유 2026-07-24] RAID·PULL·BASE에 적용. 하드컷·15:10 강제청산은
        #   위에서 이미 검사했으므로 절대 유예하지 않는다. RAID 동작은 종전 그대로이며,
        #   PULL/BASE는 기존 매도장악 3조건이 15초 연속이면 MA20 위에서도 매도한다.
        rider_structure_broken = previous_structure_low > 0 and p.price < previous_structure_low
        ma3_permit, ma3_m5, ma3_m10, ma3_m20 = self.ma3_rider.status(p.code)
        state.ma3_rider_permit = bool(state.lane in ("RAID", "PULL", "BASE") and ma3_permit)
        state.ma3_ma5 = ma3_m5
        state.ma3_ma10 = ma3_m10
        state.ma3_ma20 = ma3_m20
        if state.ma3_rider_permit:
            trend_sell_override = bool(
                state.lane in ("PULL", "BASE")
                and state.flow_ratio_recent <= self.cfg.sell_buy_ratio
                and rider_structure_broken
                and not state.money_accel
            )
            if trend_sell_override:
                if state.sell_cond_since is None:
                    state.sell_cond_since = p.ts
                    self._event(
                        p, state, f"{state.lane}_MA3_SELL_WATCH",
                        f"최근{self.cfg.flow_window_sec:.0f}초 매수비"
                        f"{state.flow_ratio_recent:.1%}+구조붕괴")
                override_age = (p.ts - state.sell_cond_since).total_seconds()
                if override_age >= self.cfg.sell_confirm_sec:
                    self._close(
                        p, state,
                        f"{state.lane}_MA3_SELL_OVERRIDE 최근{self.cfg.flow_window_sec:.0f}초"
                        f"비율={state.flow_ratio_recent:.1%} 구조붕괴 지속={override_age:.0f}초")
                    return
            else:
                state.sell_cond_since = None
            # 허가 중 쌓인 다른 매도 타이머가 해제 직후 즉시 매도시키지 않도록 새로 확인한다.
            state.phase = Phase.HOLD
            state.watch_since = None
            state.dryup_since = None
            state.sell_ready_since = None
            state.vwap_warn_since = None
            if not state.ma3_hold_logged:
                self._event(p, state, "MA3_RIDER_HOLD",
                            f"3m MA5={ma3_m5:.0f} MA10={ma3_m10:.0f} MA20={ma3_m20:.0f}")
            state.ma3_hold_logged = True
            return
        if state.ma3_hold_logged:
            self._event(p, state, "MA3_RIDER_RELEASE",
                        f"현재={p.price:.0f} MA20={ma3_m20:.0f} — 일반 매도판정 재개")
        state.ma3_hold_logged = False

        # ★[보완3종→설계8단계 2026-07-22] ㉮이익 보호 = 단계식 트레일(친구님 명시값).
        #   도달한 최고 수익 구간의 되돌림 폭 적용 — 수익이 클수록 폭을 넓혀 큰 상승을 끝까지 탄다.
        if state.entry_price > 0 and state.peak_price > 0 and self._trail_steps:
            peak_ret = (state.peak_price / state.entry_price - 1.0) * 100
            drop_th = 0.0
            for arm_, drop_ in self._trail_steps:          # 오름차순 — 마지막으로 도달한 구간이 이긴다
                if peak_ret >= arm_:
                    drop_th = drop_
            if drop_th > 0:
                drop = (state.peak_price - p.price) / state.peak_price * 100
                if drop >= drop_th:
                    # ★[VWAP 3종 2026-07-23] 트레일 돈 가드 — 최근 10초 실제 매수대금비율 ≥ 90%
                    #   이고 속도가 유지(약화 아님)면 유예. 7/23 지엔씨 실측: 직전 10초 매수 8.31억
                    #   (매수비 97%) 폭주 중 1% 되돌림 매도 → 반납 2.21%p + 10분 뒤 재매수 왕복.
                    #   돈이 약해지거나 매도우위로 바뀌는 순간 유예 자동 해제(매 루프 재평가) —
                    #   drop 조건이 남아 있으면 그 루프에 트레일이 정상 발동한다.
                    guard = False
                    if self.cfg.trail_money_guard_on:
                        r10 = self.agg.roll(p.code, 10.0, p.ts.timestamp())
                        if r10 is not None and r10[4] > 0:
                            b10m = max(0.0, r10[2])
                            s10m = max(0.0, r10[3])
                            m10 = b10m + s10m
                            speed_ok = not (
                                state.roll30_money_ps > 0
                                and state.roll10_money_ps
                                < self.cfg.persist_min_frac * state.roll30_money_ps)
                            if (m10 > 0 and b10m / m10 >= self.cfg.trail_guard_buy_ratio
                                    and speed_ok):
                                guard = True
                                self._event(p, state, "TRAIL_HOLD_MONEY",
                                            f"매수비{b10m / m10:.0%} 속도유지 — 트레일 유예"
                                            f"(고점{peak_ret:+.1f}% 되돌림{drop:.1f}%)")
                    if not guard:
                        self._close(p, state,
                                    f"PROFIT_TRAIL 고점{peak_ret:+.1f}%→되돌림{drop:.1f}%(폭{drop_th:.1f})")
                        return
        # ★[보완3종 2026-07-22] ㉯돈 마름 — 유입속도가 보유 중 피크의 dryup_frac 아래로
        #   dryup_confirm_sec 연속 붕괴하면 돈이 빠진 것. 조기 노이즈 방지: 보유 최소시간·피크 하한.
        # ★[매수우위 판정 2026-07-23 친구님 확정] 거래량(총대금) 감소 자체는 매도 신호가 아니다 —
        #   매수·매도가 같이 마르며 매수가 여전히 우위면(공급 부족, Case A) 계속 보유한다.
        #   ★동률(매수=매도)·무거래·측정불가도 매도 아님(친구님 정정: "똑같다고 매도하면 안 돼") —
        #   DRYUP은 '매도 우위'라는 명확한 증거가 있을 때만 발동하고, 나머지 상황의 매도 판단은
        #   기존 매도규칙(흐름매도 48%·SCORE·트레일·하드손절)의 몫이다. Case C 활황은 애초 저거래 아님.
        if state.roll30_money_ps > state.hold_peak_money_ps:
            state.hold_peak_money_ps = state.roll30_money_ps
        hold_age = (p.ts - state.entry_ts).total_seconds() if state.entry_ts else 0.0
        if (hold_age >= self.cfg.dryup_min_hold_sec
                and state.hold_peak_money_ps >= self.cfg.dryup_min_peak_mps
                and state.roll30_money_ps < self.cfg.dryup_frac * state.hold_peak_money_ps
                and not state.money_accel):     # ★가속 중엔 마름 판정 보류(들어오는 중)
            rd = self.agg.roll(p.code, 30.0, p.ts.timestamp())
            dry_b = max(0.0, rd[2]) / rd[4] if rd and rd[4] > 0 else 0.0
            dry_s = max(0.0, rd[3]) / rd[4] if rd and rd[4] > 0 else 0.0
            if not (rd is not None and rd[4] > 0 and dry_s > dry_b):
                state.dryup_since = None        # 매수우위·동률·무거래·측정불가 = DRYUP 침묵
            else:
                if state.dryup_since is None:
                    state.dryup_since = p.ts
                if (p.ts - state.dryup_since).total_seconds() >= self.cfg.dryup_confirm_sec:
                    self._close(p, state,
                                f"MONEY_DRYUP 우위붕괴 매수 {dry_b / 1e4:.0f}만/초"
                                f" vs 매도 {dry_s / 1e4:.0f}만/초"
                                f"(피크 {state.hold_peak_money_ps / 1e4:.0f}만/초→"
                                f"현재 {state.roll30_money_ps / 1e4:.0f}만/초)")
                    return
        else:
            state.dryup_since = None

        # ★[점수 엔진 2026-07-23 친구님 확정] NORMAL→WATCH(25)→WARNING(50)→SELL READY(75)
        #   →[최근5초 매수대금 증가? YES=유예(최대 10초) / NO=SELL]→강제SELL. 가격은 점수에 없다.
        #   하드손절·강제청산은 위에서 이미 우선 처리(최후 보험). ON이면 아래 VWAP 조기경보(부분집합) 대체.
        if self.cfg.score_sell_on:
            score, parts = self._sell_score(p, state)
            new_st = ("SELL_READY" if score >= self.cfg.score_sell_ready
                      else "WARNING" if score >= self.cfg.score_warning
                      else "WATCH" if score >= self.cfg.score_watch else "NORMAL")
            if new_st != state.score_state:
                state.score_state = new_st
                self._event(p, state, f"SCORE_{new_st}", f"{score:.0f}점 [{parts}]")
            if new_st == "SELL_READY":
                if state.sell_ready_since is None:
                    state.sell_ready_since = p.ts
                # 마지막 기회: 최근 5초 매수대금 > 직전 5초 매수대금이면 유예
                money_up = False
                now_ep = p.ts.timestamp()
                r5 = self.agg.roll(p.code, 5.0, now_ep)
                r10 = self.agg.roll(p.code, 10.0, now_ep)
                if r5 is not None and r10 is not None:
                    money_up = max(0.0, r5[2]) > max(0.0, r10[2] - r5[2])
                hold_age = (p.ts - state.entry_ts).total_seconds() if state.entry_ts else 0.0
                min_hold = (self.cfg.score_min_hold_sec if state.lane == "PULL"
                            else self.cfg.score_bottom_min_hold_sec)
                # ★[2026-07-24 유예수술 친구님 "문제 수정"] 유예 상한을 '돈이 끊긴 시간'으로 재정의.
                #   ㉮돈이 계속 들어오는 동안은 유예 시계 리셋 — 유예초과 강제매도로 살아있는 종목을
                #     뱉지 않는다(7/24 로보티즈: 7틱 연속 유입 중 매도 → 직후 상승 실측).
                #   ㉯유입 끊김은 실제 5초 연속 확인 후에만 매도. 하드손절·트레일·강제청산은 상위 우선.
                if state.ma_permit:
                    state.sell_ready_since = None
                    self._event(p, state, "SCORE_HOLD_MA", "MA permit active")
                elif hold_age < min_hold:
                    state.sell_ready_since = None
                    self._event(p, state, "SCORE_HOLD_MIN",
                                f"minimum hold {hold_age:.0f}/{min_hold:.0f}s")
                elif money_up:
                    state.sell_ready_since = None
                    self._event(p, state, "SCORE_HOLD_MONEY",
                                "5초 매수대금 증가 — 유예 시계 리셋")
                else:
                    ready_age = (p.ts - state.sell_ready_since).total_seconds()
                    if ready_age >= self.cfg.score_dry_confirm_sec:
                        self._close(p, state, f"SCORE_SELL {score:.0f}점 [{parts}]")
                        return
                    self._event(p, state, "SCORE_HOLD_MONEY",
                                f"유입 끊김 {ready_age:.1f}/{self.cfg.score_dry_confirm_sec:.1f}초")
            else:
                state.sell_ready_since = None
        # ★[VWAP 3종 2026-07-23] 보유 중 VWAP 이탈 = 즉시매도 아님 → 조기경보 상태.
        #   경보 중 '매도대금 우위(sell_buy_ratio 48% 재사용) + 돈 속도 약화(persist_min_frac 재사용)
        #   + 가속 아님'이 함께 확인될 때만 매도 — VWAP 하나만으로 팔지 않는다(친구님 원칙).
        #   7/23 제주 실측: 매수 4분 뒤 돈마름+VWAP 이탈인데 -3%까지 18분 태움(-1.1%로 끊을 수 있었음).
        #   VWAP 위 회복 시 경보 즉시 해제. 하드손절(-3%)·강제청산은 위에서 이미 우선 처리됨(무변경).
        #   ★점수 엔진(score_sell_on)이 켜져 있으면 이 블록은 건너뛴다(점수 엔진이 상위 호환).
        elif self.cfg.vwap_warn_exit_on:
            vw = self._vwap_of(p)
            if vw > 0 and p.price < vw:
                if state.vwap_warn_since is None:
                    state.vwap_warn_since = p.ts
                    self._event(p, state, "VWAP_WARN",
                                f"VWAP{vw:.0f} 이탈 — 조기경보(매도는 3중 확인 시)")
                sell_dom_now = state.flow_ratio_recent <= self.cfg.sell_buy_ratio
                speed_weak = (state.roll30_money_ps > 0
                              and state.roll10_money_ps
                              < self.cfg.persist_min_frac * state.roll30_money_ps)
                if sell_dom_now and speed_weak and not state.money_accel:
                    self._close(p, state,
                                f"VWAP_WARN_EXIT VWAP{vw:.0f} 이탈+매도우위"
                                f"{state.flow_ratio_recent:.0%}+속도약화")
                    return
            elif state.vwap_warn_since is not None:
                state.vwap_warn_since = None
                self._event(p, state, "VWAP_WARN_CLEAR", "VWAP 위 회복 — 경보 해제")

        structure_broken = previous_structure_low > 0 and p.price < previous_structure_low
        # ★[2026-07-22 관찰전용] 재생 로그용 보존(판정에 영향 없음)
        state.obs_prev_structure_low = previous_structure_low
        state.obs_structure_broken = bool(structure_broken)
        # ★[ROLL-LIVE 2026-07-22] 흐름 약화/매도우위 판정은 '최근 구간' 비율로 — 누적은 분모가
        #   계속 자라 50%로 평균회귀하므로(48% 하회가 시간문제 = 회전기계) 매도 판정에 쓰지 않는다.
        flow_weak = state.flow_ratio_recent < self.cfg.watch_buy_ratio
        sell_dominant = state.flow_ratio_recent <= self.cfg.sell_buy_ratio

        if state.phase == Phase.HOLD:
            if flow_weak:
                state.phase = Phase.WATCH
                state.watch_since = p.ts
                state.sell_cond_since = None
                self._event(p, state, "WATCH_START",
                            f"최근{self.cfg.flow_window_sec:.0f}초비율={state.flow_ratio_recent:.1%}")
            return

        if state.phase == Phase.WATCH:
            if not flow_weak:
                state.phase = Phase.HOLD
                state.watch_since = None
                state.sell_cond_since = None
                self._event(p, state, "HOLD_RECOVERED")
                return
            watch_age = (p.ts - (state.watch_since or p.ts)).total_seconds()
            # ★[2026-07-22 매도수술] 순간 교차 1번으로 팔지 않는다 — 매도조건(매도우위+구조붕괴)이
            #   sell_confirm_sec 동안 '연속' 유지돼야 매도. 조건이 1초라도 끊기면 타이머 리셋.
            #   (구조붕괴=새 5초저가 갱신이므로, 지속 요구 = 가격이 계속 저점을 깎아내리는 진짜 붕괴만 통과)
            # ★[설계8단계] 가속 중엔 흐름매도 보류("계속 증가하면 안 판다") — 타이머도 무효.
            if sell_dominant and structure_broken and not state.money_accel:
                if state.sell_cond_since is None:
                    state.sell_cond_since = p.ts
                cond_age = (p.ts - state.sell_cond_since).total_seconds()
                # ★[설계8단계] ⑤이평 허가증(돈 살아있음 전제) — 지속확인 시간을 늘려 "조금 더" 끈다.
                need_sec = self.cfg.sell_confirm_sec * (
                    self.cfg.ma_permit_confirm_mult if state.ma_permit else 1.0)
                if watch_age >= self.cfg.watch_confirm_sec and cond_age >= need_sec:
                    self._close(p, state,
                                f"FLOW_WEAK+STRUCTURE_BREAK 최근{self.cfg.flow_window_sec:.0f}초"
                                f"비율={state.flow_ratio_recent:.1%} 지속={cond_age:.0f}초"
                                + ("(이평허가연장)" if state.ma_permit else ""))
            else:
                state.sell_cond_since = None

    def _confirm_exit(self, p: MarketPoint, state: FlowState, avg_price: float,
                      reason: str, shadow: bool = False) -> None:
        """실제 매도 체결이 확인된 뒤에만 호출 — 여기서만 CLOSED 전환 + 공용 슬롯 해제."""
        exit_qty = int(state.qty or 0)
        realized = (avg_price - state.entry_price) * exit_qty if state.entry_price > 0 else 0.0
        self.daily_realized_pnl_krw += realized
        self.consecutive_losses = self.consecutive_losses + 1 if realized < 0 else 0
        state.phase = Phase.CLOSED
        state.exit_ts = p.ts
        state.exit_price = avg_price
        state.exit_reason = reason
        state.terminal_ts = p.ts
        state.rearm_ready = False
        state.qty = 0
        state.sell_avg_fill_price = avg_price
        self._release_slot(p.code, state, "SELL_FILLED")   # ★접수가 아니라 체결 후에만 해제
        self._event(p, state, "SHADOW_SELL_FILL" if shadow else "SELL", reason)
        ret = (avg_price / state.entry_price - 1.0) * 100 if state.entry_price > 0 else 0.0
        self.log.info("SELL %s %s @%.0f | %s | %.2f%% | 실현=%+.0f원 일누적=%+.0f원 연속손실=%d",
                      state.name, p.code, avg_price, reason, ret, realized,
                      self.daily_realized_pnl_krw, self.consecutive_losses)

    def _vi_track(self, p: MarketPoint, state: FlowState) -> None:
        """★[VI 거부 대응 2026-07-23] VI(변동성완화장치) 발동/해제를 누적거래량으로 감지.
        발동 = 누적량이 직전의 50% 미만으로 급감(키움이 예상체결 데이터로 전환 — 7/23 지엔씨 실측:
        542,105→2,614). 해제 = 정상 누적량 이상으로 복귀. VI 중엔 prev를 갱신하지 않는다."""
        if p.cum_vol <= 0:
            return
        prev = state.vi_prev_cum_vol
        if not state.vi_suspect:
            if prev > 0 and p.cum_vol < prev * 0.5:
                state.vi_suspect = True
                state.vi_normal_cum_vol = prev
                state.vi_release_epoch = 0.0
                state.vi_hold_logged = False
                self._event(p, state, "VI_SUSPECT",
                            f"누적량 급감 {prev:,.0f}→{p.cum_vol:,.0f} — 매도 발사 보류")
                self.log.warning("VI_SUSPECT %s(%s) 누적량 %s→%s — 단일가 의심·매도 보류",
                                 state.name, p.code, f"{prev:,.0f}", f"{p.cum_vol:,.0f}")
            else:
                state.vi_prev_cum_vol = p.cum_vol
        else:
            if state.vi_normal_cum_vol > 0 and p.cum_vol >= state.vi_normal_cum_vol:
                state.vi_suspect = False
                state.vi_release_epoch = time.time()
                state.vi_prev_cum_vol = p.cum_vol
                self._event(p, state, "VI_RELEASE",
                            f"누적량 복귀 {p.cum_vol:,.0f} — {self.cfg.vi_reorder_wait_sec:.1f}초 후 재주문 허용")
                self.log.info("VI_RELEASE %s(%s) — %.1f초 대기 후 재주문",
                              state.name, p.code, self.cfg.vi_reorder_wait_sec)

    def _close(self, p: MarketPoint, state: FlowState, reason: str) -> None:
        """★[2026-07-22 체결층 이식] 매도 접수만으로 CLOSED 금지.
        SHADOW는 기존대로 즉시 확정, LIVE는 SELL_PENDING으로 두고 체결확인을 기다린다."""
        if state.phase == Phase.SELL_PENDING:
            return          # 이미 매도 주문 진행 중 — 중복 발사 금지

        if self.cfg.struct_shadow_on:          # ★[구조판정 SHADOW] 같은 시각 구조판정 기록 — 실매도 무변경
            self._sh_on_close(p, state, reason)

        if not self.cfg.live:
            status = self.execution.sell(p.code, state.qty)
            if status != "SHADOW":
                self._event(p, state, "SELL_ERROR", status)
                return
            self._confirm_exit(p, state, p.price, reason, shadow=True)
            return

        # ── LIVE ──
        qty = int(state.qty or 0)
        if qty <= 0:
            self._event(p, state, "SELL_SKIP", "보유수량 0")
            return
        # ★[VI 거부 대응 2026-07-23] ①VI 중 발사 보류(최유리 주문은 거부만 됨 — 7/23 11발 실측)
        #   ②해제 후 vi_reorder_wait_sec 대기 ③재시도 상한(3회) — HARD_STOP·TIME_EXIT는 예외(최후 보험).
        is_last_resort = reason.startswith("HARD_STOP") or reason.startswith("TIME_EXIT")
        if state.vi_suspect:
            if not state.vi_hold_logged:
                state.vi_hold_logged = True
                self._event(p, state, "SELL_VI_HOLD", f"VI 의심 — 발사 보류 ({reason})")
                self.log.info("SELL_VI_HOLD %s(%s) — VI 해제까지 매도 보류 (%s)",
                              state.name, p.code, reason)
            return
        if state.vi_release_epoch > 0 and \
                time.time() - state.vi_release_epoch < self.cfg.vi_reorder_wait_sec:
            return                                   # 해제 직후 안정 대기(1~2초)
        if state.sell_retry_count >= self.cfg.max_sell_retry and not is_last_resort:
            if not state.sell_exhaust_logged:
                state.sell_exhaust_logged = True
                self._event(p, state, "SELL_RETRY_EXHAUSTED",
                            f"재시도 {state.sell_retry_count}회 소진 — 일반매도 종료"
                            f"(하드손절·강제청산만 통과)")
                self.log.warning("SELL_RETRY_EXHAUSTED %s(%s) %d회 — 로그 기록 후 일반매도 종료",
                                 state.name, p.code, state.sell_retry_count)
            return
        state.sell_known_onos = self._known_onos(p.code, "매도")
        state.sell_since_hms = datetime.now().strftime("%H:%M:%S")
        state.sell_order_no = ""
        state.sell_filled_qty = 0
        state.sell_avg_fill_price = 0.0
        state.sell_cancel_requested = False
        state.sell_cancel_epoch = 0.0
        state.sell_cancel_check_epoch = 0.0
        state.sell_requested_qty = qty
        state.sell_requested_ts = p.ts
        state.sell_sent_epoch = time.time()

        status = self.execution.sell(p.code, qty)
        if status in ("OK", "TIMEOUT"):
            state.phase = Phase.SELL_PENDING     # TIMEOUT도 SELL_PENDING 유지
            state.sell_pending_reason = reason
            self._event(p, state, "SELL_PENDING", f"{status} — 실체결 확인 대기")
            self.log.info("SELL_PENDING %s(%s) x%d status=%s", state.name, p.code, qty, status)
            return
        # 매도 실패는 포지션 유지 — 슬롯도 유지하고 다음 루프에 재시도(캡틴1과 동일 계약)
        state.sell_requested_qty = 0
        state.sell_sent_epoch = 0.0
        state.sell_retry_count += 1
        detail = self.execution.last_error_detail or "-"
        self._event(p, state, "SELL_ERROR",
                    f"{status}: {detail} 재시도{state.sell_retry_count}")
        self.log.warning("매도 실패 %s(%s) %s → 포지션 유지·재시도 %d/%d",
                         state.name, p.code, status, state.sell_retry_count, self.cfg.max_sell_retry)

    # ── ★[2026-07-22] 매도 체결확인 1스텝 (캡틴1 _pend_sell_step 643행 이식) ──
    def _sell_pending_step(self, p: MarketPoint, state: FlowState) -> None:
        self._vi_track(p, state)      # ★[VI 거부 대응 2026-07-23] 주문 진행 중에도 VI 추적
        code = p.code
        need = int(state.sell_requested_qty or 0)
        state.last_order_check_ts = p.ts
        ono = self._discover_ono(state, code, "매도")
        fills = fills_by_ono(self.cfg.fills_dir, code, "매도", state.sell_since_hms)
        filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)

        if state.sell_cancel_requested:
            if time.time() - state.sell_cancel_check_epoch < 2.0:
                return
            state.sell_cancel_check_epoch = time.time()
            op = self.execution.open_onos(code, buy=False)
            confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
            timed_out = time.time() - state.sell_cancel_epoch >= 10.0
            if not (confirmed or timed_out):
                return
            self.log.info("%s %s(%s) 주문번호=%s",
                          "CANCEL_CONFIRMED" if confirmed else "취소확인 시간초과",
                          state.name, code, ono or "?")
            fills = fills_by_ono(self.cfg.fills_dir, code, "매도", state.sell_since_hms)
            filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
            self.log.info("FINAL_FILL_QTY %s(%s) 주문번호=%s %d/%d주 · FINAL_AVG_PRICE %.0f",
                          state.name, code, ono or "?", filled, need, favg)
            if need > 0 and filled >= need:
                self._confirm_exit(p, state, favg, state.sell_pending_reason)
            elif filled >= 1:
                # 부분체결 — 잔량만 남기고 HOLD로 복귀. 슬롯 해제 금지, CLOSED 금지.
                state.qty = max(0, need - filled)
                state.sell_filled_qty = filled
                state.phase = Phase.HOLD
                state.sell_retry_count += 1
                self._event(p, state, "SELL_PARTIAL",
                            f"{filled}/{need}주 → 잔량 {state.qty}주 재매도 예정")
                self.log.warning("매도 부분체결 %s %d/%d주 → 잔량 %d주",
                                 state.name, filled, need, state.qty)
            else:
                state.phase = Phase.HOLD           # 체결 0 → 보유 유지·재매도
                state.sell_retry_count += 1
                self._event(p, state, "SELL_FILL_ZERO", "취소완료·체결0 — 보유 유지(유령 매도 방지)")
            if state.sell_retry_count >= self.cfg.max_sell_retry and state.phase == Phase.HOLD:
                self.log.warning("매도 재시도 상한 도달 %s(%s) %d회 — 이후 위험청산 조건에서만 재시도",
                                 state.name, code, state.sell_retry_count)
            return

        if ono and need > 0 and filled >= need:
            self.log.info("FINAL_FILL_QTY %s(%s) 주문번호=%s %d/%d주 · FINAL_AVG_PRICE %.0f",
                          state.name, code, ono, filled, need, favg)
            self._confirm_exit(p, state, favg, state.sell_pending_reason)
            return

        if (ono and 1 <= filled < need) or \
           (time.time() - state.sell_sent_epoch) >= self.cfg.fill_wait_sec:
            op = None
            if not ono:
                op = self.execution.open_onos(code, buy=False)
                news = [o for o in (op or {}) if o not in set(state.sell_known_onos)]
                if len(news) == 1:
                    state.sell_order_no = ono = news[0]
                    self.log.info("ORDER_NO %s 매도 주문번호=%s 확정(미체결조회)", code, ono)
                    filled = fills_by_ono(self.cfg.fills_dir, code, "매도",
                                          state.sell_since_hms).get(ono, (0, 0.0))[0]
            if ono:
                rem = (op or {}).get(ono) or max(1, need - filled)
                self.execution.cancel_order(code, ono, rem, buy=False)
                state.sell_cancel_requested = True
                state.sell_cancel_epoch = time.time()
                state.sell_cancel_check_epoch = 0.0
            else:
                # 주문번호 미확정 — 교차취소 금지. 보유 유지하고 다음 루프에 재매도.
                # ★[VI 거부 대응 2026-07-23] VI 의심 중 미확정 = 거부 추정(거부는 fills·미체결
                #   어디에도 안 남는다 — 7/23 실측). _close의 VI 게이트가 다음 발사를 보류한다.
                state.phase = Phase.HOLD
                state.sell_retry_count += 1
                tag = " (VI 의심 — 거부 추정·해제 후 재주문)" if state.vi_suspect else ""
                self.log.warning("매도 주문번호 미확정 %s(%s) — 교차취소 금지·보유 유지%s",
                                 state.name, code, tag)
                self._event(p, state, "SELL_ONO_UNRESOLVED", f"주문번호 미확정 — 보유 유지{tag}")

    # ── ★[VWAP 3종 2026-07-23] ──────────────────────────────────────────────
    def _vwap_of(self, p: MarketPoint) -> float:
        """당일 VWAP 근사 = (FID15 매수+매도대금 누계) ÷ 누적거래량.
        0 반환 = 산출 불가(FID15 부재) 또는 글리치(누적량 리셋 — 7/23 지엔씨 실측: cum_vol
        503,608→2,614 리셋로 VWAP 855만원 오염). 현재가의 0.5~2배 밖이면 무효 처리."""
        if p.buy_money_cum < 0 or p.sell_money_cum < 0 or p.cum_vol <= 0:
            return 0.0
        v = (p.buy_money_cum + p.sell_money_cum) / p.cum_vol
        if not (p.price * 0.5 <= v <= p.price * 2.0):
            return 0.0
        return v

    def _sell_score(self, p: MarketPoint, state: FlowState) -> Tuple[float, str]:
        """★[점수 엔진 2026-07-23] 돈 중심 매도 점수(0~100) — 가격 손익은 점수에 없다.
        ⓐVWAP 이탈 +25 ⓑ5초속도 보유피크 50%↓ +25(20%↓ +40) ⓒ최근30초 매수<매도 +25(매수비 35%↓ +35)
        ⓓ가속 중(money_accel) 총점 ×0.5. 75+는 3계열 동시일 때만 도달(단일 신호=노이즈 — 7/23 실측).
        피크가 score_peak_min_mps 미만이면 ⓑ 판정 안 함(먼지 노이즈 방지 — 돈마름과 동일 사상)."""
        score = 0.0
        parts = []
        vw = self._vwap_of(p)
        if vw > 0 and p.price < vw:
            score += 25; parts.append("VWAP↓")
        if p.money_speed_5s > state.hold_peak_spd5:
            state.hold_peak_spd5 = p.money_speed_5s
        pk = state.hold_peak_spd5
        if pk >= self.cfg.score_peak_min_mps:
            if p.money_speed_5s < 0.2 * pk:
                score += 40; parts.append("속도20%↓")
            elif p.money_speed_5s < 0.5 * pk:
                score += 25; parts.append("속도50%↓")
        r30 = self.agg.roll(p.code, 30.0, p.ts.timestamp())
        if r30 is not None and r30[4] > 0:
            b30m = max(0.0, r30[2]); s30m = max(0.0, r30[3])
            t30 = b30m + s30m
            if t30 > 0:
                br = b30m / t30
                if br < 0.35:
                    score += 35; parts.append("역전35%↓")
                elif br < 0.5:
                    score += 25; parts.append("역전")
        if state.money_accel:
            score *= 0.5; parts.append("가속감산")
        return score, "+".join(parts) if parts else "무신호"

    @staticmethod
    def _early_trend_contract(price: float, vwap: float, ma3_permit: bool,
                              flow_ratio: float, speed10: float, speed30: float,
                              previous_structure_low: float, sell_score: float,
                              min_flow_ratio: float = 0.52,
                              speed_frac: float = 0.5,
                              sell_ready_score: float = 75.0) -> Tuple[bool, str]:
        """09:20 연장계약. 하나라도 불충족이면 아침 포지션을 정리한다."""
        failed = []
        if not (vwap > 0 and price > vwap):
            failed.append("VWAP")
        if not ma3_permit:
            failed.append("MA3")
        if flow_ratio < min_flow_ratio:
            failed.append("FLOW")
        if not (speed30 > 0 and speed10 >= speed_frac * speed30):
            failed.append("SPEED")
        if previous_structure_low > 0 and price < previous_structure_low:
            failed.append("STRUCTURE")
        if sell_score >= sell_ready_score:
            failed.append("SELL_SCORE")
        return (not failed, "OK" if not failed else ",".join(failed))

    # ── ★[EARLY 초입레인 2026-07-23 친구님 확정] ─────────────────────────────
    def _day_open_of(self, p: MarketPoint) -> float:
        """당일 시가. 우선순위: ①엔진이 09:00~09:01에 처음 본 가격(=당일 첫 1초 가격)
        ②재시작 폴백=돈맥_1분봉 op. 둘 다 없으면 0(그 종목 EARLY 금지 — fail-closed).
        전일종가·현재가로 대체하지 않는다(친구님 확정)."""
        op = self.day_open.get(p.code, 0.0)
        if op > 0:
            return op
        t = p.ts.time()
        if t.hour == 9 and t.minute == 0:
            self.day_open[p.code] = p.price
            return p.price
        if self._m1_open is None:
            self._m1_open = {}
            try:
                with self.cfg.early_m1_path.open(encoding="utf-8") as fh:
                    m = json.load(fh).get("m") or {}
                for c, v in m.items():
                    o = float((v or {}).get("op") or 0)
                    if o > 0:
                        self._m1_open[str(c).zfill(6)] = o
                self.log.info("EARLY 시가 폴백 로드 — 1분봉 op %d종목", len(self._m1_open))
            except Exception:
                self.log.exception("EARLY 시가 폴백 로드 실패 — 첫 관측가만 사용")
        op = self._m1_open.get(p.code, 0.0)
        if op > 0:
            self.day_open[p.code] = op
        return op

    @staticmethod
    def _early_entry_variant(op: float, prev_close: float, below_open_seen: bool,
                             dip_ready: bool, chased_before: bool,
                             gap_min_pct: float = 3.0) -> str:
        """09시 초입 3경로. 빈 문자열은 진입 경로 없음."""
        if op <= 0 or prev_close <= 0:
            return ""
        if below_open_seen:
            return "DIP_RECLAIM" if dip_ready else ""
        if chased_before:
            return ""
        if op <= prev_close:
            return "DIRECT_ONSET"
        gap_pct = (op / prev_close - 1.0) * 100.0
        return "GAP_ONSET" if gap_pct >= gap_min_pct else ""

    def _early_check(self, p: MarketPoint) -> Optional[Tuple[MarketPoint, EarlyState]]:
        """장전 압축목록 + DIRECT/GAP/DIP 3경로 + 기존 FID15 돈 조건을 모두 통과해야 발화."""
        es = self.early.setdefault(p.code, EarlyState())
        if es.fired:
            return None
        prev_close = self._early_prev_close(p.code)
        if prev_close <= 0:
            return None                              # 오늘 압축목록·전일종가가 없으면 fail-closed
        if p.buy_money_cum < 0 or p.sell_money_cum < 0:
            return None                              # FID15 부재 — 판정 불가(fail-closed)
        entry_ok, _entry_reason = self._entry_filter(p, require_today_value=False)
        if not entry_ok:
            return None
        sec = p.ts.timestamp()
        if es.bm0 < 0:
            es.bm0, es.sm0 = p.buy_money_cum, p.sell_money_cum
            es.bm0_ts = sec
        base_bm, base_sm = es.bm0, es.sm0
        base_ts = es.bm0_ts or sec
        for (t2, b2, s2, _px2) in es.hist:
            if sec - t2 >= 10.0:
                base_bm, base_sm = b2, s2
                base_ts = t2
            else:
                break
        db = p.buy_money_cum - base_bm
        ds = p.sell_money_cum - base_sm
        tot = db + ds
        op = self._day_open_of(p)
        if op <= 0:
            return None
        max_px = op * (1.0 + self.cfg.early_max_above_open_pct / 100.0)
        chased_before = bool(self.cfg.early_max_above_open_pct > 0 and es.high_px > max_px)
        es.high_px = max(es.high_px, p.price)
        if p.price < op:
            es.below_open_seen = True
            if es.dip_low <= 0 or p.price < es.dip_low:
                es.dip_low = p.price
                es.dip_low_ts = sec
                es.dip_low_speed = p.money_speed_5s
        open_elapsed = sec - p.ts.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
        burst = p.money_speed_5s / max(p.money_speed_30s, 1.0)
        vw = self._vwap_of(p) if self.cfg.vwap_gate_on else 0.0
        dip_ready = bool(
            es.below_open_seen and es.dip_low > 0
            and (sec - es.dip_low_ts) >= self.cfg.early_dip_no_new_sec
            and p.price >= op and vw > 0 and p.price > vw
            and p.money_speed_5s > es.dip_low_speed
        )
        variant = self._early_entry_variant(
            op, prev_close, es.below_open_seen, dip_ready,
            chased_before, self.cfg.early_gap_min_pct)
        vwap_ok = (vw > 0 and p.price > vw) if variant == "DIP_RECLAIM" else (vw <= 0 or p.price > vw)
        ok = bool(
            variant
            and p.money_speed_5s >= self.cfg.early_min_speed
            and (open_elapsed < self.cfg.early_burst_waive_sec or burst >= self.cfg.early_min_burst)
            and tot > 0 and db / tot >= self.cfg.early_min_buy_ratio
            and p.price >= op
            and (self.cfg.early_max_above_open_pct <= 0 or p.price <= max_px)
            and vwap_ok
        )
        fired = None
        if (ok and es.streak > 0 and es.streak_kind == variant
                and (sec - es.last_sec) <= 2.5 and p.price >= es.arm_px):
            es.streak += 1
            es.last_sec = sec
        elif ok:
            ref = None
            for (t2, _b2, _s2, px2) in reversed(es.hist):
                if sec - t2 >= self.cfg.early_persist_sec:
                    ref = px2
                    break
            if ref is not None and p.price > ref:
                es.streak, es.last_sec, es.arm_px = 1, sec, p.price
                es.streak_kind = variant
            else:
                es.streak = 0
                es.streak_kind = ""
        else:
            es.streak = 0
            es.streak_kind = ""
        if es.streak >= self.cfg.early_persist_sec:
            es.fired = True
            es.entry_kind = variant
            net_buy_money_per_sec = (db - ds) / max(sec - base_ts, 1.0)
            es.sort_key = (
                1.0 if p.theme_leader else 0.0,
                net_buy_money_per_sec, db / tot, p.money_speed_5s, burst)
            fired = (p, es)
        es.hist.append((sec, p.buy_money_cum, p.sell_money_cum, p.price))
        return fired

    def _early_select_and_open(self, fired: list) -> None:
        """Rank by theme group, net-buy inflow, buy dominance, speed, then burst.
        RESET 맥락을 현재 시점으로 합성 주입 — 기존 매도로직(트레일·돈마름·하드손절)이 그대로 관리한다.
        슬롯·쿨다운·manual_buy_block·shared_slots 검사는 _open→_can_open 계약 그대로."""
        fired.sort(key=lambda t: t[1].sort_key, reverse=True)
        available = self._available_slots()
        opened = 0
        for p, es in fired:
            if opened >= available:
                break
            state = self.states.setdefault(
                p.code, FlowState(code=p.code, name=self.feed.names.get(p.code, p.code)))
            if state.phase not in (Phase.IDLE, Phase.LOW_SEARCH):
                continue                             # 이미 에피소드 진행/보유 중 — RAID·PULL 불간섭
            buy_cum, sell_cum = self.agg.cum_now(p.code)
            buy_money, sell_money = self.agg.money_now(p.code)
            state.lane = "EARLY"
            state.phase = Phase.RESET
            state.reset_id = uuid.uuid4().hex[:12]
            state.reset_ts = p.ts
            state.reset_price = es.arm_px or p.price
            state.reset_buy_cum = buy_cum
            state.reset_sell_cum = sell_cum
            state.reset_buy_money = buy_money
            state.reset_sell_money = sell_money
            state.reset_cum_vol = p.cum_vol
            state.reset_che_str = p.che_str
            state.reset_ask_tot = p.ask_tot
            state.reset_bid_tot = p.bid_tot
            state.reset_imb = p.imb
            state.reset_high = max(state.reset_price, p.price)
            state.reset_low = min(state.reset_price, p.price)
            state.structure_low = state.reset_low
            state.dominance_since = None
            state.watch_since = None
            state.recent_prices.clear()
            self._update_reset_metrics(p, state)
            early_reason = f"EARLY_{es.entry_kind or 'ONSET'}"
            self._event(p, state, early_reason,
                        f"theme={p.theme_signal or '-'} "
                        f"net={es.sort_key[1] / 1e4:,.0f}man/s buy_ratio={es.sort_key[2]:.2f} "
                        f"speed={es.sort_key[3] / 1e4:,.0f}man/s burst={es.sort_key[4]:.1f} streak={es.streak}s")
            self._open(p, state, early_reason)
            if state.phase in (Phase.HOLD, Phase.BUY_PENDING):
                opened += 1
            elif state.phase == Phase.RESET:
                state.phase = Phase.FAILED           # 주문 실패 — 에피소드 종료(찌꺼기 RESET 방지)

    @staticmethod
    def _net_buy_money_per_sec(p: MarketPoint, state: FlowState) -> float:
        if state.reset_ts is None:
            return 0.0
        elapsed = max((p.ts - state.reset_ts).total_seconds(), 1.0)
        return (state.buy_exec_money - state.sell_exec_money) / elapsed

    def _select_and_open(self, candidates: list) -> None:
        """★[2026-07-22] BUY_READY 대기 풀 — 매 루프 전체 재정렬 후 '남은 슬롯 수'만큼 상위부터 진입.

        원본은 종목 순회 도중 첫 BUY_READY를 곧바로 _open 해서, 선택이 사실상 dict 순서에 좌우됐다.

        핵심 규칙(친구님 지시):
          · 1등이 아닌 후보를 FAILED 처리하지 않는다 — phase를 BUY_READY로 유지해 대기 풀에 남긴다.
          · 순위를 한 번 정해 고정하지 않는다 — 매 루프 현재값으로 전부 다시 정렬한다.
          · 다음 루프에 슬롯이 비면 남아있는 후보 중 '그 시점' 1등부터 진입한다.

        대기 후보가 풀에서 빠지는 경우는 호출측(_process)이 이미 처리한다:
          진입창(buy_max_elapsed_sec) 초과 → FAILED / 매수우위 이탈·RESET 저점 재이탈 → _buy_signal
          False라 이번 루프 후보에서 제외(진입창 안이면 BUY_READY 유지하고 회복 시 재참여) /
          시장필터 미달 → 아래에서 제외.

        정렬(전부 내림차순) — ★[보완3종 2026-07-22 친구님 승인으로 갱신]:
          ① buy_ratio 5%p 버킷(매수 우위 우선 — 스펙 유지) ② RESET 이후 유입대금 속도(원/초)
          ③ buy_sell_ratio ④ 구간 총체결량 ⑤ price_response_pct
        갱신 근거: 7/22 실측에서 후보 매수비율이 87~100%에 몰려 변별력 0(승자 예측 실패) —
        스펙 문언("대금 규모·유입속도는 신뢰도와 보조순위에 사용")대로 버킷 안 순위는 돈의 속도가 가른다.
        """
        # 시장 필터 미달 후보는 주문 대상에서 제외(잡주 매수 금지)
        pool = []
        for p, st, reason in candidates:
            ok, why = self._entry_filter(p)
            if not ok:
                self._event(p, st, "BUY_READY_NOT_SELECTED", f"MARKET_FILTER {why}")
                continue
            # ★[VWAP 3종 2026-07-23] 진입 관문 — VWAP 아래 신규매수 금지(기존 진입조건에 '추가').
            #   BUY_READY는 유지 → VWAP 위로 회복하면 다음 루프에 현재값으로 재경쟁한다.
            vw = self._vwap_of(p)
            if self.cfg.vwap_gate_on and vw > 0 and p.price <= vw:
                self._event(p, st, "BUY_READY_NOT_SELECTED",
                            f"VWAP_GATE {p.price:.0f}<=VWAP{vw:.0f}")
                continue
            pool.append((p, st, reason))
        if not pool:
            return

        pool.sort(key=lambda item: (
            1 if item[0].theme_leader else 0,          # same top group: all canonical theme leaders
            self._net_buy_money_per_sec(item[0], item[1]),  # fresh net-buy money first
            round(item[1].buy_ratio * 20) / 20,          # 매수우위 5%p 버킷(스펙: 우위 우선)
            # ★[수급 가점 2026-07-23 친구님 승인·7/24 D-1 차선 추가] 같은 우위 버킷 안에서
            #   D-2 매집(2점) > D-1만 매집(1점) > 없음(0점). 관문 아님(차단 0·순서만) —
            #   버킷(우위)은 넘지 못한다. OFF·로드실패 시 0으로 무효.
            2 if (self.cfg.supply_boost_on
                  and str(item[0].code).zfill(6) in self._supply_badge)
            else 1 if (self.cfg.supply_boost_on
                       and str(item[0].code).zfill(6) in self._supply_badge_d1)
            else 0,
            item[1].reset_money_per_sec_krw,             # ★버킷 안에서는 돈의 속도가 가른다
            item[1].buy_sell_ratio,
            item[1].buy_exec_vol + item[1].sell_exec_vol,
            item[1].price_response_pct,
        ), reverse=True)

        # ★[2026-07-22] 빈 슬롯 수만큼 상위부터 진입.
        #   ★수정: 자체 states만 세던 옛 계산을 버리고 _available_slots()를 쓴다.
        #     LIVE는 계좌 전체(shared_slots ∪ rt_open_positions) 기준이라 캡틴1·골짜기 보유까지 포함된다.
        open_count = self._used_codes_count()
        available_slots = self._available_slots()

        win_p, win_state, _ = pool[0]
        if len(pool) > 1:
            self.log.info("BUY_READY 대기풀 %d종목 재정렬 → 빈슬롯 %d개(보유 %d/%d) · 현재 1등 %s(%s) "
                          "buy_ratio=%.1f%% (참고 %.0f원/초)",
                          len(pool), available_slots, open_count, self.cfg.max_positions,
                          win_state.name, win_p.code, win_state.buy_ratio * 100,
                          win_state.reset_money_per_sec_krw)

        opened = 0
        for p, st, _reason in pool:
            if opened >= available_slots:
                # 슬롯 소진 — 주문하지 않고 BUY_READY 유지(다음 루프에 현재값으로 재경쟁)
                self._event(p, st, "BUY_READY_NOT_SELECTED",
                            f"SLOT_FULL 보유{open_count + opened}/{self.cfg.max_positions} "
                            f"WINNER={win_p.code} "
                            f"my_buy_ratio={st.buy_ratio:.4f} "
                            f"winner_buy_ratio={win_state.buy_ratio:.4f} "
                            f"my_money_per_sec={st.reset_money_per_sec_krw:.0f}")
                continue
            # 슬롯·일일한도·쿨다운·매수차단 검사는 _open() 내부의 _can_open 계약 그대로 사용
            #   (실패 시 _open이 BUY_BLOCKED 이벤트를 남기고 phase는 BUY_READY로 남는다)
            self._open(p, st, "MARKET_STRONGEST")
            # 슬롯 소비 판정 — SHADOW는 즉시 HOLD, LIVE는 주문 접수(BUY_PENDING)로 이미 슬롯을 잡았다.
            #   주문 실패(BUY_ERROR/BLOCKED)면 phase가 BUY_READY로 남아 여기 안 걸리고,
            #   다음 순위 후보가 그 슬롯을 쓴다.
            if st.phase in (Phase.HOLD, Phase.BUY_PENDING):
                opened += 1

    def _process(self, p: MarketPoint) -> Optional[Tuple[MarketPoint, FlowState, str]]:
        """BUY_READY가 확정되면 주문하지 않고 후보 튜플을 반환한다(주문 판단은 _select_and_open)."""
        state = self.states.setdefault(p.code, FlowState(code=p.code, name=self.feed.names.get(p.code, p.code)))
        state.last_update_ts = p.ts

        # ★[2026-07-22 체결층] 주문 진행 중인 종목은 체결확인만 한다(신규 판단·중복주문 금지).
        if state.phase == Phase.BUY_PENDING:
            self._buy_pending_step(p, state)
            return None
        if state.phase == Phase.SELL_PENDING:
            self._sell_pending_step(p, state)
            return None

        if state.phase in (Phase.CLOSED, Phase.FAILED):
            # 같은 MONEY_START 파동의 반복 진입 방지: 신호가 한 번 완전히 꺼진 뒤에만 재무장한다.
            surge_now = self._is_surge(p)
            if not surge_now:
                state.rearm_ready = True
                return
            terminal = state.terminal_ts or state.exit_ts or state.last_update_ts
            cooled = terminal is None or (p.ts - terminal).total_seconds() >= self.cfg.cooldown_sec
            if cooled and state.rearm_ready:
                old = state
                state = FlowState(code=p.code, name=self.feed.names.get(p.code, p.code))
                # ★[눌림레인 2026-07-22] 직전 에피소드의 고점·종료시각 승계 — 그 고점 대비 -0.8%
                #   아래서 시작하는 새 탐색 = 눌림 반등(PULL 레인) 판정 재료
                # ★[눌림레인 점검1 수정] episode_high 포함 — 저점탐색 실패(매수 전 눌림 시작)
                #   에피소드도 고점을 남겨 다음 사이클이 PULL로 전환될 수 있게 한다.
                state.prev_episode_high = max(old.reset_high, old.peak_price, old.episode_high)
                state.prev_episode_end_ts = old.terminal_ts or old.exit_ts
                self.states[p.code] = state
                self._start_low_search(p, state)
            return
        if state.phase == Phase.IDLE:
            # ★[2026-07-22/24] 공통 진입 필터 — 가격·거래대금·역배열을 FLOW 전에 차단.
            market_ok, _market_reason = self._entry_filter(p)
            if not market_ok:
                return None
            if self._is_surge(p):
                self._start_low_search(p, state)
            return
        if state.phase == Phase.LOW_SEARCH:
            self._update_low_search(p, state)
            return
        if state.phase in (Phase.RESET, Phase.BUY_READY):
            # ★[BASE 계단하락 방어] 리테스트 뒤 확정 저점보다 더 낮은 가격이 나오면
            #   오래된 RESET에서 절대 사지 않고 BASE 저점탐색으로 되돌린다.
            #   최초 flow_detect_ts는 유지해 전체 90초 상한을 넘기지 않는다.
            if state.lane == "BASE" and state.reset_price > 0 and p.price < state.reset_price:
                buy_cum, sell_cum = self.agg.cum_now(p.code)
                buy_money, sell_money = self.agg.money_now(p.code)
                state.phase = Phase.LOW_SEARCH
                state.candidate_low = CandidateLow(
                    ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
                    ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
                    buy_cum=buy_cum, sell_cum=sell_cum,
                    buy_money=buy_money, sell_money=sell_money)
                state.last_low_update_ts = p.ts
                state.dominance_since = None
                state.recent_prices.clear()
                self._event(p, state, "BASE_LOW_RESTART",
                            f"확정저점 {state.reset_price:.0f} 이탈 → 더 낮은 실제저점 재탐색")
                return
            self._update_reset_metrics(p, state)
            signal_ok, reason = self._buy_signal(p, state)
            previous_reason = state.obs_buy_signal_reason
            state.obs_buy_signal_reason = reason
            if state.lane == "PULL" and not signal_ok and reason != previous_reason:
                self._event(p, state, "PULL_GATE_BLOCKED", reason)
            if signal_ok:
                state.phase = Phase.BUY_READY
                self._event(p, state, "BUY_READY", reason)
                # ★[2026-07-22] 즉시 주문하지 않고 후보로 반환 — 같은 루프의 다른 BUY_READY와
                #   경쟁시킨 뒤 1등만 주문한다(_select_and_open).
                return (p, state, reason)
            elif state.reset_ts and (p.ts - state.reset_ts).total_seconds() > self._lane_windows(state)[2]:
                state.phase = Phase.FAILED
                state.terminal_ts = p.ts
                state.rearm_ready = False
                self._event(p, state, "RESET_FAILED", "진입 확인창 내 매수우위 미확인")
            return
        if state.phase in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD):
            self._hold_or_sell(p, state)

    # ══ ★[2026-07-22 관찰전용] 초단위 재생 로그 ═══════════════════════════════════
    #   CAPTAIN2가 추적 중인 종목만 기록한다(전체시장 캡처 아님 — money_flow_1s_capture와 무관).
    #   판정에 절대 쓰지 않는다. 기록 실패는 삼키고 엔진은 계속 돈다.
    REPLAY_STATES = (Phase.LOW_SEARCH, Phase.RESET, Phase.BUY_READY, Phase.BUY_PENDING,
                     Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD, Phase.SELL_PENDING)

    REPLAY_COLUMNS = [
        "ts", "code", "name", "phase",
        "current_price", "cum_vol", "che_str", "ask_tot", "bid_tot", "imb",
        "money_start", "money_start_raw",
        "money_add_5s", "money_speed_5s", "money_speed_10s", "money_speed_30s",
        "flow_detect_ts", "reset_id", "reset_ts", "reset_price", "reset_cum_vol",
        "reset_che_str", "reset_buy_cum", "reset_sell_cum",
        "raw_buy_delta", "raw_sell_delta", "clipped_buy_delta", "clipped_sell_delta",
        "delta_cum_vol", "delta_sum", "conservation_error", "conservation_error_pct",
        "buy_ratio", "buy_sell_ratio", "dominance_since", "watch_since",
        "structure_low", "previous_structure_low", "structure_broken",
        "structure_diff", "structure_diff_ticks", "structure_diff_pct",
        "price_response_pct", "reset_money_add_krw", "reset_money_per_sec_krw",
        "entry_ts", "entry_price", "qty", "peak_price", "exit_reason",
        "anomaly_count", "live_mode",
        # ★[REAL-SIDE 2026-07-22] 방향별 실거래대금·출처
        "buy_exec_money", "sell_exec_money", "buy_money_ratio", "side_exact",
        # ★[ROLL-LIVE 2026-07-22] 매도판정용 최근구간 비율 + 윈도우 튜닝용 관찰 3종
        "flow_ratio_recent", "flow_span_recent",
        "roll10_ratio", "roll30_ratio", "roll60_ratio",
        "roll10_money_ps", "roll30_money_ps", "roll60_money_ps",
        # ★[설계8단계 2026-07-22] 가속·이평허가·평상시배율 + ★[눌림레인] 레인
        "money_accel", "ma_permit", "money_mult_dayavg", "lane", "buy_signal_reason",
    ]

    @staticmethod
    def _dt_txt(v: Optional[datetime]) -> str:
        return v.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if isinstance(v, datetime) else ""

    def _replay_row(self, p: MarketPoint, state: FlowState) -> None:
        """이번 루프의 종목 1행을 버퍼에 넣는다(_process 이후 1회 호출 = 종목당 정확히 1행)."""
        if not self.cfg.replay_enabled or state.phase not in self.REPLAY_STATES:
            return
        try:
            raw_b, raw_s = state.obs_raw_buy_delta, state.obs_raw_sell_delta
            cb, cs = max(0.0, raw_b), max(0.0, raw_s)
            dcv = state.obs_delta_cum_vol
            dsum = cb + cs
            cons_err = dsum - dcv
            cons_pct = cons_err / max(dcv, 1.0) * 100.0
            prev_sl = state.obs_prev_structure_low
            s_diff = (p.price - prev_sl) if prev_sl > 0 else 0.0
            tick = krx_tick_size(p.price) or 1.0
            self._replay_buf.append({
                "ts": self._dt_txt(p.ts), "code": p.code, "name": state.name,
                "phase": state.phase.value,
                "current_price": p.price, "cum_vol": p.cum_vol, "che_str": p.che_str,
                "ask_tot": p.ask_tot, "bid_tot": p.bid_tot, "imb": p.imb,
                "money_start": int(p.money_start), "money_start_raw": int(p.money_start_raw),
                "money_add_5s": p.money_add_5s, "money_speed_5s": p.money_speed_5s,
                "money_speed_10s": p.money_speed_10s, "money_speed_30s": p.money_speed_30s,
                "flow_detect_ts": self._dt_txt(state.flow_detect_ts),
                "reset_id": state.reset_id, "reset_ts": self._dt_txt(state.reset_ts),
                "reset_price": state.reset_price, "reset_cum_vol": state.reset_cum_vol,
                "reset_che_str": state.reset_che_str,
                "reset_buy_cum": round(state.reset_buy_cum, 3),
                "reset_sell_cum": round(state.reset_sell_cum, 3),
                "raw_buy_delta": round(raw_b, 3), "raw_sell_delta": round(raw_s, 3),
                "clipped_buy_delta": round(cb, 3), "clipped_sell_delta": round(cs, 3),
                "delta_cum_vol": round(dcv, 3), "delta_sum": round(dsum, 3),
                "conservation_error": round(cons_err, 3),
                "conservation_error_pct": round(cons_pct, 3),
                "buy_ratio": round(state.buy_ratio, 6),
                "buy_sell_ratio": round(state.buy_sell_ratio, 6),
                "dominance_since": self._dt_txt(state.dominance_since),
                "watch_since": self._dt_txt(state.watch_since),
                "structure_low": state.structure_low, "previous_structure_low": prev_sl,
                "structure_broken": int(state.obs_structure_broken),
                "structure_diff": round(s_diff, 3),
                "structure_diff_ticks": round(s_diff / tick, 3),
                "structure_diff_pct": round((s_diff / prev_sl * 100.0) if prev_sl > 0 else 0.0, 4),
                "price_response_pct": round(state.price_response_pct, 4),
                "reset_money_add_krw": round(state.reset_money_add_krw),
                "reset_money_per_sec_krw": round(state.reset_money_per_sec_krw),
                "entry_ts": self._dt_txt(state.entry_ts), "entry_price": state.entry_price,
                "qty": state.qty, "peak_price": state.peak_price,
                "exit_reason": state.exit_reason,
                "anomaly_count": state.anomaly_count,
                "live_mode": int(self.cfg.live),
                "buy_exec_money": round(state.buy_exec_money),
                "sell_exec_money": round(state.sell_exec_money),
                "buy_money_ratio": round(state.buy_money_ratio, 6),
                "side_exact": 1 if state.side_exact else 0,
                "flow_ratio_recent": round(state.flow_ratio_recent, 6),
                "flow_span_recent": round(state.flow_span_recent, 1),
                "roll10_ratio": round(state.roll10_ratio, 6),
                "roll30_ratio": round(state.roll30_ratio, 6),
                "roll60_ratio": round(state.roll60_ratio, 6),
                "roll10_money_ps": round(state.roll10_money_ps),
                "roll30_money_ps": round(state.roll30_money_ps),
                "roll60_money_ps": round(state.roll60_money_ps),
                "money_accel": 1 if state.money_accel else 0,
                "ma_permit": 1 if state.ma_permit else 0,
                "money_mult_dayavg": round(state.money_mult_dayavg, 2),
                "lane": state.lane,
                "buy_signal_reason": state.obs_buy_signal_reason,
            })
        except Exception:
            self.log.exception("재생로그 행 생성 실패 %s", p.code)

    def _replay_flush(self, force: bool = False) -> None:
        buf = self._replay_buf
        if not buf:
            return
        if not force and len(buf) < self.cfg.replay_flush_rows \
                and (time.time() - self._replay_last_flush) < self.cfg.replay_flush_sec:
            return
        path = self.cfg.replay_dir / f"captain2_1s_{datetime.now():%Y%m%d}.csv"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            if not new:      # 헤더 불일치 방어 — 컬럼이 바뀌면 기존 파일을 .oldN으로 보존
                with path.open("r", encoding="utf-8-sig", newline="") as fh:
                    first = (fh.readline() or "").strip()
                if first and [c.strip() for c in first.split(",")] != self.REPLAY_COLUMNS:
                    for i in range(1, 100):
                        alt = path.with_suffix(f".old{i}.csv")
                        if not alt.exists():
                            os.replace(path, alt)
                            self.log.warning("재생로그 컬럼 변경 → 기존 파일 보존: %s", alt.name)
                            break
                    new = True
            with path.open("a", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=self.REPLAY_COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerows(buf)
            self._replay_rows_written += len(buf)
            buf.clear()
            self._replay_last_flush = time.time()
        except Exception:
            self.log.exception("재생로그 flush 실패 — 버퍼 유지, 엔진은 계속")
            if len(buf) > 20000:      # 디스크가 계속 막히면 메모리 보호(가장 오래된 것부터 버림)
                del buf[:10000]
                self.log.warning("재생로그 버퍼 과다 — 오래된 10,000행 폐기")

    def _touch_lock(self) -> None:
        """★[2026-07-22 보강] 단일 인스턴스 락 mtime 갱신 — 이 엔진은 장중 몇 시간 연속 실행이라
        기동 시 1회만 쓰면 200초 뒤 락이 만료돼 중복 기동을 못 막는다(money_flow_board는 1분짜리
        단발이라 갱신이 필요없었음). 매 루프 갱신 = 살아있는 동안만 락 유효."""
        path = os.environ.get("CAPTAIN2_LOCK", r"C:\stock_bot\data\captain2.lock")
        try:
            Path(path).write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    def _save_state(self) -> None:
        # ★[2026-07-22 실체결 수술] calc_ver=2 = 틱룰 실체결 기준선. 구버전(역산) 상태와 구분해
        #   재시작 복구 시 서로 다른 원점의 숫자가 섞이는 것을 막는다.
        active = (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                  Phase.BUY_PENDING, Phase.SELL_PENDING)
        tick_agg: Dict[str, Any] = {}
        for code, s in self.states.items():
            if s.phase in active:
                snap = self.agg.snapshot(code)
                if snap is not None:
                    tick_agg[code] = snap
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "live": self.cfg.live,
            "calc_ver": 2,
            "entries_today": self.entries_today,
            "daily_buy_krw": self.daily_buy_krw,
            "daily_realized_pnl_krw": self.daily_realized_pnl_krw,
            "consecutive_losses": self.consecutive_losses,
            "entry_count_by_code": self.entry_count_by_code,
            "last_entry_signal": self.last_entry_signal,
            "c2_01_consumed_signals": sorted(self.c2_01_consumed_signals),
            "c2_01_order_attempts": self.c2_01_order_attempts,
            "tick_agg": tick_agg,
            "ma3_rider": self.ma3_rider.snapshot(),
            "states": {code: state_json(s) for code, s in self.states.items()},
        }
        # ★[2026-07-24 저장충돌] 중계가 1분마다 state를 읽는 순간 os.replace가 WinError5로
        #   실패(7/23 18회 실측·전부 :00~:01초). 짧은 재시도 후에도 잠겨 있으면 삼킨다 —
        #   상태 기록은 판정에 쓰지 않으며 다음 틱(1초 뒤)에 다시 저장된다.
        for _ in range(3):
            try:
                atomic_json_write(self.cfg.state_path, payload)
                return
            except PermissionError:
                time.sleep(0.05)
        self.log.warning("상태 저장 건너뜀(파일 잠김) — 다음 틱에 재저장")

    def _restore_state(self) -> None:
        """★[2026-07-22 체결층 이식] 재시작 복구 — 오늘 날짜 상태만 되살린다.
        BUY_PENDING/SELL_PENDING은 그대로 복원해 '기존 주문의 체결확인을 이어받는다'(중복주문 금지).
        HOLD/WATCH도 복원해 매도 추적을 잇는다. CLOSED/FAILED/IDLE은 복원하지 않는다(재무장은 신호로).
        복구 실패 시 recovery_blocked=True → LIVE 신규매수 금지, 매도 관리만 허용."""
        keep = (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD, Phase.BUY_PENDING, Phase.SELL_PENDING)
        try:
            if not self.cfg.state_path.exists():
                return
            payload = stable_json_read(self.cfg.state_path)
            saved_ts = str(payload.get("ts") or "")
            if saved_ts[:10] != datetime.now().strftime("%Y-%m-%d"):
                self.log.info("이전 날짜 상태(%s) — 복원하지 않음", saved_ts[:10] or "?")
                return
            self.ma3_rider.restore(payload.get("ma3_rider") or {})
            self.entries_today = int(payload.get("entries_today") or 0)
            self.daily_buy_krw = safe_float(payload.get("daily_buy_krw"))
            self.daily_realized_pnl_krw = safe_float(payload.get("daily_realized_pnl_krw"))
            self.consecutive_losses = int(payload.get("consecutive_losses") or 0)
            self.c2_01_consumed_signals = set(
                str(value) for value in (payload.get("c2_01_consumed_signals") or [])
            )
            self.c2_01_order_attempts = int(payload.get("c2_01_order_attempts") or 0)
            if "daily_buy_krw" not in payload and self.event_path.exists():
                open_price: Dict[str, float] = {}
                with self.event_path.open(encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        event = str(row.get("event") or "")
                        code = str(row.get("code") or "").zfill(6)
                        price = safe_float(row.get("price"))
                        if event in ("BUY", "SHADOW_FILL") and price > 0:
                            self.daily_buy_krw += price * self.cfg.qty_fixed
                            open_price[code] = price
                        elif event in ("SELL", "SHADOW_SELL_FILL") and price > 0 and code in open_price:
                            realized = (price - open_price.pop(code)) * self.cfg.qty_fixed
                            self.daily_realized_pnl_krw += realized
                            self.consecutive_losses = self.consecutive_losses + 1 if realized < 0 else 0
                self.log.info("일 위험누계 이벤트 복원 매수=%.0f원 실현=%+.0f원 연속손실=%d",
                              self.daily_buy_krw, self.daily_realized_pnl_krw,
                              self.consecutive_losses)
            self.entry_count_by_code = {
                str(k).zfill(6): int(v)
                for k, v in (payload.get("entry_count_by_code") or {}).items()
            }
            self.last_entry_signal = {
                str(k).zfill(6): tuple(float(x) for x in v[:3])
                for k, v in (payload.get("last_entry_signal") or {}).items()
                if isinstance(v, (list, tuple)) and len(v) >= 3
            }
            if not self.entry_count_by_code and self.event_path.exists():
                with self.event_path.open(encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        if str(row.get("event") or "") not in ("BUY", "SHADOW_FILL"):
                            continue
                        code = str(row.get("code") or "").zfill(6)
                        if not code:
                            continue
                        self.entry_count_by_code[code] = self.entry_count_by_code.get(code, 0) + 1
                        self.last_entry_signal[code] = (
                            safe_float(row.get("reset_money_add_krw")),
                            safe_float(row.get("reset_money_per_sec_krw")),
                            safe_float(row.get("buy_ratio"), 0.5),
                        )
            # ★[2026-07-22 실체결 수술] 기준선 계산 버전 — 2가 아니면 저장된 reset_*_cum은
            #   역산 원점의 숫자라 새 실체결 누계와 비교 불가 → 보유분은 재정박 경로로 보낸다.
            calc_ver = int(payload.get("calc_ver") or 1)
            saved_agg = payload.get("tick_agg") or {}
            restored = 0
            for code, sd in (payload.get("states") or {}).items():
                try:
                    ph = Phase(str(sd.get("phase")))
                except Exception:
                    continue
                if ph not in keep:
                    continue
                st = FlowState(code=str(code), name=str(sd.get("name") or code))
                st.phase = ph
                st.lane = str(sd.get("lane") or "RAID")
                st.common_exit_state = dict(sd.get("common_exit_state") or {})
                st.ma_permit = bool(sd.get("ma_permit"))
                st.ma3_rider_permit = bool(sd.get("ma3_rider_permit"))
                st.ma3_hold_logged = bool(sd.get("ma3_hold_logged"))
                st.morning_hold_logged = bool(sd.get("morning_hold_logged"))
                for f_ in ("entry_price", "exit_price", "peak_price", "reset_price",
                           "buy_avg_fill_price", "sell_avg_fill_price", "structure_low",
                           "ma3_ma5", "ma3_ma10", "ma3_ma20", "buy_reserved_krw"):
                    setattr(st, f_, safe_float(sd.get(f_)))
                for f_ in ("qty", "buy_requested_qty", "sell_requested_qty",
                           "buy_filled_qty", "sell_filled_qty", "sell_retry_count"):
                    try:
                        setattr(st, f_, int(float(sd.get(f_) or 0)))
                    except Exception:
                        pass
                for f_ in ("buy_order_no", "sell_order_no", "buy_pending_reason",
                           "sell_pending_reason", "exit_reason"):
                    setattr(st, f_, str(sd.get(f_) or ""))
                st.buy_since_hms = str(sd.get("buy_since_hms") or "00:00:00")
                st.sell_since_hms = str(sd.get("sell_since_hms") or "00:00:00")
                st.buy_slot_reserved = bool(sd.get("buy_slot_reserved"))
                st.buy_cancel_requested = bool(sd.get("buy_cancel_requested"))
                st.sell_cancel_requested = bool(sd.get("sell_cancel_requested"))
                st.buy_known_onos = list(sd.get("buy_known_onos") or [])
                st.sell_known_onos = list(sd.get("sell_known_onos") or [])
                # 경과시간 기준(epoch)은 재시작으로 무의미 — 지금부터 다시 센다(즉시 취소 폭주 방지)
                st.buy_sent_epoch = time.time() if ph == Phase.BUY_PENDING else 0.0
                st.sell_sent_epoch = time.time() if ph == Phase.SELL_PENDING else 0.0
                if ph == Phase.BUY_PENDING and st.buy_reserved_krw <= 0:
                    price_hint = max(st.buy_avg_fill_price, st.reset_price, st.entry_price)
                    st.buy_reserved_krw = max(0, st.buy_requested_qty) * max(0.0, price_hint)
                elif ph != Phase.BUY_PENDING:
                    st.buy_reserved_krw = 0.0

                # ★[2026-07-22] 보유 종목은 RESET 맥락까지 복원해야 전략매도를 이어갈 수 있다.
                if ph in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD) and calc_ver != 2:
                    # 구버전(역산) 기준선 — 승계 불가. 재정박 경로가 실체결 기준선을 새로 세운다.
                    st.phase = Phase.RECOVERY_HOLD
                    self.log.warning("복구: 구계산(calc_ver=%d) 기준선 폐기 %s — 재정박 예정", calc_ver, code)
                elif ph in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD):
                    snap = saved_agg.get(code) or saved_agg.get(str(code).zfill(6))
                    if not snap:
                        # 누계 승계분이 없으면 기준선과 새 누계의 원점이 어긋난다 — 재정박 경로로
                        st.phase = Phase.RECOVERY_HOLD
                        self.log.warning("복구: 실체결 누계 승계분 없음 %s — 재정박 예정", code)
                        self.states[str(code)] = st
                        restored += 1
                        continue
                    self.agg.seed(str(code).zfill(6), snap)   # 실체결 누계 승계(공백 구간은 버림)
                    st.reset_ts = _parse_saved_dt(sd.get("reset_ts"))
                    st.watch_since = _parse_saved_dt(sd.get("watch_since"))
                    # ★[2026-07-22 매도수술] 매도 지속확인 타이머도 승계 — 없으면 재시작마다 리셋돼
                    #   재시작 직후 매도가 sell_confirm_sec만큼 추가 지연된다(안전 방향이라 없어도 무해).
                    st.sell_cond_since = _parse_saved_dt(sd.get("sell_cond_since"))
                    st.entry_ts = _parse_saved_dt(sd.get("entry_ts"))
                    for f_ in ("reset_buy_cum", "reset_sell_cum", "reset_cum_vol",
                               "reset_che_str", "reset_high", "reset_low",
                               "reset_buy_money", "reset_sell_money",
                               "buy_exec_money", "sell_exec_money", "buy_money_ratio",
                               "hold_peak_money_ps",
                               "buy_ratio", "buy_sell_ratio", "buy_exec_vol", "sell_exec_vol",
                               "price_response_pct"):
                        setattr(st, f_, safe_float(sd.get(f_)))
                    st.dryup_since = _parse_saved_dt(sd.get("dryup_since"))
                    try:
                        st.recent_prices = [(float(t), float(px))
                                            for t, px in (sd.get("recent_prices") or [])]
                    except Exception:
                        st.recent_prices = []
                    ok_ctx, miss = _reset_context_ok(st)
                    if not ok_ctx:
                        st.phase = Phase.RECOVERY_HOLD
                        self.log.warning("복구 불완전 %s — RECOVERY_HOLD(전략매도 금지, "
                                         "HARD_STOP·TIME_EXIT만): 누락 %s", code, ",".join(miss))
                self.states[str(code)] = st
                restored += 1
            if restored:
                self.log.info("재시작 복구 %d종목: %s", restored,
                              ", ".join(f"{c}:{s.phase.value}" for c, s in self.states.items()))
            # 공용 슬롯·계좌와 대조 — LIVE에서 예약이 사라졌으면 다시 잡아둔다(중복 진입 방지)
            if self.cfg.live and restored:
                today = self._today()
                held, why_rt = self._account_held_codes()
                if why_rt:
                    # 계좌 진실을 못 믿는 상태 — 보유를 임의로 CLOSED 처리하면 안 된다(잔고 유실 위험).
                    self.log.warning("복구: rt_open 신뢰불가(%s) — 계좌 대조 생략, 보유 상태 유지", why_rt)
                    held = set()
                for code, st in list(self.states.items()):
                    if st.buy_slot_reserved and not shared.has(code, today):
                        if shared.acquire(code, "CAPTAIN2", today):
                            self.log.info("복구: 공용 슬롯 재예약 %s", code)
                        else:
                            self.log.warning("복구: 공용 슬롯 재예약 실패 %s — 타 전략 점유", code)
                    if st.phase in (Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD) and held and code not in held:
                        self.log.warning("복구: 계좌에 %s 보유 없음 — 계좌를 진실로 CLOSED 처리", code)
                        st.phase = Phase.CLOSED
                        st.terminal_ts = datetime.now()
                        self._release_slot(code, st, "RECOVERY_NOT_IN_ACCOUNT")
        except Exception:
            self.recovery_blocked = True
            self.log.exception("RECOVERY_BLOCK — 상태 복구 실패. LIVE 신규매수 금지·매도 관리만 허용")

    def run(self) -> None:
        if not self.execution.connect():
            raise RuntimeError("ExecutionAdapter 연결 실패")
        self._restore_state()
        self.log.info("CAPTAIN2 시작 live=%s loop=%.1fs 최대보유=%d(계좌공용) %d주고정",
                      self.cfg.live, self.cfg.loop_sec, self.cfg.max_positions, self.cfg.qty_fixed)
        self.log.info(
            "CAPTAIN2 설정 진입=%s-%s 강제청산=%s 손절=바닥%.1f%%/눌림%.1f%%/매수우위%.1f%% "
            "재진입=%d회 회전원금=%.0f원 일손실중단=%.0f원 연속손실중단=%d회",
            self.cfg.entry_start, self.cfg.entry_end, self.cfg.force_exit,
            self.cfg.hard_stop_bottom_pct, self.cfg.hard_stop_pull_pct,
            self.cfg.hard_stop_pull_buy_pct, self.cfg.max_entries_per_code,
            self.cfg.max_active_capital_krw, self.cfg.max_daily_loss_krw,
            self.cfg.max_consecutive_losses)
        self.log.info("CAPTAIN2 3분봉 상승보유=%s 5·10선 만남=%.2f%% RAID/PULL/BASE 추가TR=0",
                      self.cfg.ma3_rider_on, self.cfg.ma3_converge_pct)
        self.log.info("CAPTAIN2 BASE=%s 완성1분봉%d개·응집≤%.1f%%·거래량≥%.1f배·리테스트%d분 "
                      "저점탐색%.0f초/매수확인%.0f초·추격금지",
                      self.cfg.base_on, self.cfg.base_n, self.cfg.base_tight_pct,
                      self.cfg.base_volx, self.cfg.base_wait_bars,
                      self.cfg.base_low_search_max_sec, self.cfg.base_buy_max_sec)
        self.log.info(
            "CAPTAIN2 재가속 SHADOW=%s LIVE=%s 완성3분봉·시가+%.1f%%·고점숙성%d봉·확장≤%.1f%% "
            "거래량≥%.1f배·60초관문",
            self.cfg.reaccel_shadow_on, self.cfg.reaccel_live_on,
            self.cfg.reaccel_min_day_gain_pct,
            self.cfg.reaccel_min_age_bars, self.cfg.reaccel_max_ext_pct,
            self.cfg.reaccel_min_volx)
        while self.running:
            loop_started = time.monotonic()
            hm = datetime.now().strftime("%H%M")
            if hm > self.cfg.program_end:
                break
            try:
                kill_on = self.cfg.live and self.cfg.off_flag_path.exists()
                if kill_on and not self.kill_switch_latched:
                    self.kill_switch_latched = True
                    self.log.warning("CAPTAIN2_OFF_FLAG 감지 — 신규매수 즉시 중단, 보유종목 매도관리는 계속")
                elif not kill_on and self.kill_switch_latched:
                    self.kill_switch_latched = False
                    self.log.info("CAPTAIN2_OFF_FLAG 해제 — 안전조건 충족 시 신규매수 재개")
                points = self.feed.read_points()
                if self.feed_stale_latched:
                    if self.feed_fresh_since <= 0:
                        self.feed_fresh_since = time.monotonic()
                    fresh_age = time.monotonic() - self.feed_fresh_since
                    entry_allowed = fresh_age >= self.cfg.stale_recovery_sec
                    if entry_allowed:
                        self.feed_stale_latched = False
                        self.feed_fresh_since = 0.0
                        self.log.info("보드 정상 %.1f초 확인 — 신규매수 재개", fresh_age)
                else:
                    entry_allowed = True
                # ★[2026-07-22 실체결 수술] 판정 전에 전 종목 실체결 누계부터 갱신(루프당 정확히 1회)
                self.agg.update(points.values())
                self.ma3_rider.update(points.values())
                # C2-01은 주문0 감시기의 fresh BUY_READY만 기존 1주 주문 경로에 전달한다.
                if entry_allowed and self.cfg.c2_01_on:
                    self._c2_01_signal_step(points)
                # ★[BASE 횡보돌파] 패턴 무장/리테스트는 일반 MONEY_START와 독립.
                #   리테스트 뒤 매수는 아래 공통 FlowState 경로에서 실제 저점·매수우위로 확정한다.
                if entry_allowed and self.cfg.entry_start <= hm <= self.cfg.entry_end:
                    self._base_step(points)
                # ★[EARLY 초입레인 2026-07-23] 09:00~09:10 초입 창에서만 판정 — RAID·PULL과 독립.
                #   같은 루프 발화 다수면 매수비→속도→배율 정렬 후 빈 슬롯 수만큼 진입(친구님 확정).
                if (entry_allowed and self.cfg.early_on
                        and self.cfg.early_start <= hm <= self.cfg.early_end):
                    early_fired: list = []
                    for point in points.values():
                        ec = self._early_check(point)
                        if ec:
                            early_fired.append(ec)
                    if early_fired:
                        self._early_select_and_open(early_fired)
                # ★[2026-07-22] 같은 루프의 BUY_READY 후보를 먼저 전부 수집한다(주문은 이 루프 끝에 1건).
                candidates: list = []
                touched: list = []          # ★[2026-07-22] 이번 루프에 처리된 종목(재생로그용)
                for point in points.values():
                    # 신규 FLOW 탐색은 진입창 안에서만. 기존 보유 추적은 종료시각까지 계속.
                    state = self.states.get(point.code)
                    # ★[2026-07-22] 주문 진행중(BUY/SELL_PENDING)도 진입창 밖에서 체결확인이 계속돼야 한다.
                    has_position = bool(state and state.phase in (
                        Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                        Phase.BUY_PENDING, Phase.SELL_PENDING))
                    if has_position or (entry_allowed and self.cfg.entry_start <= hm <= self.cfg.entry_end):
                        candidate = self._process(point)
                        if candidate:
                            candidates.append(candidate)
                        touched.append(point)
                reaccel_candidates = self._reaccel_shadow_step(
                    points,
                    allow_live=(entry_allowed
                                and self.cfg.entry_start <= hm <= self.cfg.entry_end))
                if reaccel_candidates:
                    candidates.extend(reaccel_candidates)
                if candidates:
                    self._select_and_open(candidates)
                # ★[2026-07-22 관찰전용] 이 루프에서 처리된 종목만, 상태 전이가 모두 끝난 뒤
                #   최종 상태로 종목당 정확히 1행 기록한다(_select_and_open의 BUY까지 반영).
                for point in touched:
                    st = self.states.get(point.code)
                    if st is not None:
                        self._replay_row(point, st)
                self._replay_flush()
                self._save_state()
            except Exception as exc:
                if isinstance(exc, RuntimeError) and str(exc).startswith("micro board stale:"):
                    if not self.feed_stale_latched:
                        self.log.warning("%s — 신규매수 신호 폐기·정상 5초 확인 대기", exc)
                    self.feed_stale_latched = True
                    self.feed_fresh_since = 0.0
                    for es in self.early.values():
                        es.streak = 0
                        es.hist.clear()
                    for st in self.states.values():
                        if st.phase in (Phase.FLOW_DETECTED, Phase.LOW_SEARCH,
                                        Phase.RESET, Phase.BUY_READY):
                            st.phase = Phase.IDLE
                            st.candidate_low = None
                            st.dominance_since = None
                    try:
                        safety_points = self.feed.read_points(allow_stale_board=True)
                        self.agg.update(safety_points.values())
                        for point in safety_points.values():
                            state = self.states.get(point.code)
                            if state and state.phase in (
                                    Phase.HOLD, Phase.WATCH, Phase.RECOVERY_HOLD,
                                    Phase.BUY_PENDING, Phase.SELL_PENDING):
                                self._process(point)
                        self._save_state()
                    except Exception:
                        self.log.exception("보드 장애 중 보유종목 안전감시 실패")
                else:
                    self.log.exception("메인 루프 오류 — 다음 루프 계속")
            self._touch_lock()   # ★[2026-07-22 보강] 락 유지(예외가 나도 갱신 — 살아있으면 락도 살아있어야 함)
            elapsed = time.monotonic() - loop_started
            time.sleep(max(0.05, self.cfg.loop_sec - elapsed))
        self._save_state()
        self._replay_flush(force=True)      # ★[2026-07-22] 종료 시 남은 버퍼 반드시 기록
        self.log.info("CAPTAIN2 종료 (재생로그 %d행 기록)", self._replay_rows_written)


def main() -> int:
    cfg = Config()
    logger = setup_logger(cfg)
    feed = DataFeed(cfg, logger)
    execution = ExecutionAdapter(cfg, logger)
    engine = Captain2Engine(cfg, feed, execution, logger)
    signal.signal(signal.SIGINT, engine.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, engine.stop)
    try:
        engine.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("치명 오류")
        return 1


if __name__ == "__main__":
    # ★[2026-07-22 보강] 단일 인스턴스 락 — money_flow_board_v1.py의 기존 프로젝트 패턴 그대로 복사.
    #   원본에는 중복실행 방지가 없어서 스케줄러 재기동·수동실행이 겹치면 같은 종목에 대해
    #   두 프로세스가 각자 state/CSV를 쓰고(LIVE 전환 시엔 중복주문까지) 오염된다.
    #   락이 살아있으면(200초 이내 갱신) 두 번째 프로세스는 즉시 종료하고 로그를 남긴다.
    _LOCK = Path(os.environ.get("CAPTAIN2_LOCK", r"C:\stock_bot\data\captain2.lock"))
    # 락 만료 60초 — 살아있는 프로세스는 매 루프(1초)마다 갱신하므로 실측 최대 루프 83ms 대비
    #   700배 여유다. 스케줄러가 1분 반복 트리거로 재기동을 시도하므로, 프로세스가 죽었을 때
    #   이 값만큼만 기다리면 자동 복구된다(200초로 두면 복구가 4분 뒤로 밀린다).
    _LOCK_MAX_AGE = float(os.environ.get("CAPTAIN2_LOCK_MAX_AGE", "60"))
    _skip = False
    try:
        if _LOCK.exists() and (time.time() - _LOCK.stat().st_mtime) < _LOCK_MAX_AGE:
            print("CAPTAIN2 이미 실행중(lock) → skip", flush=True)
            _skip = True
    except Exception:
        pass
    if _skip:
        raise SystemExit(0)
    try:
        _LOCK.parent.mkdir(parents=True, exist_ok=True)
        _LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    # ★[2026-07-22 크래시증거] 첫날 원인불명 재기동 다수·트레이스백 0건 — 파이썬 예외는 stderr로
    #   이미 잡히므로, 남은 사각은 네이티브 크래시(access violation 등)다. faulthandler가 그 순간의
    #   스택을 이 파일에 남긴다. 파일 핸들은 프로세스 수명 내내 열어둬야 한다(닫으면 무효).
    try:
        _CRASH_LOG = open(r"C:\stock_bot\LOG\captain2_crash.log", "a",
                          encoding="utf-8", errors="replace")
        _CRASH_LOG.write(f"=== CAPTAIN2 기동 {datetime.now():%Y-%m-%d %H:%M:%S} "
                         f"pid={os.getpid()} ===\n")
        _CRASH_LOG.flush()
        faulthandler.enable(file=_CRASH_LOG)
    except Exception:
        pass
    try:
        raise SystemExit(main())
    finally:
        try:
            _LOCK.unlink()
        except Exception:
            pass
