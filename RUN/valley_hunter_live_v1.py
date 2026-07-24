# -*- coding: utf-8 -*-
"""🏔️🔥 골짜기 사냥꾼 20분단타 체결강도 매매기 — ★실시간(기본 그림자·주문0)  [2026-07-18 신설]

★crash_flow_live_v1.py(급락주) 복제본으로 출발 → 2026-07-19 밤 매수/매도 로직 독자 개편(더 이상
  급락주 원본과 동일하지 않음, valley_low_buy_v1.py 참고) → 2026-07-20 Gate1 통합: 09:00~09:30
  급락주 시간대까지 이 엔진이 흡수(entry_gate="MORNING_CRASH"·전일종가-5% 기준), 09:30~14:30은
  기존 Gate2(entry_gate="VALLEY_PEAK"·5일선위고점-5% 기준) 그대로 — 저점탐색·매도는 게이트 무관 공통.
  급락주 원본(crash_flow_live_v1.py/low_anchor_buy_v1.py)은 그림자 검증 끝날 때까지 손대지 않고
  실거래 그대로 병행 유지. 슬롯은 실전(VH_LIVE=YES) 전환 후에만 급락주와 shared_slots.py 공유 —
  그림자 동안은 자체 카운터로 격리(_shadow_slot_count, 급락주 실슬롯을 그림자가 뺏는 문제 방지).

친구님 확정 전략 (신규매수 Gate1 09:00~09:30 + Gate2 09:30~14:30 · 15:10 전량청산):
  매수 : valley_low_buy_v1.LowAnchor — 저점 대비 +VLA_OBS_PCT%(기본1~1.5%) 반등 구간에서, RESET 후
         체결강도·매수체결량·매도체결량·거래량 "변화량 추세"(judge_trend)로 반등품질 판정 후 매수
         (★2026-07-19 밤 절대 체결비율105 폐기 — valley_low_buy_v1.py 참고).
  매도 : ★[2026-07-19 밤 최종설계] "최대한 꼭지까지 끌고 가다가 매도세가 매수세를 이기는 순간에만
         판다" — 트리거를 고점대비 -1%에서 "완성된 1분봉이 음봉"으로 교체(중복이라 -1%조건은 삭제).
         ① 음봉관찰 = 완성 1분봉이 음봉으로 마감되는 순간(watch 중이 아닐 때만) RESET 후
           VH_PEAK_WATCH_SEC(10~20초) 동안 점수제 판정 — 체결강도감소·매수체결감소·매도체결증가·
           고점재돌파실패(관찰시작가 재돌파 여부) 4항목 중 VH_SELL_SCORE_TH(기본3)개 이상이면 매도
           (ALL-AND 아님·거래량은 방향 무관 변화율만 로그참고용, 점수 미반영). 관찰 중 새 고점이
           찍히면(매수가 이겼다는 뜻) 관찰 취소·계속 보유 — 양봉→음봉→양봉→음봉 반복돼도 매수세가
           살아있는 한 계속 들고 간다. 관찰 시작~종료는 전수 SELL_LOG(성공/실패 무관)로 남긴다.
         ★[2026-07-19 밤 역할분리] 매도엔진(위 음봉관찰 점수제)=실제 매도결정 / 5일선=추세확인만
         (직접매도 안 함 — 매수 후 5일선을 한 번 회복한 종목이 다시 이탈하면 "추세약화" 참고신호로만
         써서 점수제 문턱을 SELL_SCORE_TH-1로 낮춤=같은 신호에도 더 빨리 청산. 처음부터 5일선 아래서
         매수돼 회복한 적 없으면 미적용 — "약화"를 판단할 기준점이 없어서. 5일선을 지키는 동안은
         문턱 그대로 두고 매도엔진의 HOLD를 신뢰) / 10일선=최후보험선(추세종료 판정).
         ② 보험선(2층) = 고점대비 VH_INSURE_PCT(-1.5%, 실시간·빠른반응) 하회 **또는**
           10일선이탈(하루 1회 계산·구조적) — 둘 중 하나만 걸려도 조건과 무관하게 즉시 전량매도.
           10일선은 장중 급락을 못 따라가서 -1.5%가 그 공백을 보완 — 대체가 아니라 이중 안전판.
         ③ 하드손절 -2.5% 단일(구 -2%/-4% 이원·목표익절 전부 폐기)   ④ 15:10 전량청산
  유니버스 : 코스닥·1만원↑·어제대금 700억~2조 (급락주와 동일 조건 그대로 복사)
  정렬     : 갭하락(시가 전일比 -3%↓) 무조건 1순위 → 깊이순 (급락주와 동일)

■ ★안전 (급락주 구조 그대로)
  VH_LIVE=NO 가 기본 = 실주문 0(그림자). 실전 전환은 cmd(SAFEPLUS_VALLEY_HUNTER_LIVE.cmd)가 VH_LIVE=YES 설정.
  끄기 = config\\valley_off.flag 생성(다음 기동부터 그림자).
  장중 즉시정지 = config\\manual_buy_block.flag (급락주·아침대장과 공용 — 매수 차단·매도는 계속).
  주문 격리 rqname=VALLEY_ (급락주 CRASHFLOW_·아침대장·깊은바닥과 분리). 실주문 켤 땐 관문 ONLY_MF_ALLOW에
  VALLEY 추가 등록 필요(안 하면 7/14 사고형으로 조용히 주문 거부됨 — 지금은 그림자라 미등록 상태).

■ ★실시간 봉 주의 (교훈 top-sell-frame-bug)
  양봉→음봉은 '완성봉'으로만 판정한다(돈맥_1분봉.json prev = 직전 완성봉들). 진행중 봉으로 안 판다.

■ 스위치
  VH_LIVE=NO         실주문 (기본 NO=그림자·주문0)
  VH_CAP             종목당 금액 (기본 SAFEPLUS_CAP_KRW=30만)   VH_SLOTS=6(급락주와 공유 슬롯 총량과 일치시킬 것)
  (★재난손절 VH_STOP·목표익절 VH_TARGET_PROFIT_PCT·유니버스낙폭 VH_DROP·방어선 VH_DEFENSE
   전부 폐기됨 — 하드손절은 valley_low_buy_v1.VLA_REBUY_STOP=-2.5% 하나로 통합, 5일선은
   매도 결정에 안 쓰고 점수제 문턱 조정용 참고신호로만 사용)
  VH_ENTRY=0930 VH_ENTRY_END=1430   신규 매수 허용 시각(14:30 이후 신규매수 금지, 매도는 계속)
  VH_INSURE_PCT=-1.5    보험선(1층, 실시간) — 고점대비 이 이상 빠지면 조건 무관 즉시 전량매도
  ★10일선 이탈(2층, 구조적) = 회복 후 재이탈 시에만 최후보험선 활성화(즉시 전량매도, 별도 env 없음)
  VH_PEAK_WATCH_SEC=10  완성음봉 후 관찰 시간(초, 10~20 권장, 데드라인) — 이 시점에 강제 판정
  VH_SELL_TREND_MARGIN_PCT=10  매도 관찰의 "확연히" 판정 마진(%, 매수 VLA_TREND_MARGIN_PCT와 별도값)
  VH_SELL_SCORE_TH=3    매도점수 문턱(4개 항목 중 이 개수 이상이면 매도확정·5일선회복후재이탈시 -1)
  VH_PVAL_MIN=700 VH_PVAL_MAX=20000   전일 거래대금 하한/상한(억)
  VH_VOLSURGE_MULT=2.0 VH_VOLSURGE_DAYS=5   당일 거래량이 최근N일 평균(경과시간 비례) 대비 이 배수 이상만 허용
  VH_EXIT=1510   VH_END=1512
  ★매수 진입 문턱(VLA_OBS_PCT/VLA_WATCH_MIN/VLA_TREND_MARGIN_PCT/VLA_PEAK_DROP_PCT)은 valley_low_buy_v1.py 참고
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\stock_bot\RUN")
import shared_slots as shared      # 공통 슬롯 장부(아침대장·급락주와 공유 — 2026-07-18 친구님 지시)
from valley_low_buy_v1 import la_from_ledger, la_to_ledger, REBUY_STOP, REBUY_MAX, _trend_desc, judge_trend, direction_persists, trend_pct_changes   # 저점구간 판정+저점재매수, 매도관찰 추세공유

SNAP   = Path(os.environ.get("VH_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
BARS1M = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
POOL   = Path(r"C:\stock_bot\data\돈맥_전일상위풀.json")
CHE    = Path(r"C:\stock_bot\data\돈흐름_che_state.json")
EOD    = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
NAMEC  = Path(r"C:\stock_bot\data\_code_name_cache.json")
LEDGER = Path(os.environ.get("VH_LEDGER") or r"C:\stock_bot\data\valley_hunter_live_ledger.json")
CSVLOG = Path(os.environ.get("VH_CSV") or r"C:\stock_bot\LOG\valley_hunter_live.csv")
# ★[2026-07-20 친구님 승인 — 캡틴 ㉮ 이식] 지시가→실체결가 괴리 실측(captain_slip.csv와 동일 형식)
SLIPCSV = Path(os.environ.get("VH_SLIPCSV") or r"C:\stock_bot\LOG\valley_slip.csv")
LOG    = Path(r"C:\stock_bot\data\LOG\valley_hunter_live.log")

# ★[2026-07-20 안정성 패치①] 루프당 1회만 읽는 스냅샷 캐시 — 전략 무변경, 종목별 반복 파일읽기
#   (_cur/_che/_che_info/_cum_vol/_bar1m가 종목마다 각자 파일을 다시 열던 것) 제거용.
_MCACHE = {"snap": {}, "che": {}, "che_mtime": 0.0, "bars1m": {}}


def _refresh_market_cache():
    """루프 시작 시 1회 호출 — SNAP/CHE/BARS1M을 읽어 메모리에 고정. 실패해도 직전 캐시 유지(fail-open)."""
    try:
        _MCACHE["snap"] = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        pass
    try:
        _MCACHE["che"] = json.loads(CHE.read_text(encoding="utf-8-sig"))
        _MCACHE["che_mtime"] = CHE.stat().st_mtime
    except Exception:
        pass
    try:
        _MCACHE["bars1m"] = json.loads(BARS1M.read_text(encoding="utf-8-sig"))
    except Exception:
        pass

LIVE     = os.environ.get("VH_LIVE", "NO").strip().upper() == "YES"
# ★[2026-07-20 친구님 승인 — 15:13 FLAT 전용 계좌 점검] 기본 NO(본 실전 09:00 cmd는 손대지 않음).
#   VALLEY_FLAT.cmd에만 YES로 설정 — 골짜기 ledger가 이미 알고 있는 종목만 계좌수량과 대조,
#   로그·경고만 남기고 자동 매수/매도/장부 생성삭제는 절대 안 함(수동보유·타전략 오인 방지).
ACCT_CHECK = os.environ.get("VH_ACCT_CHECK", "NO").strip().upper() == "YES"
CAP      = float(os.environ.get("VH_CAP") or os.environ.get("SAFEPLUS_CAP_KRW", "300000"))
SLOTS    = int(os.environ.get("VH_SLOTS", "6"))
# ★[2026-07-19 친구님 지시 "내일 매입은 1주씩만·30만원은 최소(과함)"] >0이면 종목당 고정 주수
#   매수(금액 무시). 0=기존 CAP 금액 방식. 실전 첫날 위험 최소화용 — 롤백은 cmd에서 이 줄 제거.
QTY_FIX  = int(os.environ.get("VH_QTY_FIX", "0"))
# ★[2026-07-19 심야 친구님 "내일 실전에 연결"] 제3 게이트 = 응집폭발(BASE_BREAKOUT) — 백테 26일
#   48건 승률54% PF1.18 확정 프레임 그대로: 베이스 30봉 진폭≤3% + 거래량 5배 + 상단돌파 →
#   추격 금지·돌파선 리테스트 지정가 → 전용 출구(목표+2%/손절-1.5%/15:10). 매수는 기존 파이프라인
#   (_execute_buy: 체결확인·유령방지·1주고정·공유슬롯·관문) 공용, 매도만 전용 분기. VH_BB=NO면 꺼짐.
BB_ON    = os.environ.get("VH_BB", "NO").strip().upper() == "YES"
BB_BASE_N = int(os.environ.get("VH_BB_BASE_N", "30"))
BB_TIGHT = float(os.environ.get("VH_BB_TIGHT", "3.0"))
# ★[2026-07-23 거래량 필터 상향 5→6배] 4거래일(7/20~23) 완결 11건 실측 검증:
#   <6.0배 4건 1승3패(비용후 -4.38%p) / ≥6.0배 7건 5승2패(비용후 +0.35%). 5배 대비 승률 55→71%.
#   실전 BASE_BREAKOUT 경로만 상향(급락반등·캡틴2·골짜기 타 진입 무변경). 그림자 관찰기는 5배 유지(광역수집).
BB_VOLX  = float(os.environ.get("VH_BB_VOLX", "6.0"))
BB_WAIT  = int(os.environ.get("VH_BB_WAIT", "10"))
BB_TGT   = float(os.environ.get("VH_BB_TGT", "2.0"))
BB_STP   = float(os.environ.get("VH_BB_STP", "-1.5"))
BB_ENTRY = os.environ.get("VH_BB_ENTRY", "0930")
BB_ENTRY_END = os.environ.get("VH_BB_ENTRY_END", "1430")


def _bb_detect(hist, base_n=None, tight=None, volx=None):
    """응집폭발 순수 판정(그림자와 동일 로직·단위시험용) — hist=[(hm,o,h,l,c,v)] 완성봉.
    마지막 봉이 폭발이면 (베이스상단, 진폭%, 거래량배수) 아니면 None."""
    base_n = base_n or BB_BASE_N
    if len(hist) < base_n + 1:
        return None
    base = hist[-(base_n + 1):-1]
    _hm, o, h, l, c, v = hist[-1]
    bhi = max(b[2] for b in base)
    blo = min(b[3] for b in base)
    if blo <= 0:
        return None
    rng = (bhi / blo - 1) * 100
    if rng > (tight or BB_TIGHT):
        return None
    av = sum(b[5] for b in base) / len(base)
    if not (c > o and c > bhi and av > 0 and v >= av * (volx or BB_VOLX)):
        return None
    return bhi, round(rng, 2), round(v / av, 1)
# ★[2026-07-19 심야 통합패치] 구 -2%재매수손절/-4%재난손절 이원 체제를 -2.5% 단일 하드손절로
#   통합(REBUY_STOP은 valley_low_buy_v1.py에서 import·이미 -2.5로 변경됨) — 원래 -2%가 항상
#   먼저 걸려 -4%는 도달 불가능한 죽은 조건이었다. VH_STOP/VH_TARGET_PROFIT_PCT(목표익절)도
#   함께 폐기 — 목표익절은 고점 매도엔진이 수익을 끌고 가도록 삭제(사용자 지시).
# ★[2026-07-19 심야] 매도 트리거를 "고점대비 -1%"에서 "완성된 1분봉이 음봉"으로 교체.
#   철학: 최대한 꼭지까지 끌고 가다가 매도세가 매수세를 이기는 순간에만 판다. 음봉이 나와도 그 자체는
#   매도신호가 아니라 "매도 관찰모드 진입 신호"일 뿐 — 관찰(10~20초) 동안 점수제로 진짜 악화인지 확인.
#   고점대비 -1% 관찰시작 조건은 삭제(음봉 트리거가 이미 그 역할을 함 — 중복조건 배제).
#   ★[2026-07-19 밤 역할분리] VH_DEFENSE(d5/ma5 방어선)는 폐기(5일선은 더 이상 직접 매도조건이
#   아니라 점수제 문턱 조정용 참고신호일 뿐). 고점대비-1.5% 보험선(빠른 반응)과 10일선(구조적)은
#   층위가 달라서 둘 다 유지 — 10일선은 하루 한 번만 갱신돼 장중 급락엔 못 따라가므로 -1.5%가 보완.
INSURE_PCT     = float(os.environ.get("VH_INSURE_PCT", "-1.5"))   # 보험선 — 고점대비 이 이상 빠지면 조건 무관 즉시 전량매도
PEAK_WATCH_SEC = float(os.environ.get("VH_PEAK_WATCH_SEC", "10"))   # 관찰 시간(초, 10~20 권장) — 이 시점에 강제 판정(데드라인)
# ★[2026-07-19 밤] 절대 매도비율(구 VH_PEAK_SELL_RATIO=50) 폐기 — 매수쪽(반등품질)과 동일하게
#   관찰시작 시점 RESET 후 체결강도·매수체결량·매도체결량 "변화량 추세"+고점재돌파 여부를 점수제로 판정
#   (ALL-AND 아님 — 고점에서 4개 신호가 동시에 안 뜨고, 거래량은 패닉/정상눌림에 따라 증감이 갈려서 제외).
SELL_TREND_MARGIN_PCT = float(os.environ.get("VH_SELL_TREND_MARGIN_PCT", "10"))   # "확연히" 판정 마진(%)
SELL_SCORE_TH = int(os.environ.get("VH_SELL_SCORE_TH", "3"))   # 4개 항목 중 이 점수 이상이면 매도확정
# ★[2026-07-19 재매수개선] 30분 시간쿨다운 폐기(사용자 지시) — 재매수는 시간이 아니라 "새 저점 사이클"
#   완성으로만 통제한다. 매도 시 anchors[code]를 pop하면(아래 SELL 처리부) LowAnchor가 통째로
#   리셋(ma5_above_peak=None부터)되므로, 다음 매수는 반드시 ①새 고점형성 ②그 고점대비 새로
#   -5%하락 ③새 3연속1분음봉+양봉전환 ④반등품질 재통과를 전부 새로 거쳐야만 한다(이전 저점 재사용 불가).
SELL_LOG = Path(r"C:\stock_bot\LOG\valley_sell_watch.csv")   # 관찰 시작~종료 전수 기록(매도/보류·신고점조기취소 포함 전부) — 매도패턴 학습용
SELL_LOG_COLS = ["일자", "종목코드", "종목명", "음봉발생시각", "관찰시작", "관찰종료", "관찰시간초",
                  "체결강도변화율", "매수체결변화율", "매도체결변화율", "거래량변화율",
                  "고점재돌파", "결과", "매도사유"]

PX_FLR   = float(os.environ.get("VH_PX_FLOOR", "10000"))
# ★[2026-07-19 심야] 코드 기본값을 운영 cmd 값(700억)과 통일. 상한 2조는 그대로.
PVAL_LO  = float(os.environ.get("VH_PVAL_MIN", "700"))
PVAL_HI  = float(os.environ.get("VH_PVAL_MAX", "20000"))
GAP_TH   = float(os.environ.get("VH_GAP_TH", "-3"))    # 갭하락 1순위 문턱(시가 전일比 %)
# ★[2026-07-19 심야] 당일 동일시간 거래량이 최근평균 대비 이 배수 이상인 종목만 허용(거래량 급증 필터).
#   "동일 시간대" 과거 분봉 이력은 없어 근사한다: 최근 VOLSURGE_DAYS일 평균 일거래량 ×
#   (경과분/세션전체분)을 "이 시각까지의 기대거래량"으로 보고, 실제 당일 누적거래량이 이 배수
#   이상이면 통과.
VOLSURGE_MULT = float(os.environ.get("VH_VOLSURGE_MULT", "2.0"))
VOLSURGE_DAYS = int(os.environ.get("VH_VOLSURGE_DAYS", "5"))
SESSION_MIN   = float(os.environ.get("VH_SESSION_MIN", "390"))   # 09:00~15:30 세션 전체 분(경과비율 계산용)

# ★[2026-07-21 Money Flow 감지 개선(최종) → 골짜기 연동 — 오사장님 승인] MONEY_FLOW_ENTRY —
#   micro_rank_engine_v1.py가 이미 계산해둔 money_add_5s(최근5초 신규유입)·MONEY_START(TRUE/FALSE,
#   신규유입 증가 AND 신규유입 속도 증가 AND 체결강도 증가의 단순 AND — micro_rank_engine_v1.py
#   에서 계산)만 그대로 읽어(새 계산·새 점수·새 상태머신 없음) TOP5만 골짜기 관찰 대상에 추가하는
#   셋째 진입경로 하나만 추가. 기존 MORNING_CRASH·VALLEY_PEAK(위 order 루프)는 완전 무접촉.
#   기본 잠금(OFF) — VH_MFE_ENABLE=YES로만 켜짐.
MFE_ENABLE = os.environ.get("VH_MFE_ENABLE", "NO").strip().upper() == "YES"
MFE_BOARD  = Path(r"C:\stock_bot\data\micro_rank_board.json")
MFE_TOP_N  = int(os.environ.get("VH_MFE_TOP_N", "10"))
# ★[2026-07-21 오사장님 지시] MONEY_START 후 추가 필터 4개(전부 기존 데이터소스 재사용 — 새 계산 없음):
#   최근30초 신규거래대금·주가·전일거래대금(POOL, 급락주/Gate2와 동일 파일)은 여기서만 적용,
#   money_start 자체 계산식은 무변경.
MFE_MIN_MONEY_30S = float(os.environ.get("VH_MFE_MIN_MONEY_30S", "30000000"))   # 3,000만원
MFE_MIN_PRICE     = float(os.environ.get("VH_MFE_MIN_PRICE", "10000"))          # 10,000원
MFE_MIN_PVAL      = float(os.environ.get("VH_MFE_MIN_PVAL", "100"))             # 전일 거래대금 100억(단위=억)


def _money_flow_top5():
    """Money Flow TOP10(함수명은 최초 TOP5 버전 이름 유지 — 호출측 무변경 위해) — micro_rank_engine_v1.py가
    계산한 MONEY_START=True(2~3초 유지 확정) AND 최근30초 신규거래대금≥3천만 AND 주가≥1만원 AND
    전일거래대금≥100억(POOL 재사용)인 종목만, money_add_5s(가장 최근·즉각적인 신규유입액) 내림차순으로
    상위 N개. 새 계산·새 점수 없음(전부 기존 필드·기존 파일 그대로 읽기전용). {code:{"name":str}}
    반환(오늘자 아니면 빈 dict — fail-closed)."""
    try:
        board = json.loads(MFE_BOARD.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if str(board.get("date") or "") != datetime.now().strftime("%Y%m%d"):
        return {}
    try:
        pool = json.loads(POOL.read_text(encoding="utf-8-sig"))
        pvm = {str(c).zfill(6): float(v) for c, px, v in pool.get("rows", [])}
    except Exception:
        pvm = {}
    cands = []
    for it in (board.get("all_items") or []):
        code = it.get("code")
        if not code or not it.get("money_start"):
            continue
        if (it.get("money_30s_now") or 0) < MFE_MIN_MONEY_30S:
            continue
        if _cur(code) < MFE_MIN_PRICE:
            continue
        if pvm.get(code, 0.0) < MFE_MIN_PVAL:
            continue
        add = it.get("money_add_5s") or 0
        cands.append((add, code, it.get("name") or ""))
    cands.sort(key=lambda x: -x[0])
    return {c: {"name": n} for _, c, n in cands[:MFE_TOP_N]}


# ★[2026-07-21 오사장님 지시 — TRUE_LEADER 우선검토 + "부하를 끌고 있는 대장" 가중치]
#   theme_leader_shadow_v1.py가 이미 계산해둔 값 그대로 재사용(새 계산 없음). 정렬 우선순위에만
#   쓰고 기존 골짜기 진입조건(READY/BUY/SELL)은 전혀 안 건드림.
TL_JSON = Path(r"C:\stock_bot\data\테마주도주.json")


def _true_leader_info():
    try:
        d = json.loads(TL_JSON.read_text(encoding="utf-8-sig"))
        if str(d.get("date") or "") != datetime.now().strftime("%Y%m%d"):
            return {}
        return {str(x.get("code")).zfill(6): int(x.get("members") or 0)
                for x in (d.get("true_leaders") or []) if x.get("code")}
    except Exception:
        return {}


# ★[2026-07-21 오사장님 지시 — 기관·외국인 수급 보조 확인] 새 TR·새 엔진 없음. 이미 실전 가동 중인
#   money_flow_board_v1.py가 opt10059/opt90013로 미리 조회해 5초 폴링으로 계속 갱신해두는
#   data\돈흐름_선별판.json(rows[].inst/frgn/prog/acc10)을 읽기전용으로 그대로 재사용한다.
#   Money Flow(MONEY_START) 판정 자체와는 완전 분리 — 이 조회가 실패/누락돼도 MONEY_START·
#   매수 진행에는 전혀 영향 없음(표시·검증로그 전용, "매수를 막지 않는다").
MFLOW_SUPPLY_BOARD = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
MFE_SUPPLY_LOG = Path(r"C:\stock_bot\data\shadow\money_flow_supply_check.csv")


def _supply_lookup():
    """{code: row} — 실패해도 빈 dict(보조정보라 fail-open, 매수 안 막음)."""
    try:
        d = json.loads(MFLOW_SUPPLY_BOARD.read_text(encoding="utf-8-sig"))
        return {str(r.get("code")).zfill(6): r for r in (d.get("rows") or []) if r.get("code")}
    except Exception:
        return {}


def _supply_score(row):
    """★[2026-07-21 오사장님 지시 — 기관/외국인 우선순위 가중치] 매수를 막지 않음(사양3 그대로
    유지) — 후보 여러 개 경쟁 시 정렬 우선순위에만 가산. 기관>0·외국인>0·프로그램>0 각 1점(0~3점).
    row 없으면 0점(정보 없다고 뒤로 밀지 않음 — 그냥 가중치가 안 붙을 뿐, fail-open)."""
    if not row:
        return 0
    return sum(1 for k in ("inst", "frgn", "prog") if (row.get(k) or 0) > 0)


def _supply_tags(row):
    """PROGRAM▲/FOREIGN▲/INSTITUTION▲ 표시용 — row 없으면 '수급정보없음'(매수 무관, 표시만)."""
    if not row:
        return "수급정보없음"

    def tag(label, v):
        v = v or 0
        return f"{label}{'▲' if v > 0 else ('▼' if v < 0 else '-')}"

    return f"{tag('PROGRAM', row.get('prog'))} {tag('FOREIGN', row.get('frgn'))} {tag('INSTITUTION', row.get('inst'))}"


def _log_supply_check(code, name, entry_px, row):
    """★사양5(검증) — MONEY_FLOW로 실제 매수된 종목만 기관/외인/프로그램 유입 여부를 기록해
    나중에 통계 낸다. 필터로는 아직 안 씀(검증 전)."""
    try:
        MFE_SUPPLY_LOG.parent.mkdir(parents=True, exist_ok=True)
        new = not MFE_SUPPLY_LOG.exists()
        with MFE_SUPPLY_LOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "code", "name", "entry_px", "inst", "frgn", "prog", "indiv", "acc10"])
            r = row or {}
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code, name, entry_px,
                        r.get("inst"), r.get("frgn"), r.get("prog"), r.get("indiv"), r.get("acc10")])
    except Exception as e:
        _log(f"  ⚠️수급검증로그 실패(무시): {e}")
# ★[2026-07-19 심야] 신규매수 09:30~14:30만 허용(14:30 이후는 보유종목 매도만 계속·15:10 전량청산).
ENTRY_HM = os.environ.get("VH_ENTRY", "0900")   # ★[7/19 구조 정상화 8] 기본값=운영값(Gate1 09:00) 정렬
ENTRY_END = os.environ.get("VH_ENTRY_END", "1430")
# ★[2026-07-22 친구님 "5선위는 캡틴2가 더 잘 잡을 것 — 은퇴"] Gate2(VALLEY_PEAK·5일선위고점-5%)
#   전용 스위치. NO면 09:30 이후 Gate2 후보 유니버스를 비워 신규 VALLEY_PEAK 진입만 중단한다.
#   Gate1(급락주 09:00~09:30)·제3게이트(BB)·MONEY_FLOW READY·매도/보유 관리는 전부 무접촉.
#   (진입창 ENTRY_END를 줄이는 방식은 같은 블록 안의 BB 게이트까지 죽여서 쓰지 않는다)
GATE2_ON = os.environ.get("VH_GATE2", "YES").strip().upper() == "YES"
EXIT_HM  = os.environ.get("VH_EXIT", "1510")
END_HM   = os.environ.get("VH_END", "1512")
LOOP_SEC = float(os.environ.get("VH_LOOP_SEC", "2"))
RUN_SEC  = float(os.environ.get("VH_RUN_SEC", "55"))
# 접수OK ≠ 체결(실체결은 Chejan 별도) — 매수 후 FILL_WAIT초 안에 게이트웨이 fills CSV에서 체결확인
# 못 하면 미체결 잔량 취소 → 유령 판정. 확인 전엔 보유 아님(매도 안 함). 급락주와 동일 구조.
FILL_WAIT = float(os.environ.get("VH_FILL_WAIT", "8"))

COLS = ["일자", "시각", "종목코드", "종목명", "방향", "사유", "체결강도", "고점", "저점",
        "현재가", "일봉5일선", "진입가", "수익퍼센트", "재매수회차", "실전여부", "주문결과",
        "반등품질", "구간매수량", "구간매도량", "판정사유", "진입출처"]

# ★주문 최후 관문 미러 — VALLEY rqname은 급락주(CRASHFLOW)와 마찬가지로 MFLOW 예외가 없으면
#   브로커 관문의 가격하한(SAFEPLUS_MIN_PRICE)·시총하한(SAFEPLUS_MIN_MARKETCAP)이 그대로 적용된다.
#   지금 가격으로 못 살 종목은 주문 시도 자체를 건너뛴다(2초마다 조용한 거부 반복 방지).
#   발행주식수 모르면 통과(fail-open) = 진짜 관문(broker_client)이 최종 방어. 관문 로직과 반드시 거울 유지.
GATE_MINP  = float(os.environ.get("SAFEPLUS_MIN_PRICE", "1000"))
GATE_MINMC = float(os.environ.get("SAFEPLUS_MIN_MARKETCAP", "0"))
SHARES_CSV = Path(r"C:\stock_bot\DATA\shares_outstanding.csv")
_shares_map = None
_gate_warned = set()


def _shares_of(code):
    """발행주식수 (broker_client._load_shares_cache와 같은 CSV). 모르면 0."""
    global _shares_map
    if _shares_map is None:
        m = {}
        try:
            with SHARES_CSV.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    try:
                        m[str(r.get("code", "")).zfill(6)] = float(r.get("shares") or 0)
                    except Exception:
                        pass
        except Exception:
            pass
        _shares_map = m
    return _shares_map.get(str(code).zfill(6), 0.0)


def _gate_ok(code, cur):
    """False = 이 가격으론 브로커 주문 관문(가격·시총 하한)이 거부한다."""
    if 0 < cur < GATE_MINP:
        return False
    if GATE_MINMC > 0 and cur > 0:
        sh = _shares_of(code)
        if sh > 0 and sh * cur < GATE_MINMC:
            return False
    return True


def _log(m):
    # ★[2026-07-21] 날짜 스코프 — 기존 [HH:MM:SS]엔 날짜가 없어 로그가 여러 날 누적되면
    #   일자별 리포트(valley_day1_report.py)가 다른 날 줄까지 섞어 읽는 문제가 있었음.
    #   [YYYYMMDD HH:MM:SS]로 확장(기존 줄은 구형 포맷 그대로 남음 — 소급 변경 안 함).
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y%m%d %H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _jload(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _cur(code):
    try:
        v = _MCACHE["snap"].get(str(code).zfill(6)) or {}
        # 브로커 재기동 후 스냅샷에 어제 시세가 잔존 — ts가 있고 오늘이 아니면 무시(ts 없으면 기존대로 신뢰)
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return 0.0
        return float(v.get("cur", 0) or 0)
    except Exception:
        return 0.0


def _che(code):
    """현재 체결강도(che_state.json last). 없으면 0. 매수결정에는 안 씀 — 로그 비교용."""
    try:
        v = _MCACHE["che"].get(str(code).zfill(6))
        if isinstance(v, dict):
            return float(v.get("last", 0) or 0)
    except Exception:
        pass
    return 0.0


# ★[2026-07-19 수정지침2] 체결강도 공급 상태 — 보드(che_state) 우선, 미등재면 게이트웨이 스냅샷의
#   실측 체결강도(che_str·체결 콜백 직산출)로 폴백. 가격 방향 기반 추정·0 대체 금지(지침) —
#   둘 다 없거나 낡으면 상태코드 반환 → 경로① 매수판정 자연 금지(관찰·무장은 계속).
CHE_STALE_SEC = float(os.environ.get("VH_CHE_STALE_SEC", "120"))


def _che_info(code):
    """(status, che, age_sec) — status: OK / CHE_STALE / CHE_MISSING / CHE_NOT_SUBSCRIBED.
       ★[2026-07-20 안전성 패치②] 검증 결과 che_state.json엔 종목별 'last 갱신시각'이 없음
       (lo_ts는 세션 저점 시각이라 의미가 다름 — 오용하면 신선도 오판) → 파일 mtime 방식 그대로 유지.
       SNAP 폴백 경로는 원래도 레코드별 ts(종목별 실측)를 쓰고 있어 그대로 둠."""
    code = str(code).zfill(6)
    now_t = time.time()
    try:
        d = _MCACHE["che"]
        v = d.get(code)
        if isinstance(v, dict):
            age = now_t - _MCACHE["che_mtime"]
            if str(d.get("date") or "") == datetime.now().strftime("%Y%m%d") and age <= CHE_STALE_SEC:
                return "OK", float(v.get("last", 0) or 0), round(age, 1)
            return "CHE_STALE", float(v.get("last", 0) or 0), round(age, 1)
    except Exception:
        pass
    try:
        s = _MCACHE["snap"]
        v = s.get(code)
        if not isinstance(v, dict):
            return "CHE_NOT_SUBSCRIBED", 0.0, None
        cs = v.get("che_str")
        if cs is None:
            return "CHE_MISSING", 0.0, None
        try:
            age = now_t - datetime.fromisoformat(str(v.get("ts") or "")).timestamp()
        except Exception:
            return "CHE_STALE", 0.0, None
        if age <= CHE_STALE_SEC:
            return "OK", float(cs or 0), round(age, 1)
        return "CHE_STALE", float(cs or 0), round(age, 1)
    except Exception:
        return "CHE_MISSING", 0.0, None


def _che2(code):
    """체결강도 값(정상 소스일 때만) — 비정상이면 0(=관찰 계속·경로① 판정 불가·추정 금지)."""
    st, che, _ = _che_info(code)
    return che if st == "OK" else 0.0


def _ready_verdict(r, hm, curr, anchor, che_status, ev_age, blocked, g1_end, lo, hi):
    """★[2026-07-19 수정지침1] READY 실행 직전 재검증 — ('EXEC'|'DROP'|'HOLD', 사유).
    DROP=폐기(앵커는 계속 관찰), HOLD=대기 유지·주문 금지. 순수 함수(단위시험용)."""
    ev = r.get("ev") or {}
    if ev.get("entry_gate") == "MORNING_CRASH" and hm >= g1_end:
        return "DROP", "09:30경계(Gate1 시간창 종료)"
    if blocked:
        return "DROP", "보유중/매수대기/재매수상한/매수금지"
    if curr <= 0:
        return "HOLD", "시세없음"
    a = anchor or {}
    if a.get("observation_low") != r.get("obs_low") or a.get("reset_ts") != r.get("cyc"):
        return "DROP", "사이클변경(신저가/리셋/재탐색)"
    ol = float(r.get("obs_low") or 0)
    if ol <= 0:
        return "DROP", "저점정보없음"
    if curr < ol:
        return "DROP", "신저가발생"
    reb = (curr / ol - 1) * 100
    if not (lo <= reb <= hi):
        return "DROP", f"구간이탈({reb:+.2f}%·추격금지)"
    if che_status != "OK":
        return "HOLD", f"체결강도비정상({che_status})"
    if ev_age > 6.0:
        return "HOLD", "품질혼재(신호 6초내 미갱신·관찰 지속)"
    return "EXEC", f"재검증통과(반등{reb:+.2f}%)"


def _cum_vol(code):
    """누적거래량(live_micro_snapshot) — 저점구간 매수/매도 체결량 근사에 사용."""
    try:
        v = _MCACHE["snap"].get(str(code).zfill(6)) or {}
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return None
        cv = v.get("cum_vol")
        return float(cv) if cv is not None else None
    except Exception:
        return None


def _bar1m(code):
    """이번 분 1분봉 {o,h,l,c,pos,bull,prev[[o,h,l,c]..]} — 낡았으면 None."""
    try:
        d = _MCACHE["bars1m"]
        if str(d.get("hm", "")) != datetime.now().strftime("%H%M"):
            return None
        return (d.get("m") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _quality_watch_log(code, name, la, L, every_sec=120.0):
    """★[2026-07-24 관측성 배선(친구님 승인)] 경로① 4중조건이 어디서 걸리는지 실측용 —
    판정 무변경·로그만. 실전 4일 본체 매수 0건의 원인(밴드 밖?·표본부족?·4지표 중 무엇?)이
    기존 로그(사이클당 WAIT 1회)로는 안 보여서, 관찰(WATCHING_LOW) 중 종목마다 every_sec에
    1줄씩 판정 상태를 남긴다. 매수조건 = 체결↑·매수↑·거래량↑·매도↓ 4개 동시(마진10%)."""
    try:
        if la.state != "WATCHING_LOW" or not la.observation_low:
            return
        dw = L.setdefault("diag_watch", {})
        now_ts = time.time()
        if now_ts - float(dw.get(code) or 0) < every_sec:
            return
        dw[code] = now_ts
        cur = _cur(code)
        if not cur or cur <= 0:
            return
        reb = (cur / la.observation_low - 1) * 100.0
        band = "안" if la.obs_pct_lo <= reb <= la.obs_pct_hi else ("아래" if reb < la.obs_pct_lo else "위")
        ela = now_ts - (la.reset_ts if la.reset_ts is not None else now_ts)
        tr = judge_trend(la.trend_log, la.trend_margin_pct)
        _log(f"  🔬품질관찰 {name}({code}) 반등{reb:+.2f}%(밴드{band}·{la.obs_pct_lo:.1f}~{la.obs_pct_hi:.1f}%) "
             f"경과{ela:.0f}s 표본{len(la.trend_log)} 추세[{_trend_desc(tr) or '판정불가(표본부족)'}] "
             f"구간매수{la.seg_buy:,.0f}/매도{la.seg_sell:,.0f}")
    except Exception:
        pass


# ★[2026-07-20 안정성 패치⑤] 캡틴(morning_captain_live_v1.py)에서 이미 검증된 주문번호 기반
#   체결확인 패턴을 그대로 이식 — 시간 이후 누적합산(_fills_qty)은 다른 종목/다른 주문의 체결이
#   같은 종목·시간창에 섞여 들어올 수 있어 주문번호로 귀속을 확정한다. 전략 무변경.
def _fills_onos(code, side="매수", since_hms="00:00:00"):
    """fills CSV를 '주문번호별' {ono: (누적체결량, 가중평균체결가)}로 집계. 다른 주문과 절대 안 섞임."""
    fp = Path(r"C:\stock_bot\LOG") / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return {}
    code = str(code).zfill(6)
    prev, out = {}, {}
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


def _ono_discover(pend, code, side):
    """내 주문번호 확정 — 발주 직전 스냅샷(known)에 없던 '신규' 번호를 fills에서 찾는다.
       정확히 1개면 확정. 2개↑면 모호(다른 엔진 동시주문) — 경고 후 대기(합산 금지)."""
    if pend.get("ono"):
        return pend["ono"]
    known = set(pend.get("known") or [])
    news = [o for o in _fills_onos(code, side, str(pend.get("since") or "00:00:00")) if o not in known]
    if len(news) == 1:
        pend["ono"] = news[0]
        _log(f"  🔖ORDER_NO {code} {side} 주문번호={news[0]} 확정")
        return news[0]
    if len(news) > 1 and not pend.get("_ambig"):
        pend["_ambig"] = 1
        _log(f"  ⚠️주문번호 모호 {code} {side} 신규 {len(news)}개({','.join(news)}) — 동시주문 의심·확정 대기(합산 금지)")
    return ""


def _known_onos(br, code, side):
    """발주 직전 스냅샷 — 이 종목의 기존 주문번호 전부(fills 체결분 + 미체결 잔량)."""
    ks = set(_fills_onos(code, side, "00:00:00").keys())
    try:
        ks |= set((br.open_onos(code, buy=(side == "매수")) or {}).keys())
    except Exception:
        pass
    return sorted(ks)


def _flip_bear(b):
    """양봉→음봉 완성봉 전환 = 직전 두 완성봉이 [양봉, 음봉]. prev 없으면 False."""
    if not b:
        return False
    prev = b.get("prev") or []
    if len(prev) < 2:
        return False
    try:
        a_o, a_h, a_l, a_c = [float(x) for x in prev[-2][:4]]   # 더 이전 완성봉
        z_o, z_h, z_l, z_c = [float(x) for x in prev[-1][:4]]   # 방금 완성된 봉
        return a_c > a_o and z_c < z_o                          # 양봉 → 음봉
    except Exception:
        return False


def _ma5_1m(b):
    """1분봉 5분선 = 직전 5완성봉 종가평균. prev<5면 None."""
    if not b:
        return None
    prev = b.get("prev") or []
    if len(prev) < 5:
        return None
    try:
        return sum(float(x[3]) for x in prev[-5:]) / 5.0
    except Exception:
        return None


def _ma5_daily():
    """{code: 일봉 5일선} — EOD 직전 5거래일 종가평균."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-5:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


def _ma10_daily():
    """{code: 일봉 10일선} — EOD 직전 10거래일 종가평균. 10일선 지지 조건 판정용."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-10:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


def _ma20_daily():
    """{code: 일봉 20일선} — EOD 직전 20거래일 종가평균. 20일선 필터용(ma60은 현재 미사용)."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-20:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


def _ma60_daily():
    """{code: 일봉 60일선} — EOD 직전 60거래일 종가평균. 현재 미사용(20일선 필터로 대체됨)."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-60:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


_mkt_cache = None
_name_cache = None
_stale_logged = False
_avgvol_cache = None


def _avg_daily_vol():
    """{code: 최근 VOLSURGE_DAYS거래일(오늘 제외) 평균 일거래량} — 거래량 급증 필터용. 첫 호출만 읽고 캐시."""
    global _avgvol_cache
    if _avgvol_cache is not None:
        return _avgvol_cache
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("volume") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-(VOLSURGE_DAYS + 1):-1]   # 오늘(마지막) 제외한 직전 N일
        if len(ks) == VOLSURGE_DAYS:
            out[c] = sum(byd[d] for d in ks) / VOLSURGE_DAYS
    _avgvol_cache = out
    return out


def _crash_map():
    """골짜기 후보 {code:{depth,name}} — 코스닥·1만원↑·어제대금 700억~2조·당일 동일시간 거래량
    최근평균 2배↑. (★2026-07-19 심야 통합패치: "당일 저가 -DROP%↓" 유니버스 필터는 LowAnchor
    자체의 -5%(5일선위고점 기준) 판정과 중복이라 삭제. 대신 거래량 급증 필터를 추가.)"""
    global _mkt_cache, _name_cache, _stale_logged
    import collections
    pool = _jload(POOL, {})
    che = _jload(CHE, {})
    # 날짜 검사 — 보드가 오늘 풀·체결강도를 쓰기 전엔 어제 데이터로 급락을 오판할 수 있다. 둘 다 오늘 날짜일 때만 판정.
    _today = datetime.now().strftime("%Y%m%d")
    if str(pool.get("date") or "") != _today or str(che.get("date") or "") != _today:
        if not _stale_logged and datetime.now().strftime("%H%M") >= "0902":
            _stale_logged = True
            _log("⏳🚨 보드가 아직 오늘 풀/체결강도를 안 씀(날짜 관문에 막힘) — 골짜기 등재 대기 중. 보드 생사 확인 요망")
        return {}
    rows = pool.get("rows", [])
    pcm = {str(c).zfill(6): float(px) for c, px, v in rows}
    pvm = {str(c).zfill(6): float(v) for c, px, v in rows}
    if not _mkt_cache:                       # 읽기 실패(빈 결과)면 다음 호출서 재시도 — 빈 캐시로 굳으면 전 종목 탈락(fail-closed)이라
        m = {}
        try:
            with EOD.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    m[r["code"].zfill(6)] = r.get("market", "")
        except Exception:
            pass
        _mkt_cache = m
    mkt = _mkt_cache
    if not _name_cache:
        try:
            _name_cache = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            _name_cache = {}
    names = _name_cache
    avgvol = _avg_daily_vol()
    # 세션 경과분(09:00 기준) — "동일시간 거래량 최근평균 대비" 필터의 기대거래량 계산용.
    _now = datetime.now()
    elapsed_min = max(1.0, (_now.hour - 9) * 60 + _now.minute)
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        snap = {}
    out = {}
    for dc, cs in che.items():
        dc = str(dc).zfill(6)
        if not isinstance(cs, dict):
            continue
        pc = pcm.get(dc)
        lo = float(cs.get("lo", 0) or 0)
        if not pc or pc <= 0 or lo <= 0 or pc < PX_FLR or mkt.get(dc) != "KOSDAQ":
            continue
        pv = pvm.get(dc, 0.0)
        if not (PVAL_LO <= pv <= PVAL_HI):
            continue
        # ★거래량 급증 필터 — avgvol 데이터 없으면 fail-open(통과, 갓 상장 등으로 5일치 없는 종목 배제 방지)
        avd = avgvol.get(dc)
        if avd and avd > 0:
            cv = float((snap.get(dc) or {}).get("cum_vol") or 0)
            expected = avd * (elapsed_min / SESSION_MIN)
            if expected > 0 and cv < expected * VOLSURGE_MULT:
                continue
        # 갭하락(시가 전일比 -3%↓) = 무조건 1순위. 시가 모르면(0) 갭 아님 처리.
        o = float(cs.get("o", 0) or 0)
        gappct = (o / pc - 1) * 100 if o > 0 else 0.0
        out[dc] = {"depth": round((lo / pc - 1) * 100, 2),
                   "gap": bool(o > 0 and gappct <= GAP_TH), "gappct": round(gappct, 2),
                   "name": (names.get(dc) or "")[:10] or dc, "pc": pc,
                   "pv": pv}   # 전일 대금(억) — 정렬 우선권용
    return out


_morning_pool = None
_mpool_wait_logged = False


def _prev_eod_map(today):
    """전일(=오늘보다 과거인 마지막 거래일) 일봉 {code:(market, close, value백만)}와 그 날짜.
    ★[2026-07-19 지침11] 선별기 rows(상위 700 절단) 미사용 — 일봉 원본에서 직접. 휴장(7/17형)도
    자동 건너뜀(오늘보다 과거인 최신 날짜 채택)."""
    best = ""
    rows = {}
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                d = str(r.get("date") or "")
                if d >= today or d < best:
                    continue
                if d > best:
                    best = d
                    rows = {}
                try:
                    rows[r["code"].zfill(6)] = (r.get("market", ""),
                                                float(r.get("close") or 0),
                                                float(r.get("value") or 0))
                except Exception:
                    continue
    except Exception:
        return "", {}
    return best, rows


def _build_morning_pool(prev_map, names, snap):
    """★[2026-07-19 지침2] 아침 고정 감시풀 순수 필터 — 코스닥·전일대금 700억~2조·전일종가 존재·
    현재가 1만원 이상(시세 없으면 전일종가로 판정). 거래량급증·체결강도·이평선 등으로 절대
    탈락시키지 않는다(지침3 — 그것들은 매수판정 전용). eod value는 백만원 단위 → /100 = 억."""
    out = {}
    for c, (m, pc, v_mil) in prev_map.items():
        pv = v_mil / 100.0
        if m != "KOSDAQ" or pc <= 0 or not (PVAL_LO <= pv <= PVAL_HI):
            continue
        cur = float((snap.get(c) or {}).get("cur", 0) or 0)
        if (cur if cur > 0 else pc) < PX_FLR:
            continue
        nm = (names.get(c) or "")[:10] or c
        # ★[2026-07-19 통합지침서] 스팩·우선주(코드 끝자리≠0) 제외. ETF/ETN은 코스닥 미상장이라 해당
        #   없음·관리종목/거래정지는 로컬 판별 불가(정지면 시세가 안 들어와 무장 자체가 안 됨 = 자연 방어).
        if "스팩" in nm or c[5] != "0":
            continue
        out[c] = {"name": nm, "pc": pc, "pv": pv}
    return out


def _morning_watch_pool():
    """★[2026-07-19 지침1~3·11] Gate1(09:00~09:29) 전용 고정 감시풀 — 전일 일봉(eod)에서 직접
    1회 구축 후 09:29까지 동결(장중 순위 변동·종목 추가삭제 금지). 선별기 rows·che_state 등재
    여부와 완전 무관(보드 의존 제거 — 장 시작 즉시 구축 가능). Gate2(09:30~)는 기존 _crash_map
    그대로(지침6·9)."""
    global _morning_pool, _name_cache, _mpool_wait_logged
    if _morning_pool is not None:
        return _morning_pool
    today = datetime.now().strftime("%Y%m%d")
    prev_d, prev_map = _prev_eod_map(today)
    if not prev_map:
        if not _mpool_wait_logged:
            _mpool_wait_logged = True
            _log("🚨 전일 일봉(eod_daily_bars.csv) 읽기 실패 — 아침 고정 감시풀 구축 불가(Gate1 정지·Gate2는 정상)")
        return {}
    if not _name_cache:
        try:
            _name_cache = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            _name_cache = {}
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        snap = {}
    built = _build_morning_pool(prev_map, _name_cache, snap)
    _morning_pool = built          # ★동결 — 09:29까지 추가·삭제 금지(지침2)
    _log(f"🌄 MORNING WATCHLIST = {len(built)} (전일 {prev_d} 일봉 직접·rows 미사용·동결): "
         + " ".join(f"{v['name']}({c})" for c, v in sorted(built.items())))
    # ★[수정지침2-①②] 체결강도 공급선 등록 확인 — 스냅샷(게이트웨이 실시간)·che_str 보유 여부.
    #   게이트웨이 구독은 요청파일 메커니즘이 없어 강제 등록 불가 — 대신 공백을 즉시 검출·로그.
    no_sub = [c for c in built if not isinstance(snap.get(c), dict)]
    no_che = [c for c in built if isinstance(snap.get(c), dict) and snap[c].get("che_str") is None]
    _log(f"   체결강도 공급선: 스냅샷 등록 {len(built) - len(no_sub)}/{len(built)}"
         + (f" ⚠️CHE_NOT_SUBSCRIBED: {', '.join(no_sub)}" if no_sub else "")
         + (f" ⚠️CHE_MISSING(등록됐으나 체결강도 무값): {', '.join(no_che)}" if no_che else " ✓"))
    return built


def _gate1_candidates():
    """고정 감시풀에 실시간 깊이(현재가 기준)·갭하락 표시를 입혀 _crash_map과 같은 모양으로 반환.
    -5% 무장 판정 자체는 valley_low_buy_v1.feed가 매 폴링(2초) 현재가로 수행한다(지시4·6)."""
    base = _morning_watch_pool()
    if not base:
        return {}
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        snap = {}
    che = _jload(CHE, {})
    _today_iso = datetime.now().strftime("%Y-%m-%d")
    out = {}
    for c, b in base.items():
        v = snap.get(c) or {}
        ts = str(v.get("ts") or "")
        cur = float(v.get("cur", 0) or 0) if (not ts or ts[:10] == _today_iso) else 0.0
        depth = round((cur / b["pc"] - 1) * 100, 2) if cur > 0 else 0.0
        cs = che.get(c) if isinstance(che.get(c), dict) else {}
        o = float((cs or {}).get("o", 0) or 0)
        gappct = round((o / b["pc"] - 1) * 100, 2) if o > 0 else 0.0
        out[c] = {**b, "depth": depth,
                  "gap": bool(o > 0 and gappct <= GAP_TH), "gappct": gappct}
    return out


def _csv(r):
    try:
        CSVLOG.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVLOG.exists()
        with CSVLOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패: {e}")


def _shadow_slot_count(L):
    """★[2026-07-20 게이트 통합] 그림자(VH_LIVE=NO) 전용 슬롯 카운터 — 실거래(급락주 등)와 공유하는
    shared_slots.json 풀을 건드리지 않는다. Gate1(09:00~) 통합으로 급락주 실거래 시간대와 겹치게 되면서,
    그림자인 골짜기가 실주문 없이도 shared.acquire()로 진짜 슬롯을 선점해버리는 문제를 막기 위함."""
    return len([c for c, s in L.get("slots", {}).items()
                if isinstance(s, dict) and (s.get("pos") or s.get("pending_buy"))])


def _sell_log(r):
    """관찰 시작~종료를 매도/보류 무관하게 전수 기록 — 실측 로그 누적으로 매도패턴 학습용(SELL_LOG)."""
    try:
        SELL_LOG.parent.mkdir(parents=True, exist_ok=True)
        new = not SELL_LOG.exists()
        with SELL_LOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SELL_LOG_COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"매도관찰 로그 실패: {e}")


class Broker:
    def __init__(self):
        self.bc = None; self.acc = ""

    def connect(self):
        if not LIVE:
            return True
        try:
            from broker_client import BrokerClient, is_broker_alive
            if not is_broker_alive():
                _log("🚨 브로커 죽음 → 주문 불가"); return False
            self.bc = BrokerClient()
            ai = self.bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str):
                accs = [a for a in accs.split(";") if a]
            self.acc = (accs[0] if isinstance(accs, list) and accs else "") \
                or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()
            return bool(self.acc) or (_log("🚨 계좌 없음") or False)
        except Exception as e:
            _log(f"🚨 브로커 연결 실패: {e}"); return False

    def order(self, code, qty, side):
        if not LIVE:
            _log(f"  [그림자] {side} {code} x{qty}")
            return "SHADOW"
        # ★즉시정지 플래그 — 급락주·아침대장과 공용
        if side == "BUY" and Path(r"C:\stock_bot\config\manual_buy_block.flag").exists():
            _log("  🛑 manual_buy_block.flag → 매수 차단"); return "BLOCKED"
        try:
            r = self.bc.send_order_real(
                idempotency_key=f"valleyhunter_{side.lower()}_{code}_{uuid.uuid4()}",
                account=self.acc, code=code, qty=int(qty),
                order_type=(1 if side == "BUY" else 2), price=0,
                hoga_gb="06", rqname=f"VALLEY_{side}_{code}", screen_no="9758")
            st = str((r or {}).get("status", "")).upper()
            _log(f"  [LIVE] {side} {code} x{qty} → {st}")
            return st or "NONE"
        except Exception as e:
            _log(f"  🚨 주문 실패 {side} {code}: {e}"); return "ERROR"

    def cancel_open_buys(self, code):
        """이 종목의 미체결 매수주문 전량취소(opt10075 조회 → order_type 3).
           체결0 판정 후 재시도 전에 잔량을 죽여 이중매수를 막는다. 실패해도 fail-open(로그만) —
           만에 하나 취소 실패 후 뒤늦게 체결된 잔량은 FLAT 안전판이 청산."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "2",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"VALLEY_OPEN_{code}", screen_no="9759", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"valleyhunter_cxl_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=3, price=0, hoga_gb="00",
                    rqname=f"VALLEY_CXL_{code}", screen_no="9759",
                    origin_order_no=ono)
                _log(f"  🧹매수잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️취소 실패 {code}: {e}")

    def cancel_open_sells(self, code):
        """이 종목의 미체결 매도주문 전량취소(opt10075 매매구분1 → order_type 4).
           매도 체결0 판정 후 재매도 전에 잔량을 죽여 이중매도를 막는다. fail-open(로그만)."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"VALLEY_OPENS_{code}", screen_no="9759", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 매도 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"valleyhunter_cxls_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=4, price=0, hoga_gb="00",
                    rqname=f"VALLEY_CXLS_{code}", screen_no="9759",
                    origin_order_no=ono)
                _log(f"  🧹매도잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️매도취소 실패 {code}: {e}")

    # ---- ★[2026-07-20 안정성 패치⑤] 주문번호 단위 조회·지정취소 (캡틴과 동일 패턴 이식) ----
    def open_onos(self, code, buy=True):
        """이 종목의 미체결 {주문번호: 미체결수량} (opt10075). 실패 시 None(판단불가·fail-open)."""
        if not LIVE or not self.bc:
            return {}
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1",
                                   "매매구분": "2" if buy else "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"VALLEY_ONO_{code}", screen_no="9760", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 조회 실패 {code}: {e}")
            return None
        out = {}
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if ono and rem > 0:
                    out[ono] = rem
            except Exception:
                continue
        return out

    def cancel_order(self, code, ono, rem, buy=True):
        """내 주문번호만 지정 취소(CANCEL_REQUEST). 종목단위 전량취소는 번호 미확정 폴백 전용."""
        if not LIVE or not self.bc or not ono:
            _log(f"  📨CANCEL_REQUEST {code} 주문번호={ono or '?'} x{rem} (그림자/번호없음 — 실취소 생략)")
            return "SKIP"
        try:
            cr = self.bc.send_order_real(
                idempotency_key=f"valleyhunter_cxlono_{code}_{uuid.uuid4()}",
                account=self.acc, code=str(code).zfill(6), qty=int(rem),
                order_type=(3 if buy else 4), price=0, hoga_gb="00",
                rqname=f"VALLEY_CXL_{code}", screen_no="9760", origin_order_no=str(ono))
            st = str((cr or {}).get("status", "")).upper()
            _log(f"  📨CANCEL_REQUEST {code} 주문번호={ono} x{rem} → {st}")
            return st
        except Exception as e:
            _log(f"  ⚠️지정취소 실패 {code} 주문번호={ono}: {e}")
            return "ERROR"

    def holdings(self):
        """★[2026-07-20 15:13 FLAT 전용] 실계좌 잔고(opw00018) → {code: {qty, avail}}.
           로그·경고 용도로만 쓰인다 — 이 결과로 ledger를 생성/삭제/매매하지 않는다.
           실패 시 None(fail-open — 조회 실패가 청산 동작을 막으면 안 됨)."""
        if not LIVE or not self.bc:
            return None
        try:
            r = self.bc.balance_tr(tr_code="opw00018",
                                   inputs={"계좌번호": self.acc, "비밀번호": "",
                                           "비밀번호입력매체구분": "00", "조회구분": "2"},
                                   output_fields=["종목번호", "종목명", "보유수량", "매매가능수량"],
                                   rqname="VALLEY_ACCT_CHECK", screen_no="9761", timeout_sec=12.0)
            out = {}
            for x in ((r or {}).get("data") or {}).get("records") or []:
                c = str(x.get("종목번호", "")).strip().lstrip("A").zfill(6)
                if not c.strip("0"):
                    continue
                try:
                    out[c] = {"qty": int(float(str(x.get("보유수량") or "0").replace(",", ""))),
                              "avail": int(float(str(x.get("매매가능수량") or "0").replace(",", "")))}
                except Exception:
                    continue
            return out
        except Exception as e:
            _log(f"  ⚠️ACCOUNT_CHECK_FAIL 계좌조회 실패: {e}")
            return None


# ★[2026-07-20 친구님 승인 — 15:13 FLAT 전용] 계좌↔ledger 점검. 골짜기 ledger가 이미 추적 중인
#   종목만 대조한다(장부에 없는 계좌 보유는 절대 안 본다 — 수동보유·타전략 보유 오인 방지).
#   불일치를 발견해도 로그·경고만 남기고 자동 매수/매도/장부 생성삭제는 하지 않는다.
def _acct_check(br, L):
    acct = br.holdings()
    if acct is None:
        _log("  ⚠️ACCOUNT_CHECK_FAIL — 계좌조회 불가, 대조 생략(장부·매도 동작엔 영향 없음)")
        return
    slots = L.get("slots") or {}
    mism = 0
    for code, s in slots.items():
        if not isinstance(s, dict) or s.get("pending_buy") or s.get("pending_sell"):
            continue   # 자기 주문 체결확인 진행 중 — 확정 전 대조는 무의미(별도 order_no 로직이 처리)
        nm = s.get("name") or code
        lq = int(s.get("qty") or 0) if s.get("pos") else 0
        aq = int((acct.get(code) or {}).get("qty") or 0)
        if aq != lq:
            mism += 1
            _log(f"  🚨ACCOUNT_MISMATCH {nm}({code}) ACCOUNT_QTY={aq} LEDGER_QTY={lq} "
                 f"— 자동조치 없음(로그만·수동 확인 필요)")
    _log(f"  🧾ACCOUNT_CHECK 완료 — 골짜기 추적종목 {len(slots)}개 중 불일치 {mism}건(자동조치 없음)"
         if slots else "  🧾ACCOUNT_CHECK 완료 — 추적 중인 종목 없음")


SLIP_COLS = ["일자", "시각", "종목코드", "종목명", "방향", "지시가", "실체결가", "괴리퍼센트"]


def _slip_row(code, nm, side, px, fill):
    """★[2026-07-20 친구님 승인 — 캡틴 ㉮ 이식] 지시가 vs 실체결가 괴리 — 체결확인 시점 기록.
       매수 +면 비싸게 샀고 매도 -면 싸게 팔린 것(둘 다 손해 방향). 기록 실패해도 매매는 계속(fail-open)."""
    try:
        SLIPCSV.parent.mkdir(parents=True, exist_ok=True)
        new = not SLIPCSV.exists()
        with SLIPCSV.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SLIP_COLS)
            if new:
                w.writeheader()
            w.writerow({"일자": datetime.now().strftime("%Y%m%d"), "시각": datetime.now().strftime("%H:%M:%S"),
                        "종목코드": code, "종목명": nm, "방향": side,
                        "지시가": round(px), "실체결가": round(fill, 1),
                        "괴리퍼센트": round((fill / px - 1) * 100, 3) if px else ""})
    except Exception as e:
        _log(f"슬리피지기록 실패: {e}")


# ★[2026-07-20 안정성 패치⑤] 매수/매도 대기 1스텝 — 기존 동작(로그·CSV·anchors·buy_ban 등) 전부
#   그대로, 확정 근거만 시간누적(_fills_qty) → 주문번호(_fills_onos)로 교체. 캡틴 _pend_buy_step/
#   _pend_sell_step과 동일 흐름: 주문번호 확정 → 전량체결 즉시확정 / 부분·시간초과 → 지정취소 →
#   취소완료 확인 후에만 최종 반영(이전 주문 체결량이 새 주문에 안 섞임).
def _vh_pend_buy_step(br, L, code, s, hm, shared, today, buy_fails, buy_ban):
    pb = s["pending_buy"]
    nm = s.get("name") or code
    ono = _ono_discover(pb, code, "매수")
    fills = _fills_onos(code, "매수", str(pb.get("since") or "09:30:00"))
    filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
    need = int(pb["qty"])

    def _register(fq, fa):
        s["pos"] = True
        s["qty"] = int(min(fq, need))
        s["entry"] = float(pb["px"])   # ★전략 불변 — 매도 트리거 기준가(신호가) 유지
        s["fill_avg"] = round(fa, 1)    # ★[7/20 ㉮ 이식] 실평균체결가 — 참고 필드(장부 entry는 불변)
        s["peak"] = float(pb["px"])
        s["low"] = 0.0
        s.pop("pending_buy", None)
        if fa > 0 and float(pb.get("px") or 0) > 0:
            _slip_row(code, nm, "매수", float(pb["px"]), fa)

    def _ghost_or_partial(fq, fa):
        if fq >= 1:
            s["pos"] = True
            s["qty"] = int(min(fq, need))
            s["entry"] = float(pb["px"])
            s["fill_avg"] = round(fa, 1)
            s["peak"] = float(pb["px"])
            s["low"] = 0.0
            s.pop("pending_buy", None)
            if fa > 0 and float(pb.get("px") or 0) > 0:
                _slip_row(code, nm, "매수", float(pb["px"]), fa)
            _log(f"  ✅체결확인 {nm} {fq}/{need}주 ★부분체결 — 취소완료 확인 후 체결분만 장부")
            return
        prev_re = int(pb.get("re") or 0)
        if prev_re > 0:
            s.pop("pending_buy", None)
            s["re"] = prev_re - 1
            s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
        else:
            L["slots"].pop(code, None)
        try:
            a_g = (L.get("anchors") or {}).get(code)
            if isinstance(a_g, dict):
                a_g["done"] = False
        except Exception:
            pass
        if LIVE:
            shared.release(code, today)
        buy_fails[code] = buy_fails.get(code, 0) + 1
        if buy_fails[code] >= 3:
            buy_ban.add(code)
            L["buy_ban"] = sorted(buy_ban)
        _log(f"  👻체결0 유령판정 {nm}({code}) — 접수만 되고 체결 없음(유령 왕복 방지) "
             f"→ 취소완료·슬롯 회수 (실패 {buy_fails[code]}/3)")
        _csv({"일자": today, "시각": datetime.now().strftime("%H:%M:%S"), "종목코드": code,
              "종목명": nm, "방향": "BUY", "사유": "유령판정(체결0·잔량취소)",
              "현재가": round(_cur(code)), "진입가": round(float(pb.get("px") or 0)),
              "재매수회차": prev_re, "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": "GHOST",
              "진입출처": s.get("entry_gate")})

    if pb.get("cxl_t"):
        if time.time() - float(pb.get("cxl_chk") or 0) < 2.0:
            return False
        pb["cxl_chk"] = time.time()
        op = br.open_onos(code, buy=True)
        confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
        timed_out = time.time() - float(pb["cxl_t"]) >= 10.0
        if not (confirmed or timed_out):
            return False
        if confirmed:
            _log(f"  ✅CANCEL_CONFIRMED {nm}({code}) 주문번호={ono or '?'}")
        else:
            _log(f"  ⚠️취소확인 시간초과 {nm}({code}) 주문번호={ono or '?'} — 최종수량으로 진행")
        fills = _fills_onos(code, "매수", str(pb.get("since") or "09:30:00"))
        filled, favg2 = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono or '?'} {filled}/{need}주")
        _ghost_or_partial(filled, favg2)
        return True

    if ono and filled >= need:
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono} {filled}/{need}주")
        _register(filled, favg)
        _log(f"  ✅체결확인 {nm} {filled}/{need}주")
        return True

    if (ono and 1 <= filled < need) or \
       (time.time() - float(pb.get("sent") or 0)) >= FILL_WAIT or hm >= EXIT_HM:
        op = None
        if not ono:
            op = br.open_onos(code, buy=True)
            news = [o for o in (op or {}) if o not in set(pb.get("known") or [])]
            if len(news) == 1:
                pb["ono"] = ono = news[0]
                _log(f"  🔖ORDER_NO {code} 매수 주문번호={ono} 확정(미체결조회)")
                filled = _fills_onos(code, "매수", str(pb.get("since") or "09:30:00")).get(ono, (0, 0.0))[0]
        if ono:
            rem = (op or {}).get(ono) or max(1, need - filled)
            br.cancel_order(code, ono, rem, buy=True)
        else:
            _log(f"  ⚠️주문번호 미확정 {nm}({code}) — 종목단위 전량취소 폴백(교차취소 가능성 로그)")
            br.cancel_open_buys(code)
        pb["cxl_t"] = time.time()
        pb["cxl_chk"] = 0.0
        return True
    return False


def _vh_pend_sell_step(br, L, code, s, hm, shared, today, ma5d):
    ps = s["pending_sell"]
    nm = s.get("name") or code
    need = int(ps.get("qty") or 0)
    ono = _ono_discover(ps, code, "매도")
    fills = _fills_onos(code, "매도", str(ps.get("since") or "09:30:00"))
    filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)

    def _full_done(fq, fa):
        ret2 = float(ps.get("ret") or 0)
        s["realized"] = round(float(s["realized"]) + ret2, 3)
        # ★[2026-07-20 친구님 승인 — 캡틴 ㉮ 이식] 실체결 기준 손익 병기(장부 realized=신호가 기준 불변).
        rr = None
        fe = float(s.get("fill_avg") or 0)
        if fa > 0 and fe > 0:
            rr = (fa / fe - 1) * 100
            s["real_realized"] = round(float(s.get("real_realized") or 0) + rr, 3)
            s["real_won"] = round(float(s.get("real_won") or 0) + (fa - fe) * fq, 1)
        if fa > 0 and float(ps.get("px") or 0) > 0:
            _slip_row(code, nm, "매도", float(ps["px"]), fa)
        _log(f"  ✅매도 체결확인 {nm}({code}) {fq}/{need}주 ({ret2:+.2f}%)"
             + (f" ★실체결 {rr:+.2f}%" if rr is not None else ""))
        _csv({"일자": today, "시각": datetime.now().strftime("%H:%M:%S"), "종목코드": code,
              "종목명": nm, "방향": "SELL", "사유": str(ps.get("why") or ""),
              "체결강도": ps.get("che", ""), "고점": round(float(s.get("peak") or 0)),
              "현재가": round(float(ps.get("px") or 0)), "일봉5일선": round(ma5d.get(code, 0)),
              "진입가": round(float(s.get("entry") or 0)), "수익퍼센트": round(ret2, 2),
              "재매수회차": int(s.get("re", 0) or 0),
              "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": str(ps.get("st") or "OK"),
              "진입출처": s.get("entry_gate")})
        s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
        L.setdefault("anchors", {}).pop(code, None)
        _log(f"  🔁{nm}({code}) 매도 후 IDLE복귀 — 새 저점 사이클 재탐색 시작 "
             f"(재매수 {int(s.get('re', 0) or 0) + 1}/{REBUY_MAX}회까지)")
        s.pop("pending_sell", None)
        if LIVE:
            shared.release(code, today)

    def _partial_or_ghost(fq):
        if fq >= 1:
            s["qty"] = max(0, need - fq)
            s.pop("pending_sell", None)
            _log(f"  ⚠️매도 부분체결 {nm}({code}) {fq}/{need}주 → 취소완료 확인 후 잔량 {s['qty']}주 재매도 예정")
        else:
            s.pop("pending_sell", None)
            _log(f"  👻매도 체결0 {nm}({code}) — 취소완료·재매도(유령 매도 방지)")

    if ps.get("cxl_t"):
        if time.time() - float(ps.get("cxl_chk") or 0) < 2.0:
            return False
        ps["cxl_chk"] = time.time()
        op = br.open_onos(code, buy=False)
        confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
        timed_out = time.time() - float(ps["cxl_t"]) >= 10.0
        if not (confirmed or timed_out):
            return False
        if confirmed:
            _log(f"  ✅CANCEL_CONFIRMED {nm}({code}) 주문번호={ono or '?'}")
        else:
            _log(f"  ⚠️취소확인 시간초과 {nm}({code}) 주문번호={ono or '?'} — 최종수량으로 진행")
        fills = _fills_onos(code, "매도", str(ps.get("since") or "09:30:00"))
        filled, favg2 = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono or '?'} {filled}/{need}주")
        if need > 0 and filled >= need:
            _full_done(filled, favg2)
        else:
            _partial_or_ghost(filled)
        return True

    if ono and need > 0 and filled >= need:
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono} {filled}/{need}주")
        _full_done(filled, favg)
        return True

    if (ono and 1 <= filled < need) or \
       (time.time() - float(ps.get("sent") or 0)) >= FILL_WAIT:
        op = None
        if not ono:
            op = br.open_onos(code, buy=False)
            news = [o for o in (op or {}) if o not in set(ps.get("known") or [])]
            if len(news) == 1:
                ps["ono"] = ono = news[0]
                _log(f"  🔖ORDER_NO {code} 매도 주문번호={ono} 확정(미체결조회)")
                filled = _fills_onos(code, "매도", str(ps.get("since") or "09:30:00")).get(ono, (0, 0.0))[0]
        if ono:
            rem = (op or {}).get(ono) or max(1, need - filled)
            br.cancel_order(code, ono, rem, buy=False)
        else:
            _log(f"  ⚠️주문번호 미확정 {nm}({code}) — 종목단위 매도 전량취소 폴백(교차취소 가능성 로그)")
            br.cancel_open_sells(code)
        ps["cxl_t"] = time.time()
        ps["cxl_chk"] = 0.0
        return True
    return False


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    # ★[2026-07-20] 하드코딩 "0930" → ENTRY_HM(VH_ENTRY)로 교체 — Gate1(09:00~) 통합 시 cmd에서
    #   VH_ENTRY=0900으로 당겨도 여기 하드코딩에 막혀 프로세스 자체가 조용히 안 돌던 버그.
    if hm < ENTRY_HM or hm > END_HM:
        return
    _log("=" * 78)
    from valley_low_buy_v1 import PEAK_DROP_PCT as LA_PEAK_DROP, BEARISH_3M_N as LA_BEAR_N, \
        OBS_PCT_LO as LA_OBS_LO, OBS_PCT_HI as LA_OBS_HI, WATCH_MIN as LA_WATCH_MIN, \
        TREND_MARGIN_PCT as LA_TREND_MARGIN, MA_CONFIRM as LA_MA_CONFIRM, \
        GATE1_START as LA_G1_START, GATE1_END as LA_G1_END, GATE1_ARM_PCT as LA_G1_ARM
    _log(f"🏔️🔥 골짜기 저점앵커 {'★실전(LIVE)' if LIVE else '그림자(주문0)'} — "
         f"Gate1[MORNING_CRASH]{LA_G1_START[:2]}:{LA_G1_START[2:]}~{LA_G1_END[:2]}:{LA_G1_END[2:]} "
         f"전일종가대비{LA_G1_ARM:.0f}%↓→저점추적→완성양봉 즉시관찰(음봉패턴·거래량·몸통 조건없음) / "
         f"Gate2[VALLEY_PEAK]{LA_G1_END[:2]}:{LA_G1_END[2:]}~{ENTRY_END[:2]}:{ENTRY_END[2:]} "
         f"5일선위고점대비{LA_PEAK_DROP:.0f}%↓(5일선아래)+{LA_BEAR_N}연속1분음봉후양봉전환(거래량·몸통확대·Gate2전용) → 공통 저점반등+{LA_OBS_LO:.1f}~{LA_OBS_HI:.1f}%·"
         f"{LA_WATCH_MIN:.0f}초워밍업후 반등품질(체결강도·매수·거래량↑+매도↓ 변화량추세·마진{LA_TREND_MARGIN:.0f}%) "
         f"매수②20일선위+5/10일선접촉돌파{LA_MA_CONFIRM}봉확인매수(★Gate2전용·Gate1금지) · "
         f"매도 하드손절{REBUY_STOP:.1f}%(재매수{REBUY_MAX}회까지) / "
         f"보험선{INSURE_PCT:.1f}%즉시 또는 10일선회복후재이탈즉시(2층 안전판) / 완성음봉관찰{PEAK_WATCH_SEC:.0f}초"
         f"(점수제 4개중{SELL_SCORE_TH}개↑매도·5일선회복후재이탈시문턱-1·마진{SELL_TREND_MARGIN_PCT:.0f}%·"
         f"재매수=시간쿨다운없음·새저점사이클완성시만) / "
         f"{EXIT_HM[:2]}:{EXIT_HM[2:]}청산 · {'%d주고정' % QTY_FIX if QTY_FIX > 0 else format(CAP, ',.0f') + '원'}×{SLOTS}슬롯"
         f"({'급락주와 실슬롯 공유' if LIVE else '그림자 자체카운터(실슬롯 안 건드림)'}·슬롯부족해도 관찰은 계속)")

    if BB_ON:
        _log(f"💥 제3게이트 응집폭발 ON — 베이스{BB_BASE_N}봉 진폭≤{BB_TIGHT}%·거래량{BB_VOLX}배·상단돌파 "
             f"→ 리테스트({BB_WAIT}봉) 지정가 → 목표+{BB_TGT:.1f}%/손절{BB_STP:.1f}%/{EXIT_HM[:2]}:{EXIT_HM[2:]} "
             f"· 감시=아침 고정 감시풀·{BB_ENTRY[:2]}:{BB_ENTRY[2:]}~{BB_ENTRY_END[:2]}:{BB_ENTRY_END[2:]}·종목당 {REBUY_MAX + 1}회")
    br = Broker()
    if not br.connect():
        return
    ma5d = _ma5_daily()          # 매도엔진 점수제 문턱 조정용(추세확인, "회복후재이탈"만) — 직접 매도조건 아님
    ma10d = _ma10_daily()        # ★최후 보험선(회복후재이탈) — 조건 충족 시 즉시매도
    ma20d = _ma20_daily()   # 20일선 필터용
    ma60d = _ma60_daily()   # 현재 미사용

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "slots": {}}
        _jsave(LEDGER, L)

    if ACCT_CHECK:
        _acct_check(br, L)

    # ★[2026-07-20 친구님 승인 — 캡틴 ㉰ 이식] 계좌 기존보유 종목 매수 제외 — 캡틴 원익IPS 평단 오염
    #   재발 방지(오늘 골짜기 관심종목 12개에도 원익IPS 포함). reconcile(08:50)의 계좌 진실 스냅샷 사용.
    #   파일 없거나 깨지면 필터 없이 진행(fail-open — 매수 자체를 막는 안전판이 아니라 오염 방지용).
    try:
        _rt = _jload(Path(r"C:\stock_bot\data\rt_open_positions.json"), {}) or {}
        HELD = {str(c).zfill(6) for c, v in _rt.items() if int(float((v or {}).get("qty") or 0)) > 0}
    except Exception:
        HELD = set()
    if HELD:
        _log(f"  🏦계좌 기존보유 매수제외 {len(HELD)}종목: " + ", ".join(sorted(HELD)))
    held_logged = set()   # ACCOUNT_HELD 거부 로그 1회/기동

    deadline = time.monotonic() + RUN_SEC
    buy_fails = {}      # 종목별 매수 실패 횟수 — 3회면 그 종목만 매수 금지(다른 종목 계속)
    # ★[2026-07-20 안정성 패치③] buy_ban을 원장(L)에 저장 — 20분 재시작에도 당일 종료까지 금지 유지.
    #   buy_fails(3회 전 카운터)는 그대로 재시작마다 초기화(스펙상 영구화 대상은 buy_ban만).
    buy_ban = set(L.get("buy_ban") or [])
    lowreset_cnt = {}   # ★[7/19 친구님 "도움되면 해라"] 신저가 리셋 실시간 로그용 — 분당 1회 스로틀+누적
    lowreset_min = {}

    def _execute_buy(code, info, ev, cur, ex):
        """반등조건 완성(ev={'signal':'BUY',...})된 종목의 실제 매수 실행 — 관문체크→수량계산→
        슬롯확보→주문→장부기록. ★[2026-07-19 재매수개선(item4·5)] 관찰(la.feed)과 주문실행을
        분리해서 슬롯이 없을 땐 이 함수를 호출하지 않고 L['ready']에 큐잉했다가, 슬롯이 비는
        즉시 그 시점 현재가(cur)로 다시 호출한다 — 신호는 버리지 않되 체결가는 항상 실행시점 값."""
        def _revive():
            # ★[수정지침1] 주문 불가/실패 시 done=True 영구잠금 금지 — 앵커를 관찰(WATCH)로 복귀시켜
            #   같은 사이클을 계속 보게 한다(신호가 살아있으면 재발화·아니면 자연 소멸).
            try:
                a_r = (L.get("anchors") or {}).get(code)
                if isinstance(a_r, dict):
                    a_r["done"] = False
            except Exception:
                pass
        che = _che2(code)
        if not _gate_ok(code, cur):
            if code not in _gate_warned:
                _gate_warned.add(code)
                _log(f"  🚧{info['name']}({code}) @{cur:,.0f} 관문미러 차단"
                     f"(가격<{GATE_MINP:,.0f} 또는 시총<{GATE_MINMC/1e8:,.0f}억) → 주문 시도 안 함")
            _revive()
            return False
        # ★[2026-07-20 친구님 승인 — 캡틴 ㉰ 이식] 계좌에 이미 있는 종목은 매수 금지 — 평단 오염 방지.
        if code in HELD:
            if code not in held_logged:
                held_logged.add(code)
                _log(f"  ⛔VALLEY_REJECT REASON=ACCOUNT_HELD {info['name']}({code}) 계좌 기존보유")
            _revive()
            return False
        qty = QTY_FIX if QTY_FIX > 0 else int(CAP // cur)
        if qty < 1:
            _revive()
            return False
        # ★[2026-07-20] 그림자는 실거래(급락주 등)와 공유하는 진짜 슬롯 풀을 안 건드림(_shadow_slot_count 참고)
        if LIVE:
            if not shared.acquire(code, "VALLEY", today):   # 공통 슬롯 확보(풀 차면 스킵)
                _revive()
                return False
        elif _shadow_slot_count(L) >= SLOTS:
            _revive()
            return False
        kn = _known_onos(br, code, "매수") if LIVE else []   # ★[패치⑤] 발주 직전 주문번호 스냅샷
        st = br.order(code, qty, "BUY")
        if st not in ("OK", "TIMEOUT", "SHADOW"):
            # 실패 시 슬롯 반환·2초 루프 재시도, 같은 종목 3회 실패면 그 종목만 금지(전체 매수 금지 아님)
            if LIVE:
                shared.release(code, today)
            buy_fails[code] = buy_fails.get(code, 0) + 1
            if buy_fails[code] >= 3:
                buy_ban.add(code)
                L["buy_ban"] = sorted(buy_ban)   # ★[안정성 패치③] 재시작 생존 — 당일 종료까지 유지
                _log(f"  🛑{info['name']}({code}) 매수 3회 연속 실패 → 이 종목만 매수 금지(다른 종목 계속)")
            else:
                _log(f"  ⚠️{info['name']}({code}) 매수 {st} → 재시도 {buy_fails[code]}/3")
            _revive()
            return False
        buy_fails.pop(code, None)
        re_n = int((ex or {}).get("re", 0) or 0) + (1 if ex else 0)   # 재진입이면 회차 +1
        # 접수OK ≠ 체결 — LIVE는 pending_buy로 적고 체결확인 후에만
        # pos=True(유령 방지). 그림자는 기존대로 즉시 보유.
        L["slots"][code] = {"name": info["name"], "depth": info.get("depth", 0),
                            "qty": qty if st == "SHADOW" else 0,
                            "entry": cur if st == "SHADOW" else 0.0,
                            "peak": cur, "low": 0.0, "pos": st == "SHADOW",
                            "done": False, "re": re_n,
                            # ★[2026-07-19 심야] 5일선/10일선 "회복 후 재이탈" 상태 —
                            # 매수 시점엔 false(처음부터 그 선 아래였을 수 있으므로).
                            "ma5_reclaimed": False, "ma10_reclaimed": False,
                            "entry_gate": ev.get("entry_gate"),   # ★[2026-07-20] MORNING_CRASH/VALLEY_PEAK — 게이트별 승률·기대값 비교용
                            "realized": float((ex or {}).get("realized", 0) or 0)}
        now2 = datetime.now()
        if st != "SHADOW":
            L["slots"][code]["pending_buy"] = {
                "qty": qty, "px": cur, "re": re_n, "ono": "", "known": kn,
                "since": (now2 - timedelta(seconds=2)).strftime("%H:%M:%S"),
                "sent": time.time()}
        reason = "눌림재진입" if re_n else "저점앵커진입"
        trend = _trend_desc(ev.get("trend"))
        # 실행시점 기준 반등률 재계산(슬롯대기 큐를 거쳤으면 ev의 원래 값은 과거 시점 값이라 갱신)
        live_rebound = ((cur / ev["observation_low"] - 1) * 100) if ev.get("observation_low") else (ev.get("rebound_pct") or 0)
        _log(f"🏔️🔥[{ev.get('entry_gate','?')}] {'재진입#' + str(re_n) if re_n else '진입'} {info['name']}({code}) @{cur:,.0f} x{qty} "
             f"깊이{info.get('depth', 0):+.1f}%{'·★갭하락' + format(info.get('gappct', 0), '+.1f') + '%' if info.get('gap') else ''} "
             f"저점{ev['observation_low']:,.0f}→반등{cur:,.0f}({live_rebound:+.1f}%) "
             f"반등품질[{trend}](매수{ev.get('seg_buy', 0):,.0f}/매도{ev.get('seg_sell', 0):,.0f}·누적체결강도{che:.0f}참고) "
             f"일봉5일선{ma5d.get(code,0):,.0f} [{ev.get('reason','')}]")
        _csv({"일자": today, "시각": now2.strftime("%H:%M:%S"), "종목코드": code,
              "종목명": info["name"], "방향": "BUY", "사유": reason,
              "체결강도": round(che, 1), "저점": round(ev["observation_low"]), "현재가": round(cur),
              "일봉5일선": round(ma5d.get(code, 0)),
              "진입가": round(cur), "재매수회차": re_n,
              "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": st,
              "반등품질": trend, "구간매수량": ev.get("seg_buy"), "구간매도량": ev.get("seg_sell"),
              "판정사유": ev.get("reason"), "진입출처": ev.get("entry_gate")})
        return True   # ★주문 접수 성공(포지션 확정은 체결확인(pending_buy) 통과 시에만 — 기존 파이프라인)

    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        _refresh_market_cache()   # ★[안정성 패치①] 이번 루프에서 전 종목이 쓸 스냅샷 1회 고정
        dirty = False

        # ══ 진입 — 골짜기 저점서 반등품질(변화량추세) 판정 ══
        # ★[2026-07-19 재매수개선(item4)] 관찰(LowAnchor·체결강도·체결량·로그)은 슬롯 여유와 무관하게
        #   계속한다 — 슬롯 부족은 아래 "주문 실행"에서만 걸린다. 재매수는 시간쿨다운이 아니라
        #   "새 저점 사이클" 완성으로만 통제(매도 시 anchors가 리셋되므로 자동으로 보장됨, item2·3).
        if ENTRY_HM <= hm <= ENTRY_END:
            # ★[2026-07-19 친구님 지시8] 09:30 경계 1회 청소 — 미체결 MORNING_CRASH는 전부 폐기
            #   (ARMED/WATCH=anchors·READY=슬롯대기열). 이미 매수된 포지션(slots pos)은 공통
            #   매도엔진이 계속 관리. feed의 경계컷과 동일 리셋 — 봉 이력은 남겨 Gate2 즉시판정 가능.
            if hm >= LA_G1_END and not L.get("_g1_purged"):
                for rc in [k for k, r in list((L.get("ready") or {}).items())
                           if ((r.get("ev") or {}).get("entry_gate")) == "MORNING_CRASH"]:
                    r = L["ready"].pop(rc)
                    _log(f"  🗑️09:30경계 — MORNING_CRASH 슬롯대기 폐기 {r.get('name')}({rc})")
                for c2, a in (L.get("anchors") or {}).items():
                    if not isinstance(a, dict) or a.get("done"):
                        continue
                    if a.get("entry_gate") == "MORNING_CRASH" or a.get("gate1_armed"):
                        a.update({"state": "IDLE", "observation_low": None, "entry_gate": None,
                                  "ma_touch_confirmed_bars": 0, "gate1_armed": False,
                                  "gate1_cand_low": None, "gate1_armed_ts": None,
                                  "gate1_armed_px": None})
                L["_g1_purged"] = True
                dirty = True
            # ★[2026-07-19 친구님 지시1] 09:30 전엔 che_state 순회가 아니라 고정 감시풀(지시2·3)
            # ★[2026-07-22] Gate2 은퇴 스위치 — VH_GATE2=NO면 09:30 이후 후보 유니버스를 비운다
            cm = _gate1_candidates() if hm < LA_G1_END else (_crash_map() if GATE2_ON else {})
            # 정렬 = TRUE_LEADER 우선(부하 많은 순) → 기관/외국인/프로그램 수급 가중치 → 갭하락
            #   1순위 → 대금 700억↑ 그룹 우선 → 그룹 안에서 깊이순(급락주와 동일). 앞 두 단만
            #   추가, 나머지 기존 그대로 — 매수 자체를 막는 조건 아님(순서만 바꿈).
            tl_info = _true_leader_info()
            supply_map = _supply_lookup()
            order = sorted(cm.items(), key=lambda kv: (kv[0] not in tl_info, -tl_info.get(kv[0], 0),
                                                       -_supply_score(supply_map.get(kv[0])),
                                                       not kv[1].get("gap"),
                                                       kv[1].get("pv", 0) < 700,
                                                       kv[1]["depth"]))
            for code, info in order:
                ex = L["slots"].get(code)
                # 공통 슬롯(아침대장·급락주와 합산) · 매수 3회 실패 종목(buy_ban)은 건너뜀 — 다른 종목으로 갈아탐
                # 체결확인 대기(pending_buy/sell) 중에도 건너뜀 — 대기 8초 동안 같은 신호로
                # 2초마다 중복 매수 주문이 나가던 구멍(이중매수 폭주) 봉쇄. 유령 판정 시 슬롯이 pop되므로 재시도는 그대로 가능.
                # ★재매수 횟수 상한(REBUY_MAX)은 여기서 건다 — 최초매수+재매수까지 합쳐 총
                # REBUY_MAX+1번(기본 1이면 총 2번: 최초 1 + 재매수 1)만 사고 그 종목은 끝낸다.
                # ready 대기중(반등완성·슬롯대기)인 종목도 건너뜀 — 아래 별도 루프가 처리한다.
                # ★[수정지침1] READY 종목도 건너뛰지 않는다 — 관찰(feed)을 계속 돌려 신호 신선도를
                #   유지(품질 유지 시 매 폴링 BUY 재발화로 대기열 항목이 갱신·악화 시 RESET으로 폐기 유도)
                if code in buy_ban \
                        or (ex and (ex.get("pos") or ex.get("done")
                                    or ex.get("pending_buy") or ex.get("pending_sell")
                                    or int(ex.get("re", 0) or 0) >= REBUY_MAX)):
                    continue
                cur = _cur(code); cv = _cum_vol(code)
                # ★[수정지침2] 체결강도 소스 상태 — 비정상이면 값 0(경로① 판정 금지)·사유 1회 로그
                che_st, che, che_age = _che_info(code)
                # ★[2026-07-21 지속성 패치] 이전엔 메모리 셋(_che_warned)이라 20분 재기동마다
                #   초기화 → "회복" 로그가 재기동 경계에서 유실됨(회복 자체는 됐는데 안 보임).
                #   장부(L)에 저장해 재기동 이어받기 — 판정 로직은 무변경, 로그 관측성만 개선.
                warned = L.setdefault("che_warned", [])
                if che_st != "OK":
                    che = 0.0
                    if code not in warned:
                        warned.append(code)
                        dirty = True
                        _log(f"  ⚠️체결강도 {che_st} {info['name']}({code}) age={che_age if che_age is not None else '-'}s"
                             f" — 무장·관찰은 계속, 경로① 매수판정 금지(추정값 대체 안 함)")
                elif code in warned:
                    # ★[2026-07-20 친구님 승인 ⑥] 신선 회복 시점 로그 — 언제 매수판정 재개됐는지 확인 가능하게.
                    warned.remove(code)
                    dirty = True
                    _log(f"  ✅체결강도 회복 {info['name']}({code}) age={che_age if che_age is not None else '-'}s"
                         f" — 경로① 매수판정 재개")
                if cur <= 0:
                    continue
                # 저점구간 매수/매도 체결량 비율 판정 — ledger의 anchors에 종목별 상태 유지(재기동 이어받기)
                L.setdefault("anchors", {})
                a = L["anchors"].get(code) or {}
                la = la_from_ledger(code, a)
                b1 = _bar1m(code)
                ev = la.feed(hm, cur, cv, time.time(), ma5d.get(code, 0), b1,
                             ma10d.get(code, 0), ma20d.get(code, 0), ma60d.get(code, 0), che,
                             prev_close=info.get("pc"))   # 반등품질 판정. prev_close=Gate1(09:00~09:30 전일종가-5%) 판정용
                L["anchors"][code] = la_to_ledger(la)
                dirty = True
                _quality_watch_log(code, info["name"], la, L)   # ★[2026-07-24 관측성] 판정 무변경·로그만
                # ★[2026-07-19 지침12②] -5% 무장 순간 실시간 로그 — 피드 전 상태(a)와 비교해 전이 시 1회만
                if la.gate1_armed and not a.get("gate1_armed") and info.get("pc"):
                    _log(f"  ⚡무장 {info['name']}({code}) 전일종가{info['pc']:,.0f} → {cur:,.0f} "
                         f"({(cur / info['pc'] - 1) * 100:+.1f}%) — 저점추적 시작(반등해도 무장 유지)")
                # ★[7/19 밤] 신저가 리셋 로그(분당 1회·누적 횟수) — WAIT 통계의 '신저가리셋' 실측용
                if (la.state == "WATCHING_LOW" and a.get("state") == "WATCHING_LOW"
                        and a.get("observation_low") and la.observation_low
                        and la.observation_low < float(a["observation_low"])):
                    lowreset_cnt[code] = lowreset_cnt.get(code, 0) + 1
                    if lowreset_min.get(code) != hm:
                        lowreset_min[code] = hm
                        _log(f"  🔻신저가 리셋 {info['name']}({code}) 저점 {float(a['observation_low']):,.0f}"
                             f"→{la.observation_low:,.0f} (이 프로세스 누적 {lowreset_cnt[code]}회 — 워밍업 재시작)")
                if ev and ev["signal"] == "WATCH_START":
                    ap = ev.get("armed_px")
                    _log(f"  🏁관찰시작 {info['name']}({code}) 저점{ev['observation_low']:,.0f} "
                         f"5일선위고점{(ev.get('ma5_above_peak') or 0):,.0f} 낙폭{(ev.get('drop_pct') or 0):+.1f}%"
                         + (f" 무장가{ap:,.0f}({datetime.fromtimestamp(ev['armed_ts']):%H:%M:%S})"
                            if ap and ev.get("armed_ts") else "")
                         + f" [{ev['reason']}]")
                if ev and ev["signal"] == "RESET":
                    _log(f"  🔄{info['name']}({code}) IDLE복귀·재탐색 [{ev['reason']}]")
                if ev and ev["signal"] == "WAIT":
                    trend = _trend_desc(ev.get("trend"))
                    _log(f"  ⏳관망 {info['name']}({code}) 저점{ev['observation_low']:,.0f}→{ev['entry_px']:,.0f} "
                         f"반등{ev.get('rebound_pct', 0):+.1f}% 반등품질[{trend}](누적체결강도{che:.0f}참고) "
                         f"[{ev['reason']}] — 신저점 재대기")
                if ev and ev["signal"] == "BUY":
                    cur_slot_n = shared.count(today) if LIVE else _shadow_slot_count(L)
                    if cur_slot_n < SLOTS:
                        L.get("ready", {}).pop(code, None)   # 방금 신호가 최신 — 대기열 흔적 제거 후 즉시 실행
                        _execute_buy(code, info, ev, cur, ex)
                    else:
                        # ★[2026-07-19 수정지침1] 슬롯대기 — 신호를 동결하지 않는다: 앵커 done을 풀어
                        #   관찰을 계속시키고, 품질이 유지되는 동안 매 폴링 BUY 재발화가 이 항목을
                        #   갱신한다(ts). 실행은 _ready_verdict 재검증 통과 시에만(추격·낡은신호 금지).
                        prev_r = (L.get("ready") or {}).get(code) or {}
                        first_q = not prev_r
                        la.done = False
                        L["anchors"][code] = la_to_ledger(la)
                        L.setdefault("ready", {})[code] = {
                            "name": info["name"], "depth": info.get("depth", 0),
                            "gap": info.get("gap"), "gappct": info.get("gappct"), "ev": ev,
                            "obs_low": ev.get("observation_low"), "cyc": la.reset_ts,
                            "sig_px": ev.get("entry_px"),
                            "created": prev_r.get("created") or now.strftime("%H:%M:%S"),
                            "ts": time.time()}
                        if first_q:
                            _log(f"  🕗READY 생성 {info['name']}({code}) [{ev.get('entry_gate','?')}] "
                                 f"저점{ev['observation_low']:,.0f} 신호가{ev.get('entry_px', 0):,.0f}"
                                 f"({ev.get('rebound_pct', 0):+.2f}%) 품질[{_trend_desc(ev.get('trend'))}] "
                                 f"사이클{la.reset_ts} — 재검증 통과 시에만 매수(관찰 계속)")
                    dirty = True

            # ── ★[2026-07-21 Money Flow 연동] MONEY_FLOW_ENTRY — 위 order 루프(MORNING_CRASH·
            #    VALLEY_PEAK)는 완전 무접촉·무수정. cm에 이미 있는 종목은 건너뛴다(같은 틱에
            #    두 경로로 동시 feed되는 것 방지 — 그 종목은 기존 게이트가 그대로 처리). 아래는
            #    위 order 루프 본문을 money_flow=True 한 줄만 다르게 최소 재현한 것 — 관찰(feed)
            #    이후의 READY 재검증·실행(다음 블록)은 기존 공용 루프를 그대로 공유한다.
            if MFE_ENABLE:
                # supply_map은 위(1560행 부근)에서 이미 1회 읽음 — 재사용(CPU 절약, 중복읽기 제거)
                mf_cands_sorted = sorted(_money_flow_top5().items(),
                                          key=lambda kv: (kv[0] not in tl_info, -tl_info.get(kv[0], 0),
                                                           -_supply_score(supply_map.get(kv[0]))))
                for code, mf_info in mf_cands_sorted:
                    if code in cm:
                        continue
                    ex = L["slots"].get(code)
                    if code in buy_ban \
                            or (ex and (ex.get("pos") or ex.get("done")
                                        or ex.get("pending_buy") or ex.get("pending_sell")
                                        or int(ex.get("re", 0) or 0) >= REBUY_MAX)):
                        continue
                    cur = _cur(code); cv = _cum_vol(code)
                    che_st, che, che_age = _che_info(code)
                    if che_st != "OK":
                        che = 0.0
                    if cur <= 0:
                        continue
                    L.setdefault("anchors", {})
                    a = L["anchors"].get(code) or {}
                    la = la_from_ledger(code, a)
                    b1 = _bar1m(code)
                    ev = la.feed(hm, cur, cv, time.time(), ma5d.get(code, 0), b1,
                                 ma10d.get(code, 0), ma20d.get(code, 0), ma60d.get(code, 0), che,
                                 money_flow=True)
                    L["anchors"][code] = la_to_ledger(la)
                    dirty = True
                    _quality_watch_log(code, mf_info["name"], la, L)   # ★[2026-07-24 관측성] 판정 무변경·로그만
                    info = {"name": mf_info["name"]}
                    srow = supply_map.get(code)
                    info["_supply_row"] = srow   # ★사양3 — 없어도/늦어도 진행(fail-open), CSV검증 전용(사양5)
                    # ★[수급 사용 원칙 최종·사양4] 실시간 로그에는 표시 안 함(간결 유지) — 조회 자체는
                    # 계속하되(검증로그용), _supply_tags()는 여기서 더 이상 호출하지 않는다.
                    if ev and ev["signal"] == "WATCH_START":
                        _log(f"  🏁[MONEY_FLOW] WATCH_START {info['name']}({code}) 저점{ev['observation_low']:,.0f} "
                             f"[{ev['reason']}]")
                    if ev and ev["signal"] == "RESET":
                        _log(f"  🔄{info['name']}({code}) IDLE복귀·재탐색 [{ev['reason']}]")
                    if ev and ev["signal"] == "WAIT":
                        trend = _trend_desc(ev.get("trend"))
                        _log(f"  ⏳관망 {info['name']}({code}) 저점{ev['observation_low']:,.0f}→{ev['entry_px']:,.0f} "
                             f"반등{ev.get('rebound_pct', 0):+.1f}% 반등품질[{trend}] [{ev['reason']}] — 신저점 재대기")
                    if ev and ev["signal"] == "BUY":
                        cur_slot_n = shared.count(today) if LIVE else _shadow_slot_count(L)
                        if cur_slot_n < SLOTS:
                            L.get("ready", {}).pop(code, None)
                            ok_mf = _execute_buy(code, info, ev, cur, ex)
                            if ok_mf:
                                _log_supply_check(code, info["name"], cur, srow)   # ★사양5(검증전용, 매수판단 무관)
                        else:
                            prev_r = (L.get("ready") or {}).get(code) or {}
                            first_q = not prev_r
                            la.done = False
                            L["anchors"][code] = la_to_ledger(la)
                            L.setdefault("ready", {})[code] = {
                                "name": info["name"], "depth": 0, "gap": False, "gappct": 0, "ev": ev,
                                "obs_low": ev.get("observation_low"), "cyc": la.reset_ts,
                                "sig_px": ev.get("entry_px"), "supply": srow,
                                "created": prev_r.get("created") or now.strftime("%H:%M:%S"),
                                "ts": time.time()}
                            if first_q:
                                _log(f"  🕗READY 생성(MONEY_FLOW) {info['name']}({code}) "
                                     f"저점{ev['observation_low']:,.0f} 신호가{ev.get('entry_px', 0):,.0f}"
                                     f"({ev.get('rebound_pct', 0):+.2f}%) 품질[{_trend_desc(ev.get('trend'))}] "
                                     f"사이클{la.reset_ts} — 재검증 통과 시에만 매수(관찰 계속)")

            # ── ★[2026-07-19 수정지침1] READY 재검증 실행 루프 — 과거 신호로 즉시 매수하지 않는다.
            #    검증(시간창·사이클·신저가·구간·체결강도·품질신선도)은 슬롯 유무와 무관하게 매 폴링
            #    수행해 낡은 항목을 즉시 폐기하고, 실행은 슬롯이 있고 EXEC 판정일 때만. ──
            for rc in list(L.get("ready", {}).keys()):
                r = L["ready"][rc]
                exr = L["slots"].get(rc)
                blocked = rc in buy_ban or bool(exr and (exr.get("pos") or exr.get("pending_buy")
                                                or exr.get("pending_sell")
                                                or int(exr.get("re", 0) or 0) >= REBUY_MAX))
                curr = _cur(rc)
                st_r, _cv_r, _ag_r = _che_info(rc)
                wait_s = time.time() - float(r.get("ts") or 0)
                verdict, why_r = _ready_verdict(r, hm, curr, (L.get("anchors") or {}).get(rc),
                                                st_r, wait_s, blocked,
                                                LA_G1_END, LA_OBS_LO, LA_OBS_HI)
                if verdict == "DROP":
                    L["ready"].pop(rc); dirty = True
                    _log(f"  🗑️READY 폐기 {r.get('name')}({rc}) — {why_r} "
                         f"(생성 {r.get('created')}·신호가{float(r.get('sig_px') or 0):,.0f})")
                    continue
                if verdict == "HOLD":
                    # ★[7/19 밤] HOLD 사유 로그 — 사유가 바뀔 때만 1회(스팸 방지)
                    if r.get("last_hold") != why_r:
                        r["last_hold"] = why_r
                        _log(f"  ⏸️READY 대기 {r.get('name')}({rc}) — {why_r} (생성 {r.get('created')})")
                        dirty = True
                    continue
                cur_slot_n = shared.count(today) if LIVE else _shadow_slot_count(L)
                if cur_slot_n >= SLOTS:
                    continue
                ok_b = _execute_buy(rc, r, r["ev"], curr, exr)
                if ok_b:
                    _log(f"  ✅READY 실행 {r.get('name')}({rc}) @{curr:,.0f} — {why_r} (생성 {r.get('created')})")
                    # ★[기관·외국인 수급 보조 확인 사양5] 판단 로직 무접촉·순수 검증로그 추가일 뿐 —
                    #   MONEY_FLOW 출신 READY만 골라 기록(다른 게이트는 supply 키 자체가 없어 그냥 스킵됨).
                    if (r.get("ev") or {}).get("entry_gate") == "MONEY_FLOW":
                        _log_supply_check(rc, r.get("name"), curr, r.get("supply"))
                L["ready"].pop(rc)   # 실패 시에도 팝 — 앵커 done 해제로 재관찰·재신호가 새 항목을 만든다
                dirty = True

            # ── ★[2026-07-19 심야 친구님 "실전 연결"] 제3 게이트: 응집폭발(BASE_BREAKOUT) ──
            #    아침 고정 감시풀 전 종목: 완성봉 자체수집(45봉) → 폭발 감지 → 돌파선 리테스트
            #    지정가에서 기존 파이프라인(_execute_buy)으로 매수. 추격 금지(폭발봉 종가 매수 없음).
            if BB_ON and BB_ENTRY <= hm <= BB_ENTRY_END:
                bpool = _morning_watch_pool()
                if bpool:
                    _ba = _MCACHE["bars1m"]   # ★[안정성 패치①] 이번 루프 캐시 재사용(중복 읽기 제거)
                    _ba_ok = str(_ba.get("hm", "")) == hm
                    BBt = L.setdefault("bb", {})
                    for code, binfo in bpool.items():
                        b = BBt.setdefault(code, {"hist": [], "cap_hm": None, "state": "SCAN",
                                                  "trades": 0})
                        if int(b.get("trades", 0) or 0) >= REBUY_MAX + 1:
                            continue
                        if _ba_ok and b.get("cap_hm") != hm:
                            mrec = (_ba.get("m") or {}).get(code)
                            if mrec:
                                prevb = mrec.get("prev") or []
                                pvb = mrec.get("pv") or []
                                if prevb and pvb:
                                    try:
                                        o_, h_, l_, c_ = [float(x) for x in prevb[-1][:4]]
                                        mm = int(hm[:2]) * 60 + int(hm[2:]) - 1
                                        ph = f"{mm // 60:02d}{mm % 60:02d}"
                                        if not b["hist"] or b["hist"][-1][0] != ph:
                                            b["hist"].append([ph, o_, h_, l_, c_, float(pvb[-1])])
                                            b["hist"] = b["hist"][-45:]
                                            dirty = True
                                            if b["state"] == "SCAN":
                                                det = _bb_detect(b["hist"])
                                                if det:
                                                    bhi, rng, vx = det
                                                    b.update({"state": "WAIT", "limit": bhi,
                                                              "wait_left": BB_WAIT,
                                                              "bo_che": _che2(code),
                                                              "bo_rng": rng, "bo_vx": vx})
                                                    _log(f"  💥응집폭발 {binfo['name']}({code}) "
                                                         f"베이스상단{bhi:,.0f} 진폭{rng}% 거래량{vx}배 "
                                                         f"— 리테스트 {BB_WAIT}봉 대기(추격 금지)")
                                            elif b["state"] == "WAIT":
                                                b["wait_left"] = int(b.get("wait_left", 0)) - 1
                                                if b["wait_left"] <= 0:
                                                    b["state"] = "SCAN"
                                                    _log(f"  ⌛리테스트 미도달 {binfo['name']}({code}) — 재탐색")
                                    except Exception:
                                        pass
                            b["cap_hm"] = hm
                        # 리테스트 체결(실시간 지정가 도달) → 기존 파이프라인 매수
                        if b.get("state") == "WAIT":
                            exb = L["slots"].get(code)
                            if code in buy_ban or code in (L.get("ready") or {}) \
                                    or (exb and (exb.get("pos") or exb.get("pending_buy")
                                                 or exb.get("pending_sell")
                                                 or int(exb.get("re", 0) or 0) >= REBUY_MAX)):
                                continue
                            curb = _cur(code)
                            if curb <= 0 or curb > float(b.get("limit", 0) or 0):
                                continue
                            if (shared.count(today) if LIVE else _shadow_slot_count(L)) >= SLOTS:
                                continue
                            evb = {"signal": "BUY", "observation_low": float(b["limit"]),
                                   "entry_px": curb, "rebound_pct": 0.0, "trend": None,
                                   "seg_buy": 0, "seg_sell": 0, "entry_gate": "BASE_BREAKOUT",
                                   "reason": f"응집폭발리테스트(진폭{b.get('bo_rng')}%·거래량{b.get('bo_vx')}배·"
                                             f"체결강도{float(b.get('bo_che', 0) or 0):.0f}→{_che2(code):.0f})"}
                            if _execute_buy(code, binfo, evb, curb, exb):
                                b["state"] = "SCAN"
                                b["trades"] = int(b.get("trades", 0) or 0) + 1
                            dirty = True

        # ══ 매수/매도 체결확인 — 접수OK ≠ 체결(확정 전엔 상태 전환 금지) ══
        # ★[2026-07-20 안정성 패치⑤] 확정 근거를 주문번호 기반으로 교체(_vh_pend_buy_step/_vh_pend_sell_step) —
        #   동작(로그·CSV·anchors·buy_ban)은 기존과 동일, "이전 주문 체결량이 새 주문에 섞이는" 경로만 차단.
        for code, s in list(L.get("slots", {}).items()):
            if not isinstance(s, dict) or s.get("done"):
                continue
            if s.get("pending_sell"):
                if _vh_pend_sell_step(br, L, code, s, hm, shared, today, ma5d):
                    dirty = True
                continue
            if s.get("pending_buy"):
                if _vh_pend_buy_step(br, L, code, s, hm, shared, today, buy_fails, buy_ban):
                    dirty = True

        # ══ 매도 ══
        for code, s in L.get("slots", {}).items():
            if s.get("done") or not s.get("pos"):
                continue
            if s.get("pending_sell") or s.get("pending_buy"):   # 체결확인 대기 중엔 중복 주문 금지
                continue
            cur = _cur(code); che = _che2(code); cv = _cum_vol(code)   # ★[수정지침2] 매도 관찰도 보강 소스
            if cur <= 0:
                continue
            ent = float(s["entry"] or 0)
            if ent <= 0:
                continue
            ret = (cur / ent - 1) * 100

            # ── 고점앙커 갱신 — 새 고점이면 관찰 취소(트렌드 관찰 데이터는 음봉 트리거 시점에 새로 RESET) ──
            if cur > s["peak"]:
                s["peak"] = cur
                if s.get("peak_watch_start") is not None:
                    # ★[2026-07-19 심야] 신고점 갱신으로 조기취소되는 HOLD도 전수 기록(사용자 지시
                    #   — "신고점 갱신으로 관찰이 조기취소된 HOLD 사례도 반드시 기록").
                    elapsed_c = time.time() - float(s["peak_watch_start"])
                    log_c = s.get("sw_trend_log") or []
                    pct_c = trend_pct_changes(log_c)
                    _sell_log({"일자": today, "종목코드": code, "종목명": s.get("name", code),
                               "음봉발생시각": s.get("sw_bar_hm", ""), "관찰시작": s.get("sw_start_wall", ""),
                               "관찰종료": now.strftime("%H:%M:%S"), "관찰시간초": round(elapsed_c, 1),
                               "체결강도변화율": pct_c["che_pct"], "매수체결변화율": pct_c["buy_pct"],
                               "매도체결변화율": pct_c["sell_pct"], "거래량변화율": pct_c["vol_pct"],
                               "고점재돌파": "성공", "결과": "HOLD", "매도사유": "신고점갱신관찰취소"})
                    s["peak_watch_start"] = None
                dirty = True

            peak = float(s["peak"] or cur)
            drop_pk = (cur / peak - 1) * 100 if peak > 0 else 0.0
            # ★[2026-07-19 심야] 5일선/10일선 "회복 후 재이탈" 상태 추적 — 처음부터 그 선 아래에서
            #   매수된 종목에는 관련 규칙을 적용하지 않는다(원래도 그 선 아래였던 걸 "약화됐다"고
            #   오판하면 안 되므로). 매수 시점엔 기본 False(아래 매수확정 코드에서 세팅).
            ma5_now_h = ma5d.get(code); ma10_now_h = ma10d.get(code)
            if ma5_now_h and cur > ma5_now_h:
                s["ma5_reclaimed"] = True
            if ma10_now_h and cur > ma10_now_h:
                s["ma10_reclaimed"] = True
            why = None
            if s.get("entry_gate") == "BASE_BREAKOUT":
                # ★[2026-07-19 심야] 응집폭발 전용 출구(백테 확정 프레임 그대로) — 목표/손절/시간청산만.
                #   골짜기 매도사슬(보험선·10일선·음봉관찰)은 이 포지션에 적용하지 않는다(전략별 출구 분리).
                if hm >= EXIT_HM:
                    why = "시간청산"
                elif ret <= BB_STP:
                    why = f"BB손절{BB_STP:.1f}%"
                elif ret >= BB_TGT:
                    why = f"BB목표익절+{BB_TGT:.1f}%"
            elif hm >= EXIT_HM:
                why = "시간청산"
            # ★[2026-07-19 심야] -2%/-4% 이원 손절 폐기 — -2.5% 단일 하드손절이 최우선(조건·예외 없음).
            #   원래 -2%가 항상 먼저 걸려 -4%는 도달 불가능한 죽은 조건이었던 걸 정리.
            #   사유명 "재매수손절"은 그대로 유지 — 아래 재관찰(쿨다운 없음) 로직과 문자열로 연결됨.
            elif ret <= REBUY_STOP:
                why = "재매수손절"
            # ★[2026-07-19 밤 역할분리] 목표익절 삭제(사용자 지시 — 고점 매도엔진이 수익을 끌고
            #   가도록 함) / 5일선 이탈 즉시매도 폐기 — 5일선은 이제 "추세확인"용 참고신호일 뿐
            #   (아래 음봉관찰 점수제의 문턱 조정에만 관여), 매도를 직접 결정하지 않는다.
            #   고점대비-1.5% 보험선(빠른반응·실시간)과 10일선(구조적)은 층위가 달라서 둘 다 유지.
            elif drop_pk <= INSURE_PCT:
                why = f"보험선{INSURE_PCT:.1f}%즉시매도"
            elif s.get("ma10_reclaimed") and ma10_now_h and cur < ma10_now_h:
                # ★[2026-07-19 심야] 10일선 최후보험선은 "매수 후 10일선을 한 번 회복한 종목"에만
                #   활성화 — 처음부터 10일선 아래에서 매수된 종목은 즉시매도 대상이 아니다.
                why = "10일선이탈(최후보험선)즉시매도"
            else:
                # ① 음봉관찰 — ★[2026-07-19 밤 최종설계] 완성된 1분봉이 음봉으로 마감되는 순간이
                #   트리거다(고점대비 -1% 조건은 삭제 — 음봉 트리거가 이미 그 역할을 하는 중복조건).
                #   "최대한 꼭지까지 끌고 가다가 매도세가 매수세를 이기는 순간에만 판다" — 음봉 자체는
                #   매도신호가 아니라 "관찰모드 진입 신호"일 뿐이다.
                b1 = _bar1m(code)
                if b1 is not None and hm != s.get("sell_last_hm"):
                    prev = b1.get("prev") or []
                    if prev:
                        try:
                            bo, bh, bl, bc = [float(x) for x in prev[-1][:4]]
                            s["sell_bearish_now"] = bc < bo   # 방금 완성된 분이 음봉인가
                        except Exception:
                            s["sell_bearish_now"] = False
                    s["sell_last_hm"] = hm
                    dirty = True

                if s.get("peak_watch_start") is None:
                    if s.get("sell_bearish_now"):
                        # ── 음봉 완성 확인 → RESET 후 관찰 시작 ──
                        s["peak_watch_start"] = time.time()
                        s["sw_seg_buy"] = 0.0; s["sw_seg_sell"] = 0.0
                        s["sw_last_cum_vol"] = cv; s["sw_last_px"] = cur; s["sw_last_dir"] = 0
                        s["sw_trend_log"] = []
                        s["sw_start_px"] = cur; s["sw_recovered"] = False
                        s["sw_bar_hm"] = hm; s["sw_start_wall"] = now.strftime("%H:%M:%S")
                        s["sell_bearish_now"] = False   # 트리거 소모 — 다음 새 완성봉이 또 음봉이어야 재발동
                        dirty = True
                else:
                    # ── 관찰 진행중 — 매 폴링마다 매수/매도 체결량(근사) 누적 + 트렌드 기록 ──
                    lp = s.get("sw_last_px"); lv = s.get("sw_last_cum_vol")
                    if lp is not None and cv is not None and lv is not None:
                        dv = max(0.0, cv - lv)
                        d = s.get("sw_last_dir", 0)
                        if cur > lp:
                            d = 1
                        elif cur < lp:
                            d = -1
                        if d > 0:
                            s["sw_seg_buy"] = float(s.get("sw_seg_buy", 0) or 0) + dv
                        elif d < 0:
                            s["sw_seg_sell"] = float(s.get("sw_seg_sell", 0) or 0) + dv
                        s["sw_last_dir"] = d
                    s["sw_last_px"] = cur
                    if cv is not None:
                        s["sw_last_cum_vol"] = cv
                    if cur > float(s.get("sw_start_px") or cur):
                        s["sw_recovered"] = True   # 관찰시작가를 다시 넘어선 적 있음 — 재돌파 시도 성공
                    if che and che > 0:
                        log = s.setdefault("sw_trend_log", [])
                        log.append((time.time(), che, float(s.get("sw_seg_buy", 0) or 0),
                                    float(s.get("sw_seg_sell", 0) or 0), cv if cv is not None else 0.0))
                        s["sw_trend_log"] = log[-300:]
                    dirty = True

                    elapsed = time.time() - float(s["peak_watch_start"])
                    if elapsed >= PEAK_WATCH_SEC:
                        # ★[2026-07-19 밤 재설계] ALL-AND 폐기(고점에서 4개 신호가 동시에 안 뜨고, 거래량은
                        #   패닉/정상눌림에 따라 증감이 갈려서 방향조건 제외) → 4개 항목 독립채점, 3/4↑ 매도.
                        #   가속도(judge_trend)만으론 등속 하락을 놓쳐 direction_persists를 OR로 추가.
                        log_ = s.get("sw_trend_log") or []
                        tr = judge_trend(log_, SELL_TREND_MARGIN_PCT)
                        reclaim_fail = not s.get("sw_recovered", False)
                        pts = {"체결강도감소": bool(tr and tr["che"] < 0),
                               "매수체결감소": bool(tr and tr["buy"] < 0) or direction_persists(log_, 2, -1),
                               "매도체결증가": bool(tr and tr["sell"] > 0) or direction_persists(log_, 3, 1),
                               "고점재돌파실패": reclaim_fail}
                        score = sum(1 for v in pts.values() if v)
                        vol_note = tr["vol"] if tr else None   # 참고용(점수 미반영)
                        # ★[2026-07-19 심야 통합패치] 5일선 = 추세확인(직접매도 아님) — "매수 후
                        #   5일선을 한 번 회복한 종목이 다시 이탈"할 때만 문턱을 1 낮춘다(같은 신호에도
                        #   더 빨리 청산). 처음부터 5일선 아래에서 매수된 종목(저점앵커 매수는 원래
                        #   5일선 아래에서 자주 일어남)은 이 규칙을 바로 적용하지 않는다 — 회복한 적이
                        #   없으면 "약화"라고 볼 기준점 자체가 없기 때문.
                        trend_weak = bool(s.get("ma5_reclaimed")) and bool(ma5_now_h and cur < ma5_now_h)
                        eff_th = max(2, SELL_SCORE_TH - 1) if trend_weak else SELL_SCORE_TH
                        result_txt = "SELL" if score >= eff_th else "HOLD"
                        if score >= eff_th:
                            hit = "+".join(k for k, v in pts.items() if v)
                            why = (f"고점앙커매도(점수{score}/4:{hit}·거래량{ {1:'증가',0:'보합',-1:'감소',None:'-'}[vol_note] }참고·"
                                   f"문턱{eff_th}{'(5일선약화)' if trend_weak else ''})")
                        # ── 실측 로그: 관찰 전수(매도/보류 무관) 기록 — 매도패턴 자동학습용 ──
                        pct = trend_pct_changes(log_)
                        _sell_log({"일자": today, "종목코드": code, "종목명": s.get("name", code),
                                   "음봉발생시각": s.get("sw_bar_hm", ""), "관찰시작": s.get("sw_start_wall", ""),
                                   "관찰종료": now.strftime("%H:%M:%S"), "관찰시간초": round(elapsed, 1),
                                   "체결강도변화율": pct["che_pct"], "매수체결변화율": pct["buy_pct"],
                                   "매도체결변화율": pct["sell_pct"], "거래량변화율": pct["vol_pct"],
                                   "고점재돌파": "실패" if reclaim_fail else "성공",
                                   "결과": result_txt, "매도사유": why or ""})
                        if not why:
                            s["peak_watch_start"] = None; dirty = True   # 점수 미달 — 관찰 취소·계속 보유
            if why:
                kn_s = _known_onos(br, code, "매도") if LIVE else []   # ★[패치⑤] 발주 직전 주문번호 스냅샷
                st = br.order(code, s["qty"], "SELL")
                if st not in ("OK", "TIMEOUT", "SHADOW"):
                    # 매도 실패는 성공 취급 안 함 — 포지션 유지·다음 루프 재시도(방치 금지)
                    _log(f"  🚨매도 실패 {why} {s['name']} {st} → 포지션 유지·다음 루프 재시도")
                    dirty = True
                    continue
                if st == "SHADOW":
                    s["realized"] = round(float(s["realized"]) + ret, 3)
                    _log(f"  💰{why} {s['name']} @{cur:,.0f} ({ret:+.2f}%) 체결강도{che:.0f}")
                    _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": s["name"], "방향": "SELL", "사유": why, "체결강도": round(che, 1),
                          "고점": round(s["peak"]), "현재가": round(cur), "일봉5일선": round(ma5d.get(code, 0)),
                          "진입가": round(ent), "수익퍼센트": round(ret, 2), "재매수회차": int(s.get("re", 0) or 0),
                          "실전여부": "SHADOW", "주문결과": st, "진입출처": s.get("entry_gate")})
                    s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
                    L.setdefault("anchors", {}).pop(code, None)
                    # ★[2026-07-19 재매수개선] 시간쿨다운 폐기 — anchors를 지웠으므로 다음 매수는
                    # 반드시 새 저점 사이클을 처음부터 다시 완성해야만 한다(매도 사유 무관 즉시 재관찰).
                    _log(f"  🔁{s['name']}({code}) 매도 후 IDLE복귀 — 새 저점 사이클 재탐색 시작 "
                         f"(재매수 {int(s.get('re', 0) or 0) + 1}/{REBUY_MAX}회까지)")
                    if LIVE:
                        shared.release(code, today)                  # 슬롯 반환 → 로테이션(그림자는 진짜 풀 안 씀)
                else:
                    # 접수OK ≠ 팔림 — 체결확인 후에만 '팔림' 기록(유령 매도 방지)
                    s["pending_sell"] = {"qty": int(s["qty"]), "px": cur, "ret": round(ret, 3),
                                         "why": why, "che": round(che, 1), "st": st,
                                         "ono": "", "known": kn_s,
                                         "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                                         "sent": time.time()}
                    _log(f"  💰{why} {s['name']} @{cur:,.0f} ({ret:+.2f}%) 체결강도{che:.0f} "
                         f"접수 → 체결확인 대기")
                dirty = True

        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)

    # 마감 요약
    if datetime.now().strftime("%H%M") >= EXIT_HM and L.get("slots"):
        tot = sum(float(s.get("realized") or 0) for s in L["slots"].values())
        n = len([k for k in L["slots"] if not k.startswith("_")])
        _log("─" * 78)
        for code, s in L["slots"].items():
            _log(f"  {s.get('name')}({code}) → {float(s.get('realized') or 0):+.2f}%"
                 + (f" (실체결 {float(s['real_realized']):+.2f}%)"
                    if s.get("real_realized") is not None else ""))
        _log(f"★합계 {tot:+.2f}% · 추정 {tot/100*CAP:+,.0f}원 ({'실전' if LIVE else '그림자'}) → {CSVLOG}")
        # ★[2026-07-20 친구님 승인 — 캡틴 ㉮ 이식] 실체결 기준 정산 병기 — 위 줄은 신호가 기준 낙관치.
        if any(s.get("real_won") is not None for s in L["slots"].values()):
            rtot = sum(float(s.get("real_realized") or 0) for s in L["slots"].values())
            rwon = sum(float(s.get("real_won") or 0) for s in L["slots"].values())
            _log(f"★실체결 정산 {rtot:+.2f}%  ·  {rwon:+,.0f}원 (수수료·세금 전 — 괴리 상세는 {SLIPCSV})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
