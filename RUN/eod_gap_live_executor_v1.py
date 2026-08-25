# -*- coding: utf-8 -*-
"""[EOD_GAP 실시간 실전 executor] 친구님 "자동매수 소액".
   pick(15:17): opt10032 실시간 거래대금상위 → EOD_GAP_SCORE(분봉+전일일봉+opt10032오후) → 1등(75+) → 자동매수(소액캡).
   sell(09:00): 전날 산 EOD_GAP 종목 익일 시가매도. 위치(52주/20일선)는 로그만. 상한가 안 컷(오후거래대금으로 판정).
   ★안전: EOD_GAP_LIVE=NO면 모의(주문0)·소액캡·검증된 broker경로·env즉시롤백. -X utf8.
   실행: python eod_gap_live_executor_v1.py pick   /   sell"""
import sys, io, csv, json, uuid, time, hashlib
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\stock_bot\RUN")
sys.path.insert(0, r"C:\stock_bot\MONITOR")
import os
import eod_gap_track_shadow_v1 as G   # _intraday, _load_opt10032_aft, _load_memb, _load_block 재사용

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
POS = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
LOG = Path(r"C:\stock_bot\data\LOG\eod_gap_live.log")

LIVE = os.environ.get("EOD_GAP_LIVE", "NO").strip().upper() == "YES"
CAP = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or os.environ.get("EOD_GAP_CAP_KRW") or "300000"))  # ★통일캡: SAFEPLUS_CAP_KRW 마스터(전 전략 공통·기본30만). 키울땐 이것만.
try:  # [레짐 금액 스케일러 2026-06-29 친구님] 시장 나쁘면 건당 작게(개수는 그대로=작게많이). REGIME_SIZE_SCALE=NO면 1.0(무변경)
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
MAX_POS = int(os.environ.get("EOD_GAP_MAX_POS", "1"))            # 검증 전 현행 1 유지. 승인 목표는 3이며 PROD_REPLAY 통과 후 런처에서 전환.
QTY_ONE_ALL = os.environ.get("EOD_GAP_QTY_ONE_ALL", "NO").strip().upper() == "YES"
PORTFOLIO_V2 = os.environ.get("EOD_GAP_PORTFOLIO_V2", "NO").strip().upper() == "YES"
# [SUPPLY 2026-06-28 친구님] 종가매수에 기관/외국인 순매수 우선(세력=기관/외인 가설) + 익일갭 검증 그림자
SUP_DIR = Path(r"C:\stock_bot\data\shadow\eod_supply_gap")
SUPPLY_PRIORITY = os.environ.get("EOD_GAP_SUPPLY_PRIORITY", "YES").strip().upper() == "YES"
LOCKED_D2_PRIORITY = os.environ.get(
    "EOD_GAP_LOCKED_D2_PRIORITY", "NO"
).strip().upper() == "YES"
LOCKED_D2_PRIORITY_UNTIL = os.environ.get(
    "EOD_GAP_LOCKED_D2_PRIORITY_UNTIL", ""
).strip()
# [SUPPLY-D2 2026-07-01 친구님·직접백테 교정] 당일 기관수급=익일 역신호(−)·2일전(D-2)=익일+(최강).
#   기존 _supply_net(당일 opt10059)은 그림자 기록만, 우선순위 정렬은 supply_signal D-lag(기본2)로 교체.
SUPPLY_LAG = int(os.environ.get("EOD_GAP_SUPPLY_LAG", "2"))
MIN_SCORE = float(os.environ.get("EOD_GAP_MIN_SCORE", "75"))
# [통일 종가점수 연결 2026-07-02 친구님 "선별방법 더 구체적으로 만들어 실행기에 연결·그림자 먼저·내일 실전"]
#   ★daily_leader_board 종가점수 방법(마감+상승+추세+거래량+유동성+D-2)을 오늘 15:17 데이터로 이식해 후보 랭킹.
#   기본 NO=그림자(실매수 vs 통일점수 top 로그만·매수 무변경). YES=통일점수로 재랭킹(라이브). 롤백 setx EOD_GAP_UNIFIED_PICK NO.
UNIFIED_PICK = os.environ.get("EOD_GAP_UNIFIED_PICK", "NO").strip().upper() == "YES"
UNIFIED_MIN  = float(os.environ.get("EOD_GAP_UNIFIED_MIN", "0") or "0")   # 통일점수 매수 하한(0=off)
# ★금요일=주말 오버나잇(월요일 매도)=갭 리스크 큼 → 더 엄선(친구님 "금요일은 점수가 더 커야").
#   금요일엔 통일점수 floor 를 이 값으로(UNIFIED_PICK=YES일 때만 적용). 0=off. 롤백 setx EOD_GAP_FRI_UNIFIED_MIN 0.
FRI_UNIFIED_MIN = float(os.environ.get("EOD_GAP_FRI_UNIFIED_MIN", "60") or "0")
# [2026-06-20 친구님] LOCKED 우선 — 1년백테: 갭엣지는 종가상한가(LOCKED)에만(+7.69% vs FADED/일반+0.2%).
#   규칙: 후보풀에 LOCKED 있으면 LOCKED를 비-LOCKED보다 위로, 단 LOCKED 안에서는 점수순 유지(갭 보존).
#   ★실데이터검증(6/20)으로 '거래대금최고 LOCKED'안은 갭버려 폐기(거래대금↑=갭↓) → 현 score의 갭선호 유지.
#   LOCKED=종가 +28.5%↑. 체결성은 orderbook(FROM_RUNNER walk) 몫. 롤백 setx EOD_GAP_LOCKED_PRIORITY NO. LOCKED픽 floor 기본60.
LOCKED_PRIORITY = os.environ.get("EOD_GAP_LOCKED_PRIORITY", "YES").strip().upper() == "YES"
# ★[2026-07-29 친구님 지시 "0으로 해"] LOCKED 점수 문턱 60 → 0(사실상 해제).
#   이유: 상한가는 거래가 잠겨 거래대금이 적다 → 거래대금 점수를 못 받는다 → 총점이 구조적으로 낮다.
#     (7/29 실측: 엔젤로보틱스 31.1점 = 거래대금2 + 종가22 + 폭발3. 5억뿐이라 2점)
#     즉 상한가라는 이유로 점수가 깎여서 문턱 60에 전부 걸렸다.
#   근거: 상한가 950건 전체가 +5.963%/승률 75.8%(익일 시가매도·비용 0.38% 차감).
#     점수로 거를 이유가 없다. "찔끔찔끔"(저가 -3%↓ 눌린) 상한가도 +5.399%.
#     기존 메모 "MIN_SCORE 75 미만이 더 좋다"와도 방향이 같다.
#   남는 안전장치: 거래대금 상한(VAL_CEIL_EOK)·스마트머니 던지기 차단·외국계 매도 게이트·
#     종가 체결강도(EOD_CHE_WEAK)·중복보유 방지. 롤백: setx EOD_GAP_LOCKED_MIN 60
LOCKED_MIN = float(os.environ.get("EOD_GAP_LOCKED_MIN", "0"))   # LOCKED픽 전용 품질 floor(비-LOCKED는 MIN_SCORE)
# ★[2026-07-29 친구님 지시 "상한가 우선 경로 지금 해"] 상한가(LOCKED)를 전략A/B보다 먼저 집는다.
#   근거(일봉 1년·상한가 950건·종가매수→익일 시가매도·왕복 0.38% 차감):
#     상한가 전체 +5.963%/승률 75.8% · 폭락일에도 +6.262%/승률 73.1%(67건)
#     vs 비-LOCKED 강세주 +0.2%(위 42줄 기존 백테와 일치) · +25~28% 구간은 -0.155% 적자
#     ⇒ 엣지는 "상한가에 잠김" 상태 자체에 있다. 등락률 절벽.
#   기존 구조에서 상한가는 4겹으로 막혀 매수가 아예 불가능했다:
#     ①전략A/B 조건의 `and not is_locked`(611·623줄) ②전략A/B가 켜져 elif SKIP_LOCKED 미도달
#     ③SKIP_LOCKED=YES ④정배열 관문(상한가 46% 탈락·성과차 0.334%p뿐·승률은 탈락이 더 높음)
#   ⚠️상한가는 매도호가 0이라 15:18 즉시체결은 안 될 수 있다. 그래도 주문을 넣어두면
#     15:20~15:30 장마감 동시호가까지 유효하다(7/29 엔젤로보틱스 동시호가 25,848주 체결 실측).
#     지금까지는 주문 자체를 안 넣어 동시호가 기회조차 없었다.
#   롤백: setx EOD_GAP_LOCKED_FIRST NO
LOCKED_FIRST = os.environ.get("EOD_GAP_LOCKED_FIRST", "YES").strip().upper() == "YES"
# ★[LOCKED-FLOOR 2026-08-14 친구님 지시 "문턱 면제 적용해"] 상한가 전용 점수 하한.
#   왜 — 7/29 에 LOCKED-FIRST 경로를 만들었지만 점수 검사(_passes_final_score,
#   MIN_SCORE 70~75)를 그대로 공유해서 **한 번도 발동하지 못했다**. 상한가는 거래가
#   잠겨 거래대금 점수를 못 받아 실전 점수가 최대 28점대다
#   (8/14 실측 5개: 28.2 / 22.5 / 21.1 / 19.8 / 18.9 → 전부 탈락, NO_TRADE).
#   그래서 종가매수는 7/28 이후 정상 왕복 0건이었다.
#   근거 — 백테 `RUN\eodgap_limitup_score_backtest_v1.py` (일봉 1년·252거래일):
#     상한가 진입 전수 1,527건, D종가매수→D+1시가매도, 왕복비용 0.38%p 차감
#       전수 평균 +7.543% / 중앙값 +5.978% / 승률 79.1%
#       거래대금 5분위(=실전 점수의 주재료)별:
#         Q1(최저 ~3,103억) +12.492% 승률84.3%  ← 지금 문턱에 걸려 못 사던 쪽
#         Q5(최고 69,327억~) +3.669% 승률69.0%  ← 점수 높아 통과하던 쪽
#       **단조 역상관. 점수가 낮은 상한가가 3.4배 좋다.** 13개월 전부 플러스(마이너스 달 0).
#   ⇒ 점수 문턱은 상한가에 도움이 안 될 뿐 아니라 해롭다. 0 = 검사 면제.
#   ⚠️MIN_SCORE(일반 경로)는 손대지 않는다 — 거긴 검증 안 했고 기각 이력이 있다.
#   ⚠️남은 안전장치: MAX_POS·VAL_CEIL_EOK·DR_CEIL·중복방지·_buyable(체결가능성).
#   ⚠️백테의 '점수'는 거래대금 대용치다(실전 점수식을 그대로 못 씀). 방향은 맞으나 근사.
#   롤백: setx EOD_GAP_LOCKED_MIN_SCORE 75   (또는 setx EOD_GAP_LOCKED_FIRST NO)
LOCKED_MIN_SCORE = float(os.environ.get("EOD_GAP_LOCKED_MIN_SCORE", "0") or "0")
LOCKED_MIN_MARKETCAP = 100_000_000_000.0  # BrokerClient EODGAP 주문 하한과 동일: 1,000억원
# 상한가에 한해 정배열(5>20>60) 관문 면제. 비-LOCKED는 종전대로 유지(거기선 검증 안 했다).
JB_EXEMPT_LOCKED = os.environ.get("EOD_GAP_JB_EXEMPT_LOCKED", "YES").strip().upper() == "YES"
# [2026-06-22 친구님] ★score경로가 잠긴 상한가(LOCKED=종가+28.5%↑=호가0=못삼) 1등을 고르면 체결안돼 NO_TRADE.
#   SKIP_LOCKED=YES면 LOCKED 건너뛰고 '살 수 있는(비잠김) 강세주 중 점수≥MIN_SCORE 최고'를 매수. 롤백 setx EOD_GAP_SKIP_LOCKED NO.
SKIP_LOCKED = os.environ.get("EOD_GAP_SKIP_LOCKED", "YES").strip().upper() == "YES"
# [2026-06-19 친구님] 2차 매수를 '14:30 1차(코스닥 상승 러너) 풀' 안에서만 경쟁선발. 점수=거래대금+종가강함+막판+테마대장(기존 EOD_GAP_SCORE).
#   FROM_RUNNER=YES면 후보를 pool.json(1차 5%↑ 상승) 코드로 제한 + 문턱 RUNNER_MIN(기본40, 강한 러너 위주라 75 안씀). 롤백 setx EOD_GAP_FROM_RUNNER NO.
FROM_RUNNER = os.environ.get("EOD_GAP_FROM_RUNNER", "NO").strip().upper() == "YES"
# [2026-06-21 친구님] walk 순서: 기본=거래대금 큰순(확실히 살수있는). YES=거래대금 작은순(갭 큰쪽 우선·_buyable이 잠긴놈 자동거름)
#   취지: 살수있는 것들 중 거래대금 작은(=약하게잠겨 갭 더큰) 놈을 먼저. 일봉백테 불가(호가의존)→라이브 그림자로 검증. 롤백 setx EOD_GAP_WALK_SMALL_FIRST NO.
WALK_SMALL_FIRST = os.environ.get("EOD_GAP_WALK_SMALL_FIRST", "NO").strip().upper() == "YES"
# [2026-06-21 친구님] 거래대금 상한(억): 500억+ 상한가=갭업55%/갭다운45%/큰손실25%(작은것 갭업100%/갭다운0% 대비 나쁨) → 매수제외. 0=무제한. 롤백 setx EOD_GAP_VAL_CEIL_EOK 0.
VAL_CEIL_EOK = float(os.environ.get("EOD_GAP_VAL_CEIL_EOK", "0") or "0")
# [2026-06-22 친구님] ★당일 상승률 상한(과열 제외): 백테(eod_limitup_daily_log 최근20일) 당일등락 +15%↑ 강세주는
#   다음날 갭다운(+8~15% +0.89%/승50 vs +8~18% +0.11%/승40). DR_CEIL=0.15면 +15%↑ 픽 제외. 0=무제한. 롤백 setx EOD_GAP_DR_CEIL 0.
DR_CEIL = float(os.environ.get("EOD_GAP_DR_CEIL", "0") or "0")
# [2026-06-22 친구님] ★선택진입: 거래대금배수(당일/20일평균)≥VR_MIN 인 진짜 강세주만 매수(약한날 skip=패↓·승↑).
#   백테(최근20일·+10~15%): 매일 승60% → 배수≥3 승74%/+1.62%(19/20일). 0=매일. 롤백 setx EOD_GAP_VR_MIN 0.
VR_MIN = float(os.environ.get("EOD_GAP_VR_MIN", "0") or "0")
# [LEADER-ONLY SHADOW 2026-06-24 친구님 "대장주만"] ★종가매수 선별 = 테마 거래대금1위(대장)만 + 거래대금배수≥LEAD_VR_MIN.
#   백테(Phase2 분봉423·dry-run): 대장만 +1.36% vs 현행 대장+2등+3등 +1.04%, 대장만+배수≥3 +1.87%/승58%(n45). 2등≈3등=대장만.
#   ★기본 NO=그림자(현행 매수 그대로·새 선별 픽을 항상 CSV 기록) → 2주 EV비교 후 setx YES로 라이브 플립. 롤백 setx NO.
LEADER_ONLY = os.environ.get("EOD_GAP_LEADER_ONLY", "NO").strip().upper() == "YES"
LEAD_VR_MIN = float(os.environ.get("EOD_GAP_LEAD_VR_MIN", "3.0"))   # 대장 배수 하한(dry-run sweet spot 3~5)
LEAD_VR_CEIL = float(os.environ.get("EOD_GAP_LEAD_VR_CEIL", "0") or "0")  # 0=무제한·>0이면 배수 이 이상(blow-off) 제외
LEAD_SHADOW = Path(r"C:\stock_bot\data\shadow\eod_gap_leader_shadow.csv")
# [2026-07-17 친구님 "종가매수 통합"] COIL/ACCUM/LIMITUP/RANK200/BRK20/COIL5/MEET60/SURGECONV/VALTOP 9개 셋업 폐기.
#   "오늘 캔들모양이 핵심" → 전략A(횡보후 장대양봉 돌파) + 전략B(수렴선) 2택1로 재설계.
#   26거래일 백테스트(06-11~07-16, top60): A 하루1.24건/승71.0%/+2.59% · B 하루1.96건/승55.1%/+0.66% · 합계 하루3.20건/승61.3%/+1.41%.
TOP_N_UNI = int(os.environ.get("EOD_GAP_TOPN", "60"))   # 대상풀: 거래대금 상위 N위(공용)
# ★[2026-07-29] 거래대금 상위에 못 든 상한가를 유니버스에 보탠다(_limitup_extra 주석 참조).
LIMITUP_ADD = os.environ.get("EOD_GAP_LIMITUP_ADD", "YES").strip().upper() == "YES"
LIMITUP_ADD_MAX = int(os.environ.get("EOD_GAP_LIMITUP_ADD_MAX", "10"))   # 보탤 상한가 최대 개수(TR 절약)
# ★[2026-07-29 친구님 지시] 상한가는 CAP 금액이 아니라 무조건 1주만 산다(변동폭이 커서).
LOCKED_QTY_ONE = os.environ.get("EOD_GAP_LOCKED_QTY_ONE", "YES").strip().upper() == "YES"

# [전략A 2026-07-17] 사전횡보(14:00~15:09 종가박스 좁음) 후 돌파캔들(15:00~15:16 마지막3틱)이 5일선 걸치거나 위·장대양봉.
STRATA_ON = os.environ.get("EOD_GAP_STRATA", "YES").strip().upper() == "YES"
STRATA_BOX_LO = os.environ.get("EOD_GAP_STRATA_BOX_LO", "1400")
STRATA_BOX_HI = os.environ.get("EOD_GAP_STRATA_BOX_HI", "1509")
STRATA_BOX_PCT = float(os.environ.get("EOD_GAP_STRATA_BOX_PCT", "5.0"))    # 사전횡보 박스폭(종가 고저) 상한%
STRATA_BODY_MIN = float(os.environ.get("EOD_GAP_STRATA_BODY_MIN", "0.4"))  # 돌파캔들 몸통비율 하한
STRATA_UW_MAX = float(os.environ.get("EOD_GAP_STRATA_UW_MAX", "0.25"))     # 돌파캔들 위꼬리 비율 상한

# [전략B 2026-07-17] 수렴선: 정배열(종가>5>20>60) + 5·20일선 수렴 + 5,20이 60일선보다 확실히 위(이격).
STRATB_ON = os.environ.get("EOD_GAP_STRATB", "YES").strip().upper() == "YES"
STRATB_CONV_PCT = float(os.environ.get("EOD_GAP_STRATB_CONV", "5.0"))      # 5·20일선 수렴 이격 상한%
STRATB_DEV60_MIN = float(os.environ.get("EOD_GAP_STRATB_DEV60", "3.0"))   # 5,20이 60일선보다 위인 이격 하한%
RUNNER_MIN = float(os.environ.get("EOD_GAP_RUNNER_MINSCORE", "40"))
RUNNER_POOL = r"C:\stock_bot\DATA\eod_runner_pool.json"
RUNNER_PICK = r"C:\stock_bot\DATA\eod_runner_pick.json"   # 러너 stage2 최종픽(막판가속 반영)
RUNNER_STAGE2 = r"C:\stock_bot\DATA\eod_runner_stage2.json"  # ②랭킹 top10 — 1번 잠기면 2번..로 walk
# [REAL-MICRO 2026-06-24] ★종가 체결강도 확인(친구님): 매도우위로 마감하는 픽=다음날 갭 불리 → 매수보류(FROM_RUNNER는 다음순번 walk). 데이터없으면 통과(fail-open)
EOD_MICRO_USE    = os.environ.get("EOD_GAP_MICRO_USE", "YES").strip().upper() == "YES"  # 끄려면 setx EOD_GAP_MICRO_USE NO
EOD_CHE_WEAK     = float(os.environ.get("EOD_GAP_CHE_WEAK", "90"))   # 종가 체결강도 이 미만이면 매수보류(매도세 마감)
EOD_OB_WEAK      = float(os.environ.get("EOD_GAP_OB_WEAK", "0.7"))   # 호가 imb(매수/매도총잔량) 이 미만(매도잔량 우위)이면 매수보류
MICRO_SNAP_FILE  = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
MICRO_WATCH_FILE = Path(r"C:\stock_bot\IPC\micro_watch_eod.json")
AUCTION_GATE_MODE = os.environ.get("EOD_GAP_AUCTION_GATE_MODE", "SHADOW").strip().upper()
AUCTION_MAX_AGE_SEC = float(os.environ.get("EOD_GAP_AUCTION_MAX_AGE_SEC", "30"))
AUCTION_DECISION_HHMM = int(os.environ.get("EOD_GAP_AUCTION_DECISION_HHMM", "1527"))
AUCTION_MIN_SAMPLES = int(os.environ.get("EOD_GAP_AUCTION_MIN_SAMPLES", "3"))
AUCTION_MIN_SPAN_SEC = float(os.environ.get("EOD_GAP_AUCTION_MIN_SPAN_SEC", "60"))
AUCTION_SCREEN = "9290"
AUCTION_FIDS = "21;23;24;121;125"
AUCTION_AUDIT_DIR = Path(r"C:\stock_bot\data\audit\eod_gap_auction")
AUCTION_REPLAY_DIR = Path(r"C:\stock_bot\data\audit\eod_gap_auction_replay")
LIVE_BOARD_CACHE = Path(r"C:\stock_bot\DATA\eod_gap_live_board_cache.json")
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()
LAST_ORDER_STATUS = ""
PORTFOLIO_ROUTE_TAGS = {}
SELL_RETRY_COUNT = 3
SELL_RETRY_INTERVAL_SEC = 2.0
LIVE_BOARD_MAX_AGE_SEC = float(os.environ.get("EOD_GAP_BOARD_MAX_AGE_SEC", "120"))
LIVE_BOARD_CACHE_FALLBACK = os.environ.get(
    "EOD_GAP_BOARD_CACHE_FALLBACK", "NO"
).strip().upper() == "YES"


def _pick_window_open(now=None):
    """Allow new EOD_GAP entries through the final auction decision minute."""
    now = now or datetime.now()
    return (15, 0) <= (now.hour, now.minute) < (15, 29)


def _passes_final_score(score):
    """One immutable score floor shared by every EOD_GAP buy route.

    ★[2026-08-14] 단 LOCKED(상한가) 경로만 예외다 — _passes_locked_score 를 쓴다.
      상한가는 거래가 잠겨 거래대금 점수를 못 받아 이 문턱을 구조적으로 못 넘는다.
    """
    try:
        return float(score) >= MIN_SCORE
    except (TypeError, ValueError):
        return False


def _passes_locked_score(score):
    """상한가 전용 하한. 기본 0 = 면제 (백테 근거는 LOCKED_MIN_SCORE 주석 참조)."""
    try:
        return float(score) >= LOCKED_MIN_SCORE
    except (TypeError, ValueError):
        return False


def _passes_locked_marketcap(cand):
    """LOCKED PICK 전에 BrokerClient와 같은 시총 하한을 미리 적용한다."""
    try:
        from broker_client import _load_shares_cache
        code = str(cand[1]).zfill(6)
        price = float(cand[4] or 0)
        shares = float(_load_shares_cache().get(code, 0) or 0)
        if price <= 0 or shares <= 0:  # BrokerClient와 동일한 fail-open
            return True
        marketcap = shares * price
        if marketcap < LOCKED_MIN_MARKETCAP:
            _log(
                f"[LOCKED-MCAP] {code} {marketcap/1e8:.0f}억<1000억 "
                "→ PICK 사전제외"
            )
            return False
        return True
    except Exception:
        return True


def _save_live_board_cache(rows, now=None):
    """당일 opt10032 성공 결과만 원자적으로 보존한다."""
    now = now or datetime.now()
    _jsave(LIVE_BOARD_CACHE, {
        "date": now.strftime("%Y%m%d"),
        "captured_at": now.isoformat(),
        "source": "opt10032",
        "rows": [list(row[:3]) for row in rows],
    })


def _load_fresh_live_board_cache(now=None, max_age_sec=None):
    """같은 날·기본 2분 이내 opt10032 캐시만 허용한다."""
    now = now or datetime.now()
    max_age_sec = LIVE_BOARD_MAX_AGE_SEC if max_age_sec is None else float(max_age_sec)
    payload = _jload(LIVE_BOARD_CACHE)
    if str(payload.get("date") or "") != now.strftime("%Y%m%d"):
        return []
    try:
        captured = datetime.fromisoformat(str(payload.get("captured_at") or ""))
        age_sec = (now - captured).total_seconds()
    except Exception:
        return []
    if age_sec < 0 or age_sec > max_age_sec:
        return []
    out = []
    for row in payload.get("rows") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            out.append((str(row[0]).zfill(6), str(row[1]), float(row[2] or 0)))
    return out


def _shadow_log(today, cur, leader, active):
    """[LEADER-ONLY SHADOW] 현행픽(cur) vs 대장만+배수≥기준 픽(leader)을 CSV 기록 → 2주 EV 비교용.
       cur/leader = cands 튜플(…,vr=12,vrt=13) or None(NO_TRADE). active=새 선별이 라이브 적용중인지."""
    try:
        LEAD_SHADOW.parent.mkdir(parents=True, exist_ok=True)
        new = not LEAD_SHADOW.exists()
        with io.open(LEAD_SHADOW, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "ts", "leader_only_active",
                            "cur_code", "cur_name", "cur_score", "cur_vr", "cur_vrt", "cur_locked",
                            "lead_code", "lead_name", "lead_score", "lead_vr", "lead_vrt"])
            def fld(c, i, d=""):
                return c[i] if c else d
            w.writerow([today, datetime.now().strftime("%H:%M:%S"), "Y" if active else "N",
                        fld(cur, 1), fld(cur, 2), fld(cur, 0),
                        (round(cur[12], 2) if cur else ""), fld(cur, 13), (1 if (cur and cur[8]) else 0),
                        fld(leader, 1), fld(leader, 2), fld(leader, 0),
                        (round(leader[12], 2) if leader else ""), fld(leader, 13)])
    except Exception:
        pass


def _buyable(code, need_qty):
    """[2026-06-19 친구님] 체결가능 판정 = 호가 매도잔량(opt10004). 잠긴 상한가(매도0)=못 삼 → 다음 순번으로.
       반환 (ok, msg). 5호가 누적 매도잔량 ≥ 필요수량이면 살 수 있음."""
    try:
        import eod_pickup_orderbook_v1 as OB
        ob = OB.fetch_orderbook(str(code).zfill(6))
    except Exception as e:
        return False, f"호가조회실패({e})"
    if not ob:
        return False, "호가없음(잠김/매도0 추정)"
    a1 = float(ob.get("ask1", 0) or 0); a5 = int(ob.get("ask_total_5", 0) or 0)
    if a1 <= 0 or a5 <= 0:
        return False, "매도호가0(잠김)"
    if a5 < need_qty:
        return False, f"매도잔량부족(5호가{a5}<{need_qty}주)"
    return True, f"체결가능(매도1호가{a1:.0f}·5호가잔량{a5}주)"


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as handle:
            handle.write(s + "\n")
    except Exception:
        pass


def _jload(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return {}


def _pos_update_locked(mutate):
    """eod_gap_positions.json 잠금 갱신 — 전용 추적 매도기(eod_gap_lowbuy_sell_v1)와
    같은 DATA\\eod_gap_positions.lock 공유.

    ★[2026-07-31 친구님 승인 #6] 09:01 공용매도가 '시작 때 읽은 사본'을 매도 후
    통째로 저장하면, 그 사이 전용 매도기(09:00~09:32 2초 루프)가 쓴 CLOSED 가
    낡은 사본에 밀려 OPEN 으로 되살아난다(경합→유령). 잠금 → 재읽기 →
    자기 종목만 수정 → 저장. 잠금 3초 실패 시 잠금 없이 진행(fail-open)."""
    import msvcrt
    lock_path = POS.with_suffix(".lock")
    handle = None
    locked = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+")
        try:  # 씨앗 1바이트 — 상대가 잠근 중이면 읽기/쓰기 자체가 PermissionError → 무시
            if lock_path.stat().st_size == 0:
                handle.write("1")
                handle.flush()
        except OSError:
            pass
        for _ in range(30):
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
                break
            except OSError:
                time.sleep(0.1)
        held = _jload(POS)
        mutate(held)
        _jsave(POS, held)
        return held
    finally:
        if handle is not None:
            if locked:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            handle.close()


def _jsave(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")          # [원자적쓰기 2026-06-29] 임시파일→os.replace = 쓰기중 크래시시 손상방지
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        return None
    return BrokerClient()


def _order(bc, code, qty, side, tag):
    """검증된 send_order_real(최유리06). side=BUY/SELL. LIVE=NO면 모의."""
    global LAST_ORDER_STATUS
    LAST_ORDER_STATUS = ""
    # ★[2026-07-01 대장주 순위표 게이트] 종가매수도 전날 종가 대장주 순위표 안에서만.
    #   board 없거나 LEADER_FILTER OFF면 is_leader=True(fail-open). 롤백 setx EODGAP_LEADER_BOARD NO
    if side == "BUY" and os.environ.get("EODGAP_LEADER_BOARD", "YES").strip().upper() == "YES":
        try:
            if os.environ.get("EODGAP_EOD_SELECT", "YES").strip().upper() == "YES":   # [7/6 친구님] 종가 선별(codes_by_eod) 게이트
                import json as _j
                _bd = _j.load(open(r"C:\stock_bot\data\daily_leader_board.json", encoding="utf-8"))
                _eod = set(str(c).zfill(6) for c in (_bd.get("codes_by_eod") or []))
                if _eod and str(code).zfill(6) not in _eod:
                    _log(f"[{tag}][종가선별밖] {code} 종가 선별 밖 → 매수차단"); return False
            else:
                import leader_filter as _lf
                if not _lf.is_leader(bc, code):
                    _log(f"[{tag}][대장외] {code} 전날 순위표 밖 → 매수차단"); return False
        except Exception:
            pass
    if not LIVE:
        LAST_ORDER_STATUS = "SIMULATED"
        _log(f"[{tag}][모의] {side} {code} x{qty} (EOD_GAP_LIVE=NO)")
        return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음 → 주문불가"); return False
        ot = 1 if side == "BUY" else 2
        # ★[2026-07-31] 매수만 고정 키 — uuid 면 게이트웨이 중복주문 차단(TTL 5분)이 안 걸린다.
        #   매도는 uuid 유지: 실패 응답도 캐시되므로(broker_gateway_v1.py:2087) 고정하면
        #   직전 실패에 막혀 재시도가 안 나간다 — 못 파는 쪽이 더 나쁘다.
        _idem = (f"eodgap_buy_{datetime.now():%Y%m%d}_{code}" if side == "BUY"
                 else f"eodgap_{side.lower()}_{code}_{uuid.uuid4()}")
        r = bc.send_order_real(idempotency_key=_idem,
                               account=ACCOUNT, code=code, qty=int(qty), order_type=ot,
                               price=0, hoga_gb="06", rqname=f"EODGAP_{side}_{code}", screen_no="9703")
        try:
            _raw_response = json.dumps(r, ensure_ascii=False, default=str)
        except Exception:
            _raw_response = repr(r)
        _log(f"[{tag}][LIVE] {side} {code} x{qty} acct={ACCOUNT[:4]}** → {_raw_response}")
        _st = str((r or {}).get("status", "")).upper()
        LAST_ORDER_STATUS = _st or "EMPTY"
        # [BUGFIX 2026-06-30 #1 비대칭] 매수=OK|TIMEOUT 기록(미체결확인불가→재매수 중복위험 회피)·매도=OK만 완료(비OK는 OPEN유지 재시도)
        _ok = (_st == "OK")
        if not _ok or _st != "OK":
            _log(f"[{tag}] 주문 status={_st or 'EMPTY'} → " + ("성공" if _ok else "실패처리") + (" (TIMEOUT=체결미확인·수동확인 권장)" if _st == "TIMEOUT" else ""))
        return _ok
    except Exception as e:
        LAST_ORDER_STATUS = "ERROR"
        _log(f"[{tag}] 주문실패: {e}"); return False


def _sell_truth(bc, code):
    """Return (broker holding quantity, open sell orders), or None."""
    try:
        balance = bc.balance_tr(
            "opw00018",
            inputs={"계좌번호": ACCOUNT, "비밀번호": "",
                    "비밀번호입력매체구분": "00", "조회구분": "2"},
            output_fields=["종목번호", "보유수량"],
            rqname=f"EODGAP_SELL_BALANCE_{code}", screen_no="9704",
            timeout_sec=1.3,
        )
        if str((balance or {}).get("status", "")).upper() != "OK":
            return None
        holding = 0
        for row in (((balance or {}).get("data") or {}).get("records") or []):
            row_code = str(row.get("종목번호", "")).strip().lstrip("A").zfill(6)
            if row_code == str(code).zfill(6):
                holding = max(0, int(float(str(row.get("보유수량", "0")).replace(",", "") or 0)))
                break
        pending = bc.balance_tr(
            "opt10075",
            inputs={"계좌번호": ACCOUNT, "전체종목구분": "1", "매매구분": "1",
                    "종목코드": str(code).zfill(6), "체결구분": "1"},
            output_fields=["주문번호", "종목코드", "미체결수량"],
            rqname=f"EODGAP_SELL_OPEN_{code}", screen_no="9704",
            timeout_sec=1.3,
        )
        if str((pending or {}).get("status", "")).upper() != "OK":
            return None
        open_orders = {}
        for row in (((pending or {}).get("data") or {}).get("records") or []):
            order_no = str(row.get("주문번호", "")).strip()
            remaining = max(0, int(float(str(row.get("미체결수량", "0")).replace(",", "") or 0)))
            if order_no and remaining > 0:
                open_orders[order_no] = remaining
        return holding, open_orders
    except Exception as exc:
        _log(f"[SELL-TRUTH] {code} failed {type(exc).__name__}: {exc}")
        return None


def _cancel_sell_order(bc, code, order_no, remaining):
    try:
        response = bc.send_order_real(
            idempotency_key=f"eodgap_sell_cancel_{code}_{order_no}_{uuid.uuid4()}",
            account=ACCOUNT, code=code, qty=int(remaining), order_type=4,
            price=0, hoga_gb="00", rqname=f"EODGAP_SELL_CANCEL_{code}",
            screen_no="9703", origin_order_no=str(order_no), timeout_sec=2.0,
        )
        status = str((response or {}).get("status", "")).upper()
        _log(f"[SELL-CANCEL] {code} order={order_no} remain={remaining} status={status or 'EMPTY'}")
        return status == "OK"
    except Exception as exc:
        _log(f"[SELL-CANCEL] {code} failed {type(exc).__name__}: {exc}")
        return False


def _portfolio_v2_select(cands, theme_map, d2_map, held_codes, max_pos, unified=None):
    """Owner-approved portfolio: <=1 locked, remaining non-locked, <=1 per theme."""
    unified = unified or {}
    held_codes = {str(code).zfill(6) for code in (held_codes or set())}
    slots = max(0, int(max_pos) - len(held_codes))
    if slots <= 0:
        return [], {}
    tags = {}
    locked, normal = [], []
    for c in cands:
        code = str(c[1]).zfill(6)
        if code in held_codes or c[4] <= 0:
            continue
        if VAL_CEIL_EOK > 0 and c[3] > VAL_CEIL_EOK:
            continue
        route_tags = set()
        if bool(c[8]):
            if _passes_locked_score(c[0]):
                route_tags.add("LOCKED")
                locked.append(c)
        else:
            if len(c) > 17 and c[17]:
                route_tags.add("A")
            if len(c) > 18 and c[18]:
                route_tags.add("B")
            if _passes_final_score(c[0]):
                route_tags.add("GENERAL")
            if not route_tags or not _passes_final_score(c[0]):
                continue
            if DR_CEIL > 0 and c[11] >= DR_CEIL:
                continue
            if VR_MIN > 0 and c[12] < VR_MIN:
                continue
            normal.append(c)
        if route_tags:
            tags[code] = sorted(route_tags)

    def rank_key(c):
        code = str(c[1]).zfill(6)
        unified_score = float(unified.get(code, 0) or 0) if UNIFIED_PICK else 0.0
        return (float(d2_map.get(code, 0) or 0), unified_score,
                float(c[0]), float(c[3]))

    locked.sort(key=rank_key, reverse=True)
    normal.sort(key=rank_key, reverse=True)
    selected = []
    used_themes = set()
    for code in held_codes:
        theme = theme_map.get(code)
        if theme:
            used_themes.add(str(theme))

    def add(c):
        code = str(c[1]).zfill(6)
        theme = str(theme_map.get(code) or f"__{code}")
        if theme in used_themes:
            return False
        selected.append(c)
        used_themes.add(theme)
        return True

    if locked and len(selected) < slots:
        add(locked[0])
    for c in normal:
        if len(selected) >= slots:
            break
        add(c)
    return selected, tags


def _sell_with_recovery(bc, code, quantity):
    """Initial sell plus three cancel/replace retries; close only when flat."""
    ambiguous = False
    for attempt in range(SELL_RETRY_COUNT + 1):
        if attempt:
            time.sleep(SELL_RETRY_INTERVAL_SEC)
        truth = _sell_truth(bc, code)
        if truth is None:
            _log(f"[SELL-RETRY {attempt}/{SELL_RETRY_COUNT}] {code} truth unavailable; wait")
            continue
        holding, open_orders = truth
        if holding <= 0:
            _log(f"[SELL-FILLED] {code} broker balance=0")
            return True
        if open_orders:
            for order_no, remaining in open_orders.items():
                if not _cancel_sell_order(bc, code, order_no, remaining):
                    ambiguous = True
            time.sleep(0.3)
            confirmed = _sell_truth(bc, code)
            if confirmed is None or confirmed[1]:
                ambiguous = True
                continue
            holding = confirmed[0]
        if ambiguous:
            time.sleep(0.5)
            confirmed = _sell_truth(bc, code)
            if confirmed is None or confirmed[1]:
                continue
            holding = confirmed[0]
            ambiguous = False
            if holding <= 0:
                return True
        _order(bc, code, min(int(quantity), int(holding)), "SELL", f"SELL-{attempt + 1}")
        ambiguous = LAST_ORDER_STATUS == "TIMEOUT"
    time.sleep(SELL_RETRY_INTERVAL_SEC)
    final_truth = _sell_truth(bc, code)
    if final_truth is not None and final_truth[0] <= 0:
        _log(f"[SELL-FILLED] {code} broker balance=0 after final retry")
        return True
    remaining = "UNKNOWN" if final_truth is None else final_truth[0]
    _log(f"[SELL-RETRY-EXHAUSTED] {code} remaining={remaining}; OPEN retained")
    return False


def _opt10032_top(bc, n=100):
    res = bc.tr("opt10032", inputs={"시장구분": "101", "관리종목포함": "0"},
                output_fields=["종목코드", "종목명", "거래대금"],
                rqname="EODGAP_OPT10032", screen_no="9705", timeout_sec=20.0)
    out = []
    for r in (((res or {}).get("data") or {}).get("records") or [])[:n]:
        code = str(r.get("종목코드", "")).strip().lstrip("A").zfill(6)
        if len(code) != 6:
            continue
        try:
            v = float(str(r.get("거래대금", "0")).replace(",", "").replace("+", "").replace("-", "") or 0)
        except ValueError:
            v = 0
        out.append((code, str(r.get("종목명", "")).strip(), v))  # v=누적거래대금(백만원)
    if out:
        _save_live_board_cache(out)
    return out


def _limitup_extra(bc, exclude, min_chg=28.0, max_add=10):
    """★[2026-07-29 친구님 지시 "유니버스에 상한가 합치는것도 지금 해"]
       거래대금 상위 N(TOP_N_UNI)에 못 든 상한가를 유니버스에 보탠다.

       왜 필요한가 — 상한가는 거래가 '잠겨서' 거래대금이 낮아진다. 그래서
       opt10032(거래대금상위) 안에 잘 못 든다. 7/29 실측: 상위 100 중 상한가는
       매드업(40위) 하나뿐이고 엔젤로보틱스(+29.87%)·오가닉티코스메틱(+29.72%)은 밖.
       그런데 엣지는 상한가에만 있다(950건 +5.963%/승률75.8% vs 비-LOCKED +0.2%).

       opt10027(등락률상위)은 거래대금을 안 준다(빈값) → opt10001 로 거래량을 받아
       거래량×현재가 로 채운다(상한가는 종일 그 가격 근처라 오차 작음).
       거래대금이 0이면 점수의 큰 축(로그의 '거래대금NN점')이 죽어 LOCKED_MIN 미달로 탈락한다.

       반환 형식은 _opt10032_top 과 동일: (code, name, v_백만원)
       실패해도 빈 리스트 → 종전 유니버스 그대로(fail-open). 롤백: setx EOD_GAP_LIMITUP_ADD NO
    """
    try:
        res = bc.tr("opt10027",
                    inputs={"시장구분": "101", "정렬구분": "1", "거래량조건": "0000",
                            "종목조건": "0", "신용조건": "0", "가격조건": "0",
                            "거래대금조건": "0"},
                    output_fields=["종목코드", "종목명", "현재가", "등락률"],
                    timeout_sec=12.0, rqname="opt10027_limitup_universe")
    except Exception as exc:
        _log(f"[LIMITUP-ADD] opt10027 실패 fail-open: {exc}")
        return []
    out = []
    for r in (((res or {}).get("data") or {}).get("records") or []):
        code = str(r.get("종목코드", "")).strip().lstrip("A").zfill(6)
        if len(code) != 6 or code in exclude:
            continue
        try:
            chg = float(str(r.get("등락률", "0")).replace("+", "").strip() or 0)
            px = abs(float(str(r.get("현재가", "0")).replace("+", "").replace("-", "").strip() or 0))
        except ValueError:
            continue
        if chg < min_chg or px <= 0:
            continue
        v = 0.0
        try:                                    # 거래대금(백만원) = 거래량 x 현재가 / 1e6
            time.sleep(0.4)                     # 키움 조회 페이스
            r2 = bc.tr("opt10001", inputs={"종목코드": code},
                       output_fields=["거래량"], timeout_sec=10.0,
                       rqname="opt10001_limitup_value")
            recs2 = ((r2 or {}).get("data") or {}).get("records") or []
            if recs2:
                vol = abs(float(str(recs2[0].get("거래량", "0")).replace(",", "").strip() or 0))
                v = vol * px / 1_000_000.0
        except Exception:
            v = 0.0
        out.append((code, str(r.get("종목명", "")).strip(), v, px))
        if len(out) >= max_add:
            break
    return out


def _board_fallback_top(n=100):
    """★[2026-07-01 백업] opt10032(거래대금상위) 조회 실패 시 전날 '대장주 순위표'를
       universe 로 대체 → 종가매수가 조회 실패로 통째 중단되지 않게(오늘 7/1 사례).
       반환 (code, name, v_백만원) — v=전날 거래대금(억×100)·거래대금 내림차순.
       종목별 오늘 데이터(등락율·마감강도 등)는 기존대로 intraday 로 산출되므로 정상 평가.
       env EODGAP_BOARD_FALLBACK=NO 로 끔."""
    if os.environ.get("EODGAP_BOARD_FALLBACK", "YES").strip().upper() != "YES":
        return None
    try:
        import json
        d = json.loads(Path(r"C:\stock_bot\data\daily_leader_board.json").read_text(encoding="utf-8"))
        rows = d.get("board", []) or []
        rows = sorted(rows, key=lambda b: -float(b.get("value_eok", 0) or 0))   # 거래대금 내림차순(opt10032와 동일 정렬)
        out = []
        for b in rows[:n]:
            code = str(b.get("code", "")).lstrip("A").zfill(6)
            if len(code) != 6:
                continue
            v = float(b.get("value_eok", 0) or 0) * 100.0   # 억 → 백만원
            out.append((code, str(b.get("name", "")), v))
        return out or None
    except Exception:
        return None


def _prev_eod():
    """code -> {v20, w52, ma20, c5, close_prev, name, ma5, ma60, ma200} (전일까지)."""
    import pandas as pd, numpy as np
    num = ["close", "high", "low", "value", "value_ratio", "w52_high_pct"]
    e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=["date", "code", "name", "market"] + num, low_memory=False)
    e = e[e["market"] == "KOSDAQ"].copy()
    for c in num:
        e[c] = pd.to_numeric(e[c], errors="coerce")
    e = e.dropna(subset=["close", "value"]).sort_values(["code", "date"])
    e["code"] = e["code"].str.zfill(6)
    # ★[2026-07-29 친구님 승인 "미조치 3건도 고쳐"] 오늘 날짜 행은 제외한다(함수 설명의 "전일까지" 그대로).
    #   일봉 수집기가 16:05 에 당일 봉을 넣기 때문에, 그 뒤 실행하면 close_prev 자리에 '오늘 종가'가
    #   들어가 등락률이 0 이 되고 상한가 판정(day_ret>=0.285)이 통째로 죽는다(7/29 밤 실측: CSV에
    #   이미 20260729 행 존재 → 재실행 시 상한가 0건). 15:18 정규 실행은 당일 행이 아직 없어 무변화.
    #   ⚠️남은 위험: 수집이 하루 빠지면 close_prev 가 이틀 전 종가가 되어 2일 합산 등락률을 상한가로
    #   오판할 수 있다. 그래서 아래에서 실제 사용한 기준일을 로그로 남긴다. 롤백: *.bak_20260729_prevdate
    _today = datetime.now().strftime("%Y%m%d")
    e = e[e["date"] < _today]
    if e.empty:
        _log("⛔ 일봉 기준일 없음(오늘 이전 데이터 0건) — 상한가/이평 판정 불가")
        return {}
    g = e.groupby("code")
    e["v20"] = g["value"].transform(lambda s: s.rolling(20).mean())
    e["ma20"] = g["close"].transform(lambda s: s.rolling(20).mean())
    e["ma5"] = g["close"].transform(lambda s: s.rolling(5).mean())
    e["ma60"] = g["close"].transform(lambda s: s.rolling(60).mean())        # [전략A/B] 정배열·60선이격
    e["ma200"] = g["close"].transform(lambda s: s.rolling(200, min_periods=200).mean())  # [D-2 tiebreak] 200일선
    e["c5"] = g["close"].shift(5)
    last = e.groupby("code").tail(1)
    _base = str(e["date"].max())
    holidays = set()
    try:
        for line in Path(r"C:\stock_bot\config\krx_holidays.txt").read_text(
                encoding="utf-8-sig").splitlines():
            token = line.split("#", 1)[0].strip()
            if len(token) == 8 and token.isdigit():
                holidays.add(token)
    except Exception:
        pass
    expected = datetime.now().date() - timedelta(days=1)
    while expected.weekday() >= 5 or expected.strftime("%Y%m%d") in holidays:
        expected -= timedelta(days=1)
    expected_s = expected.strftime("%Y%m%d")
    if _base != expected_s:
        _log(f"⛔ [EOD-FRESH-GATE] 전일 거래일={expected_s}, 일봉 기준일={_base} — NO_TRADE")
        return {}
    _gap = (datetime.now() - datetime.strptime(_base, "%Y%m%d")).days
    _warn = " ⚠️수집 누락 의심(등락률이 여러 날 합산이라 상한가 오판 가능)" if _gap > 4 else ""
    _log(f"[일봉 기준일] close_prev = {_base} 기준 (오늘로부터 {_gap}일 전·종목 {len(last)}개){_warn}")
    out = {}
    for r in last.itertuples(index=False):
        out[r.code] = {"v20": r.v20, "w52": r.w52_high_pct, "ma20": r.ma20, "c5": r.c5,
                       "close_prev": r.close, "name": str(r.name),
                       "ma5": r.ma5, "ma60": r.ma60, "ma200": r.ma200}
    return out


def _read_micro(code):
    """★IPC live_micro_snapshot에서 종목 실시간 체결강도/호가 읽기(키움 직접호출 X). 없으면 None."""
    try:
        d = json.loads(MICRO_SNAP_FILE.read_text(encoding="utf-8-sig"))
        return (d.get("codes") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _real_value(bc, code, fid):
    """BrokerClient 단건 실시간 FID 응답에서 원문 값을 꺼낸다."""
    try:
        response = bc.get_comm_real_data(str(code).zfill(6), int(fid), timeout_sec=1.0)
        if str((response or {}).get("status", "")).upper() != "OK":
            return ""
        return str(((response.get("data") or {}).get("value") or "")).strip()
    except Exception:
        return ""


def _auction_snapshot(bc, code, reference_px=0, is_locked=False):
    """Register auction FIDs, then preserve the broker's asynchronously received snapshot."""
    code = str(code).zfill(6)
    reg = bc.setreal_reg(AUCTION_SCREEN, code, AUCTION_FIDS,
                         real_type="1", timeout_sec=1.5)
    snap = _read_micro(code) or {}
    auction_ts = str(snap.get("auction_ts") or "")
    hhmmss = ""
    try:
        hhmmss = datetime.fromisoformat(auction_ts).strftime("%H%M%S")
    except Exception:
        pass
    raw = {
        "21": hhmmss or _real_value(bc, code, 21),
        "23": snap.get("auction_expected_px") or _real_value(bc, code, 23),
        "24": snap.get("auction_expected_qty") or _real_value(bc, code, 24),
        "121": snap.get("ask_tot") or _real_value(bc, code, 121),
        "125": snap.get("bid_tot") or _real_value(bc, code, 125),
    }
    record = {
        "observed_at": datetime.now().isoformat(timespec="milliseconds"),
        "code": code,
        "register_status": str((reg or {}).get("status", "")),
        "source": "broker_micro_snapshot" if snap else "direct_fid_fallback",
        "source_ts": auction_ts,
        "reference_px": float(reference_px or 0),
        "is_locked": bool(is_locked),
        "fid": raw,
    }
    try:
        AUCTION_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = AUCTION_AUDIT_DIR / f"auction_{datetime.now():%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        _log(f"[AUCTION-AUDIT] 기록실패 {code}: {exc}")
    return record


def _auction_history(record):
    """Return today's valid saved auction observations for one code."""
    code = str((record or {}).get("code") or "").zfill(6)
    path = Path((record or {}).get("history_path") or
                (AUCTION_AUDIT_DIR / f"auction_{datetime.now():%Y%m%d}.jsonl"))
    points = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if str(row.get("code") or "").zfill(6) != code:
                continue
            raw = row.get("fid") or {}
            px = abs(float(str(raw.get("23", "")).replace(",", "") or 0))
            qty = abs(float(str(raw.get("24", "")).replace(",", "") or 0))
            if px <= 0 or qty <= 0:
                continue
            ask = abs(float(str(raw.get("121", "")).replace(",", "") or 0))
            bid = abs(float(str(raw.get("125", "")).replace(",", "") or 0))
            points.append({"ts": datetime.fromisoformat(row["observed_at"]),
                           "px": px, "qty": qty, "ask": ask, "bid": bid})
    except Exception:
        return []
    return sorted(points, key=lambda x: x["ts"])


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _auction_replay_report_path(now=None):
    now = now or datetime.now()
    return AUCTION_REPLAY_DIR / f"auction_replay_{now:%Y%m%d}.json"


def _auction_replay_ready(now=None):
    """Require today's truth-gated saved-input replay before any auction-gated order."""
    now = now or datetime.now()
    path = _auction_replay_report_path(now)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("date") != now.strftime("%Y%m%d"):
            return False, "replay 날짜 불일치"
        if report.get("replay_engine_sha256") != _sha256(Path(__file__)):
            return False, "replay 이후 실행기 변경"
        from trading_report_truth_gate_v1 import validate
        ok, reason = validate(report)
        return bool(ok), str(reason)
    except Exception as exc:
        return False, f"replay 없음/오류: {exc}"


def _auction_gate_decision(record, now=None):
    """(통과여부, 사유). 예상체결가·수량·호가시각·불균형을 모두 fail-closed 확인."""
    now = now or datetime.now()
    if (now.hour, now.minute) < (15, 20):
        return False, "15:20 동시호가 시작 전"
    raw = (record or {}).get("fid") or {}
    try:
        expected_px = abs(float(str(raw.get("23", "")).replace(",", "") or 0))
        expected_qty = abs(float(str(raw.get("24", "")).replace(",", "") or 0))
        ask = abs(float(str(raw.get("121", "")).replace(",", "") or 0))
        bid = abs(float(str(raw.get("125", "")).replace(",", "") or 0))
    except (TypeError, ValueError):
        return False, "동시호가 수치 파싱 실패"
    hhmmss = "".join(ch for ch in str(raw.get("21", "")) if ch.isdigit())[-6:]
    if len(hhmmss) != 6:
        return False, "호가시각(FID21) 없음"
    try:
        stamp = now.replace(hour=int(hhmmss[0:2]), minute=int(hhmmss[2:4]),
                            second=int(hhmmss[4:6]), microsecond=0)
        age = abs((now - stamp).total_seconds())
    except ValueError:
        return False, "호가시각(FID21) 형식 오류"
    if age > AUCTION_MAX_AGE_SEC:
        return False, f"동시호가 자료 {age:.0f}초 지연"
    if expected_px <= 0 or expected_qty <= 0:
        return False, f"예상체결가/수량 없음(px={expected_px:.0f}, qty={expected_qty:.0f})"
    if ask <= 0 and bid <= 0:
        return False, "매수·매도 총잔량 없음"
    imbalance = (bid / ask) if ask > 0 else float("inf")
    if imbalance < EOD_OB_WEAK:
        return False, f"동시호가 매도우위 imb={imbalance:.3f}"
    hhmm = now.hour * 100 + now.minute
    if hhmm < AUCTION_DECISION_HHMM:
        return False, f"지속관측 중({hhmm:04d}<{AUCTION_DECISION_HHMM:04d})"
    points = _auction_history(record)
    if len(points) < AUCTION_MIN_SAMPLES:
        return False, f"관측표본 부족({len(points)}/{AUCTION_MIN_SAMPLES})"
    span = (points[-1]["ts"] - points[0]["ts"]).total_seconds()
    if span < AUCTION_MIN_SPAN_SEC:
        return False, f"관측기간 부족({span:.0f}/{AUCTION_MIN_SPAN_SEC:.0f}초)"
    first, last = points[0], points[-1]
    is_locked = bool((record or {}).get("is_locked"))
    reference_px = float((record or {}).get("reference_px") or 0)
    if is_locked:
        if reference_px > 0 and last["px"] < reference_px:
            return False, f"상한가 예상체결가 이탈({last['px']:.0f}<{reference_px:.0f})"
    elif last["px"] < first["px"]:
        return False, f"예상체결가 하락({first['px']:.0f}->{last['px']:.0f})"
    if last["qty"] < first["qty"]:
        return False, f"예상체결수량 감소({first['qty']:.0f}->{last['qty']:.0f})"
    return True, (f"samples={len(points)} span={span:.0f}s px={first['px']:.0f}->{last['px']:.0f} "
                  f"qty={first['qty']:.0f}->{last['qty']:.0f} imb={imbalance:.3f} age={age:.0f}s")


def _write_micro_watch(codes):
    """★종가 후보를 micro_watch_eod에 기록 → broker 실시간 구독(snapshot에 체결강도 채움)."""
    try:
        seen = []
        for c in codes:
            c = str(c).zfill(6)
            if c and c not in seen:
                seen.append(c)
        tmp = MICRO_WATCH_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"codes": seen[:40]}, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(MICRO_WATCH_FILE))
    except Exception:
        pass


def _eod_micro_skip(bc, code, reference_px=0, is_locked=False):
    """★종가 체결강도 확인: 매도우위로 마감(체결강도<WEAK or 호가 매도우위)=다음날 갭 불리 → 매수보류(skip). 데이터없으면 False(통과)."""
    auction = _auction_snapshot(bc, code, reference_px=reference_px, is_locked=is_locked)
    auction_ok, auction_reason = _auction_gate_decision(auction)
    if auction_ok:
        _log(f"  [AUCTION-GATE] {code} PASS {auction_reason}")
    elif AUCTION_GATE_MODE == "LIVE":
        _log(f"★EOD_GAP 매수보류 {code}: [AUCTION-GATE] {auction_reason}")
        return True
    else:
        _log(f"  [AUCTION-SHADOW] {code} WOULD_BLOCK {auction_reason}")
    if not EOD_MICRO_USE:
        return False
    m = _read_micro(code)
    che = (m or {}).get("che_str"); imb = (m or {}).get("imb")
    if che is None:
        return False
    _log(f"  체결강도 {che:.0f}·호가 {imb}")
    if che < EOD_CHE_WEAK or (imb is not None and imb < EOD_OB_WEAK):
        _log(f"★EOD_GAP 매수보류 {code}: 체결강도 {che:.0f}·imb {imb} (종가 매도우위·다음날갭 불리)")
        return True
    return False


def _supply_net(bc, code):
    """opt10059 당일 기관계·외국인투자자 순매수(주). 종가시점=거의확정. 못읽으면 (None,None)."""
    try:
        r = bc.tr("opt10059", inputs={"일자": "", "종목코드": code, "금액수량구분": "2",
                                      "매매구분": "0", "단위구분": "1"},
                  output_fields=["기관계", "외국인투자자"], timeout_sec=10.0)
        recs = ((r or {}).get("data") or {}).get("records") or []
        if recs:
            def _n(v):
                try:
                    return int(float(str(v).replace(",", "").replace("+", "").strip() or 0))
                except (ValueError, TypeError):
                    return None
            return _n(recs[0].get("기관계")), _n(recs[0].get("외국인투자자"))
    except Exception:
        pass
    return (None, None)


def _supply_shadow(today, c, inst, frgn):
    """종가시점 셋업후보 수급+종가 기록(익일갭 검증 토대·익일 갭은 후일 eod_daily_bars로 백필 분석)."""
    accum = (inst is not None and inst > 0) or (frgn is not None and frgn > 0)
    try:
        SUP_DIR.mkdir(parents=True, exist_ok=True)
        f = SUP_DIR / f"sup_{today}.csv"
        new = not f.exists()
        with io.open(f, "a", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(["date", "code", "name", "setup_score", "close", "inst_net", "frgn_net", "accum"])
            w.writerow([today, c[1], str(c[2])[:10], c[0], c[4],
                        inst if inst is not None else "", frgn if frgn is not None else "", int(accum)])
    except Exception:
        pass


def _buy_one(bc, pick, today, held):
    """[MULTIPOS] pick 1건 매수+기록(held 딕셔너리 mutate·RT_OPEN 갱신). 성공 True. 중복/실패시 False."""
    sc, code, nm, eok, px, pv, pc, pb, _lim, w52, ma20over, _dret, _vr, _vrt, *_rest = pick
    if px <= 0:
        _log(f"{code} 가격0 → skip"); return False
    # ★[LOCKED-FLOOR-2 2026-08-14 친구님 승인] 점수 관문이 두 겹이었다.
    #   LOCKED-FIRST 경로(:968)에서 LOCKED_MIN_SCORE 로 통과시켜도 여기서 다시
    #   MIN_SCORE(70)로 잘려 결국 NO_TRADE 였다 — 상한가는 거래가 잠겨 거래대금
    #   점수를 못 받아 최대 28점대다(8/14 실측 5개 전부 탈락).
    #   상한가만 LOCKED_MIN_SCORE, 일반 후보는 종전 MIN_SCORE 그대로.
    #   MAX_POS·상한가 1주(LOCKED_QTY_ONE)·후보순위·주문방식·매도조건은 무변경.
    #   백업: eod_gap_live_executor_v1_20260814_before_buyone_locked_floor.py
    _floor_ok = _passes_locked_score(sc) if bool(_lim) else _passes_final_score(sc)
    if not _floor_ok:
        _log(f"[FINAL-SCORE-GATE] {code} {sc} < "
             f"{LOCKED_MIN_SCORE if bool(_lim) else MIN_SCORE} -> NO_TRADE")
        return False
    if code in held and held[code].get("status") in ("OPEN", "PENDING"):
        return False                              # 이미 보유 → 중복방지
    qty = max(1, int(CAP // px))
    # ★[2026-07-29 친구님 지시 "상한가도 무조건 1주로 해줘 15만원 아니야"]
    #   상한가는 익일 변동폭이 크다(1년 950건 최악 -29.14%). CAP 15만원어치가 아니라 1주만 산다.
    #   비-상한가는 종전대로 CAP 기준 수량. 롤백: setx EOD_GAP_LOCKED_QTY_ONE NO
    if bool(_lim) and LOCKED_QTY_ONE:
        qty = 1
    if QTY_ONE_ALL:
        qty = 1
    if _eod_micro_skip(bc, code, reference_px=px, is_locked=bool(_lim)):
        return False                              # ★종가 매도우위 → 매수보류
    if AUCTION_GATE_MODE == "LIVE":
        replay_ok, replay_reason = _auction_replay_ready()
        if not replay_ok:
            _log(f"★EOD_GAP 매수보류 {code}: [PROD-REPLAY-GATE] {replay_reason}")
            return False
    # [2026-07-17 친구님 "종가매수 통합" 정배열 면제 전면 폐지] 전략A/B 무관 무조건 5>20>60 확인. 데이터없으면 통과(fail-open).
    # ★[2026-07-29 친구님 지시 "상한가만 정배열 면제해"] 상한가(_lim)만 이 관문을 건너뛴다.
    #   근거(일봉 1년·상한가 950건·익일 시가매도·비용 0.38% 차감):
    #     정배열 통과 512건 +6.117%/승률 75.4%  vs  탈락 438건 +5.783%/승률 76.3%
    #     차이 0.334%p뿐이고 승률은 오히려 탈락이 높다 = 상한가에 선별력이 없는데 기회의 46%를 버린다.
    #   비-LOCKED 는 종전대로 관문 유지(거기선 검증하지 않았다). 롤백: setx EOD_GAP_JB_EXEMPT_LOCKED NO
    if bool(_lim) and JB_EXEMPT_LOCKED:
        _log(f"EOD_GAP {code} 정배열 면제(상한가·근거 950건 성과차 0.33%p)")
    else:
        try:
            import trend_filter as _tf
            if not _tf.is_jeongbae(code, "strict"):
                _log(f"EOD_GAP {code} 스킵(정배열 strict 5>20>60 아님)"); return False
        except Exception:
            pass
    # [FOREIGN-GATE 2026-06-28 친구님] 거래원 외국계 매도우세 게이트(env FOREIGN_GATE: LOG/BLOCK)
    try:
        import foreign_supply as _fs
        if not _fs.buy_gate(code, log=_log, tag="EOD_GAP"):
            return False
    except Exception:
        pass
    try:                                           # ★[2026-07-06] 스마트머니 던지기 회피(공용·외국인금액+프로그램 실시간·구foreign버그 보완)
        import smart_money as _SM
        _blk, _smi = _SM.dumping(bc, code, px)
        if _blk:
            _log(f"⛔ EOD_GAP {code} 스마트머니 던지기 차단 [{_smi}] — 매수스킵"); return False
    except Exception:
        pass
    _log(f"★EOD_GAP 매수 {code} {nm} {sc}점 @{px:,.0f} x{qty}={qty*px:,}원 (캡{CAP:,})")
    order_ok = _order(bc, code, qty, "BUY", "PICK")
    if LIVE and LAST_ORDER_STATUS in ("OK", "TIMEOUT"):
        held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px, "score": sc,
                      "date": today, "status": "PENDING", "live": True,
                      "route_tags": PORTFOLIO_ROUTE_TAGS.get(str(code).zfill(6), []),
                      "order_status": LAST_ORDER_STATUS, "ts": datetime.now().isoformat()}
        _jsave(POS, held)
        _log(f"[PENDING] {code} order_status={LAST_ORDER_STATUS}; balance confirmation required")
        return True
    if not order_ok:
        _log("매수 실패/모의 → 기록보류" if LIVE else "모의매수")
        if LIVE:
            return False
    held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px, "score": sc,
                  "date": today, "status": "OPEN", "live": LIVE,
                  "route_tags": PORTFOLIO_ROUTE_TAGS.get(str(code).zfill(6), []),
                  "ts": datetime.now().isoformat()}
    if LIVE:
        rt = _jload(RT_OPEN)
        rt[code] = {"qty": qty, "entry_price": px, "code": code, "strategy": "EOD_GAP",
                    "peak_price": px, "stop_price": round(px * 0.95), "_eodgap": 1,
                    "_chejan_ts": datetime.now().isoformat()}
        _jsave(RT_OPEN, rt)
    return True


def _unified_scores(cands, today, lag):
    """[통일 종가점수 2026-07-02] daily_leader_board 종가점수 방법을 오늘 15:17 데이터로 이식.
       후보 pool 내 (마감강도/상승/추세/거래량/유동성/D-2) 백분위 가중합(0~100). 반환 {code: score}.
       ★선별점수(daily_leader_board)와 동일 가중치(DLB_E_*) 사용 → 아침 순위표와 방법 통일. 실패=빈dict(무영향)."""
    try:
        d2 = {}
        try:
            import supply_signal as _ss
            d2 = _ss.aged_supply_map([c[1] for c in cands], as_of=today, lag=lag) or {}
        except Exception:
            d2 = {}
        W = [float(os.environ.get("DLB_E_CLOSE", "25")), float(os.environ.get("DLB_E_MOM", "25")),
             float(os.environ.get("DLB_E_TREND", "20")), float(os.environ.get("DLB_E_VOL", "15")),
             float(os.environ.get("DLB_E_LIQ", "15")),  float(os.environ.get("DLB_E_SUPPLY", "20"))]
        feats = []   # (code, [마감강도, 상승, 추세(5-60이격), 거래량배수, 유동성, D-2])
        for c in cands:
            dev = c[16] if (len(c) > 16 and c[16] > -900) else 0.0
            feats.append((c[1], [c[6], c[11], dev, c[12], c[3], (d2.get(c[1], 0) or 0)]))
        n = len(feats)
        if n == 0:
            return {}

        def pct(col):
            order = sorted(range(n), key=lambda i: col[i])
            rk = [0.0] * n
            for r, i in enumerate(order):
                rk[i] = (r + 1) / n
            return rk
        prs = [pct([f[1][k] for f in feats]) for k in range(6)]
        wsum = sum(W) or 1.0
        out = {}
        for i, f in enumerate(feats):
            out[f[0]] = round(sum(prs[k][i] * W[k] for k in range(6)) / wsum * 100.0, 1)
        return out
    except Exception:
        return {}


def _rank_locked_by_d2(cands, today):
    """LOCKED끼리 D-2 기관수급 → 기존점수(5일강세 포함) → 거래대금 순."""
    ranked = list(cands)
    d2 = {}
    if SUPPLY_PRIORITY and ranked:
        try:
            import supply_signal as _ss
            d2 = _ss.aged_supply_map(
                [c[1] for c in ranked], as_of=today, lag=SUPPLY_LAG
            ) or {}
        except Exception as exc:
            _log(
                f"[LOCKED-D{SUPPLY_LAG}] 헬퍼 실패 fail-open"
                f"(기존점수 순 유지): {exc}"
            )
    ranked.sort(
        key=lambda c: (
            float(d2.get(c[1], 0) or 0),
            float(c[0]),
            float(c[3]),
        ),
        reverse=True,
    )
    return ranked, d2


def mode_pick():
    today = datetime.now().strftime("%Y%m%d")
    _log(f"=== EOD_GAP pick (LIVE={LIVE} CAP={CAP:,} MAX_POS={MAX_POS} MIN={MIN_SCORE}) ===")
    if not _pick_window_open():
        _log("[TIME-GATE] new entries allowed only from 15:00 through 15:25 -> NO_TRADE")
        return
    _existing = _jload(POS)
    _pending = [c for c, p in _existing.items()
                if isinstance(p, dict) and p.get("status") == "PENDING"]
    if _pending:
        _log(f"[PENDING-GATE] awaiting fill confirmation {_pending} -> block new/repeat order")
        return
    bc = _broker()
    if not bc:
        _log("broker dead → pick 중단"); return
    # ★[FROM_RUNNER] ②랭킹(stage2)을 1번부터 walk: 잠긴 상한가(호가 매도0)면 못 사니 다음 순번으로 → 살 수 있는 첫 놈 매수
    if FROM_RUNNER:
        try:
            sj = json.loads(open(RUNNER_STAGE2, encoding="utf-8").read())
        except Exception:
            sj = {}
        rows = sj.get("rows", []) if str(sj.get("date", "")) == today else []
        if not rows:   # stage2 없으면 단일 pick 폴백
            try:
                pj = json.loads(open(RUNNER_PICK, encoding="utf-8").read())
            except Exception:
                pj = {}
            if str(pj.get("date", "")) == today and pj.get("code"):
                rows = [pj]
        if not rows:
            _log("[FROM_RUNNER] 오늘 ②후보 없음 → NO_TRADE"); return
        # ★공부표(rows)는 상한가부터 10개지만, 실매수는 상한가(+29%↑)만 → 거래대금 큰 순으로 walk
        #   [2026-06-20] 잠긴 상한가는 late_vacc≈0이라 무의미 → 거래대금 큰 순(=살수있을 가능성 큰 순)으로 walk.
        #   1년백테: 거래대금 큰 LOCKED = 잠기기전 체결가능+갭 = '살수있는 거래대금 큰 상한가'. orderbook이 잠긴놈 skip.
        lim = [d for d in rows if float(d.get("chg", 0)) >= 29.0]
        if WALK_SMALL_FIRST:
            lim.sort(key=lambda d: float(d.get("val", 0)))      # 거래대금 작은 순(갭 큰쪽·_buyable이 잠긴놈 거름)
        else:
            lim.sort(key=lambda d: -float(d.get("val", 0)))     # 거래대금 큰 순(기존)
        _log(f"[FROM_RUNNER] walk순서={'작은거래대금부터' if WALK_SMALL_FIRST else '큰거래대금부터'} · 상한가후보 {len(lim)}개")
        if not lim:
            _log("[FROM_RUNNER] 오늘 상한가 없음 → NO_TRADE(비상한가는 갭 엣지0)"); return
        held = _jload(POS)
        if any(p.get("status") == "OPEN" for p in held.values()):
            _log("[FROM_RUNNER] 이미 보유중 → 신규없음"); return
        bought = False
        for rank, d in enumerate(lim, 1):
            code = str(d.get("code", "")).zfill(6); nm = d.get("name", "")
            px = abs(int(float(d.get("px", 0) or 0)))
            if not (1000 <= px <= 500000):
                _log(f"[FROM_RUNNER] ②{rank} {code} {nm} 가격{px} 범위밖 → 다음"); continue
            val_eok = float(d.get("val", 0)) / 100.0
            if VAL_CEIL_EOK > 0 and val_eok >= VAL_CEIL_EOK:
                _log(f"[FROM_RUNNER] ②{rank} {code} {nm} 거래대금{val_eok:.0f}억 ≥ 상한{VAL_CEIL_EOK:.0f}억 → skip(갭다운위험)"); continue
            qty = max(1, int(CAP // px))
            ok, msg = _buyable(code, qty)
            if not ok:
                _log(f"[FROM_RUNNER] ②{rank} {code} {nm} 못삼: {msg} → 다음 순번"); continue
            if _eod_micro_skip(bc, code):
                continue   # ★종가 매도우위 → 다음 순번으로 walk
            try:
                import trend_filter as _tf
                if not _tf.is_jeongbae(code, "strict"):
                    _log(f"[FROM_RUNNER] ②{rank} {code} {nm} 스킵(정배열 strict 아님) → 다음"); continue
            except Exception:
                pass
            try:                                   # ★[2026-07-06] 스마트머니 던지기 회피(공용·외국인+프로그램 실시간)
                import smart_money as _SM
                _blk, _smi = _SM.dumping(bc, code, px)
                if _blk:
                    _log(f"⛔ EOD_GAP[FROM_RUNNER] {code} 스마트머니 던지기 차단 [{_smi}] — 매수스킵"); continue
            except Exception:
                pass
            runner_score = round(float(d.get("score2", 0)))
            if not _passes_final_score(runner_score):
                _log(f"[FINAL-SCORE-GATE] {code} {runner_score} < {MIN_SCORE} -> NO_TRADE")
                continue
            _log(f"★[FROM_RUNNER] ②{rank} {code} {nm} @{px:,} x{qty}={qty*px:,}원 {msg} "
                 f"(거래대금{d.get('val',0)/100:.0f}억·종가{d.get('cp',0)*100:.0f}%·상승{d.get('chg',0):+.0f}%·가속{d.get('late_vacc',0):.1f})")
            order_ok = _order(bc, code, qty, "BUY", "PICK")
            if LIVE and LAST_ORDER_STATUS in ("OK", "TIMEOUT"):
                held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px,
                              "score": runner_score, "date": today, "status": "PENDING",
                              "live": True, "src": "RUNNER", "rank": rank,
                              "order_status": LAST_ORDER_STATUS, "ts": datetime.now().isoformat()}
                _jsave(POS, held); bought = True
                _log(f"[PENDING] {code} order_status={LAST_ORDER_STATUS}; balance confirmation required")
                break
            if not order_ok:
                _log("매수 실패/모의" if LIVE else "모의매수")
                if LIVE: return
            held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px,
                          "score": runner_score, "date": today, "status": "OPEN",
                          "live": LIVE, "src": "RUNNER", "rank": rank, "ts": datetime.now().isoformat()}
            _jsave(POS, held); bought = True; break
        if not bought:
            _log("[FROM_RUNNER] ②후보 전원 못삼(잠김/유동성) → NO_TRADE")
        return
    top = _opt10032_top(bc, TOP_N_UNI)
    if not top:
        cached_top = _load_fresh_live_board_cache()
        if cached_top and LIVE_BOARD_CACHE_FALLBACK:
            top = cached_top
            _log(f"[LIVE-BOARD-CACHE] opt10032 실패 → 당일 2분 이내 캐시 {len(top)}종목 사용")
        else:
            if cached_top:
                _log(
                    f"[LIVE-BOARD-CACHE-SHADOW] fresh cache {len(cached_top)} rows available; "
                    "fallback disabled pending production replay"
                )
            _log("[LIVE-BOARD-GATE] opt10032 empty/error; no same-day <=2m cache -> NO_TRADE")
            return
    # ★[LIMITUP-ADD 2026-07-29] 상한가는 거래가 잠겨 거래대금 상위 N 밖으로 밀린다 → 따로 보탠다.
    limitup_px = {}     # ★유니버스 밖 상한가는 분봉(im)이 없다 → 현재가를 여기서 받아 day_ret 계산에 쓴다
    if LIMITUP_ADD and top:
        _have = {c for c, _n, _v in top}
        _extra = _limitup_extra(bc, _have, max_add=LIMITUP_ADD_MAX)
        if _extra:
            top = top + [(c, n, v) for c, n, v, _p in _extra]
            limitup_px = {c: p for c, _n, _v, p in _extra if p > 0}
            _log("[LIMITUP-ADD] 거래대금 상위 %d 밖 상한가 %d개 보탬 → %s"
                 % (TOP_N_UNI, len(_extra),
                    ", ".join("%s %s(%.0f억)" % (c, (n or "")[:6], v / 100.0)
                              for c, n, v, _p in _extra)))
        else:
            _log("[LIMITUP-ADD] 유니버스 밖 상한가 없음")
    memb = G._load_memb(); block = G._load_block()
    intra = G._intraday(today)
    opt_aft = G._load_opt10032_aft(today)
    prev = _prev_eod()
    # 테마내 거래대금 순위(opt10032 거래대금 기준)
    from collections import defaultdict
    th_vals = defaultdict(list)
    for code, nm, v in top:
        th = memb.get(code)
        if th: th_vals[th].append((v, code))
    vrank = {}
    for th, lst in th_vals.items():
        for i, (v, c) in enumerate(sorted(lst, reverse=True), 1):
            vrank[c] = i
    ntop = len(top)
    cands = []
    for rank0, (code, nm, v) in enumerate(top):
        eok = v / 100.0
        if code in block:
            continue
        pe = prev.get(code, {})
        cl_prev = pe.get("close_prev", 0)
        if cl_prev and not (1000 <= cl_prev <= 500000):
            continue
        im = intra.get(code)
        if im:                                  # 분봉 하드컷
            if not im["vwap_over"]: continue
            if im["upper_wick"] >= 0.5: continue
            if im["late_drop"] <= -3.0: continue
            if im["close_pos"] < 0.3 and im["late_drop"] <= -1.5: continue
        # 점수(공급우선순위 D-2 정렬/타이브레이크용 — 손대지 않음)
        vr = (v / pe["v20"]) if (pe.get("v20") and pe["v20"] > 0) else 0   # 거래대금/20일
        p_val_abs = (1.0 - rank0 / max(ntop, 1)) * 20                      # opt10032 거래대금 순위(1위=만점)
        p_val_20 = 10 if vr >= 3 else 7 if vr >= 2 else 4 if vr >= 1.5 else max(0, (vr - 1) / 0.5 * 4)
        oa = opt_aft.get(code)
        if oa and oa["n"] >= 2:
            p_aft = min(oa["aft_ratio"] / 0.4, 1.0) * 5 + min(oa["late_ratio"] / 0.15, 1.0) * 3 + (2 if oa["sustained"] else 0)
        elif im:
            p_aft = min(im["aft_val_eok"] / 50.0, 1.0) * 5 + min(im["pm_ratio"] / 0.4, 1.0) * 5
        else:
            p_aft = 0
        p_aft = min(p_aft, 10)
        p_value = p_val_abs + p_val_20 + p_aft
        cpos = im["close_pos"] if im else 0.5
        p_close = (8 if (im and im["vwap_over"]) else 0) + cpos * 7 \
            + (5 if im and im["late_drop"] >= -1 else 0) + (max(0, 1 - (im["upper_wick"] if im else 0.3) / 0.5) * 5)
        p_boom = 0
        if im:
            p_boom = min((5 if im["big13"] else 0) + (7 if im["big1430"] else 0) + (5 if im["big_spike"] else 0)
                        + (5 if im["follow"] else 0) + (3 if im["vwap_over"] else 0), 20)
        vrt = vrank.get(code, 99)
        p_theme = 6 if vrt == 1 else 4 if vrt == 2 else 0
        # ★[LIMITUP-ADD 2026-07-29] 유니버스 밖에서 보탠 상한가는 분봉(im)이 없다.
        #   im 이 없으면 cur_close=cl_prev 가 되어 day_ret=0 → is_locked 가 영원히 False 였다.
        #   opt10027 에서 받아둔 현재가로 채워 상한가 판정이 되게 한다.
        cur_close = im["close"] if im else (limitup_px.get(code) or cl_prev)
        p_rs = (3 if (pe.get("c5") and cur_close > pe["c5"]) else 0) + 2
        score = round(p_value + p_close + p_boom + p_theme + p_rs, 1)
        day_ret = (cur_close / cl_prev - 1) if cl_prev else 0   # 당일 상승률
        is_locked = bool(cl_prev and day_ret >= 0.285)   # 종가 상한가(LOCKED)
        _ma5 = pe.get("ma5"); _ma20 = pe.get("ma20"); _ma60 = pe.get("ma60")
        _uw = im["upper_wick"] if im else 0.3
        _body = im.get("body_ratio", 0) if im else 0
        w52 = pe.get("w52", ""); ma20over = (cur_close > pe["ma20"]) if pe.get("ma20") else ""
        _ma200 = pe.get("ma200"); ma200over = bool(_ma200 and _ma200 == _ma200 and cur_close > _ma200)
        _dev5_60 = ((_ma5 / _ma60 - 1) * 100) if (_ma5 and _ma60 and _ma5 == _ma5 and _ma60 == _ma60 and _ma60 > 0) else -999.0

        # [전략A 2026-07-17] 횡보후 장대양봉 돌파: 14:00~15:09 종가박스≤BOX_PCT 후
        #   마지막3틱(15:00~15:16) 캔들이 5일선 걸치거나 위·양봉·몸통≥BODY_MIN·위꼬리≤UW_MAX.
        is_stratA = False
        if STRATA_ON and im:
            bhi = im.get("box_hi") or 0; blo = im.get("box_lo") or 0
            l3n = im.get("l3_n") or 0
            l3o = im.get("l3_open") or 0; l3h = im.get("l3_high") or 0
            l3l = im.get("l3_low") or 0; l3c = im.get("l3_close") or 0
            if (l3n >= 1 and blo > 0 and (bhi / blo - 1) * 100 <= STRATA_BOX_PCT
                    and l3h > l3l and l3c > l3o
                    and _ma5 is not None and _ma5 == _ma5 and l3h >= _ma5
                    and (l3c - l3o) / (l3h - l3l) >= STRATA_BODY_MIN
                    and (l3h - l3c) / (l3h - l3l) <= STRATA_UW_MAX
                    and not is_locked):
                is_stratA = True

        # [전략B 2026-07-17] 수렴선: 정배열(종가>5>20>60) + 5·20일선 수렴(≤CONV_PCT) + 5,20이 60선보다 확실히 위(≥DEV60_MIN)
        is_stratB = False
        if STRATB_ON:
            if (_ma5 is not None and _ma20 is not None and _ma60 is not None
                    and _ma5 == _ma5 and _ma20 == _ma20 and _ma60 == _ma60 and _ma60 > 0
                    and cur_close > _ma5 > _ma20 > _ma60
                    and abs(_ma5 / _ma20 - 1) * 100 <= STRATB_CONV_PCT
                    and (_ma5 / _ma60 - 1) * 100 >= STRATB_DEV60_MIN
                    and (_ma20 / _ma60 - 1) * 100 >= STRATB_DEV60_MIN
                    and not is_locked):
                is_stratB = True

        cands.append((score, code, nm or pe.get("name", ""), eok, cur_close, p_value, p_close, p_boom,
                      is_locked, w52, ma20over, day_ret, vr, vrt, ma200over, _body, _dev5_60,
                      is_stratA, is_stratB))
        # [14]ma200over [15]몸통 [16]5-60이격% [17]전략A [18]전략B
    # ── 정렬: LOCKED 우선(비-LOCKED보다 위), 단 LOCKED 안에서는 점수순 유지 ──
    n_locked = sum(1 for c in cands if c[8])
    if LOCKED_PRIORITY and n_locked:
        cands.sort(key=lambda x: (1 if x[8] else 0, x[0]), reverse=True)
        _log(f"[LOCKED-PRIORITY] 풀내 LOCKED {n_locked}개 → LOCKED 우선(점수순 유지)")
    else:
        cands.sort(key=lambda x: x[0], reverse=True)
    _log(f"opt10032 {len(top)} → 후보 {len(cands)}")
    for c in cands[:5]:
        _log(f"  {c[1]} {c[2][:8]} {c[0]}점{'★L' if c[8] else ''} (거래대금{c[5]:.0f}+종가{c[6]:.0f}+폭발{c[7]:.0f}) {c[3]:.0f}억 w52={c[9]}")
    # [LEADER-ONLY SHADOW 2026-06-24] 대장(테마거래대금1위 vrt==1)+배수≥LEAD_VR_MIN 선별 — 항상 계산(그림자), LEADER_ONLY=YES면 라이브 교체
    _lead = [c for c in cands if len(c) > 13 and c[13] == 1 and c[12] >= LEAD_VR_MIN
             and not c[8] and c[0] >= MIN_SCORE and (LEAD_VR_CEIL <= 0 or c[12] < LEAD_VR_CEIL)]
    leader_pick = _lead[0] if _lead else None   # cands는 점수순 정렬됨 → 첫째=최고점
    _log(f"[LEADER-ONLY·{'LIVE' if LEADER_ONLY else 'shadow'}] 대장+배수≥{LEAD_VR_MIN:g} 후보 {len(_lead)}"
         + (f" → {leader_pick[1]} {leader_pick[2][:8]} {leader_pick[0]}점 배수{leader_pick[12]:.1f}" if leader_pick else " → 없음"))
    # [통일 종가점수 연결 2026-07-02] 오늘 데이터로 통일점수 계산(그림자/라이브 공용). 실패=빈dict(무영향).
    uni = _unified_scores(cands, today, SUPPLY_LAG)
    _isfri = datetime.now().weekday() == 4    # 금요일=주말 홀드
    if uni:
        _utop = sorted(uni.items(), key=lambda kv: -kv[1])[:5]
        _unm = {c[1]: c[2] for c in cands}
        _mode = "LIVE" if UNIFIED_PICK else "그림자"
        _frtag = "·금요일엄선" if (_isfri and UNIFIED_PICK and FRI_UNIFIED_MIN > 0) else ("·금요일(그림자)" if _isfri else "")
        _log(f"[통일점수·{_mode}{_frtag}] top5: " + ", ".join(f"{c} {(_unm.get(c,'') or '')[:6]} {s:.0f}" for c, s in _utop))
    picks = None   # [MULTIPOS] setup분기=리스트 / 레거시분기=단일 pick→아래서 [pick] 변환
    if PORTFOLIO_V2:
        global PORTFOLIO_ROUTE_TAGS
        _held_codes = {
            str(code).zfill(6) for code, row in _jload(POS).items()
            if isinstance(row, dict) and row.get("status") in ("OPEN", "PENDING")
        }
        _d2_all = {}
        if SUPPLY_PRIORITY and cands:
            try:
                import supply_signal as _ss
                _d2_all = _ss.aged_supply_map(
                    [c[1] for c in cands], as_of=today, lag=SUPPLY_LAG
                ) or {}
            except Exception as exc:
                _log(f"[PORTFOLIO-V2] D-{SUPPLY_LAG} 수급 없음 — 기존점수로 정렬: {exc}")
        picks, PORTFOLIO_ROUTE_TAGS = _portfolio_v2_select(
            cands, memb, _d2_all, _held_codes, MAX_POS, unified=uni
        )
        _log("[PORTFOLIO-V2] 상한가≤1·동일테마≤1·중복제거 → "
             + (", ".join(
                 f"{c[1]}({'/'.join(PORTFOLIO_ROUTE_TAGS.get(str(c[1]).zfill(6), []))})"
                 for c in picks
             ) if picks else "후보 없음"))
        if not picks:
            _log("[PORTFOLIO-V2] 3슬롯 조건 통과 후보 없음 → NO_TRADE")
            return
    # ★[LOCKED-FIRST 2026-07-29] 상한가가 있으면 전략A/B보다 먼저 집는다(위 LOCKED_FIRST 주석 참조).
    #   상한가 없으면 picks=None 유지 → 종전 흐름(전략A/B → LEADER_ONLY → SKIP_LOCKED) 그대로.
    if LOCKED_FIRST and n_locked:
        # [LOCKED-FLOOR 2026-08-14] 상한가에는 LOCKED_MIN_SCORE 를 쓴다(기본 0=면제).
        #   종전엔 _passes_final_score(MIN_SCORE 70~75)를 공유해 이 경로가 늘 죽었다.
        _lk = [c for c in cands if c[8] and _passes_locked_score(c[0])
               and _passes_locked_marketcap(c)
               and (VAL_CEIL_EOK <= 0 or c[3] <= VAL_CEIL_EOK)]
        if _lk:
            _lk_d2 = {}
            _locked_d2_live = LOCKED_D2_PRIORITY and (
                not LOCKED_D2_PRIORITY_UNTIL
                or today <= LOCKED_D2_PRIORITY_UNTIL
            )
            if _locked_d2_live:
                _lk, _lk_d2 = _rank_locked_by_d2(_lk, today)
            picks = _lk[:MAX_POS]
            if _locked_d2_live:
                _log(
                    f"[LOCKED-D{SUPPLY_LAG}] D-{SUPPLY_LAG} 기관수급 → "
                    "5일강세 포함 기존점수 → 거래대금 순: "
                    + ", ".join(
                        f"{c[1]} d2={float(_lk_d2.get(c[1], 0) or 0):.0f} "
                        f"score={c[0]:.1f}"
                        for c in _lk[:min(5, len(_lk))]
                    )
                )
            _log("[LOCKED-FIRST] 상한가 %d개 중 상위 %d 매수 (문턱 %g) → "
                 % (len(_lk), len(picks), LOCKED_MIN_SCORE)
                 + ", ".join("%s %s %s점" % (c[1], (c[2] or "")[:6], c[0]) for c in picks))
        else:
            _log("[LOCKED-FIRST] 상한가 %d개 있으나 점수<%g 또는 대금상한 초과 → 종전 경로"
                 % (n_locked, LOCKED_MIN_SCORE))
    if picks is None and (STRATA_ON or STRATB_ON):
        # [2026-07-17 친구님 "종가매수 통합"] 전략A(횡보후돌파) OR 전략B(수렴선) 2택1. 중복종목 제거 안 함.
        _setup = []
        if STRATA_ON:
            _setup += [("A", c) for c in cands if len(c) > 17 and c[17]
                       and (VAL_CEIL_EOK <= 0 or c[3] <= VAL_CEIL_EOK)]
        if STRATB_ON:
            _setup += [("B", c) for c in cands if len(c) > 18 and c[18]
                       and (VAL_CEIL_EOK <= 0 or c[3] <= VAL_CEIL_EOK)]
        _coil = list(_setup)
        _coil.sort(key=lambda tc: -tc[1][3])   # 거래대금 큰순 1차정렬(아래 D-2가 재정렬)
        # [SUPPLY-D2 2026-07-01 친구님·직접백테 교정] 당일 기관수급=익일 역신호(−)·2일전(D-2)=익일+(최강).
        #   우선순위 정렬은 supply_signal D-lag(기본2) 기관 순매수 크기순. 당일수급(_supply_net)은 비교용 그림자만.
        if SUPPLY_PRIORITY and _coil:
            _codes = [_c[1] for _t, _c in _coil]
            try:
                import supply_signal as _ss
                _d2 = _ss.aged_supply_map(_codes, as_of=today, lag=SUPPLY_LAG)   # {code: 기관 D-lag 순매수}
            except Exception as _e:
                _d2 = {}
                _log(f"[SUPPLY-D{SUPPLY_LAG}] 헬퍼 실패 fail-open(거래대금 정렬 유지): {_e}")
            # 당일수급은 비교용 그림자만 기록(랭킹엔 안 씀=역신호라)
            _seen = set()
            for _tag, _c in _coil:
                if _c[1] not in _seen:
                    _seen.add(_c[1])
                    try:
                        _i, _f = _supply_net(bc, _c[1])
                        _supply_shadow(today, _c, _i, _f)
                    except Exception:
                        pass

            def _d2net(code):
                return _d2.get(code, 0) or 0
            # ★[2026-07-01] 종가강도 tiebreaker: D-2 수급이 동점(대개 0=중립)일 때만,
            #   ★오늘(매수일) 데이터로 계산한 오버나잇 강도가 높은 대장을 먼저.
            #   후보 tuple 인덱스: [11]등락율(소수) [12]거래대금배수 [14]200선위 [15]몸통 [16]5-60이격%.
            _eod_tie = os.environ.get("EODGAP_EOD_SCORE_TIE", "YES").strip().upper() == "YES"
            def _eod_today(c):
                if not _eod_tie:
                    return 0.0
                try:
                    ret  = float(c[11]) * 100.0                       # 등락율 %(오늘)
                    body = float(c[15]) if c[15] == c[15] else 0.0    # 몸통 0~1(장대양봉=마감강도)
                    dev  = float(c[16]);  dev = dev if dev > -900 else 0.0   # 5-60이격%(우상향)·결측 sentinel 제거
                    vr   = float(c[12]) if c[12] == c[12] else 0.0    # 거래대금배수(관심)
                    ov2  = 5.0 if c[14] else 0.0                      # 200일선 위 보너스(추세)
                    return body * 30.0 + ret * 1.5 + max(dev, 0.0) * 1.0 + vr * 3.0 + ov2
                except Exception:
                    return 0.0
            # [평일/금요일 다른 기준 2026-07-02 친구님 "평일 점수하고 금요일 점수 다르게"] 통일점수 floor:
            #   평일=UNIFIED_MIN · 금요일=FRI_UNIFIED_MIN(주말 홀드라 더 높게=더 엄선). ★UNIFIED_PICK 무관하게 항상 적용(>0일 때).
            if uni:
                _floor = FRI_UNIFIED_MIN if _isfri else UNIFIED_MIN
                if _floor > 0:
                    _before = len(_coil)
                    _coil = [tc for tc in _coil if uni.get(tc[1][1], 0) >= _floor]
                    _log(f"[통일점수 floor {'금요일' if _isfri else '평일'} {_floor:.0f}] 셋업후보 {_before}→{len(_coil)}개 통과(약한 후보 제외)")
            # [매수 우선순위] UNIFIED_PICK=YES=통일점수 큰 순(라이브 연결) / NO(기본·그림자)=기존(D-2→종가강도→거래대금)
            if UNIFIED_PICK and uni:
                _coil.sort(key=lambda tc: -uni.get(tc[1][1], 0))
                _log("[통일점수 LIVE] 통일점수 큰 순으로 매수 우선순위 재정렬")
            else:
                _coil.sort(key=lambda tc: (-_d2net(tc[1][1]), -_eod_today(tc[1]), -tc[1][3]))
            _npos = sum(1 for _t, _c in _coil if _d2net(_c[1]) > 0)
            _log(f"[SUPPLY-D{SUPPLY_LAG}] 셋업후보 {len(_coil)}개 중 기관 {SUPPLY_LAG}일전 순매수>0 {_npos}개 우선정렬(당일수급=그림자기록·랭킹배제)")
        # [MULTIPOS] 이미 보유 종목/수 파악 → 남은 슬롯(MAX_POS - 보유)만큼 상위 종목 선별
        _opos = {c for c, p in _jload(POS).items() if isinstance(p, dict) and p.get("status") == "OPEN"}
        _slots = MAX_POS - len(_opos)
        if _coil and _slots <= 0:
            _log(f"이미 EOD_GAP {len(_opos)}/{MAX_POS} 보유중 → 신규없음"); return
        picks = []
        for tag, c in _coil:
            if len(picks) >= _slots:
                break
            if c[4] <= 0 or c[1] in _opos:
                continue
            picks.append(c)
            _log(f"[전략{tag}] 매수확정 {c[1]} {c[2][:8]} {c[0]}점 거래대금{c[3]:.0f}억 ({len(picks)}/{_slots}슬롯)")
        _shadow_log(today, picks[0] if picks else None, leader_pick, True)
        if not picks:
            _log(f"[전략A/B] 통과 {len(_coil)}개 — 매수가능 없음(중복/유동성/0개) → NO_TRADE"); return
    elif picks is not None:
        pass                    # ★LOCKED-FIRST 로 이미 골랐다 — 아래 레거시 분기 타지 않는다
    elif LEADER_ONLY:
        _shadow_log(today, leader_pick, leader_pick, True)
        if leader_pick is None:
            _log("[LEADER-ONLY] 대장+배수≥기준 후보 없음 → NO_TRADE"); return
        pick = leader_pick
    elif SKIP_LOCKED:
        # ★잠긴 상한가(호가0=못삼)는 건너뛰고 '살 수 있는' 비잠김 강세주 중 점수≥MIN_SCORE 최고.
        #   + DR_CEIL>0이면 당일 +DR_CEIL%↑ 과열주도 제외(다음날 갭다운 함정).
        buyable = [c for c in cands if not c[8] and c[0] >= MIN_SCORE
                   and (DR_CEIL <= 0 or c[11] < DR_CEIL) and (VR_MIN <= 0 or c[12] >= VR_MIN)]
        if not buyable:
            top_lk = next((c for c in cands if c[8]), None)
            n_over = sum(1 for c in cands if not c[8] and c[0] >= MIN_SCORE and DR_CEIL > 0 and c[11] >= DR_CEIL)
            n_weakvr = sum(1 for c in cands if not c[8] and c[0] >= MIN_SCORE and VR_MIN > 0 and c[12] < VR_MIN)
            _shadow_log(today, None, leader_pick, False)
            _log(f"살수있는 후보 없음 (과열제외 {n_over}·배수<{VR_MIN}제외 {n_weakvr}"
                 f"{' · 잠긴1등 '+str(top_lk[1])+' '+str(top_lk[0]) if top_lk else ''}) → NO_TRADE(약한날 skip)"); return
        pick = buyable[0]
        if DR_CEIL > 0 or VR_MIN > 0:
            _log(f"[필터] 과열<{DR_CEIL:.0%}·배수≥{VR_MIN} → {pick[1]} (당일{pick[11]*100:+.1f}% 배수{pick[12]:.1f})")
        skipped = [c for c in cands if c[8] and c[0] > pick[0]]
        if skipped:
            _log(f"[SKIP_LOCKED] 잠긴 상위 {len(skipped)}개 건너뜀(예:{skipped[0][1]} {skipped[0][0]}점) → 살수있는 {pick[1]} {pick[0]}점 매수")
    else:
        pick_floor = MIN_SCORE
        if not cands or cands[0][0] < pick_floor:
            _shadow_log(today, None, leader_pick, False)
            _log(f"1등 {cands[0][0] if cands else '-'} < {pick_floor}{'(LOCKED)' if (cands and cands[0][8]) else ''} → NO_TRADE"); return
        pick = cands[0]
    if picks is None:   # [MULTIPOS] 레거시분기(leader_only/skip_locked/else)=단일 pick → 리스트화
        if not (LEADER_ONLY or STRATA_ON or STRATB_ON):
            _shadow_log(today, pick, leader_pick, False)
        picks = [pick]
    # [통일점수 그림자 비교] 실제 매수 예정 종목의 통일점수/순위 기록(그림자=정렬무변경·라이브=적용됨)
    try:
        if uni and picks:
            _urank = {c: i + 1 for i, (c, _s) in enumerate(sorted(uni.items(), key=lambda kv: -kv[1]))}
            for _pk in picks:
                _pc = _pk[1]
                _log(f"[통일점수 비교] 실매수 {_pc} {(_pk[2] or '')[:6]} = 통일 {uni.get(_pc, 0):.0f}점"
                     f"(통일순위 {_urank.get(_pc, '?')}/{len(uni)}위)"
                     + (" ← 라이브 적용중" if UNIFIED_PICK else " (그림자·현 로직 그대로 매수)"))
    except Exception:
        pass
    # [MULTIPOS] 남은 슬롯만큼 매수(상위순)·중복방지·각 CAP
    held = _jload(POS)
    open_now = sum(1 for p in held.values()
                   if isinstance(p, dict) and p.get("status") in ("OPEN", "PENDING"))
    # [GLOBAL-BUDGET 2026-06-28 친구님] 전 전략 합산 동시보유 상한
    _grem = 9999
    try:
        import position_budget as _gb
        if _gb.budget_on():
            _grem = _gb.remaining()
            if _grem <= 0:
                _log(f"[GLOBAL-CAP] 전역 실보유 {_gb.total_open()}/{_gb.global_max()} 도달 → 종가매수 보류"); return
    except Exception as _ge:
        _log(f"[GLOBAL-BUDGET] skip({_ge})")
    bought = 0
    for pk in picks:
        if open_now + bought >= MAX_POS or bought >= _grem:
            break
        if _buy_one(bc, pk, today, held):
            bought += 1
            if held.get(pk[1], {}).get("status") == "PENDING":
                _jsave(POS, held)
                break
            _jsave(POS, held)          # [즉시저장 2026-06-29] 매수 직후 영구화 → 크래시시 broker/RT_OPEN/POS 불일치 방지
    if bought:
        _log(f"기록완료 {bought}건 (보유 {open_now + bought}/{MAX_POS}) → {POS}")
    else:
        _log("매수 0건 (중복/실패/보류)")


def mode_sell():
    _log(f"=== EOD_GAP sell (익일 시가매도, LIVE={LIVE}) ===")
    held = _jload(POS)
    # ★[2026-07-30 친구님 "다음날 아침은 매도조건대로 — 우상향이면 끝까지 끌고 가"]
    #   저점매수(route=LOWBUY)는 09:01 일괄 시가매도에서 제외 — 전용 추적 매도기
    #   (eod_gap_lowbuy_sell_v1.py·고점 대비 -3% 꺾임 매도·15:10 강제)가 전담한다.
    #   15:18 종가매수 픽(상한가 포함)은 백테 확정대로 종전 09:01 시가매도 유지.
    #   롤백: backup\eod_gap_live_executor_v1_20260730_lowbuy_sellsplit.py
    opens = {c: p for c, p in held.items()
             if isinstance(p, dict) and p.get("status") == "OPEN"
             and str(p.get("route", "")) != "LOWBUY"}
    if not opens:
        _log("매도할 EOD_GAP 보유 없음(LOWBUY 는 전용 추적 매도기 담당)"); return
    bc = _broker()
    if not bc and LIVE:
        _log("broker dead → 매도불가"); return
    for code, p in opens.items():
        if _sell_with_recovery(bc, code, int(p["qty"])):
            # ★[2026-07-31 #6] 잠금 갱신 — 자기 종목만 고쳐 저장(전용 매도기와 경합 방지)
            _sell_day = datetime.now().strftime("%Y%m%d")
            def _close(h, _c=code, _d=_sell_day):
                row = h.get(_c)
                if isinstance(row, dict):
                    row["status"] = "CLOSED"; row["sell_date"] = _d
            _pos_update_locked(_close)
            if LIVE:
                rt = _jload(RT_OPEN)
                if code in rt and rt[code].get("strategy") == "EOD_GAP":
                    del rt[code]; _jsave(RT_OPEN, rt)
            _log(f"매도 {code} x{p['qty']}")
    # ★[2026-07-31 #6] 마지막 전체 저장(_jsave(POS, held)) 제거 — 시작 때 사본을
    #   통째로 덮어써 전용 매도기의 CLOSED 를 OPEN 으로 되살리던 경합의 원인이었다.


def mode_prefetch():
    """Warm the same-day opt10032 cache without entering the order path."""
    _log("=== EOD_GAP board prefetch (ORDER_PATH=NONE) ===")
    bc = _broker()
    if not bc:
        _log("[PREFETCH] broker dead")
        return
    for attempt in range(1, 3):
        rows = _opt10032_top(bc, TOP_N_UNI)
        if rows:
            _log(f"[PREFETCH] saved {len(rows)} rows attempt={attempt}")
            return
        _log(f"[PREFETCH] empty/error attempt={attempt}/2")
        if attempt < 2:
            time.sleep(1.0)
    _log("[PREFETCH] failed; live fallback remains disabled")


def mode_auction_replay():
    """Replay the current production auction decision on an immutable saved input."""
    now = datetime.now()
    source = AUCTION_AUDIT_DIR / f"auction_{now:%Y%m%d}.jsonl"
    AUCTION_REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    saved = AUCTION_REPLAY_DIR / f"auction_input_{now:%Y%m%d}_{now:%H%M%S}.jsonl"
    report_path = _auction_replay_report_path(now)
    if not source.exists():
        _log(f"[PROD-REPLAY] source 없음: {source}")
        raise RuntimeError("auction replay source missing")
    saved.write_bytes(source.read_bytes())
    latest = {}
    for line in saved.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            code = str(row.get("code") or "").zfill(6)
            if code:
                latest[code] = row
        except Exception:
            continue
    decisions = []
    complete = 0
    for code, row in sorted(latest.items()):
        row = dict(row)
        row["history_path"] = str(saved)
        points = _auction_history(row)
        span = ((points[-1]["ts"] - points[0]["ts"]).total_seconds()
                if len(points) >= 2 else 0)
        raw = row.get("fid") or {}
        hhmmss = "".join(ch for ch in str(raw.get("21", "")) if ch.isdigit())[-6:]
        fresh = False
        try:
            stamp = now.replace(hour=int(hhmmss[0:2]), minute=int(hhmmss[2:4]),
                                second=int(hhmmss[4:6]), microsecond=0)
            fresh = abs((now - stamp).total_seconds()) <= AUCTION_MAX_AGE_SEC
        except Exception:
            pass
        input_complete = (len(points) >= AUCTION_MIN_SAMPLES
                          and span >= AUCTION_MIN_SPAN_SEC and fresh)
        if input_complete:
            complete += 1
        passed, reason = _auction_gate_decision(row, now=now)
        decisions.append({"code": code, "input_complete": input_complete,
                          "decision": "PASS" if passed else "BLOCK", "reason": reason})
    report = {
        "provenance": "[PROD_REPLAY]",
        "date": now.strftime("%Y%m%d"),
        "source_data": str(saved),
        "status": "PASS" if complete > 0 else "FAIL",
        "command": (r"C:\python310\python.exe -X utf8 "
                    r"C:\stock_bot\RUN\eod_gap_live_executor_v1.py auction_replay"),
        "production_entry_point": str(Path(__file__).resolve()),
        "source_sha256": _sha256(saved),
        "replay_engine_sha256": _sha256(Path(__file__)),
        "performance_scope": "DECISION_ONLY",
        "complete_inputs": complete,
        "decisions": decisions,
    }
    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(report_path))
    from trading_report_truth_gate_v1 import validate
    truth_ok, truth_reason = validate(report)
    _log(f"[PROD-REPLAY] status={report['status']} complete={complete} "
         f"truth={truth_reason} report={report_path}")
    if not truth_ok:
        raise RuntimeError(f"auction replay truth gate failed: {truth_reason}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    try:
        if mode == "pick":
            mode_pick()
        elif mode == "sell":
            mode_sell()
        elif mode == "prefetch":
            mode_prefetch()
        elif mode == "auction_replay":
            mode_auction_replay()
        else:
            raise ValueError(f"unknown mode: {mode}")
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)
