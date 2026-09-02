# -*- coding: utf-8 -*-
"""새전략 02 저점매수·매도소진 신호전용 감시기(주문 0)."""
from __future__ import annotations

import argparse
import csv
import json
import msvcrt
import os
import sys
import time as time_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from intraday_anchor_v1 import day_anchor
from strategy_02_signal_contract_v1 import SIGNAL_MODE, SIGNAL_SCHEMA
from 저점매수_매도소진 import BottomSignal, MarketPoint, detect_flow_book_exhaustion

KST = ZoneInfo("Asia/Seoul")
# ★[2026-07-31 친구님 지시 "시각 9시 05부터 14시 20"] 09:30 → 09:05.
#   7/31 실측: 고저폭 30종목의 당일 저점이 25개/30개가 09:10 이전에 형성됐다.
#   09:30 시작이면 그날 가장 좋은 자리를 통째로 놓친다.
ENTRY_START = time(9, 0)
MORNING_OPEN_REFERENCE_END = time(9, 30)
# ★[DAY-LOW 2026-08-05] 정규장 시작. 진짜 당일 저점 기록에만 쓴다(판정 미사용).
REGULAR_SESSION_START = time(9, 0)
ENTRY_END = time(14, 20)
AFTERNOON_START = time(12, 0)
# 그림자 AFT5F 확정값: 12시 이후 신호가격이 장중 고점 대비 -5% 이상이고
# 최근 10초 매수대금 속도가 매도대금 속도보다 강할 때만 진입한다.
AFTERNOON_MIN_SIGNAL_DROP_PCT = 5.0
S02_SEVERE_BOOK_IMBALANCE = -0.25
S02_BOOK_RECOVERY_LEVEL = -0.15


# ★[2026-07-31 친구님 지시 "2번 이렇게 바꿔"] 매수 판정 전면 교체.
#   폐기한 것 = detect_flow_book_exhaustion (하락파동 2개 + 약화지표 2개 + 첫저점 회복
#     + 매도압력 전환 + 총호가 매수우위 60% + 진입가 저점+1.5% 이내, 7개 동시 충족).
#   폐기 이유 — 두 달 가까이 신호 0건. 7/29 후보 264개·7/31 후보 231건이 전원
#     같은 자리(FLOW_BOOK_RECOVERY_WAIT)에서 죽었다.
#   7/31 단계별 실측(고저폭30·09:30~14:20):
#       하락파동 2개 이상        26/30 통과
#       + 두번째 저점이 더 낮음  25/30 통과
#       + 고점대비 낙폭 2%↑     25/30 통과
#       + 매도압력·호가·진입가   **0/30**   ← 전멸
#   병목은 "총호가 매수우위 60%"다. 바닥에서 사겠다면서 호가가 매수우위여야 한다는
#     건 서로 모순이다 — 매수우위로 바뀔 때쯤이면 값이 올라 진입가 제한(저점+1.5%)에
#     걸린다. 어느 쪽으로 가도 죽는 구조다.
#   새 규칙 = 1번(S01)에서 검증된 되돌림 3조건을 이 시간대에 이식.
#     7/31 재현: 27종목 체결 · 평균 +3.18% · 승률 93%  (기존 규칙은 0종목)
#     ⚠️기준점은 1번과 다르다 — 1번은 '시가 대비'(개장 직후라 시가가 기준),
#       2번은 '장중 고점 대비'(09:05 이후엔 시가가 이미 옛 값).
#     ⚠️밀림 문턱도 다르다 — 09:30 이후 되돌림은 09시대의 절반(중앙값 0.72% vs 1.64%).
#   롤백: setx S02_DIP_MODE NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260731_dipmode.py 복원
DIP_MODE = os.environ.get("S02_DIP_MODE", "YES").strip().upper() == "YES"
MORNING_DIP_DROP_PCT = 3.0   # 09:00~09:29:59 시가 대비 -3% 이하
INTRADAY_DIP_DROP_PCT = 5.0  # 09:30 이후: 장중 고점 대비 -5% 이하
# ★[DIRECT-REBOUND 2026-08-13 친구님 지시] 눌림 없는 직접반등 공통 판정 —
#   정책은 low_rebound_common_v1 한 곳(S06 와 동일 코드 호출). 기본 OFF(기록만).
from low_rebound_common_v1 import (
    DirectReboundConfig,
    judge_direct_rebound,
)
from strategy_common_relative_strength_rebound_v1 import (
    RelativeStrengthReboundShadow,
)

DIP_REBOUND_PCT = float(os.environ.get("S02_DIP_REBOUND_PCT", "0.5"))  # 저점 +X% 회복 = 신호
DIP_CHASE_CAP_PCT = float(os.environ.get("S02_DIP_CHASE_CAP", "3.0"))  # 저점 +X% 넘으면 추격 금지
# ★[2026-08-01 친구님 지시 "2번 저점매수 방법을 6번과 동일하게"] 6번식 매수 확인 이식.
#   ①관찰 60초 — 저점이 생기고 최소 60초는 지켜본다(덥썩 방지)
#   ②속도 역전 — 저점 전 180초는 매도 우위였다가, 저점 후에는 매수 속도가
#     매도 속도를 넘어야 산다(자료가 없어 판별 불가면 통과 — 조건 최소 원칙)
#   ③재무장 깊이 — 같은 종목 2번째 신호는 직전 신호 저점보다 1% 더 깊은
#     저점에서만(연속 가짜 반등에 2발을 다 쓰는 것 방지)
#   근거: 7/29 지엔씨에너지 분당 재생 — 속도 역전이 진짜 바닥을 정확히 갈랐고
#   (가짜 6개 전부 역전 없음), 6번에서 같은 규칙이 -2.18%→+0.98% 로 뒤집었다.
#   발동 기준(장중 고점 대비)·시간창·매도는 그대로 — 사는 "방법"만 6번식.
#   롤백: setx S02_SIX_STYLE NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260801_sixstyle.py 복원
# ★[2026-08-01 보안점검 중간6] 딥모드 롤백(S02_DIP_MODE=NO) 시 6번식도 함께
#   내려간다 — 옛 매도소진 판정에 확정대기 생략·재무장만 얹힌 잡종 조합 방지.
# ★[2026-08-03 보안점검] S02_SIX_STYLE 재연결 — 이 줄이 `SIX_STYLE = DIP_MODE` 로
#   바뀌면서 67줄이 안내하는 롤백(setx S02_SIX_STYLE NO)이 아무 효과가 없었다.
#   기본값 YES 라 환경변수 미설정 시 결과는 종전과 완전히 같다(DIP_MODE 그대로).
SIX_STYLE = (os.environ.get("S02_SIX_STYLE", "YES").strip().upper() == "YES") and DIP_MODE
SIX_OBSERVE_SEC = float(os.environ.get("S02_OBSERVE_SEC", "60"))
# ★[MORNING-FASTPATH 2026-08-06 친구님 지시]
#   "아침엔 60초 관찰을 피해가야 돼" · "저점 리셋해서 매수 매도가 역전되면 바로 매수해야 돼"
#   · "1-1.5%, 2%는 추격" · "눌림도 면제(A)"
#
#   왜: 아침은 계단이 빨라 60초를 기다리면 저점이 계속 갈아치워진다.
#   8/6 실측(피에스케이 319660, 09:00~09:20 재생) — 저점 리셋 9회, 단계가 내내 CHASE 였고
#   OBSERVE 에 처음 들어간 것이 09:20:34 로 아침 창이 끝난 뒤였다. 즉 아침엔 이 경로가
#   구조적으로 한 건도 못 낸다.
#
#   면제하는 것 : 60초 관찰 · 눌림(0.4%) 대기 · 2차반등 확인   ← 전부 '시간을 버는' 조건
#   그대로 두는 것: 흐름 역전(flow_flip) · 흐름 가속 · 상대 흐름 전환 ← '매수세가 이겼나'의 증거
#   즉 관찰을 포기하는 게 아니라, 이미 역전이 확인된 순간에는 더 안 기다린다.
#
#   구간은 2번 값을 그대로 쓴다(1번도 같은 모듈을 부르므로 전략별 분기를 만들지 않는다):
#     하한 = SIX_FIRST_REBOUND_PCT(1.0) · 상한 = 아래 1.5 · 2.0 초과는 종전대로 추격(저점 죽임)
#   ⚠️절대 체결강도(옛 급행의 che 120)는 쓰지 않는다 — 바닥에서는 나올 수 없는 값이다(친구님).
#
# ★★[2026-08-06 같은 날 저녁 친구님 지시 "2번은 급락이 없어 / 통합 매수 확인해봐 /
#   급행 끄고"] 기본값을 YES -> NO 로 되돌린다. 만들어놓고 끄는 이유 둘:
#
#   ① 중복이었다. 2번에는 급락용 별도 경로(_detect_money_surge_onset)가 이미 있고
#      그 경로에는 애초에 60초 관찰이 없다(SURGE_TURN_MAX_SEC=10초).
#      SIX_OBSERVE_SEC 는 계단 경로 두 곳에만 걸린다.
#      아침에 그 경로가 안 돌던 진짜 이유는 관찰이 아니라 '태스크가 09:20 에 떠서
#      프로세스가 없었던 것'이고, 그건 오늘 태스크를 09:00 으로 당겨 이미 고쳤다.
#   ② 반증이 나왔다(8/6 RFHIC 218410 재생):
#      급행 자리 09:01:22 @50,000 -> 그 뒤 48,300 까지 -3.4% 밀려 하드스톱.
#      급행 없는 실제 09:40:37 @49,050 -> 11:47 51,300 매도 +4.587%.
#      09:01 에 이미 -14.36% 인데 더 빠졌다.
#
#   코드는 남긴다 — 며칠 치 재생으로 다시 볼 값이다.
#   켜기: setx S02_MORNING_FASTPATH YES   (프로세스 재기동 후 적용)
#   ⚠️환경변수가 아니라 이 기본값이 실전을 정한다. 예약 태스크가 사용자 환경변수를
#     못 받는 경우가 있어 기본값을 실전 값으로 둔다(8/6 S01 에서 같은 판단).
MORNING_FASTPATH = (
    os.environ.get("S02_MORNING_FASTPATH", "NO").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)


def _hhmm(text: str, default: time) -> time:
    """'0920' -> time(9,20). 형식이 깨지면 기본값으로 물러선다."""
    raw = str(text or "").strip()
    if len(raw) == 4 and raw.isdigit():
        hh, mm = int(raw[:2]), int(raw[2:])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return time(hh, mm)
    return default


MORNING_FASTPATH_END = _hhmm(
    os.environ.get("S02_MORNING_FASTPATH_END", "0920"), time(9, 20))
MORNING_FASTPATH_MAX_REBOUND_PCT = float(
    os.environ.get("S02_MORNING_FASTPATH_MAX_REBOUND_PCT", "1.5"))
SIX_REARM_DEEPER_PCT = float(os.environ.get("S02_REARM_DEEPER_PCT", "1.0"))
# ★[S03-ALIGN 되돌림 2026-08-05 저녁 친구님 지시 "어제 값 되돌려줘"]
#   같은 날 낮에 S03 와 같은 값으로 맞췄다(1차반등 1.5->1.0, 추격상한 2.0->1.5).
#   저녁에 그 근거가 착시였음이 드러나 원래 값으로 되돌린다.
#
#   ★무엇이 착시였나 — 낮에 쓴 근거는 "저점(96,000) 대비 +1.875% 에서 매수했다,
#     상한이 1.5 였으면 차단됐다" 였다. 그런데 96,000 은 당일 저점이 아니다.
#     _reset_six_cycle 이 새 고점이 찍힐 때마다 six_low 를 현재가로 통째로 갈아치우므로
#     anchor_low 는 "마지막 고점 이후의 저점"일 뿐이다. 진짜 당일 저점은 95,100(09:10:20).
#     그래서 문턱을 조일수록 anchor 기준 수치는 좋아 보이는데 실제 매수가는 올라간다.
#
#   ★실증 (8/5 원익IPS 240810 · 1초 캡처 재생 · 실제 신호 11:00:09@97,800 재현 확인)
#     실전 조건(회전엔진 태스크가 09:20:20 에 뜬다) 기준 첫 매수:
#       반등1.0/상한1.5 (낮에 바꾼 값) : 09:33:48 @98,700
#                                        계약서 1.439%(1등) / 진짜 3.785%(꼴찌) / 종가대비 -1.013%
#       반등1.5/상한2.0 (원래 값)      : 11:00:08 @97,800
#                                        계약서 1.875%     / 진짜 2.839%      / 종가대비 -0.102%
#     🔑추격상한은 1.5/2.0/2.5/3.0 어떤 값이어도 매수 시각·가격이 같다(09:33:48 @98,700).
#       실제로 작동한 건 "1차반등 1.5->1.0" 하나뿐이고, 그게 매수를 1시간 26분 앞당겨
#       900원 비싸게 만들었다. 착시폭 2.347%p.
#
#   ⚠️이건 새 문턱을 고른 게 아니라 근거가 착시였던 변경을 무른 것이다.
#     S03 와는 값이 다시 달라진다 — S02 는 60초 관찰이 있는 다른 전략이라 무방하다.
#     문턱을 진짜로 고르려면 며칠 쌓아서 봐야 한다(7/31 교훈: 하루로 고르면 실패 반복).
#   ⚠️관찰시간(SIX_OBSERVE_SEC=60)은 낮에도 안 바꿨고 지금도 안 바꾼다 — 전략 정체성.
#   기록: memory.md 8/5 저녁 "② S02 저점 대비 % 착시" 항목.
# ★[2026-08-06 낮 친구님 지시] 1차반등만 1.5 -> 1.0. 추격상한은 2.0 그대로 둔다.
#   경위: "2번은 1.5/2.0 으로 예외 처리돼 이걸 1-1.5% 똑같이 해" → 1.0/1.5 로 바꿔봤더니
#   시험 1건이 죽었다 → 원인을 숫자로 보여드린 뒤 친구님이 "1.0/2.0" 을 받아들이셨다.
#   위 8/5 기록은 지우지 않는다(반대 증거로 남긴다).
#
#   ★왜 추격상한 1.5 는 안 되는가 (실측 - test_s06_staircase_full_retest...)
#     시험 시나리오의 저점은 9,500. 상한 2.0% 면 천장이 9,690, 1.5% 면 9,642.5 다.
#     문제의 틱은 9,643 - 겨우 0.5원 차이로 1.5% 천장을 넘는다.
#     그런데 천장을 넘으면 코드가 그 저점을 '죽은 저점'으로 낙인찍는다
#     (six_dead_low = six_low, 980행). 그 뒤로는 9,500 보다 '더 깊은' 새 저점이
#     나와야만 다시 보는데 이후 가격은 9,595~9,644 라 영영 안 산다.
#     ⇒ 늦게 사는 게 아니라 신호가 1건 -> 0건 으로 사라진다.
#     ⚠️8/5 주석의 "상한은 1.5~3.0 어느 값이어도 결과가 같다" 는 한 종목 하루 이야기였다.
#       이 시험이 그 반례다.
#
#   ★1차반등 1.0 은 그대로 간다 - 8/5 실측에서 '실제로 작동한 건 1차반등 하나뿐'이었고,
#     친구님의 설계 원칙(저점 찾는 법은 전략끼리 같아야 한다)에 맞춘다.
#   ⚠️알고 넘어갈 것 - 8/5 원익IPS 재생에서 1차반등 1.0 은 매수를 1시간 26분 앞당겨
#     900원 비싸게 샀다(종가대비 -1.013% vs -0.102%). 하루·한 종목 표본이다.
#     며칠 치가 쌓이면 다시 본다.
#   ⚠️이 값이 바뀌면 계약서 config\lowfind_contract_v1.json 도 같이 바꾼다.
#     한쪽만 고치면 다음날 08:30 리허설이 잡는다.
#   롤백: setx S02_SIX_FIRST_REBOUND_PCT 1.5 (프로세스 재기동 후 적용) + 계약서 되돌리기.
SIX_FIRST_REBOUND_PCT = float(os.environ.get("S02_SIX_FIRST_REBOUND_PCT", "1.0"))
SIX_CHASE_CAP_PCT = float(os.environ.get("S02_SIX_CHASE_CAP_PCT", "2.0"))
SIX_PULLBACK_MIN_PCT = float(os.environ.get("S02_SIX_PULLBACK_MIN_PCT", "0.4"))
SIX_HIGHER_LOW_BUFFER_PCT = float(os.environ.get(
    "S02_SIX_HIGHER_LOW_BUFFER_PCT", "0.3"))
SIX_SECOND_REBOUND_PCT = float(os.environ.get(
    "S02_SIX_SECOND_REBOUND_PCT", "0.5"))
SIX_ENTRY_FLOOR_PCT = float(os.environ.get("S02_SIX_ENTRY_FLOOR_PCT", "1.0"))
SIX_FLOW_ACCEL_WINDOW_SEC = float(os.environ.get(
    "S02_SIX_FLOW_ACCEL_WINDOW_SEC", "10"))
# ★[저점리셋 관문 2026-08-07 친구님 지시 "저점에서 리셋하고 해야 돼"]
#   8/7 전패(13건 -9.02%) 뒤 1초 캡처로 그날 신호 27건을 재생해 저점 리셋 횟수로 갈랐다.
#     리셋 1회 0승(2건) · 2~3회 0승(2건) · 4회 이상 65.2%(23건)
#   리셋이 적은 저점 = 아직 한두 번밖에 안 깨진 저점 = 바닥이 아니다.
#   오늘 27건 -> 23건. 이익먼저 15건은 하나도 안 잘리고 손절만 3건 줄었다.
#   ⚠️하루치다(N=27). 문턱 4는 며칠 더 쌓아 확정할 것.
#   ⚠️낙폭 하한은 넣지 않는다 — 계약서 정답이 5.954% 인데 8/7 패배가 5.90% 라 못 가른다.
#   폐기 기록(재시도 금지):
#     · 매도속도 previous_sell>0   재생 -0.02%p · 그날 최고 수익건을 죽임
#     · 봉 전환 판정(직전봉 음봉+양봉전환+봉내 매수우위+매도감속)
#                                 통과 50.0% vs 탈락 63.2% = 방향이 반대
#     · 낙폭 하한 6.0%            계약서 정답(5.954%)을 막아 잠금시험 파괴
#   롤백: setx S02_MIN_LOW_RESET_STEPS 0  (= 종전과 완전히 동일)
#         또는 RUN\backup\strategy_02_low_buy_signal_v1_20260807_lowreset.py 복원
#
# ★[철회 2026-08-07 밤 친구님 지시 "전으로 되돌려"] 기본값을 4 -> 0 으로 내렸다.
#   친구님 원문: "내가 의도한 대로 안 만들고 제맘대로 만들었어". 원하신 것은 리셋
#   횟수 세기가 아니라 "반등해 올라오는 사이 매도와 흡수가 어떻게 변해 가는지 보고
#   살지 말지 판단"이다. 관문 자체가 의도와 다른 물건이었다.
#   ⚠️기본값을 0 으로 내린 이유: 되돌림이 사용자 환경변수 하나에만 걸려 있으면,
#     그 값이 프로세스에 안 실리는 순간(프로필 초기화·다른 계정으로 수동 실행·
#     다른 세션이 값 삭제) 철회한 관문이 조용히 되살아난다. 신호가 사라져도 로그에
#     "관문 때문"이라는 흔적이 없어 원인 추적이 안 된다. 그래서 코드가 기본으로
#     꺼져 있게 한다 — 켜려면 명시적으로 켜야 한다.
#   다시 켜려면: setx S02_MIN_LOW_RESET_STEPS 4  (친구님 승인 후에만)
#   ⚠️12일 재생(7/23~8/7 신호 1107건)에서 이 축은 승패를 못 갈랐다 —
#     리셋 횟수 중앙이 승자 12회 · 패자 12회로 같다. 되살릴 근거가 없다.
MIN_LOW_RESET_STEPS = int(os.environ.get("S02_MIN_LOW_RESET_STEPS", "0"))
SIX_OBSERVE_MAX_SEC = float(os.environ.get("S02_SIX_OBSERVE_MAX_SEC", "720"))
S02_DIRECT_MIN_NO_NEW_LOW_SEC = 60.0
S02_DIRECT_MAX_NO_NEW_LOW_SEC = 240.0


def _direct_rebound_age_route(no_new_low_sec: float) -> str:
    """WAIT < 60s, DIRECT through 240s, then use the existing RETEST path."""
    if no_new_low_sec < S02_DIRECT_MIN_NO_NEW_LOW_SEC:
        return "WAIT"
    if no_new_low_sec > S02_DIRECT_MAX_NO_NEW_LOW_SEC:
        return "RETEST"
    return "DIRECT"


# 급락 직후 첫 장대양봉 초입을 잡는 별도 경로. 기존 6번식 계단 저점 경로는 유지한다.
MONEY_SURGE_ENABLED = (
    os.environ.get("S02_MONEY_SURGE_ENABLED", "YES").strip().upper() == "YES"
)
FLOW_BOOK_SHADOW_ENABLED = (
    os.environ.get("S02_FLOW_BOOK_SHADOW_ENABLED", "YES").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)
SURGE_DROP_WINDOW_SEC = float(os.environ.get("S02_SURGE_DROP_WINDOW_SEC", "30"))
SURGE_MIN_DROP_PCT = float(os.environ.get("S02_SURGE_MIN_DROP_PCT", "3.0"))
SURGE_MIN_DOWN_STEPS = int(os.environ.get("S02_SURGE_MIN_DOWN_STEPS", "3"))
SURGE_TURN_MAX_SEC = float(os.environ.get("S02_SURGE_TURN_MAX_SEC", "10"))
SURGE_REBOUND_MIN_PCT = float(os.environ.get("S02_SURGE_REBOUND_MIN_PCT", "0.5"))
SURGE_REBOUND_MAX_PCT = float(os.environ.get("S02_SURGE_REBOUND_MAX_PCT", "2.0"))
SURGE_CONFIRM_TICKS = int(os.environ.get("S02_SURGE_CONFIRM_TICKS", "2"))
SURGE_CONFIRM_MAX_GAP_SEC = float(os.environ.get("S02_SURGE_CONFIRM_MAX_GAP_SEC", "2"))
SURGE_RECENT_SEC = float(os.environ.get("S02_SURGE_RECENT_SEC", "5"))
SURGE_PREVIOUS_SEC = float(os.environ.get("S02_SURGE_PREVIOUS_SEC", "10"))
# 공통 컨텍스트(strategy_common_candidate_context_v1)가 all_meta 에 실어주는 고저폭 지표.
# 신호 행에 그대로 붙여 기록한다. ★2026-07-31 부터 감시대상 제한에도 쓴다(아래 참조).
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
    "hr_money_speed_ratio", "hr_turnover_pct", "hr_volatility_quality",
    "hr_quality_risks", "hr_live_status",
)
MONEY_FLOW_KEYS = (
    "mf_inst", "mf_frgn", "mf_prog", "mf_che", "mf_chg",
)
S02_CANDIDATE_LIMIT = 50
# ★[2026-08-27 사용자 승인] S02 감시대상은 고저폭·돈흐름 선별판 합집합 최대 50개.
#   두 판에 모두 든 종목을 먼저 두고, 나머지는 고저폭 순위·돈흐름 순으로 채운다.
#   근거 — 일봉 1년 코스닥 전수(12만건·왕복비용 0.38% 차감)로 S02 진입을 근사
#   (당일 저가 +1% 매수 → 당일 종가 매도) 했을 때:
#       고저폭 조건 밖   +1.251% / 승률 58.8%  (11.4만건)
#       고저폭 연속 1~2일 +3.292% / 승률 77.2%  (9,544건)
#       고저폭 연속 3~4일 +4.178% / 승률 80.5%  (1,904건)
#       고저폭 연속 5일↑  +4.343% / 승률 81.4%  (1,370건)
#     = 고저폭 안이 밖보다 3.5배. 이유는 익일 고저폭 자체가 5.87% → 14.06% 로
#       2.4배 크고, 다음날에도 10%↑ 로 움직일 확률이 12.5% → 72.0% 라서다.
#   ⚠️같은 자료에서 "시가 매수 → 당일 종가"(S01 급상승 근사)는 고저폭을 붙이면
#     오히려 나빠진다(-0.75% → -1.47%). 저점에서 사는 전략에만 유효한 제한이다.
#   안전장치: 두 후보 소스가 모두 비면 전건 차단한다(fail-closed).
#   기존 환경변수 이름은 호환을 위해 유지한다.
#   롤백: setx S02_HIGH_RANGE_ONLY NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260731_hronly.py 복원
HIGH_RANGE_ONLY = os.environ.get("S02_HIGH_RANGE_ONLY", "YES").strip().upper() == "YES"


def _select_candidate_codes(
    watch: Mapping[str, Any],
    candidate_meta: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """고저폭·돈흐름 선별판 합집합을 최대 50개로 제한한다."""
    source_tags = watch.get("source_tags") or {}
    high_range_codes = {
        code for code, meta in candidate_meta.items()
        if meta.get("hr_rank") is not None
    }
    money_flow_codes = {
        str(code).zfill(6)
        for code, tags in source_tags.items()
        if "moneyflow_selector" in set(tags or [])
    }

    def money_score(code: str) -> float:
        meta = candidate_meta.get(code) or {}
        return sum(max(0.0, _number(meta.get(key))) for key in (
            "mf_inst", "mf_frgn", "mf_prog",
        ))

    def high_rank(code: str) -> int:
        rank = _number((candidate_meta.get(code) or {}).get("hr_rank"), 9999)
        return int(rank) if rank > 0 else 9999

    overlap = high_range_codes & money_flow_codes
    high_only = high_range_codes - overlap
    money_only = money_flow_codes - overlap
    ordered = (
        sorted(overlap, key=lambda code: (high_rank(code), -money_score(code), code))
        + sorted(high_only, key=lambda code: (high_rank(code), code))
        + sorted(money_only, key=lambda code: (-money_score(code), code))
    )
    return ordered[:S02_CANDIDATE_LIMIT]

# ★[ADAPTIVE-BOTTOM 2026-08-20 사용자 상시 승인]
# FAST: 강세장 + 직접반등 + 시장대비 약세비율<=0.25 + 저점대비<=1.5%.
# RETEST: 계단식 재확인 + 저점대비<=2.0%; 약장에서는 관찰>=300초.
# 차단 신호는 emission_count/anchor 를 쓰지 않고 WAIT 로 남아 다음 저점을 계속 본다.
ADAPTIVE_BOTTOM_ENABLED = (
    # [UNVERIFIED 2026-08-20] 생산재생 4개 중 1개만 재현되어 기본 OFF 유지.
    # 정확한 저장입력으로 PROD_REPLAY PASS 후 승인된 실전 런처에서만 YES로 켠다.
    os.environ.get("S02_ADAPTIVE_BOTTOM_ENABLED", "NO").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)
ADAPTIVE_FAST_MAX_WEAKNESS_RATIO = 0.25
ADAPTIVE_FAST_MAX_ENTRY_GAP_PCT = 1.5
ADAPTIVE_RETEST_MAX_ENTRY_GAP_PCT = 2.0
ADAPTIVE_WEAK_MIN_OBSERVE_SEC = 300.0

# ★[DAY-LOW-CAP 2026-08-25 친구님 승인 "고점매수만 차단"]
#   당일 저점 대비 매수 상한(%). 저점매수 조건은 건드리지 않고 고점 추격만 막는다.
#   롤백: setx S02_DAY_LOW_MAX_GAP_PCT 999 (사실상 해제) 후 신호기 재시작
try:
    DAY_LOW_MAX_GAP_PCT = float(
        os.environ.get("S02_DAY_LOW_MAX_GAP_PCT", "2.0"))
except (TypeError, ValueError):
    DAY_LOW_MAX_GAP_PCT = 2.0


def _adaptive_regime_group(band: str) -> str:
    normalized = str(band or "").strip().upper()
    if normalized in {"BULL", "LEAN_BULL", "LEAN_BULL_US"}:
        return "STRONG"
    if normalized in {"BEAR", "LEAN_BEAR", "LEAN_BEAR_US"}:
        return "WEAK"
    if normalized in {"FLAT", "GRAY"}:
        return "NORMAL"
    return "UNKNOWN"


def adaptive_bottom_decision(
    *,
    algorithm: str,
    entry_gap_pct: float,
    anchor_low: float,
    open_price: float,
    avg_5d_range_pct: float,
    regime_band: str,
    u201_pct: float | None,
    observe_sec: float,
) -> Dict[str, Any]:
    group = _adaptive_regime_group(regime_band)
    low_from_open = (
        (anchor_low / open_price - 1.0) * 100.0
        if anchor_low > 0 and open_price > 0 else None
    )
    relative_low = (
        low_from_open - u201_pct
        if low_from_open is not None and u201_pct is not None else None
    )
    weakness = (
        abs(min(0.0, relative_low)) / avg_5d_range_pct
        if relative_low is not None and avg_5d_range_pct > 0 else None
    )
    direct = "DIRECT_REBOUND" in str(algorithm or "")
    staircase = "STAIRCASE_RETEST" in str(algorithm or "")
    fast = bool(
        group == "STRONG" and direct and weakness is not None
        and weakness <= ADAPTIVE_FAST_MAX_WEAKNESS_RATIO
        and entry_gap_pct <= ADAPTIVE_FAST_MAX_ENTRY_GAP_PCT
    )
    retest = bool(
        group != "UNKNOWN" and staircase
        and entry_gap_pct <= ADAPTIVE_RETEST_MAX_ENTRY_GAP_PCT
        and (group != "WEAK" or observe_sec >= ADAPTIVE_WEAK_MIN_OBSERVE_SEC)
    )
    lane = "FAST" if fast else ("RETEST" if retest else "BLOCK")
    reason = (
        f"ADAPTIVE_{lane}" if lane != "BLOCK"
        else "ADAPTIVE_REGIME_MISSING" if group == "UNKNOWN"
        else "ADAPTIVE_BOTTOM_BLOCK"
    )
    return {
        "adaptive_pass": lane != "BLOCK",
        "adaptive_lane": lane,
        "adaptive_reason": reason,
        "adaptive_regime": str(regime_band or "UNKNOWN"),
        "adaptive_regime_group": group,
        "adaptive_u201_pct": u201_pct,
        "adaptive_low_from_open_pct": (
            round(low_from_open, 4) if low_from_open is not None else None
        ),
        "adaptive_relative_weakness_ratio": (
            round(weakness, 4) if weakness is not None else None
        ),
        "adaptive_avg_5d_range_pct": avg_5d_range_pct,
        "adaptive_observe_sec": observe_sec,
    }


@dataclass(frozen=True)
class SignalConfig:
    watch_path: Path = Path(os.environ.get(
        "S02_WATCH", r"C:\stock_bot\IPC\micro_watch_strategy_shared.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S02_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    minute_path: Path = Path(os.environ.get(
        "S02_MINUTE_PATH", str(Path(r"C:\stock_bot\data") / "돈맥_1분봉.json")))
    names_path: Path = Path(os.environ.get(
        "S02_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S02_OUTPUT", r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json"))
    event_dir: Path = Path(os.environ.get(
        "S02_EVENT_DIR", r"C:\stock_bot\data\strategy_02_signal_v1"))
    regime_path: Path = Path(os.environ.get(
        "S02_REGIME_PATH", r"C:\stock_bot\data\BACKTEST\regime_std_shadow.csv"))
    adaptive_bottom_enabled: bool = ADAPTIVE_BOTTOM_ENABLED
    exact_replay_dir: Path = Path(os.environ.get(
        "S02_EXACT_REPLAY_DIR", r"C:\stock_bot\data\s02_exact_replay"))
    exact_replay_journal_enabled: bool = (
        os.environ.get("S02_EXACT_REPLAY_JOURNAL", "NO").strip().upper()
        in {"YES", "Y", "1", "TRUE", "ON"}
    )
    exact_replay_max_bytes: int = int(os.environ.get(
        "S02_EXACT_REPLAY_MAX_BYTES", str(200 * 1024 * 1024)))
    loop_sec: float = float(os.environ.get("S02_LOOP_SEC", "1"))
    max_snapshot_age_sec: float = float(os.environ.get("S02_SNAPSHOT_MAX_AGE", "4"))
    max_signals_per_code: int = int(os.environ.get("S02_MAX_CYCLES_PER_CODE", "2"))
    min_price: float = float(os.environ.get("S02_MIN_PRICE", "10000"))
    confirm_sec: float = float(os.environ.get("S02_CONFIRM_SEC", "2"))
    confirm_points: int = int(os.environ.get("S02_CONFIRM_POINTS", "3"))
    max_spread_bps: float = float(os.environ.get("S02_MAX_SPREAD_BPS", "30"))
    min_microprice_edge_bps: float = float(os.environ.get(
        "S02_MIN_MICROPRICE_EDGE_BPS", "0"))
    min_best_bid_share: float = float(os.environ.get(
        "S02_MIN_BEST_BID_SHARE", "0.50"))
    max_confirm_chase_bps: float = float(os.environ.get(
        "S02_MAX_CONFIRM_CHASE_BPS", "25"))
    max_entry_gap_pct: float = float(os.environ.get(
        "S02_MAX_ENTRY_GAP_PCT", "1.50"))

    def __post_init__(self) -> None:
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 02 requires exactly two opportunities per code")


@dataclass
class CodeState:
    points: Deque[MarketPoint] = field(default_factory=lambda: deque(maxlen=360))
    emission_count: int = 0
    emitted_anchors: set[str] = field(default_factory=set)
    pending_anchor_id: str = ""
    pending_since: datetime | None = None
    pending_signal_price: float = 0.0
    pending_hits: int = 0
    last_signal_low: float = 0.0
    last_signal_high: float = 0.0
    six_phase: str = "IDLE"
    six_episode_high: float = 0.0
    six_low: float = 0.0
    six_low_ts: datetime | None = None
    six_low_buy_money: float = 0.0
    six_low_sell_money: float = 0.0
    six_low_buy_vol: float = -1.0
    six_low_sell_vol: float = -1.0
    six_low_che_str: float = 0.0
    six_pre_buy_rate: float = -1.0
    six_pre_sell_rate: float = -1.0
    six_reset_steps: int = 0
    six_dead_low: float = 0.0
    six_observe_since: datetime | None = None
    six_first_rebound_peak: float = 0.0
    six_pullback_seen: bool = False
    six_pullback_low: float = 0.0
    six_micro_confirm_hits: int = 0
    six_micro_last_confirm_ts: datetime | None = None
    # ★[DIRECT-REBOUND 2026-08-13] 공통 직접반등 레인의 연속 확인 상태.
    direct_confirm_hits: int = 0
    direct_last_confirm_ts: datetime | None = None
    # ★[수정1] ready 전환 시 1회만 기록하기 위한 깃발(로그 폭증 방지).
    direct_ready_logged: bool = False
    open_price: float = 0.0
    session_high: float = 0.0
    # ★[DAY-LOW 2026-08-05] 정규장 진짜 저점(리셋 없음). 기록 전용 — 판정 미사용.
    session_low: float = 0.0
    session_low_ts: datetime | None = None
    six_reference_price: float = 0.0
    six_reference_mode: str = ""
    handoff_to_s03_s06: bool = False
    surge_phase: str = "IDLE"
    surge_high: float = 0.0
    surge_low: float = 0.0
    surge_high_ts: datetime | None = None
    surge_low_ts: datetime | None = None
    surge_low_che_str: float = 0.0
    surge_drop_steps: int = 0
    surge_confirm_hits: int = 0
    surge_last_confirm_ts: datetime | None = None
    flow_book_shadow_emission_count: int = 0
    flow_book_shadow_emitted_anchors: set[str] = field(default_factory=set)
    flow_book_shadow_pending_anchor_id: str = ""
    flow_book_shadow_pending_since: datetime | None = None
    flow_book_shadow_pending_price: float = 0.0
    flow_book_shadow_pending_hits: int = 0


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        first = path.read_bytes()
        time_module.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


_REGIME_CACHE: Dict[str, Any] = {"mtime_ns": None, "rows": []}


def _market_regime_at(path: Path, now: datetime) -> tuple[str, float | None]:
    """장세 그림자의 당일 최신 확정행을 읽는다. 자료가 없으면 UNKNOWN으로 차단한다."""
    try:
        mtime_ns = path.stat().st_mtime_ns
        if _REGIME_CACHE["mtime_ns"] != mtime_ns:
            rows = []
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    try:
                        ts = datetime.fromisoformat(str(raw.get("ts") or ""))
                    except ValueError:
                        continue
                    rows.append((
                        ts,
                        str(raw.get("band_us") or raw.get("band") or "UNKNOWN"),
                        _number(raw.get("u201_chg"), None),
                    ))
            _REGIME_CACHE["mtime_ns"] = mtime_ns
            _REGIME_CACHE["rows"] = rows
    except OSError:
        return "UNKNOWN", None
    prior = [
        row for row in _REGIME_CACHE["rows"]
        if row[0].date() == now.date() and row[0] <= now
    ]
    if not prior:
        return "UNKNOWN", None
    _, band, u201 = prior[-1]
    return band, u201


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _required_drop_pct(ts: datetime) -> float:
    return (
        MORNING_DIP_DROP_PCT
        if ts.time() < MORNING_OPEN_REFERENCE_END
        else INTRADAY_DIP_DROP_PCT
    )


def _effective_required_drop_pct(ts: datetime, adaptive_enabled: bool) -> float:
    """Adaptive mode tracks every anchor low; legacy mode keeps fixed depth."""
    return 0.0 if adaptive_enabled else _required_drop_pct(ts)


def _parse_dt(value: Any, now: datetime) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_time = datetime.strptime(text[:8], "%H:%M:%S").time()
            parsed = datetime.combine(now.date(), parsed_time)
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)
    return parsed


def _afternoon_buy_speed_lead(points: list[MarketPoint]) -> bool:
    """그림자 AFT5F와 동일한 최근 10초 매수대금 속도 우위."""
    if len(points) < 2:
        return False
    end = points[-1]

    def rate(window_sec: float, field: str) -> float:
        target = end.ts.timestamp() - window_sec
        start = next(
            (row for row in points if row.ts.timestamp() >= target), end)
        span = max(1.0, (end.ts - start.ts).total_seconds())
        return max(0.0, getattr(end, field) - getattr(start, field)) / span

    buy30 = rate(30.0, "buy_money_cum")
    sell30 = rate(30.0, "sell_money_cum")
    if not (buy30 > 0 and sell30 > 0):
        return False
    buy10 = rate(10.0, "buy_money_cum")
    sell10 = rate(10.0, "sell_money_cum")
    return buy10 > sell10


def _s02_book_recovery_ready(points: list[MarketPoint]) -> bool:
    """Delay only severe sell-book signals until two consecutive improvements."""
    values = []
    for point in points[-3:]:
        total = point.bid_tot + point.ask_tot
        if total <= 0:
            return False
        values.append((point.bid_tot - point.ask_tot) / total)
    if not values:
        return False
    current = values[-1]
    if current >= S02_BOOK_RECOVERY_LEVEL:
        return True
    if current > S02_SEVERE_BOOK_IMBALANCE:
        return True
    return len(values) == 3 and values[0] < values[1] < values[2]


def _name_map(payload: Mapping[str, Any]) -> Dict[str, str]:
    raw = payload.get("map", payload)
    return {str(code).zfill(6): str(name) for code, name in raw.items()}


def _minute_references(
    payload: Mapping[str, Any], today: str,
) -> Dict[str, Dict[str, float]]:
    if str(payload.get("ts") or "").replace("-", "")[:8] != today:
        return {}
    output: Dict[str, Dict[str, float]] = {}
    for code, raw in (payload.get("m") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        open_price = _number(raw.get("op"))
        highs = [open_price, _number(raw.get("h"))]
        for bar in raw.get("prev") or []:
            if isinstance(bar, (list, tuple)) and len(bar) >= 2:
                highs.append(_number(bar[1]))
        session_high = max((value for value in highs if value > 0), default=0.0)
        if open_price > 0 or session_high > 0:
            output[str(code).zfill(6)] = {
                "open": open_price,
                "high": session_high,
            }
    return output

def load_live_points(
    config: SignalConfig,
    now: datetime,
) -> tuple[list[tuple[str, str, MarketPoint]], str, int, Dict[str, Dict[str, Any]]]:
    watch = _read_json(config.watch_path)
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "").replace("-", "")[:8] != today:
        return [], "WATCH_DATE_MISMATCH", 0, {}
    codes = {str(code).zfill(6) for code in (watch.get("codes") or [])}
    if not codes:
        return [], "WATCH_EMPTY", 0, {}
    range_meta: Dict[str, Dict[str, Any]] = {}
    for meta_code, meta in (watch.get("all_meta") or {}).items():
        if not isinstance(meta, Mapping):
            continue
        picked = {
            key: meta[key]
            for key in RANGE_KEYS + MONEY_FLOW_KEYS
            if meta.get(key) is not None
        }
        if picked:
            prev_close = _number(meta.get("prev_close"))
            if prev_close > 0:
                picked["hr_prev_close"] = prev_close
            range_meta[str(meta_code).zfill(6)] = picked
    if HIGH_RANGE_ONLY:
        selected_codes = _select_candidate_codes(watch, range_meta)
        if not selected_codes:
            return [], "CANDIDATE_META_MISSING", len(codes), {}
        codes = set(selected_codes)
    snapshot = _read_json(config.snapshot_path)
    names = _name_map(_read_json(config.names_path))
    output: list[tuple[str, str, MarketPoint]] = []
    for code, raw in (snapshot.get("codes") or {}).items():
        code = str(code).zfill(6)
        if code not in codes or not isinstance(raw, Mapping):
            continue
        # ★[S02-DATA-FAIL-CLOSED 2026-08-27 사용자 승인]
        # 고저폭·돈흐름 선별판 합집합에서 우선순위 상위 50개만 관찰한다.
        if HIGH_RANGE_ONLY and code not in codes:
            continue
        # S01/S03의 신호만으로 S02 관찰을 중단하지 않는다. 실제 중복 주문은
        # 엔진의 계좌 보유·미체결·공용 슬롯 검사에서 주문 직전에 차단한다.
        ts = _parse_dt(raw.get("ts"), now)
        ob_ts = _parse_dt(raw.get("ob_ts"), now)
        if ts is None or ob_ts is None:
            continue
        if not (
            -2 <= (now - ts).total_seconds() <= config.max_snapshot_age_sec
            and -2 <= (now - ob_ts).total_seconds() <= config.max_snapshot_age_sec
        ):
            continue
        price = abs(_number(raw.get("cur")))
        ask_tot = abs(_number(raw.get("ask_tot")))
        bid_tot = abs(_number(raw.get("bid_tot")))
        best_ask = abs(_number(raw.get("best_ask_px")))
        best_bid = abs(_number(raw.get("best_bid_px")))
        best_ask_qty = abs(_number(raw.get("best_ask_qty")))
        best_bid_qty = abs(_number(raw.get("best_bid_qty")))
        buy_cum = _number(raw.get("buy_money_cum"), -1)
        sell_cum = _number(raw.get("sell_money_cum"), -1)
        if (
            price < config.min_price
            or ask_tot <= 0
            or bid_tot <= 0
            or not best_ask > best_bid > 0
            or best_ask_qty <= 0
            or best_bid_qty <= 0
            or buy_cum < 0
            or sell_cum < 0
        ):
            continue
        output.append((code, names.get(code, code), MarketPoint(
            ts=ts,
            price=price,
            cum_vol=abs(_number(raw.get("cum_vol"))),
            che_str=abs(_number(raw.get("che_str"))),
            ask_tot=ask_tot,
            bid_tot=bid_tot,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            buy_vol_cum=_number(raw.get("buy_vol_cum"), -1),
            sell_vol_cum=_number(raw.get("sell_vol_cum"), -1),
            best_ask_px=best_ask,
            best_bid_px=best_bid,
            best_ask_qty=best_ask_qty,
            best_bid_qty=best_bid_qty,
            # ★[DAY-LOW 2026-08-05] 거래소 당일 저가/고가. 없으면 0(=자체 추적으로 폴백).
            broker_day_low=abs(_number(raw.get("lo"))),
            broker_day_high=abs(_number(raw.get("hi"))),
        )))
    return output, ("LIVE" if output else "DATA_WAIT"), len(codes), range_meta


class LowBuySignalMonitor:
    def __init__(
        self,
        *,
        max_signals_per_code: int = 2,
        confirm_sec: float = 2.0,
        confirm_points: int = 3,
        max_spread_bps: float = 30.0,
        min_microprice_edge_bps: float = 0.0,
        min_best_bid_share: float = 0.50,
        max_confirm_chase_bps: float = 25.0,
        max_entry_gap_pct: float = 1.50,
        adaptive_bottom_enabled: bool = False,
    ) -> None:
        if max_signals_per_code != 2:
            raise ValueError("Strategy 02 requires exactly two opportunities per code")
        self.max_signals_per_code = max_signals_per_code
        self.confirm_sec = max(0.0, float(confirm_sec))
        self.confirm_points = max(2, int(confirm_points))
        self.max_spread_bps = float(max_spread_bps)
        self.min_microprice_edge_bps = float(min_microprice_edge_bps)
        self.min_best_bid_share = float(min_best_bid_share)
        self.max_confirm_chase_bps = float(max_confirm_chase_bps)
        self.max_entry_gap_pct = float(max_entry_gap_pct)
        self.adaptive_bottom_enabled = bool(adaptive_bottom_enabled)
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []
        self.flow_book_shadow_latest: Dict[str, Dict[str, Any]] = {}
        self.flow_book_shadow_signals: list[Dict[str, Any]] = []
        self._pending_flow_book_shadow_signals: list[Dict[str, Any]] = []

    @staticmethod
    def _clear_pending(state: CodeState) -> None:
        state.pending_anchor_id = ""
        state.pending_since = None
        state.pending_signal_price = 0.0
        state.pending_hits = 0

    def _book_telemetry(
        self, point: MarketPoint,
    ) -> tuple[bool, str, float, float, float]:
        ask = float(point.best_ask_px)
        bid = float(point.best_bid_px)
        ask_qty = float(point.best_ask_qty)
        bid_qty = float(point.best_bid_qty)
        if not (ask > bid > 0 and ask_qty > 0 and bid_qty > 0):
            return False, "EXACT_TOPBOOK_REQUIRED", 0.0, 0.0, 0.0
        midpoint = (ask + bid) / 2.0
        spread_bps = (ask - bid) / midpoint * 10_000.0
        microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
        edge_bps = (microprice - midpoint) / midpoint * 10_000.0
        best_bid_share = bid_qty / (bid_qty + ask_qty)
        if spread_bps > self.max_spread_bps:
            return False, "SPREAD_TOO_WIDE", spread_bps, edge_bps, best_bid_share
        if edge_bps < self.min_microprice_edge_bps:
            return False, "MICROPRICE_NOT_RECOVERED", spread_bps, edge_bps, best_bid_share
        if best_bid_share < self.min_best_bid_share:
            return False, "BEST_BID_NOT_DOMINANT", spread_bps, edge_bps, best_bid_share
        return True, "PASS", spread_bps, edge_bps, best_bid_share

    def restore(self, payload: Mapping[str, Any], today: str) -> None:
        if str(payload.get("schema") or "") != SIGNAL_SCHEMA:
            return
        if str(payload.get("date") or "") != today:
            return
        for raw in payload.get("signals") or []:
            code = str(raw.get("code") or "").zfill(6)
            if not code:
                continue
            row = dict(raw)
            state = self.states.setdefault(code, CodeState())
            state.emission_count = max(
                state.emission_count, int(row.get("signal_sequence") or 0))
            anchor = str(row.get("anchor_id") or "")
            if anchor:
                state.emitted_anchors.add(anchor)
            low_val = _number(row.get("anchor_low"))
            if low_val > 0:
                state.last_signal_low = low_val
            high_val = _number(row.get("dip_episode_high"))
            if high_val > 0:
                state.last_signal_high = high_val
            self.signals.append(row)
        for raw in payload.get("flow_book_shadow_signals") or []:
            code = str(raw.get("code") or "").zfill(6)
            if not code:
                continue
            row = dict(raw)
            state = self.states.setdefault(code, CodeState())
            state.flow_book_shadow_emission_count = max(
                state.flow_book_shadow_emission_count,
                int(row.get("shadow_signal_sequence") or 0),
            )
            anchor = str(row.get("anchor_id") or "")
            if anchor:
                state.flow_book_shadow_emitted_anchors.add(anchor)
            self.flow_book_shadow_signals.append(row)

    @staticmethod
    def _six_flow_flip(state: CodeState, point: MarketPoint) -> str:
        """저점 전후로 매수·매도 '대금 속도'가 역전됐는가.

        ★[2026-08-06] 종전엔 이 계산이 판정 한복판에 인라인으로 있었다. 아침 급행이
          같은 판정을 앞당겨 써야 해서 한 군데로 뽑았다 — 두 벌로 갈라지면 안 된다.
        반환: "O"(역전) · "X"(역전 아님) · ""(잴 자료가 없음)
        ⚠️절대 체결강도는 쓰지 않는다. 저점 전 매도 우위 -> 저점 후 매수 우위만 본다.
        """
        if state.six_low_ts is None:
            return ""
        flow_elapsed = max(1.0, (point.ts - state.six_low_ts).total_seconds())
        post_buy = max(0.0, point.buy_money_cum - state.six_low_buy_money) / flow_elapsed
        post_sell = max(0.0, point.sell_money_cum - state.six_low_sell_money) / flow_elapsed
        if not (
            state.six_pre_buy_rate >= 0
            and state.six_pre_sell_rate >= 0
            and (state.six_pre_buy_rate + state.six_pre_sell_rate) > 0
            and (post_buy + post_sell) > 0
        ):
            return ""
        return "O" if (
            state.six_pre_sell_rate > state.six_pre_buy_rate
            and post_buy > post_sell
        ) else "X"

    @classmethod
    def _six_flow_flipped(cls, state: CodeState, point: MarketPoint) -> bool:
        return cls._six_flow_flip(state, point) == "O"

    @staticmethod
    def _clear_six_retest(state: CodeState) -> None:
        state.six_observe_since = None
        state.six_first_rebound_peak = 0.0
        state.six_pullback_seen = False
        state.six_pullback_low = 0.0
        state.six_micro_confirm_hits = 0
        state.six_micro_last_confirm_ts = None

    @staticmethod
    def _reset_money_surge(state: CodeState) -> None:
        state.surge_phase = "IDLE"
        state.surge_high = 0.0
        state.surge_low = 0.0
        state.surge_high_ts = None
        state.surge_low_ts = None
        state.surge_low_che_str = 0.0
        state.surge_drop_steps = 0
        state.surge_confirm_hits = 0
        state.surge_last_confirm_ts = None

    @staticmethod
    def _surge_window_rates(
        points: list[MarketPoint],
    ) -> tuple[float, float, float, float, float, float, float] | None:
        if len(points) < 3:
            return None
        end = points[-1]
        end_epoch = end.ts.timestamp()
        recent_target = end_epoch - SURGE_RECENT_SEC
        previous_target = recent_target - SURGE_PREVIOUS_SEC

        def at_or_before(target: float) -> MarketPoint | None:
            for row in reversed(points):
                if row.ts.timestamp() <= target:
                    return row
            return None

        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        tolerance = max(2.0, SURGE_RECENT_SEC * 0.4)
        if recent_start is None or previous_start is None:
            return None
        if (
            recent_target - recent_start.ts.timestamp() > tolerance
            or previous_target - previous_start.ts.timestamp() > tolerance
        ):
            return None
        recent_span = (end.ts - recent_start.ts).total_seconds()
        previous_span = (recent_start.ts - previous_start.ts).total_seconds()
        if recent_span <= 0 or previous_span <= 0:
            return None
        deltas = (
            end.buy_money_cum - recent_start.buy_money_cum,
            end.sell_money_cum - recent_start.sell_money_cum,
            end.cum_vol - recent_start.cum_vol,
            recent_start.buy_money_cum - previous_start.buy_money_cum,
            recent_start.sell_money_cum - previous_start.sell_money_cum,
            recent_start.cum_vol - previous_start.cum_vol,
        )
        if min(deltas) < 0:
            return None
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / recent_span,
            deltas[3] / previous_span,
            deltas[4] / previous_span,
            deltas[5] / previous_span,
            recent_start.che_str,
        )

    @staticmethod
    def _relative_flow_turn(
        points: list[MarketPoint],
        recent_sec: float,
        previous_sec: float,
    ) -> dict[str, float | bool] | None:
        """절대 체결강도 없이 매도 우세가 약해지고 매수 우세로 바뀌는지 본다."""
        if len(points) < 3:
            return None
        end = points[-1]
        recent_target = end.ts.timestamp() - recent_sec
        previous_target = recent_target - previous_sec

        def at_or_before(target: float) -> MarketPoint | None:
            return next(
                (row for row in reversed(points) if row.ts.timestamp() <= target),
                None,
            )

        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        if recent_start is None or previous_start is None:
            return None
        if (
            recent_target - recent_start.ts.timestamp() > max(2.0, recent_sec * 0.4)
            or previous_target - previous_start.ts.timestamp()
            > max(3.0, previous_sec * 0.4)
        ):
            return None
        recent_span = (end.ts - recent_start.ts).total_seconds()
        previous_span = (recent_start.ts - previous_start.ts).total_seconds()
        if recent_span <= 0 or previous_span <= 0:
            return None
        raw = (
            end.buy_money_cum - recent_start.buy_money_cum,
            end.sell_money_cum - recent_start.sell_money_cum,
            recent_start.buy_money_cum - previous_start.buy_money_cum,
            recent_start.sell_money_cum - previous_start.sell_money_cum,
            end.buy_vol_cum - recent_start.buy_vol_cum,
            end.sell_vol_cum - recent_start.sell_vol_cum,
            recent_start.buy_vol_cum - previous_start.buy_vol_cum,
            recent_start.sell_vol_cum - previous_start.sell_vol_cum,
        )
        if min(raw) < 0:
            return None
        rbm, rsm, pbm, psm, rbv, rsv, pbv, psv = (
            raw[0] / recent_span,
            raw[1] / recent_span,
            raw[2] / previous_span,
            raw[3] / previous_span,
            raw[4] / recent_span,
            raw[5] / recent_span,
            raw[6] / previous_span,
            raw[7] / previous_span,
        )
        return {
            "recent_buy_money_rate": rbm,
            "recent_sell_money_rate": rsm,
            "previous_buy_money_rate": pbm,
            "previous_sell_money_rate": psm,
            "recent_buy_volume_rate": rbv,
            "recent_sell_volume_rate": rsv,
            "previous_buy_volume_rate": pbv,
            "previous_sell_volume_rate": psv,
            "money_buy_turn": rbm > rsm and rbm > pbm and rsm <= psm,
            "volume_buy_turn": rbv > rsv and rbv > pbv and rsv <= psv,
            "previous_money_sell_dominant": psm > pbm,
            "previous_volume_sell_dominant": psv > pbv,
            "prior_che_str": recent_start.che_str,
            "che_rising": end.che_str > recent_start.che_str,
        }

    def _detect_money_surge_onset(
        self, state: CodeState, points: list[MarketPoint],
    ) -> BottomSignal | None:
        if not MONEY_SURGE_ENABLED or not points:
            return None
        point = points[-1]
        if point.price <= 0:
            return None

        if state.surge_phase == "IDLE":
            required_drop_pct = _required_drop_pct(point.ts)
            cutoff = point.ts.timestamp() - SURGE_DROP_WINDOW_SEC
            window = [
                row for row in points
                if row.ts.timestamp() >= cutoff and row.price > 0
            ]
            if len(window) < SURGE_MIN_DOWN_STEPS + 1:
                return None
            high_idx = max(range(len(window)), key=lambda idx: window[idx].price)
            descent = window[high_idx:]
            if len(descent) < SURGE_MIN_DOWN_STEPS + 1:
                return None
            if point.price != min(row.price for row in descent):
                return None
            local_high = descent[0]
            local_drop_pct = (
                (local_high.price - point.price) / local_high.price * 100.0
            )
            reference_drop_pct = (
                (state.six_reference_price - point.price)
                / state.six_reference_price * 100.0
                if state.six_reference_price > 0 else 0.0
            )
            down_steps = sum(
                1 for before, after in zip(descent, descent[1:])
                if after.price < before.price
            )
            if (
                local_drop_pct < SURGE_MIN_DROP_PCT
                or reference_drop_pct < required_drop_pct
                or down_steps < SURGE_MIN_DOWN_STEPS
            ):
                return None
            state.surge_phase = "ARMED"
            state.surge_high = local_high.price
            state.surge_low = point.price
            state.surge_high_ts = local_high.ts
            state.surge_low_ts = point.ts
            state.surge_low_che_str = point.che_str
            state.surge_drop_steps = down_steps
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        if state.surge_low <= 0 or state.surge_low_ts is None:
            self._reset_money_surge(state)
            return None
        if point.price < state.surge_low:
            state.surge_low = point.price
            state.surge_low_ts = point.ts
            state.surge_low_che_str = point.che_str
            state.surge_drop_steps += 1
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        turn_sec = (point.ts - state.surge_low_ts).total_seconds()
        rebound_pct = (point.price / state.surge_low - 1.0) * 100.0
        if turn_sec > SURGE_TURN_MAX_SEC or rebound_pct > SURGE_REBOUND_MAX_PCT:
            self._reset_money_surge(state)
            return None
        if rebound_pct < SURGE_REBOUND_MIN_PCT:
            return None

        rates = self._surge_window_rates(points)
        relative = self._relative_flow_turn(
            points, SURGE_RECENT_SEC, SURGE_PREVIOUS_SEC)
        book_ok, _, _, _, _ = self._book_telemetry(point)
        if rates is None or relative is None or not book_ok:
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None
        (
            recent_buy, recent_sell, recent_volume,
            previous_buy, _previous_sell, previous_volume, _prior_che,
        ) = rates
        flow_ok = (
            bool(relative["previous_money_sell_dominant"])
            and bool(relative["previous_volume_sell_dominant"])
            and bool(relative["money_buy_turn"])
            and bool(relative["volume_buy_turn"])
            and bool(relative["che_rising"])
            and point.che_str > state.surge_low_che_str
        )
        if not flow_ok:
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        if (
            state.surge_last_confirm_ts is None
            or (point.ts - state.surge_last_confirm_ts).total_seconds()
            > SURGE_CONFIRM_MAX_GAP_SEC
        ):
            state.surge_confirm_hits = 1
        else:
            state.surge_confirm_hits += 1
        state.surge_last_confirm_ts = point.ts
        if state.surge_confirm_hits < SURGE_CONFIRM_TICKS:
            return None

        drop_pct = (
            (state.surge_high - state.surge_low) / state.surge_high * 100.0
        )
        self._last_dip_meta = {
            "dip_drop_pct": round(drop_pct, 4),
            "required_drop_pct": _required_drop_pct(point.ts),
            "dip_episode_high": state.surge_high,
            "dip_low_reset_steps": state.surge_drop_steps,
            "surge_turn_sec": round(turn_sec, 3),
            "surge_rebound_pct": round(rebound_pct, 4),
            "surge_recent_buy_rate_5s": round(recent_buy, 3),
            "surge_recent_sell_rate_5s": round(recent_sell, 3),
            "surge_previous_buy_rate": round(previous_buy, 3),
            "surge_recent_volume_rate_5s": round(recent_volume, 3),
            "surge_previous_volume_rate": round(previous_volume, 3),
            "surge_che_str": round(point.che_str, 3),
            "surge_low_che_str": round(state.surge_low_che_str, 3),
            "surge_recent_buy_volume_rate": round(
                float(relative["recent_buy_volume_rate"]), 3),
            "surge_recent_sell_volume_rate": round(
                float(relative["recent_sell_volume_rate"]), 3),
            "surge_flow_turn": "O",
            "surge_confirm_ticks": state.surge_confirm_hits,
        }
        return BottomSignal(
            algorithm="S02_MONEY_SURGE_ONSET_V1",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=state.surge_low_ts,
            anchor_low_price=state.surge_low,
            wave_count=state.surge_drop_steps + 1,
            reason=(
                f"MONEY_SURGE_ONSET drop={drop_pct:.2f}% "
                f"rebound={rebound_pct:.2f}%"
            ),
        )

    @classmethod
    def _reset_six_cycle(
        cls, state: CodeState, point: MarketPoint | None = None,
    ) -> None:
        state.six_phase = "IDLE"
        state.six_episode_high = point.price if point is not None else 0.0
        state.six_low = point.price if point is not None else 0.0
        state.six_low_ts = point.ts if point is not None else None
        state.six_low_buy_money = point.buy_money_cum if point is not None else 0.0
        state.six_low_sell_money = point.sell_money_cum if point is not None else 0.0
        state.six_low_buy_vol = point.buy_vol_cum if point is not None else -1.0
        state.six_low_sell_vol = point.sell_vol_cum if point is not None else -1.0
        state.six_low_che_str = point.che_str if point is not None else 0.0
        state.six_pre_buy_rate = -1.0
        state.six_pre_sell_rate = -1.0
        state.six_reset_steps = 0
        state.six_dead_low = 0.0
        cls._clear_six_retest(state)

    @staticmethod
    def _six_pre_rates(
        points: list[MarketPoint], low_ts: datetime,
    ) -> tuple[float, float]:
        rows = [
            row for row in points
            if row.ts <= low_ts and 0 <= (low_ts - row.ts).total_seconds() <= 180.0
        ]
        if len(rows) < 2:
            return -1.0, -1.0
        span = (rows[-1].ts - rows[0].ts).total_seconds()
        if span < 30.0:
            return -1.0, -1.0
        return (
            max(0.0, rows[-1].buy_money_cum - rows[0].buy_money_cum) / span,
            max(0.0, rows[-1].sell_money_cum - rows[0].sell_money_cum) / span,
        )

    @staticmethod
    def _six_flow_acceleration(
        points: list[MarketPoint],
    ) -> tuple[str, float, float, float, float]:
        if len(points) < 3:
            return "", 0.0, 0.0, 0.0, 0.0
        window = SIX_FLOW_ACCEL_WINDOW_SEC
        end = points[-1]
        tolerance = max(3.0, window * 0.4)

        def at_or_before(target: float) -> MarketPoint | None:
            for row in reversed(points):
                if row.ts.timestamp() <= target:
                    return row
            return None

        end_epoch = end.ts.timestamp()
        middle_target = end_epoch - window
        start_target = end_epoch - 2.0 * window
        middle = at_or_before(middle_target)
        start = at_or_before(start_target)
        if middle is None or start is None:
            return "", 0.0, 0.0, 0.0, 0.0
        if (
            middle_target - middle.ts.timestamp() > tolerance
            or start_target - start.ts.timestamp() > tolerance
        ):
            return "", 0.0, 0.0, 0.0, 0.0
        previous_span = (middle.ts - start.ts).total_seconds()
        recent_span = (end.ts - middle.ts).total_seconds()
        if min(previous_span, recent_span) < window * 0.6:
            return "", 0.0, 0.0, 0.0, 0.0
        previous_buy = max(
            0.0, middle.buy_money_cum - start.buy_money_cum) / previous_span
        previous_sell = max(
            0.0, middle.sell_money_cum - start.sell_money_cum) / previous_span
        recent_buy = max(
            0.0, end.buy_money_cum - middle.buy_money_cum) / recent_span
        recent_sell = max(
            0.0, end.sell_money_cum - middle.sell_money_cum) / recent_span
        passed = (
            recent_buy > previous_buy
            and recent_buy > recent_sell
            and recent_sell <= previous_sell
        )
        return (
            "O" if passed else "X",
            previous_buy, recent_buy, previous_sell, recent_sell,
        )

    def _detect_six_staircase(
        self, state: CodeState, points: list[MarketPoint],
    ) -> BottomSignal | None:
        self._last_dip_meta = {}
        if not points:
            return None
        point = points[-1]
        # 적응형 저점이 켜진 실전 경로에서는 종전의 아침 -3%/장중 -5%
        # 낙폭을 선행 하드게이트로 쓰지 않는다. 모든 새 anchor 저점을 추적한 뒤
        # FAST/RETEST 장세·수급·재확인 관문이 최종 진입을 결정한다.
        # 적응형을 끄면 기존 고정 낙폭 동작으로 즉시 복귀한다.
        # ★[DROP-GATE 복원 2026-08-25 친구님 "낙폭 문턴 복원 승인"]
        #   위 설명과 달리, 적응형이 켜져도 낙폭 게이트를 유지한다.
        #   8/25 356860: 장중고점 대비 -2.36% 뿐인데 FAST/RETEST 관문을 통과해
        #   당일 저가 +9.37% 자리에서 매수됐다. 대체 관문이 제 역할을 못했다.
        #   저점 추적(six_low 갱신)은 그대로 돌아간다 — 추격 시작만 막는다.
        #   롤백: 이 두 줄을 _effective_required_drop_pct(point.ts, self.adaptive_bottom_enabled) 로 되돌림
        required_drop_pct = _required_drop_pct(point.ts)
        if point.price <= 0:
            return None
        reference_price = state.six_reference_price
        if reference_price <= 0:
            return None
        if (
            state.six_episode_high <= 0
            or reference_price > state.six_episode_high
        ):
            self._reset_six_cycle(state, point)
        state.six_episode_high = reference_price

        if state.six_phase == "IDLE":
            if state.six_low <= 0 or point.price < state.six_low:
                state.six_low = point.price
                state.six_low_ts = point.ts
                state.six_low_buy_money = point.buy_money_cum
                state.six_low_sell_money = point.sell_money_cum
                state.six_low_buy_vol = point.buy_vol_cum
                state.six_low_sell_vol = point.sell_vol_cum
                state.six_low_che_str = point.che_str
            drop_pct = (
                (state.six_episode_high - state.six_low)
                / state.six_episode_high * 100.0
            )
            if drop_pct < required_drop_pct:
                return None
            state.six_phase = "CHASE"
            state.six_low_ts = point.ts
            state.six_low_buy_money = point.buy_money_cum
            state.six_low_sell_money = point.sell_money_cum
            state.six_low_buy_vol = point.buy_vol_cum
            state.six_low_sell_vol = point.sell_vol_cum
            state.six_low_che_str = point.che_str
            state.six_pre_buy_rate, state.six_pre_sell_rate = (
                self._six_pre_rates(points, point.ts)
            )
            return None

        if point.price < state.six_low:
            state.six_reset_steps += 1
            # ★[DIRECT-REBOUND 2026-08-13] 신저점 갱신 = 직접반등 확인 초기화.
            state.direct_confirm_hits = 0
            state.direct_last_confirm_ts = None
            state.six_low = point.price
            state.six_low_ts = point.ts
            state.six_low_buy_money = point.buy_money_cum
            state.six_low_sell_money = point.sell_money_cum
            state.six_low_buy_vol = point.buy_vol_cum
            state.six_low_sell_vol = point.sell_vol_cum
            state.six_low_che_str = point.che_str
            state.six_pre_buy_rate, state.six_pre_sell_rate = (
                self._six_pre_rates(points, point.ts)
            )
            state.six_phase = "CHASE"
            if state.six_dead_low <= 0 or point.price < state.six_dead_low:
                state.six_dead_low = 0.0
            self._clear_six_retest(state)
            return None

        if state.six_low <= 0 or state.six_low_ts is None:
            self._reset_six_cycle(state, point)
            return None
        if state.six_dead_low > 0 and state.six_low >= state.six_dead_low:
            return None

        rebound_floor = state.six_low * (1.0 + SIX_FIRST_REBOUND_PCT / 100.0)
        chase_ceiling = state.six_low * (1.0 + SIX_CHASE_CAP_PCT / 100.0)
        entry_floor = state.six_low * (1.0 + SIX_ENTRY_FLOOR_PCT / 100.0)
        higher_low_floor = state.six_low * (
            1.0 + SIX_HIGHER_LOW_BUFFER_PCT / 100.0)

        if state.six_phase == "CHASE":
            if point.price > chase_ceiling:
                state.six_dead_low = state.six_low
                return None
            if point.price >= rebound_floor:
                state.six_phase = "OBSERVE"
                state.six_observe_since = point.ts
                state.six_first_rebound_peak = point.price
                state.six_pullback_seen = False
                state.six_pullback_low = 0.0
            return None

        if state.six_observe_since is None or state.six_first_rebound_peak <= 0:
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None
        if point.price > chase_ceiling:
            state.six_dead_low = state.six_low
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None
        elapsed = (point.ts - state.six_observe_since).total_seconds()
        if elapsed > SIX_OBSERVE_MAX_SEC:
            state.six_dead_low = state.six_low
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None

        # ★[DIRECT-REBOUND 2026-08-13 친구님 지시 "눌림은 선택 경로"] 공통 직접반등 레인.
        #   판정 정책은 low_rebound_common_v1 한 곳(S06 동일). 수급 원시값은 S02 기존
        #   함수(흐름역전·가속·상대전환·체결강도)를 그대로 입력으로 넘긴다 — 복사 금지.
        #   기본 OFF(LOW_REBOUND_DIRECT 미설정): 판정만 하고 주문 신호는 내지 않는다.
        relative_direct = self._relative_flow_turn(
            points, SIX_FLOW_ACCEL_WINDOW_SEC, SIX_FLOW_ACCEL_WINDOW_SEC)
        accel_direct = self._six_flow_acceleration(points)
        direct_age_sec = (point.ts - state.six_low_ts).total_seconds()
        direct_age_route = _direct_rebound_age_route(direct_age_sec)
        direct = judge_direct_rebound(
            confirm_hits=state.direct_confirm_hits,
            last_confirm_ts=state.direct_last_confirm_ts,
            cfg=DirectReboundConfig(
                first_rebound_pct=SIX_FIRST_REBOUND_PCT,
                chase_cap_pct=SIX_CHASE_CAP_PCT,
                confirm_ticks=SURGE_CONFIRM_TICKS,
                confirm_max_gap_sec=SURGE_CONFIRM_MAX_GAP_SEC,
                min_no_new_low_sec=S02_DIRECT_MIN_NO_NEW_LOW_SEC,
            ),
            ts=point.ts,
            price=point.price,
            low_price=state.six_low,
            no_new_low_sec=direct_age_sec,
            drop_ok=True,  # OBSERVE 진입 자체가 전략별 낙폭 충족 이후다
            flow_flip=(self._six_flow_flip(state, point) == "O"),
            flow_accel=(
                (accel_direct[2] > accel_direct[1])
                if accel_direct and accel_direct[2] > 0 else None
            ),
            money_buy_turn=(
                bool(relative_direct["money_buy_turn"])
                if relative_direct is not None else None
            ),
            volume_buy_turn=(
                bool(relative_direct["volume_buy_turn"])
                if relative_direct is not None else None
            ),
            sell_restrength=(
                (accel_direct[4] > accel_direct[3])
                if accel_direct and accel_direct[2] > 0 else None
            ),
            che_rising=(
                (point.che_str > state.six_low_che_str)
                if state.six_low_che_str > 0 else None
            ),
        )
        if direct_age_route == "RETEST":
            direct["ready"] = False
            direct["allow"] = False
            direct["confirm_ticks"] = 0
            direct["last_confirm_ts"] = None
            direct["fail"] = list(direct["fail"]) + [
                "LOW_TOO_STALE_FOR_DIRECT"
            ]
        state.direct_confirm_hits = direct["confirm_ticks"]
        state.direct_last_confirm_ts = direct["last_confirm_ts"]
        # ★[수정1 2026-08-13] ready 전건 감사 — 게이트 OFF 여도 기록(주문만 금지).
        #   기존 통로 = 이 프로세스 stdout(예약 태스크가 sched 로그로 저장).
        #   ready 전환 시 1회만 남겨 로그 폭증을 막는다.
        if direct["ready"] and not state.direct_ready_logged:
            _audit = {k: direct[k] for k in (
                "lane", "ready", "armed", "allow", "fail", "low_price",
                "rebound_pct", "no_new_low_sec", "flow_flip", "flow_accel",
                "money_buy_turn", "volume_buy_turn", "che_rising",
                "confirm_ticks", "chase_cap_pass")}
            _audit["sell_restrength"] = (
                (accel_direct[4] > accel_direct[3])
                if accel_direct and accel_direct[2] > 0 else None)
            print(
                f"[{point.ts.strftime('%Y-%m-%d %H:%M:%S')}] S02_DIRECT_READY "
                f"code={getattr(self, '_detect_code', '')} {_audit}",
                flush=True,
            )
        state.direct_ready_logged = bool(direct["ready"])
        if direct["allow"]:
            drop_pct = (
                (state.six_episode_high - state.six_low)
                / state.six_episode_high * 100.0
            )
            self._last_dip_meta = {
                "entry_lane": direct["lane"],
                "dip_low_reset_steps": state.six_reset_steps,
                "dip_drop_pct": round(drop_pct, 3),
                "required_drop_pct": required_drop_pct,
                "dip_episode_high": round(state.six_episode_high, 4),
                "low_price": direct["low_price"],
                "rebound_pct": direct["rebound_pct"],
                "no_new_low_sec": direct["no_new_low_sec"],
                "dip_flow_flip": "O" if direct["flow_flip"] else "X",
                "flow_accel": "O" if direct["flow_accel"] else "X",
                "money_buy_turn": direct["money_buy_turn"],
                "volume_buy_turn": direct["volume_buy_turn"],
                "che_rising": direct["che_rising"],
                "low_confirm_ticks": direct["confirm_ticks"],
                "chase_cap_pass": direct["chase_cap_pass"],
            }
            return BottomSignal(
                algorithm="S02_S06_DIRECT_REBOUND_V1",
                signal_ts=point.ts,
                signal_price=point.price,
                anchor_low_ts=state.six_low_ts,
                anchor_low_price=state.six_low,
                wave_count=state.six_reset_steps + 1,
                reason=(
                    f"DIRECT_REBOUND drop={((state.six_episode_high - state.six_low) / state.six_episode_high * 100.0):.2f}% "
                    f"rebound={direct['rebound_pct']:.2f}%"
                ),
            )

        # ★[MORNING-FASTPATH 2026-08-06] 아침 창에서 '역전 + 1.0~1.5%' 면 더 안 기다린다.
        #   여기서 켜는 것은 '시간을 버는 조건'(60초·눌림·2차반등)뿐이다.
        #   아래 흐름 검증(flow_flip·가속·상대전환)은 그대로 다 통과해야 신호가 나간다.
        fastpath = False
        if (
            MORNING_FASTPATH
            and point.ts.time() < MORNING_FASTPATH_END
            and state.six_low > 0
        ):
            fast_rebound = (point.price / state.six_low - 1.0) * 100.0
            if (
                SIX_FIRST_REBOUND_PCT
                <= fast_rebound
                <= MORNING_FASTPATH_MAX_REBOUND_PCT
                and self._six_flow_flipped(state, point)
                # ★[수정2 2026-08-13] 급행도 공통 판정(allow)이 최종 권위 —
                #   공통이 WAIT/BLOCK 이면 급행 경로도 주문으로 가지 않는다.
                and direct["allow"]
            ):
                fastpath = True
                # 뒤의 눌림·2차반등 검사가 통과하도록 저점 자체를 눌림바닥으로 삼는다.
                # (값을 지어내는 것이 아니라 '눌림을 안 기다린다'를 이렇게 표현한다)
                state.six_pullback_seen = True
                state.six_pullback_low = state.six_low

        if not state.six_pullback_seen:
            state.six_first_rebound_peak = max(
                state.six_first_rebound_peak, point.price)
            pullback_trigger = state.six_first_rebound_peak * (
                1.0 - SIX_PULLBACK_MIN_PCT / 100.0)
            if point.price <= pullback_trigger:
                if point.price < higher_low_floor:
                    state.six_phase = "CHASE"
                    self._clear_six_retest(state)
                    return None
                state.six_pullback_seen = True
                state.six_pullback_low = point.price
        else:
            if point.price < higher_low_floor:
                state.six_phase = "CHASE"
                self._clear_six_retest(state)
                return None
            state.six_pullback_low = min(state.six_pullback_low, point.price)

        if elapsed < SIX_OBSERVE_SEC and not fastpath:
            return None
        if not state.six_pullback_seen or state.six_pullback_low <= 0:
            return None
        if point.price < state.six_pullback_low * (
            1.0 + SIX_SECOND_REBOUND_PCT / 100.0
        ):
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None
        if point.price < entry_floor or point.price > chase_ceiling:
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None

        flow_elapsed = max(1.0, (point.ts - state.six_low_ts).total_seconds())
        delta_buy = point.buy_money_cum - state.six_low_buy_money
        delta_sell = point.sell_money_cum - state.six_low_sell_money
        # ★[2026-08-06] 역전 판정은 _six_flow_flip 한 곳에서만 한다(아침 급행과 공유).
        flow_flip = self._six_flow_flip(state, point)
        acceleration = self._six_flow_acceleration(points)
        if flow_flip != "O" or acceleration[0] != "O":
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None
        # ★[저점리셋 관문 2026-08-07] 저점이 몇 번 깨졌는지를 본다.
        #   한두 번 깨진 저점은 아직 바닥이 아니다(8/7 재생: 리셋 3회 이하 4건 전원 이익 0).
        if state.six_reset_steps < MIN_LOW_RESET_STEPS:
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None

        # 절대 체결강도 기준은 쓰지 않는다. 저점 리셋 뒤 매도 체결량·대금 속도가
        # 약해지고 매수 체결량·대금 속도가 우세로 역전되는지만 확인한다.
        relative = self._relative_flow_turn(
            points, SIX_FLOW_ACCEL_WINDOW_SEC, SIX_FLOW_ACCEL_WINDOW_SEC)
        if relative is None:
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None
        micro_flow_ok = (
            bool(relative["money_buy_turn"])
            and bool(relative["volume_buy_turn"])
            and bool(relative["che_rising"])
            and point.che_str > state.six_low_che_str
        )
        if not micro_flow_ok:
            state.six_micro_confirm_hits = 0
            state.six_micro_last_confirm_ts = None
            return None
        if (
            state.six_micro_last_confirm_ts is None
            or (point.ts - state.six_micro_last_confirm_ts).total_seconds()
            > SURGE_CONFIRM_MAX_GAP_SEC
        ):
            state.six_micro_confirm_hits = 1
        else:
            state.six_micro_confirm_hits += 1
        state.six_micro_last_confirm_ts = point.ts
        if state.six_micro_confirm_hits < SURGE_CONFIRM_TICKS:
            return None

        drop_pct = (
            (state.six_episode_high - state.six_low)
            / state.six_episode_high * 100.0
        )
        rebound_pct = (point.price / state.six_low - 1.0) * 100.0
        self._last_dip_meta = {
            "dip_low_reset_steps": state.six_reset_steps,
            "dip_buy_money_since_low": round(delta_buy, 1),
            "dip_sell_money_since_low": round(delta_sell, 1),
            "dip_buy_sell_ratio": (
                round(delta_buy / delta_sell, 3) if delta_sell > 0 else None),
            "dip_flow_obs_sec": round(flow_elapsed, 1),
            "dip_drop_pct": round(drop_pct, 3),
            "required_drop_pct": required_drop_pct,
            "dip_episode_high": round(state.six_episode_high, 4),
            "dip_flow_flip": flow_flip,
            "flow_accel": acceleration[0],
            "previous_buy_rate_10s": round(acceleration[1], 1),
            "recent_buy_rate_10s": round(acceleration[2], 1),
            "previous_sell_rate_10s": round(acceleration[3], 1),
            "recent_sell_rate_10s": round(acceleration[4], 1),
            "low_confirm_recent_buy_money_rate": round(
                float(relative["recent_buy_money_rate"]), 1),
            "low_confirm_recent_sell_money_rate": round(
                float(relative["recent_sell_money_rate"]), 1),
            "low_confirm_recent_buy_volume_rate": round(
                float(relative["recent_buy_volume_rate"]), 1),
            "low_confirm_recent_sell_volume_rate": round(
                float(relative["recent_sell_volume_rate"]), 1),
            "low_confirm_previous_buy_volume_rate": round(
                float(relative["previous_buy_volume_rate"]), 1),
            "low_confirm_previous_sell_volume_rate": round(
                float(relative["previous_sell_volume_rate"]), 1),
            "low_confirm_low_che_str": round(state.six_low_che_str, 1),
            "low_confirm_che_str": round(point.che_str, 1),
            "low_confirm_flow_turn": "O",
            "low_confirm_ticks": state.six_micro_confirm_hits,
            "first_rebound_peak": state.six_first_rebound_peak,
            "pullback_low": state.six_pullback_low,
            "observe_sec": round(elapsed, 1),
        }
        return BottomSignal(
            algorithm="S02_S06_STAIRCASE_RETEST_V1",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=state.six_low_ts,
            anchor_low_price=state.six_low,
            wave_count=state.six_reset_steps + 1,
            reason=(
                f"S06_STAIRCASE drop={drop_pct:.2f}% "
                f"rebound={rebound_pct:.2f}%"
            ),
        )

    def _detect_dip_rebound(self, points):
        if SIX_STYLE:
            state = getattr(self, "_detect_state", None)
            if state is None:
                return None
            surge_signal = self._detect_money_surge_onset(state, points)
            if surge_signal is not None:
                return surge_signal
            return self._detect_six_staircase(state, points)
        """★[2026-07-31] 되돌림 판정 — 시간대별 기준만큼 밀린 뒤
        저점에서 DIP_REBOUND_PCT 회복하면 신호. 저점 +DIP_CHASE_CAP_PCT 를 넘으면
        추격이라 보고 신호를 내지 않는다. 부작용 없음(테스트용 분리).

        기존 detect_flow_book_exhaustion 과 반환 형식(BottomSignal)이 같아
        이후 흐름(호가 확인·확정 대기·anchor 중복 방지)은 그대로 작동한다."""
        self._last_dip_meta = {}
        if len(points) < 3:
            return None
        high = points[0].price
        low = points[0].price
        low_ts = points[0].ts
        low_idx = 0                          # ★저점 리셋 지점(매수/매도 배수 기준)
        steps = 0                            # ★계단 수 = 저점이 새로 갱신된 횟수
        armed = False
        for idx, p in enumerate(points):
            if p.price <= 0:
                continue
            if p.price > high:              # 새 고점 → 되돌림 계산을 다시 시작
                high = low = p.price
                low_ts = p.ts
                low_idx = idx
                steps = 0
                armed = False
                continue
            if p.price < low:
                low = p.price
                low_ts = p.ts
                low_idx = idx               # ★저점 리셋
                steps += 1
            if (
                high > 0
                and (high - low) / high * 100.0 >= _required_drop_pct(p.ts)
            ):
                armed = True
        if not armed or low <= 0:
            return None
        last = points[-1]
        rebound = (last.price / low - 1.0) * 100.0
        # ★[2026-07-31 친구님 지시 "저점 리셋 매수매도 배수 기록 붙여줘"]
        #   당일 누적 매수비율은 아침부터의 전체가 섞여 바닥 순간의 변화를 못 본다.
        #   저점을 찍은 그 순간의 누적을 기준으로 삼고 그 뒤 증가분만 비교한다
        #   (저점매수 매도기의 '꼭지 리셋'과 같은 원리를 매수에 적용).
        #   지금은 매수 판정에 쓰지 않고 기록만 한다 — 문턱을 정할 근거가 아직 없다.
        #   3거래일쯤 쌓이면 "배수가 높았던 건이 실제로 더 올랐나"를 보고 문턱을 정한다.
        #   steps = 계단 수(저점이 몇 번 더 낮아졌나) → 계단식 하락을 사후에 걸러낼 자료.
        d_buy = last.buy_money_cum - points[low_idx].buy_money_cum
        d_sell = last.sell_money_cum - points[low_idx].sell_money_cum
        self._last_dip_meta = {
            "dip_low_reset_steps": steps,
            "dip_buy_money_since_low": round(d_buy, 1),
            "dip_sell_money_since_low": round(d_sell, 1),
            "dip_buy_sell_ratio": (round(d_buy / d_sell, 3) if d_sell > 0 else None),
            "dip_flow_obs_sec": round((last.ts - points[low_idx].ts).total_seconds(), 1),
            "dip_drop_pct": round((high - low) / high * 100.0, 3),
            "dip_episode_high": round(high, 4),
        }
        # ★[2026-08-01 "6번과 동일하게"] ①관찰 60초 ②속도 역전 (상단 SIX_STYLE 주석)
        if SIX_STYLE:
            obs_sec = (last.ts - points[low_idx].ts).total_seconds()
            if obs_sec < SIX_OBSERVE_SEC:
                return None
            flip = ""
            pre = [p for p in points[:low_idx + 1]
                   if (points[low_idx].ts - p.ts).total_seconds() <= 180.0]
            if len(pre) >= 2:
                span = (pre[-1].ts - pre[0].ts).total_seconds()
                if span >= 30.0:
                    pre_b = max(0.0, pre[-1].buy_money_cum - pre[0].buy_money_cum) / span
                    pre_s = max(0.0, pre[-1].sell_money_cum - pre[0].sell_money_cum) / span
                    post_b = max(0.0, d_buy) / max(1.0, obs_sec)
                    post_s = max(0.0, d_sell) / max(1.0, obs_sec)
                    if (pre_b + pre_s) > 0 and (post_b + post_s) > 0:
                        flip = "O" if (pre_s > pre_b and post_b > post_s) else "X"
            self._last_dip_meta["dip_flow_flip"] = flip
            if flip == "X":
                return None
        if rebound < DIP_REBOUND_PCT or rebound > DIP_CHASE_CAP_PCT:
            return None
        return BottomSignal(
            algorithm="S02_DIP_REBOUND_V1",
            signal_ts=last.ts,
            signal_price=last.price,
            anchor_low_ts=low_ts,
            anchor_low_price=low,
            wave_count=1,
            reason=(f"DIP_REBOUND drop={(high - low) / high * 100.0:.2f}% "
                f"rebound={rebound:.2f}%"),
        )

    @staticmethod
    def _clear_flow_book_shadow_pending(state: CodeState) -> None:
        state.flow_book_shadow_pending_anchor_id = ""
        state.flow_book_shadow_pending_since = None
        state.flow_book_shadow_pending_price = 0.0
        state.flow_book_shadow_pending_hits = 0

    def drain_flow_book_shadow_signals(self) -> list[Dict[str, Any]]:
        rows = self._pending_flow_book_shadow_signals
        self._pending_flow_book_shadow_signals = []
        return rows

    def _track_flow_book_shadow(
        self,
        code: str,
        name: str,
        point: MarketPoint,
        state: CodeState,
        *,
        allow_signal: bool,
    ) -> None:
        if not FLOW_BOOK_SHADOW_ENABLED or not DIP_MODE:
            return
        row: Dict[str, Any] = {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "SHADOW_WAIT",
            "reason": "FLOW_BOOK_RECOVERY_WAIT",
            "price": point.price,
            "algorithm": "PRO_FLOW_BOOK_EXHAUSTION",
            "mode": "SHADOW_ORDER_ZERO",
            "provenance": "[HYPOTHETICAL]",
        }
        signal = detect_flow_book_exhaustion(list(state.points))
        if signal is None:
            self._clear_flow_book_shadow_pending(state)
            self.flow_book_shadow_latest[code] = row
            return
        if abs((point.ts - signal.signal_ts).total_seconds()) > 1:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = "STALE_DETECTOR_RESULT"
            self.flow_book_shadow_latest[code] = row
            return
        if point.ts.time() >= AFTERNOON_START:
            drop_pct = (
                (state.session_high - point.price) / state.session_high * 100.0
                if state.session_high > 0 else 0.0
            )
            if drop_pct < AFTERNOON_MIN_SIGNAL_DROP_PCT:
                self._clear_flow_book_shadow_pending(state)
                row["reason"] = "AFTERNOON_DROP_LT_5PCT"
                self.flow_book_shadow_latest[code] = row
                return
            if not _afternoon_buy_speed_lead(list(state.points)):
                self._clear_flow_book_shadow_pending(state)
                row["reason"] = "AFTERNOON_BUY_SPEED_NOT_LEADING"
                self.flow_book_shadow_latest[code] = row
                return
        book_ok, book_reason, spread_bps, edge_bps, best_bid_share = (
            self._book_telemetry(point)
        )
        row.update({
            "spread_bps": round(spread_bps, 4),
            "microprice_edge_bps": round(edge_bps, 4),
            "best_bid_share": round(best_bid_share, 4),
        })
        if not book_ok:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = book_reason
            self.flow_book_shadow_latest[code] = row
            return
        if not allow_signal:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = "ENTRY_TIME_CLOSED"
            self.flow_book_shadow_latest[code] = row
            return
        anchor_id = (
            f"{signal.anchor_low_ts.isoformat(timespec='seconds')}:"
            f"{signal.anchor_low_price:.4f}"
        )
        if anchor_id in state.flow_book_shadow_emitted_anchors:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = "SHADOW_ANCHOR_ALREADY_USED"
            self.flow_book_shadow_latest[code] = row
            return
        if state.flow_book_shadow_emission_count >= self.max_signals_per_code:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = "SHADOW_CYCLE_LIMIT"
            self.flow_book_shadow_latest[code] = row
            return
        if (
            state.flow_book_shadow_pending_anchor_id != anchor_id
            or state.flow_book_shadow_pending_since is None
        ):
            state.flow_book_shadow_pending_anchor_id = anchor_id
            state.flow_book_shadow_pending_since = point.ts
            state.flow_book_shadow_pending_price = point.price
            state.flow_book_shadow_pending_hits = 1
            row["reason"] = "SHADOW_ENTRY_CONFIRM_WAIT"
            self.flow_book_shadow_latest[code] = row
            return
        chase_bps = (
            (point.price / state.flow_book_shadow_pending_price - 1.0) * 10_000.0
            if state.flow_book_shadow_pending_price > 0 else 0.0
        )
        if chase_bps < 0 or chase_bps > self.max_confirm_chase_bps:
            state.flow_book_shadow_pending_since = point.ts
            state.flow_book_shadow_pending_price = point.price
            state.flow_book_shadow_pending_hits = 1
            row["reason"] = "SHADOW_ENTRY_CONFIRM_PRICE_RESET"
            self.flow_book_shadow_latest[code] = row
            return
        state.flow_book_shadow_pending_hits += 1
        confirm_age_sec = max(
            0.0,
            (point.ts - state.flow_book_shadow_pending_since).total_seconds(),
        )
        if (
            confirm_age_sec < self.confirm_sec
            or state.flow_book_shadow_pending_hits < self.confirm_points
        ):
            row["reason"] = "SHADOW_ENTRY_CONFIRM_WAIT"
            self.flow_book_shadow_latest[code] = row
            return
        entry_gap = (
            (point.price / signal.anchor_low_price - 1.0) * 100.0
            if signal.anchor_low_price > 0 else 999.0
        )
        if entry_gap > self.max_entry_gap_pct:
            self._clear_flow_book_shadow_pending(state)
            row["reason"] = "ENTRY_GAP_TOO_WIDE"
            self.flow_book_shadow_latest[code] = row
            return
        state.flow_book_shadow_emission_count += 1
        state.flow_book_shadow_emitted_anchors.add(anchor_id)
        row.update({
            "action": "SHADOW_READY",
            "reason": signal.reason,
            "anchor_low": signal.anchor_low_price,
            "anchor_low_ts": signal.anchor_low_ts.isoformat(timespec="seconds"),
            "anchor_id": anchor_id,
            "entry_gap_pct": round(entry_gap, 4),
            "confirm_age_sec": round(confirm_age_sec, 3),
            "confirm_points": state.flow_book_shadow_pending_hits,
            "wave_count": signal.wave_count,
            "shadow_signal_sequence": state.flow_book_shadow_emission_count,
        })
        emitted = dict(row)
        self.flow_book_shadow_signals.append(emitted)
        self._pending_flow_book_shadow_signals.append(emitted)
        self._clear_flow_book_shadow_pending(state)
        self.flow_book_shadow_latest[code] = row

    def process_point(
        self,
        code: str,
        name: str,
        point: MarketPoint,
        *,
        allow_signal: bool = True,
        open_price: float = 0.0,
        session_high: float = 0.0,
        regime_band: str = "UNKNOWN",
        u201_pct: float | None = None,
        avg_5d_range_pct: float = 0.0,
    ) -> tuple[Dict[str, Any], bool]:
        state = self.states.setdefault(code, CodeState())
        if open_price > 0:
            state.open_price = open_price
        # [S02-SESSION-HIGH-RECOVERY-V1]
        # Keep the accumulated, reference, live-trade and exchange day highs.
        # Ignore the exchange day-high field before the regular session.
        broker_high = (
            abs(getattr(point, "broker_day_high", 0.0) or 0.0)
            if point.ts.time() >= REGULAR_SESSION_START
            else 0.0
        )
        state.session_high = max(
            state.session_high, session_high, point.price, broker_high,
        )
        # ★[DAY-LOW 2026-08-05] 정규장 진짜 저점. 절대 리셋하지 않는다(anchor_low 와 다름).
        #   ①거래소가 주는 당일 저가(브로커 FID 18)를 최우선으로 쓴다 — 장중에
        #     신호기가 재기동해도 정확하다(자체 추적은 그 시점부터 다시 시작해 버린다).
        #   ②안 실려 오면 내가 본 틱으로 만든다(폴백).
        #   기록 전용이라 어떤 판정 분기에도 들어가지 않는다.
        if point.ts.time() >= REGULAR_SESSION_START and point.price > 0:
            broker_low = abs(getattr(point, "broker_day_low", 0.0) or 0.0)
            if broker_low > 0:
                if state.session_low <= 0 or broker_low < state.session_low:
                    state.session_low = broker_low
                    state.session_low_ts = point.ts
            elif state.session_low <= 0 or point.price < state.session_low:
                state.session_low = point.price
                state.session_low_ts = point.ts
        if state.points:
            last = state.points[-1]
            if point.ts <= last.ts:
                return self._wait_row(code, name, point, "DUPLICATE_SNAPSHOT"), False
            # ★[2026-07-30 친구님 지시] 관측창 리셋 문턱 10초 → 20초.
            #   증상: 7/27 이후 3거래일 신호 0건(회전엔진 로그 7/28·29·30 각 1줄=기동만).
            #   7/27은 매수 6건 + 신호 19건이 났다 → 매도소진 5개 조건은 통과 가능하다.
            #   바뀐 것은 조건이 아니라 들어오는 데이터. 7/28에 발견된 "전략 감시 종목이
            #   실시간 구독을 못 받는다(돈맥 195개가 상한 200 독점 → strategy 몫 0칸)"와 날짜가 맞다.
            #   실측(7/30 11:20): 스냅샷 1,477종목 중 66%가 6초↑, 38%가 5분↑ 낡음.
            #   그림자 3일치 대조(s02_window_shadow_2026072[8|9]·30):
            #     10초 = 리셋 하루 8천~2만회 / 창180초↑ 확보 평균 74.3%
            #     20초 = 리셋 1/3로 감소     / 창180초↑ 확보 평균 92.2%  (+17.9%p)
            #   ⚠ 근본 원인은 구독 슬롯 부족이다. 5분 이상 낡은 38%는 이 문턱으로 못 살린다.
            #   되돌리기: RUN\backup\strategy_02_low_buy_signal_v1_20260730_reset20s.py 복원(=10초 원본).
            # ★[2026-07-30 2차 지시] 20초 → 60초. 20초도 부족했다.
            #   실측(후보 175종목·40초 관측): 최대 갱신 간격 p50=8.2초·p90=22.6초.
            #   40초 안에 문턱 초과가 1번 이상 발생한 비율 = 6초 66.3% / 10초 40.0% /
            #   20초 13.1% / 30초 5.7% / 60초 0.0%.
            #   창 300초를 채우려면 약 150번 연속 공백이 없어야 한다 → 20초로는 거의 확실히 걸린다.
            #   60초가 안전한 이유: 실시간은 체결이 있을 때만 온다 → 공백 = 거래 없음 = 가격 불변.
            #   이 전략이 보는 종목은 micro_watch_strategy_shared(140)에 전부 포함돼 구독된다
            #   → "체결이 있었는데 놓친" 경우가 아니다. 누계 역전 조건은 그대로 남긴다(실측 0건).
            if (
                point.buy_money_cum < last.buy_money_cum
                or point.sell_money_cum < last.sell_money_cum
                or (point.ts - last.ts).total_seconds() > 60
            ):
                state.points.clear()
                if SIX_STYLE:
                    self._reset_six_cycle(state)
                    self._reset_money_surge(state)
        state.points.append(point)
        # ★[2026-07-30 친구님 지시] 관측창 300초(5분) → 1800초(30분).
        #   사유: 이 전략은 "늘어지는 하락의 매도 소진"을 잡는 설계인데, 매도 소진 판정은
        #   하락 파동 2개를 비교한다(previous_leg vs current_leg·약화 지표 2개 이상).
        #   창이 5분이면 각 파동이 2분 30초 이내여야 담긴다 → 실제로는 "5분 안에 두 번
        #   꺾이는 빠른 진동"만 포착했다. 설계 의도와 구현이 어긋나 있었다.
        #   실측 사례: 087010 펩트론이 09:30 136,800 → 09:56 129,000(26분에 -5.70%)로
        #   흘러내렸는데 파동 하나도 창에 못 담겨 FLOW_BOOK_RECOVERY_WAIT로 종일 대기.
        #   (이 종목은 급락이 아니라 늘어지는 하락이므로 전략03 소관이 아니라 이 전략 소관이다)
        #   ⚠ 부하: 루프당 순회가 약 3.6만 점 → 21만 점(6배). 재시작 직후 루프 속도로 검증한다.
        #     기준 = s02_window_shadow 의 loops/경과초. 재시작 전 0.979루프/초.
        #     0.5루프/초 아래로 떨어지면 판정 주기가 늘어져 신호를 놓치므로 되돌린다.
        #   되돌리기: RUN\backup\strategy_02_low_buy_signal_v1_20260730_reset20s.py 복원(=5분·10초 원본).
        cutoff = point.ts.timestamp() - 1800
        while state.points and state.points[0].ts.timestamp() < cutoff:
            state.points.popleft()

        self._track_flow_book_shadow(
            code,
            name,
            point,
            state,
            allow_signal=allow_signal,
        )

        morning = point.ts.time() < MORNING_OPEN_REFERENCE_END
        reference_price = state.open_price if morning else state.session_high
        if reference_price <= 0:
            self._clear_pending(state)
            return self._wait_row(
                code, name, point, "REFERENCE_PRICE_MISSING"), False
        state.six_reference_price = reference_price
        state.six_reference_mode = "OPEN" if morning else "INTRADAY_HIGH"

        # ★[2026-07-31] 되돌림 판정으로 교체(위 DIP_MODE 주석 참조).
        #   S02_DIP_MODE=NO 로 두면 종전 매도소진 판정으로 즉시 복귀한다.
        if DIP_MODE:
            self._detect_state = state
            # ★[수정1 2026-08-13] 직접반등 감사 기록용 종목코드 전달.
            self._detect_code = code
            signal = self._detect_dip_rebound(list(state.points))
            wait_reason = (
                "S02_MONEY_SURGE_OR_STAIRCASE_WAIT" if SIX_STYLE
                else "DIP_REBOUND_WAIT"
            )
        else:
            signal = detect_flow_book_exhaustion(list(state.points))
            wait_reason = "FLOW_BOOK_RECOVERY_WAIT"
        if signal is None:
            self._clear_pending(state)
            return self._wait_row(code, name, point, wait_reason), False

        # ★[AFT5F 2026-08-03] 그림자 확정 후보를 12시 이후 실전 관문에 동일 적용.
        if point.ts.time() >= AFTERNOON_START:
            signal_drop_pct = (
                (state.session_high - point.price) / state.session_high * 100.0)
            if signal_drop_pct < AFTERNOON_MIN_SIGNAL_DROP_PCT:
                self._clear_pending(state)
                return self._wait_row(code, name, point, "AFTERNOON_DROP_LT_5PCT"), False
            if not _afternoon_buy_speed_lead(list(state.points)):
                self._clear_pending(state)
                return self._wait_row(code, name, point, "AFTERNOON_BUY_SPEED_NOT_LEADING"), False
            self._last_dip_meta = getattr(self, "_last_dip_meta", None) or {}
            self._last_dip_meta["afternoon_signal_drop_pct"] = round(signal_drop_pct, 3)
            self._last_dip_meta["afternoon_buy_speed_lead"] = "O"
        if abs((point.ts - signal.signal_ts).total_seconds()) > 1:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "STALE_DETECTOR_RESULT"), False
        anchor_id = (
            f"{signal.anchor_low_ts.isoformat(timespec='seconds')}:"
            f"{signal.anchor_low_price:.4f}"
        )
        book_ok, book_reason, spread_bps, edge_bps, best_bid_share = (
            self._book_telemetry(point)
        )
        if SIX_STYLE and not _s02_book_recovery_ready(list(state.points)):
            self._clear_pending(state)
            return self._wait_row(
                code, name, point, "S02_BOOK_RECOVERY_WAIT"
            ), False
        if not book_ok and not SIX_STYLE:
            # ★[2026-08-01 친구님 "6번에 없는 건 넣지 마·똑같이"] 6번에는 호가 관문이
            #   없다 — SIX_STYLE 에서는 스프레드/호가 값은 기록만 하고 막지 않는다.
            self._clear_pending(state)
            return self._wait_row(code, name, point, book_reason), False
        if not allow_signal:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ENTRY_TIME_CLOSED"), False
        if (
            anchor_id in state.emitted_anchors
            or state.emission_count >= self.max_signals_per_code
        ):
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ANCHOR_OR_CYCLE_ALREADY_USED"), False
        # ★[2026-08-01 "6번과 동일하게"] ③재무장 깊이 — 2번째 신호는 직전 신호
        #   저점보다 SIX_REARM_DEEPER_PCT 만큼 더 깊은 저점에서만.
        # ★[2026-08-01 밤 친구님 "왜 장 고점에서 떨어져서 사는 건 하나도 없니"]
        #   예외 추가 — 직전 신호 뒤 "새 고점"을 갱신했다면 재무장 허용.
        #   더 깊은 저점만 요구하는 건 6번(폭포) 세계의 규칙이고, 2번의 본업
        #   (올라갔다 눌리는 놈)은 다음 눌림 저점이 더 높은 게 정상이라
        #   종전 규칙이 장 고점 눌림 매수를 전부 차단하고 있었다.
        episode_high = _number(
            (getattr(self, "_last_dip_meta", None) or {}).get("dip_episode_high"))
        made_new_high = (
            state.last_signal_high > 0 and episode_high > state.last_signal_high
        )
        if (
            SIX_STYLE
            and state.last_signal_low > 0
            and not made_new_high
            and signal.anchor_low_price
            >= state.last_signal_low * (1.0 - SIX_REARM_DEEPER_PCT / 100.0)
        ):
            self._clear_pending(state)
            return self._wait_row(code, name, point, "REARM_NEED_DEEPER_LOW"), False

        if SIX_STYLE:
            # ★[2026-08-01 친구님 "똑같이"] 6번에는 확정 대기가 없다 — 관찰 60초와
            #   속도 역전이 이미 그 역할을 했다. 곧장 발행 판정으로 간다.
            confirm_age_sec = 0.0
        else:
            if state.pending_anchor_id != anchor_id or state.pending_since is None:
                state.pending_anchor_id = anchor_id
                state.pending_since = point.ts
                state.pending_signal_price = point.price
                state.pending_hits = 1
                return self._wait_row(code, name, point, "ENTRY_CONFIRM_WAIT"), False

            chase_bps = (
                (point.price / state.pending_signal_price - 1.0) * 10_000.0
                if state.pending_signal_price > 0
                else 0.0
            )
            if chase_bps < 0 or chase_bps > self.max_confirm_chase_bps:
                state.pending_since = point.ts
                state.pending_signal_price = point.price
                state.pending_hits = 1
                return self._wait_row(
                    code, name, point, "ENTRY_CONFIRM_PRICE_RESET"), False

            state.pending_hits += 1
            confirm_age_sec = max(
                0.0, (point.ts - state.pending_since).total_seconds())
            if (
                confirm_age_sec < self.confirm_sec
                or state.pending_hits < self.confirm_points
            ):
                return self._wait_row(code, name, point, "ENTRY_CONFIRM_WAIT"), False

        entry_gap = (point.price / signal.anchor_low_price - 1) * 100
        # ★[2026-08-01 친구님 승인 "3건 다 고쳐줘"] 딥모드 실효 진입띠 수리 —
        #   판정(_detect_dip_rebound)은 저점 +3.0%(DIP_CHASE_CAP_PCT)까지 허용하는데
        #   여기 옛 1.5% 관문이 살아남아 [0.5, 1.5]% 로 좁히고 있었다(8/1 점검 발견 3.
        #   33행 폐기 목록의 "진입가 저점+1.5% 이내"가 실제로는 안 죽어 있던 것).
        #   딥모드에서만 상한을 3.0% 로 통일 — S02_DIP_MODE=NO 롤백 시엔 종전 1.5% 그대로.
        #   롤백: backup\strategy_02_low_buy_signal_v1_20260801_secfix.py 복원.
        entry_gap_cap = (
            SIX_CHASE_CAP_PCT if SIX_STYLE
            else DIP_CHASE_CAP_PCT if DIP_MODE
            else self.max_entry_gap_pct
        )
        if entry_gap > entry_gap_cap:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ENTRY_GAP_TOO_WIDE"), False

        adaptive_meta: Dict[str, Any] = {}
        if self.adaptive_bottom_enabled:
            dip_meta = getattr(self, "_last_dip_meta", None) or {}
            adaptive_meta = adaptive_bottom_decision(
                algorithm=signal.algorithm,
                entry_gap_pct=entry_gap,
                anchor_low=signal.anchor_low_price,
                open_price=state.open_price,
                avg_5d_range_pct=avg_5d_range_pct,
                regime_band=regime_band,
                u201_pct=u201_pct,
                observe_sec=_number(dip_meta.get("observe_sec")),
            )
            if not adaptive_meta["adaptive_pass"]:
                blocked = self._wait_row(
                    code, name, point, adaptive_meta["adaptive_reason"])
                blocked.update(adaptive_meta)
                blocked.update({
                    "anchor_low": signal.anchor_low_price,
                    "anchor_low_ts": signal.anchor_low_ts.isoformat(timespec="seconds"),
                    "entry_gap_pct": round(entry_gap, 4),
                    "algorithm": signal.algorithm,
                })
                return blocked, False

        # ★[DAY-LOW-CAP 2026-08-25] 8/5 주석의 예고가 8/25 356860 에서 현실화 —
        #   anchor 기준 1.28% 인데 당일 저점 기준으로는 9.37% 였다
        #   (당일 저가 32,550 → 매수 35,600). 저점매수 조건은 그대로 두고
        #   고점 추격만 막는다. NaN 무력화 방지를 위해 not (x <= MAX) 형태.
        #   저점 자료가 없으면 차단(fail-closed).
        _day_low_gap = (
            (point.price / state.session_low - 1) * 100
            if state.session_low > 0 else None
        )
        if _day_low_gap is None or not (_day_low_gap <= DAY_LOW_MAX_GAP_PCT):
            blocked = self._wait_row(
                code, name, point,
                "S02_DAY_LOW_MISSING" if _day_low_gap is None
                else "S02_DAY_LOW_GAP_TOO_FAR")
            blocked.update({
                "anchor_low": signal.anchor_low_price,
                "anchor_low_ts": signal.anchor_low_ts.isoformat(timespec="seconds"),
                "entry_gap_pct": round(entry_gap, 4),
                "algorithm": signal.algorithm,
                "day_low": round(state.session_low, 4),
                "day_low_gap_pct": (
                    round(_day_low_gap, 4)
                    if _day_low_gap is not None else None),
                "day_low_cap_pct": DAY_LOW_MAX_GAP_PCT,
            })
            return blocked, False

        state.emission_count += 1
        state.emitted_anchors.add(anchor_id)
        state.last_signal_low = float(signal.anchor_low_price)
        state.last_signal_high = _number(
            (getattr(self, "_last_dip_meta", None) or {}).get("dip_episode_high"),
            point.price)
        imbalance = (point.bid_tot - point.ask_tot) / (point.bid_tot + point.ask_tot)
        row = {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "BUY_READY",
            "reason": signal.reason,
            "price": point.price,
            "anchor_low": signal.anchor_low_price,
            "anchor_low_ts": signal.anchor_low_ts.isoformat(timespec="seconds"),
            "anchor_id": anchor_id,
            "entry_gap_pct": round(entry_gap, 4),
            # ★[DAY-LOW 2026-08-05] 진짜 당일 저점과 그 대비 매수가.
            #   왜 — 위 anchor_low 는 새 고점이 찍힐 때마다 _reset_six_cycle 이
            #   현재가로 통째로 갈아치운다(=그 시점 이후의 저점일 뿐 당일 저점이 아님).
            #   그래서 entry_gap_pct 는 문턱을 조일수록 좋아 보이는데 실제 매수가는
            #   올라갈 수 있다. 8/5 원익IPS 실증: anchor 기준 1.439%(최우수)인 설정이
            #   진짜 저점 기준으로는 3.785%(최악)였고 종가대비 -1.013% 였다.
            #   ⚠️판정에는 쓰지 않는다 — 기록 전용. 문턱은 며칠 쌓아서 고른다.
            "day_low": round(state.session_low, 4),
            "day_low_ts": (
                state.session_low_ts.isoformat(timespec="seconds")
                if state.session_low_ts else ""
            ),
            "day_low_gap_pct": round(
                (point.price / state.session_low - 1) * 100, 4
            ) if state.session_low > 0 else 0.0,
            "book_imbalance": round(imbalance, 4),
            "best_ask_price": point.best_ask_px,
            "spread_bps": round(spread_bps, 4),
            "microprice_edge_bps": round(edge_bps, 4),
            "best_bid_share": round(best_bid_share, 4),
            "confirm_age_sec": round(confirm_age_sec, 3),
            "confirm_points": state.pending_hits,
            "wave_count": signal.wave_count,
            "signal_sequence": state.emission_count,
            "algorithm": signal.algorithm,
            "mode": SIGNAL_MODE,
        }
        # ★[2026-07-31] 저점 리셋 기준 매수/매도 배수·계단 수 기록(판정에는 미사용)
        row.update(getattr(self, "_last_dip_meta", None) or {})
        row.update(adaptive_meta)
        self._clear_pending(state)
        state.points.clear()
        state.points.append(point)
        if SIX_STYLE:
            self._reset_six_cycle(state, point)
            self._reset_money_surge(state)
        return row, True

    @staticmethod
    def _wait_row(
        code: str,
        name: str,
        point: MarketPoint,
        reason: str,
    ) -> Dict[str, Any]:
        imbalance = (point.bid_tot - point.ask_tot) / (point.bid_tot + point.ask_tot)
        return {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "WAIT",
            "reason": reason,
            "price": point.price,
            "book_imbalance": round(imbalance, 4),
            "mode": SIGNAL_MODE,
        }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(1, 7):
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
            return True
        except PermissionError as exc:
            if attempt >= 6:
                print(
                    f"ATOMIC_WRITE_RETRY_EXHAUSTED path={path} error={exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return False
            time_module.sleep(0.2)
    return False

def _append_events(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # ★[2026-07-29 친구님 승인 "열 구성 고정"] 고저폭 hr_* 메타는 TOP30 종목 행에만 붙어
    #   행마다 키가 다를 수 있다. 종전 코드(첫 행 기준 DictWriter)는 다른 키가 섞이면
    #   ValueError 로 신호기 프로세스가 죽고, 안 죽어도 열이 어긋나 기록이 오염됐다.
    #   열 = 기존 파일 헤더 ∪ 이번 배치 전체 키(등장 순서 유지). 새 열이 생기면 하루짜리
    #   작은 파일이므로 통째로 다시 써서 정렬을 맞추고, 빠진 값은 빈칸으로 둔다.
    #   읽기 실패(잠금 등) 시엔 데이터 보존 우선으로 이어쓰기만 한다. 롤백: *.bak_20260729_review23
    batch_fields = list(dict.fromkeys(key for row in rows for key in row))
    header: list[str] = []
    existing: list[dict] = []
    read_ok = True
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                header = list(reader.fieldnames or [])
                existing = list(reader)
        except (OSError, csv.Error):
            read_ok = False
    fieldnames = list(dict.fromkeys(header + batch_fields))
    if read_ok and header != fieldnames:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, restval="", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + rows)
        return
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames if read_ok else batch_fields,
            restval="", extrasaction="ignore",
        )
        writer.writerows(rows)


EXACT_REPLAY_FIELDS = (
    "ts", "code", "name", "allow_signal", "open_price", "session_high",
    "regime_band", "u201_pct", "avg_5d_range_pct", "price", "cum_vol",
    "che_str", "ask_tot", "bid_tot", "buy_money_cum", "sell_money_cum",
    "buy_vol_cum", "sell_vol_cum", "best_ask_px", "best_bid_px",
    "best_ask_qty", "best_bid_qty", "broker_day_low", "broker_day_high",
)


def _append_exact_replay_points(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    max_bytes: int,
) -> None:
    """생산 process_point 입력만 고정 열로 이어쓴다. 주문·상태에는 관여하지 않는다."""
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= max_bytes:
        return
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=EXACT_REPLAY_FIELDS,
            restval="", extrasaction="ignore",
        )
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = LowBuySignalMonitor(
        max_signals_per_code=config.max_signals_per_code,
        confirm_sec=config.confirm_sec,
        confirm_points=config.confirm_points,
        max_spread_bps=config.max_spread_bps,
        min_microprice_edge_bps=config.min_microprice_edge_bps,
        min_best_bid_share=config.min_best_bid_share,
        max_confirm_chase_bps=config.max_confirm_chase_bps,
        max_entry_gap_pct=config.max_entry_gap_pct,
        adaptive_bottom_enabled=config.adaptive_bottom_enabled,
    )
    monitor.restore(_read_json(config.output_path), now.strftime("%Y%m%d"))
    relative_strength_shadow = RelativeStrengthReboundShadow()
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        points, status, watch_count, range_meta = load_live_points(config, now)
        regime_band, u201_pct = _market_regime_at(config.regime_path, now)
        minute_refs = _minute_references(
            _read_json(config.minute_path), now.strftime("%Y%m%d"))
        new_signals = []
        new_flow_book_shadow_signals = []
        exact_replay_rows = []
        for code, name, point in points:
            allow = ENTRY_START <= point.ts.time() < ENTRY_END
            reference = minute_refs.get(code) or {}
            # ★[공통배관 2026-08-07 친구님 "전 전략이 다 같이 써야 돼"]
            #   분봉 기준값이 없는 종목만 공통 모듈(실황판→거래소 op/hi)로 메운다.
            #   분봉 값이 있으면 종전 그대로 — 비교 기준선 보존.
            anchor = day_anchor(code, today=now.strftime("%Y%m%d"),
                                snapshot_path=config.snapshot_path)
            open_price = _number(reference.get("open")) or anchor.open
            session_high = _number(reference.get("high")) or anchor.high
            avg_5d_range_pct = _number(
                (range_meta.get(code) or {}).get("hr_avg5_range")
            )
            if config.exact_replay_journal_enabled:
                exact_replay_rows.append({
                    "ts": point.ts.isoformat(timespec="microseconds"),
                    "code": code,
                    "name": name,
                    "allow_signal": int(allow),
                    "open_price": open_price,
                    "session_high": session_high,
                    "regime_band": regime_band,
                    "u201_pct": u201_pct,
                    "avg_5d_range_pct": avg_5d_range_pct,
                    "price": point.price,
                    "cum_vol": point.cum_vol,
                    "che_str": point.che_str,
                    "ask_tot": point.ask_tot,
                    "bid_tot": point.bid_tot,
                    "buy_money_cum": point.buy_money_cum,
                    "sell_money_cum": point.sell_money_cum,
                    "buy_vol_cum": point.buy_vol_cum,
                    "sell_vol_cum": point.sell_vol_cum,
                    "best_ask_px": point.best_ask_px,
                    "best_bid_px": point.best_bid_px,
                    "best_ask_qty": point.best_ask_qty,
                    "best_bid_qty": point.best_bid_qty,
                    "broker_day_low": getattr(point, "broker_day_low", 0.0),
                    "broker_day_high": getattr(point, "broker_day_high", 0.0),
                })
            row, fired = monitor.process_point(
                code, name, point, allow_signal=allow,
                open_price=open_price,
                session_high=session_high,
                regime_band=regime_band,
                u201_pct=u201_pct,
                avg_5d_range_pct=avg_5d_range_pct,
            )
            row.update(range_meta.get(code) or {})
            row.update(relative_strength_shadow.evaluate(
                code=code,
                ts=point.ts,
                price=point.price,
                previous_close=_number(
                    (range_meta.get(code) or {}).get("hr_prev_close")
                ),
                market_pct=u201_pct,
                buy_money_cum=point.buy_money_cum,
                sell_money_cum=point.sell_money_cum,
                best_ask_px=point.best_ask_px,
                best_bid_px=point.best_bid_px,
                best_ask_qty=point.best_ask_qty,
                best_bid_qty=point.best_bid_qty,
                high_range_meta=range_meta.get(code),
            ))
            monitor.latest[code] = row
            new_flow_book_shadow_signals.extend(
                monitor.drain_flow_book_shadow_signals()
            )
            if fired:
                monitor.signals.append(dict(row))
                new_signals.append(dict(row))
        if config.exact_replay_journal_enabled:
            _append_exact_replay_points(
                config.exact_replay_dir / f"s02_exact_inputs_{now:%Y%m%d}.csv",
                exact_replay_rows,
                max_bytes=config.exact_replay_max_bytes,
            )
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": SIGNAL_MODE,
            "status": status,
            "watch_count": watch_count,
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
            "flow_book_shadow_signals": monitor.flow_book_shadow_signals[-1000:],
            "flow_book_shadow_candidates": list(
                monitor.flow_book_shadow_latest.values()
            ),
        }
        if not _write_json_atomic(config.output_path, payload):
            print(f"SIGNAL_OUTPUT_STALE_CONTINUING path={config.output_path}", file=sys.stderr, flush=True)
        _append_events(
            config.event_dir / f"strategy_02_signals_{now:%Y%m%d}.csv",
            new_signals,
        )
        _append_events(
            config.event_dir
            / f"strategy_02_flow_book_shadow_{now:%Y%m%d}.csv",
            new_flow_book_shadow_signals,
        )
        if once or now.weekday() >= 5 or now.time() >= time(14, 21):
            return 0
        time_module.sleep(max(0.2, config.loop_sec))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    lock_path = Path(os.environ.get(
        "S02_LOCK_PATH", r"C:\stock_bot\data\strategy_02_signal_v1.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+")
    try:
        if lock_handle.tell() == 0:
            lock_handle.write("0")
            lock_handle.flush()
        lock_handle.seek(0)
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_handle.close()
        # 2026-08-27: 종전에는 잠금을 못 잡으면 아무 말 없이 종료해, 프로세스는 살아 있는데
        # 산출물만 0 인 '조용사'로 보였다(8/27 09:41 실전 41분 정지의 진단을 어렵게 만든 원인).
        # 종료코드 0 은 그대로 두고(태스크 판정 불변) 사유만 남긴다.
        print(
            f"S02_SIGNAL_SINGLETON_LOCK_BUSY lock={lock_path} "
            "- another S02 signal process holds it; this one exits without running.",
            file=sys.stderr, flush=True)
        return 0
    try:
        return run(SignalConfig(), once=args.once)
    finally:
        try:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
