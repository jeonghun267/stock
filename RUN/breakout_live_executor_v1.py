# -*- coding: utf-8 -*-
"""[돌파(breakout) 실시간 실전 executor — 친구님 2026-06-23] 손매매 못하니 봇이 대신.
   전략(친구님): 전날 종가배수≥3 테마대장 watchlist → 장초반/장중 눌림없이 날아가는 '당일 신고가 돌파'를
     1종목 몰빵 매수 → ★첫 고점에서 무조건 매도(고점-PEAK_DROP%) · +TP% 익절 · -HARD% 하드 · EOD 청산.
     매도 후 다음 돌파 오면 재진입(횟수제한 없음·돌파는 하루 여러번·1종목씩 자연 페이싱).
   ★보강(친구님): 52주(역사)신고가 돌파 > 60일 전고점 돌파 > 일반 順 우선매수(검증=신고가권+배수 최강).
   ★충돌방지: 눌림(NEW_PB)이 보유 중인 종목은 매수 스킵(계좌 보유 섞임 방지). 포지션파일/청산 분리.
   ★검증된 NEW_PB 실행기와 동일한 broker/order/gate_bars 패턴 재사용.
   ★안전: BRK_LIVE=NO면 모의(주문0)·CAP 소액·1종목·env 즉시롤백.
   실행: pick(주기 09:01~BUY_CUTOFF) / sell(EOD 청산).
"""
import sys, io, csv, json, uuid, os
from pathlib import Path
from datetime import datetime, timedelta
from statistics import median
sys.path.insert(0, r"C:\stock_bot\RUN")
import prices_1m_reader as _P1M   # [CENTRAL-1M 2026-06-24] 중앙 1분봉 파일읽기(opt10080 직접호출 대체)

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
WL = r"C:\stock_bot\data\shadow\prevstrong_watchlist_log.csv"
POS = Path(r"C:\stock_bot\DATA\brk_positions.json")
TRADES = Path(r"C:\stock_bot\DATA\brk_trades.csv")   # ★완료거래 append-only 원장(같은종목 재매매해도 안사라짐·매매일지 정확도)
NEWPB_POS = Path(r"C:\stock_bot\DATA\new_pb_positions.json")   # 충돌방지: 눌림 보유 확인
DEFER = Path(r"C:\stock_bot\DATA\brk_defer.json")              # ★대기후업그레이드 상태(친구님): 약한신호 본 시각 기록·날짜별 리셋
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
EOD_GAP_POS    = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")                    # [CONFLICT 2026-06-27] 종가매수(eod_gap) 보유 — 중복매수 차단
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")   # [CONFLICT 2026-06-27] 종가매수(eod_pickup) 보유 — 중복매수 차단
HICACHE = Path(r"C:\stock_bot\DATA\brk_prior_highs.json")
LOG = Path(r"C:\stock_bot\data\LOG\breakout_live.log")

LIVE = os.environ.get("BRK_LIVE", "NO").strip().upper() == "YES"   # ★기본 NO=페이퍼(주문0). 실탄=setx BRK_LIVE YES
CAP = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or os.environ.get("BRK_CAP_KRW") or "300000"))  # ★통일캡: SAFEPLUS_CAP_KRW 마스터(전 전략 공통·기본30만). 키울땐 이것만.
try:  # [레짐 금액 스케일러 2026-06-29 친구님] 시장 나쁘면 건당 작게(개수는 그대로=작게많이). REGIME_SIZE_SCALE=NO면 1.0(무변경)
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
MAX_POS = int(os.environ.get("BRK_MAX_POS", "6"))                  # ★동시 보유 종목수(친구님 200만÷30만≈6). 1=몰빵
VRMIN = float(os.environ.get("BRK_VRMIN", "3.0"))                   # 전날 배수 선별(우선)
MAX_CAND = int(os.environ.get("BRK_MAX_CAND", "10"))              # ★watchlist(전날) 감시수(친구님 B: 15→10·등락율 중요→오늘무버에 자리 더)
USE_TODAY_MOVERS = os.environ.get("BRK_USE_TODAY_MOVERS", "YES").strip().upper() == "YES"  # ★오늘 장중 거래대금 급등주를 후보에(오늘 새 상한가/눌림 잡기·친구님 커버리지)
MOVER_MIN_CHG = float(os.environ.get("BRK_MOVER_MIN_CHG", "10.0"))  # 오늘무버 편입: opt10032 등락률 이%↑
MOVER_TOP = int(os.environ.get("BRK_MOVER_TOP", "15"))             # 오늘무버 최대 편입수
MAX_TOTAL = int(os.environ.get("BRK_MAX_TOTAL", "30"))           # ★총 감시 종목수 상한(TR 용량)
STEP_UP_PCT = float(os.environ.get("BRK_STEP_UP_PCT", "3.0"))    # ★스텝업 재진입(친구님): 오늘 이미 매매한 종목은 직전 매수가 +이%↑(위로 스텝업)일 때만 재매수(churn 차단·멀티레그 허용)
CONV_MAX = int(os.environ.get("BRK_CONV_MAX", "3"))             # ★수렴/3선 진입 하루 최대(친구님: 3번까지·위로 스텝업 멀티레그)
DIP_MAX = int(os.environ.get("BRK_DIP_MAX", "2"))               # ★눌림 진입 하루 최대(친구님: 조건좋을때 2번까지·3번 절대금지·바닥에서 사기)
BREAK_MAX = int(os.environ.get("BRK_BREAK_MAX", "99"))          # [UNLIMITED-STEPUP 2026-06-26 친구님 "기회마다 무제한"] 1→99=사실상무제한·스텝업게이트로 churn차단·7%천장으로 상투차단. 롤백 setx BRK_BREAK_MAX 1
WAIT_MIN = int(os.environ.get("BRK_WAIT_MIN", "6"))             # ★대기후업그레이드(친구님): 약한신호 바로 안사고 이 분(分)만큼 대기 → 더좋은 신호 나오면 그걸·없으면 원래신호 매수(안놓침). 0=즉시(대기끔)
INSTANT_BREAKOUT = os.environ.get("BRK_INSTANT_BREAKOUT", "YES").strip().upper() == "YES"   # ★돌파 즉시진입(친구님): 형성봉이 당일 전고점 뚫는 순간 봉완성 안기다리고 매수(돌파만·빠른진입). NO=완성봉 대기
CONV_PCT = float(os.environ.get("BRK_CONV_PCT", "2.5"))          # ★5/20/60 이평선 수렴 임계(전날종가 기준 이내면 수렴=최우선 1등·친구님)
CONV_BUY_PCT = float(os.environ.get("BRK_CONV_BUY_PCT", "2.0")) # ★수렴종목 수렴 MA대 이 % 이내(3선 만난 자리)에서 오름세 전환 확인시 매수(친구님)
CONV_TURN_NEAR = float(os.environ.get("BRK_CONV_TURN_NEAR", "2.0")) # ★이평수렴지지 턴업: 바로앞 전고점 이 % 이내(돌파했거나 그 직전·친구님 "그 전에 감지해서 사면")
NEWHIGH_NEAR = float(os.environ.get("BRK_NEWHIGH_NEAR", "2.0"))   # ★40일(2달) 신고가 돌파/직전 판정: 신고가 이 % 이내면 '터치/올라오기 직전'(친구님 2026-06-24·우리데이터 40일 신고가권 최강 +5.65%)
USE_NEWHIGH = os.environ.get("BRK_USE_NEWHIGH", "YES").strip().upper() == "YES"   # ★40일 신고가 돌파 진입경로(친구님 2026-06-24)·백테검증 병행·끄려면 setx BRK_USE_NEWHIGH NO
USE_CONVERGENCE = os.environ.get("BRK_USE_CONVERGENCE", "YES").strip().upper() == "YES"  # ★수렴 스캐너 종목을 봇 후보에 추가(장전체 수렴 헌팅·친구님)
CONV_TOP = float(os.environ.get("BRK_CONV_TOP", "5.0"))         # 수렴후보 채택: px_vs_ma ≤ 이%(바닥/중간만·천정수렴 제외)
# [SETUP-WIRE 2026-06-25 친구님 패턴 실전연결] 세력매집형 셋업(한달베이스→거래량2.5배터짐→음봉소화→양봉재개)
#   스크리너(base_thrust_setup_screener)가 발행한 CSV를 후보 병합 → 전일고가 돌파시 진입(기존 돌파로직)·CHE식 청산.
#   백테 전일고가돌파 진입 +1.91%/MFE+12.6%·체결률61%. 수렴 소스와 동일 패턴. 끄려면 setx BRK_USE_SETUP NO.
USE_SETUP = os.environ.get("BRK_USE_SETUP", "YES").strip().upper() == "YES"
SETUP_MAX = int(os.environ.get("BRK_SETUP_MAX", "10"))          # 셋업 후보 최대 편입수(MAX_TOTAL 내)
# [BASESURGE-WIRE 2026-06-26 친구님 "갑툭 당일 바로 사야돼"] base_surge(횡보→거래량3배↑갑툭) 감지종목을
#   돌파 후보로 당일 병합 → 갑툭 순간 돌파로직(전고돌파+거래량+체결강도)으로 진입. 당일자 감지분만. 끄려면 setx BRK_USE_BASESURGE NO.
USE_BASESURGE = os.environ.get("BRK_USE_BASESURGE", "YES").strip().upper() == "YES"
BASESURGE_CSV = r"C:\stock_bot\data\shadow\base_surge_intraday\detect_log.csv"
BASESURGE_VMULT = float(os.environ.get("BRK_BASESURGE_VMULT", "3.0"))  # 거래량배수 이 이상만(친구님: 3배↑)
ENTRY_PCT = float(os.environ.get("BRK_ENTRY_PCT", "3.0"))          # 시가대비 +이% = 돌파
CHASE_CAP = float(os.environ.get("BRK_CHASE_CAP", "18.0"))         # 시가대비 +이% 넘으면 직진매수 금지(눌림으로만)
CPOS_MIN = float(os.environ.get("BRK_CPOS_MIN", "0.6"))           # ★매수자 우위: 종가가 봉 상단 이상(매수자가 밀어올림)
MORNING_CUTOFF = os.environ.get("BRK_MORNING_CUTOFF", "1000")    # ★아침돌파: 이 시각 이전 장초반만(눌림없이 날아가는 flyer 포착)
MORNING_CAP = float(os.environ.get("BRK_MORNING_CAP", "10.0"))   # ★아침돌파: 시가대비 이%까지만(일찍 잡고 고가추격 X)
CONV_CONFIRM = float(os.environ.get("BRK_CONV_CONFIRM", "1.0"))  # ★수렴돌파: 가격이 수렴대 +이% 위로 확인돼야 매수(가짜돌파 방지·친구님)
VOL_MULT = float(os.environ.get("BRK_VOL_MULT", "1.3"))            # 돌파/반등봉 거래량 ≥ 직전중앙×이
NO_DEEPCRASH = os.environ.get("BRK_NO_DEEPCRASH", "YES").strip().upper() == "YES"  # [2026-06-27 친구님] 당일 깊은급락후 회복(데드캣)=돌파아님→매수금지(DEEPV영역)
DEEP_CRASH = float(os.environ.get("BRK_DEEP_CRASH", "6.0"))        # 일중고 대비 이%↑ 급락찍었으면 데드캣(백테 데드캣 EV-1.53/큰손실26 vs 깨끗-0.96/19)
PREV_BODY_MIN = float(os.environ.get("BRK_PREV_BODY_MIN", "3.0")) # ★전일 일봉 장대양봉: 몸통(종가-시가)/시가 ≥ 이%(대장주 확신·친구님)
RUN_MIN = float(os.environ.get("BRK_RUN_MIN", "5.0"))            # 눌림 전제: 당일 고점이 시가대비 이%↑ 올랐던 종목
DIP_LO = float(os.environ.get("BRK_DIP_LO", "4.0"))             # 눌림: 고점대비 -이%↑ 빠짐(친구님 -4~-8%)
DIP_HI = float(os.environ.get("BRK_DIP_HI", "14.0"))            # ★눌림 깊이 상한(+4%까지=-18%·친구님 깊은눌림 JW -15% 잡게)
DIP_NO_VWAP = os.environ.get("BRK_DIP_NO_VWAP", "YES").strip().upper() == "YES"   # ★눌림 VWAP 완화(친구님 2026-06-24): 깊은눌림은 VWAP 아래서 반등 시작→VWAP 조건 빼고 '양봉턴(반등중)'만으로 진입(엑스게이트식 놓침 방지). 끄려면 setx BRK_DIP_NO_VWAP NO
DIP_LEADER_ONLY = os.environ.get("BRK_DIP_LEADER_ONLY", "YES").strip().upper() == "YES"  # ★눌림은 진짜 대장주(leader=1)에만(친구님 2026-06-24 "깊은눌림은 진짜 대장주에서"): 비대장 급등주(조아제약·위지트식) 눌림 churn 차단. 끄려면 setx BRK_DIP_LEADER_ONLY NO
# [DIP-MA5-RISING 2026-06-29 친구님 "정배열(1/5/20)일 때 눌림 적극·진입은 1일선이 5일선 만남"] 백테(5/26~6/19): 5일선근접 진입이 baseline -2.09%→-0.36%·큰손실37%→18%·트레일링시 큰손실0%.
#   눌림 경로를 rising(1/5/20 우상향)게이트 + 현재가가 일봉5일선 근접(|dev5|≤BAND%) + 양봉턴(반등확인)으로 전환. rising이면 DEEP_CRASH 면제 + 비대장 허용. 청산은 기존 che_exit(고점/체결강도하락). 끄려면 setx BRK_DIP_MA5_RISING NO(=기존 dd기반 눌림).
DIP_MA5_RISING = os.environ.get("BRK_DIP_MA5_RISING", "NO").strip().upper() == "YES"   # ★마스터: 정배열 추세눌림(Type-B) 모드 ON/OFF (눌림 경로를 Type-B 재돌파로 대체)
DIP_MA5_BAND   = float(os.environ.get("BRK_DIP_MA5_BAND", "2.0"))   # (구) 일봉5일선 근접%
# [TYPE-B 2026-06-29 친구님/GPT·백테검증] 정배열 5EMA 추세눌림 재돌파. 6개월백테 Type-B가 Type-A보다 MFE+5.26%(vs+4.09)·5%도달35%(vs26)·승률44%(vs43) 우수. 체결강도는 엔진 매수게이트(ENTRY_CHE_CONFIRM)+매도(che_exit) 자동상속.
TYPEB_RUN_MIN  = float(os.environ.get("BRK_TYPEB_RUN_MIN", "3.0"))  # 강한 상승: 당일고점이 시가+이%↑
TYPEB_EMA_NEAR = float(os.environ.get("BRK_TYPEB_EMA_NEAR", "1.5")) # 1분 5EMA 근접 눌림 기준%(저점이 5EMA +이% 이내까지 눌림)
# [EARLY_MOMENTUM_BREAK 2026-06-29 친구님 "조기진입·오전엔 거래대금문제→체결강도 1차게이트·실전바로"] ★미검증(백테불가·shadow 내일첫데이터) — 체결강도≥EARLY_CHE_MIN 하드게이트가 유일안전장치(데이터없으면 매수안함).
EARLY_LIVE     = os.environ.get("BRK_EARLY_LIVE", "NO").strip().upper() == "YES"   # 마스터: 조기돌파 실전진입 ON/OFF. 롤백 setx BRK_EARLY_LIVE NO
EARLY_END      = os.environ.get("BRK_EARLY_END", "1000")          # 조기돌파 시간창 끝(이 시각 이전만·오전)
EARLY_UP_LO    = float(os.environ.get("BRK_EARLY_UP_LO", "2.0"))  # 조기돌파 상승률 하한%
EARLY_UP_HI    = float(os.environ.get("BRK_EARLY_UP_HI", "7.0"))  # 조기돌파 상승률 상한%
EARLY_CHE_MIN  = float(os.environ.get("BRK_EARLY_CHE_MIN", "120"))# ★조기돌파 체결강도 하드게이트(거래량 대체·데이터없으면 매수금지)
# [MA20-DEV 부스터 2026-06-29 친구님 "20일선 멀어질때 엄청상승"·백테검증] 정배열 MA20이격%별: 붙음0~3=약함·5~12=건강가속(익일+0.35·승45.5 최고)·25%+=MFE+13%폭발but과열(blow-off). LOG=shadow기록만(매매무변경)·ON=25%+추격제한.
MA20DEV_MODE = os.environ.get("BRK_MA20DEV_MODE", "LOG").strip().upper()   # LOG(기록만)/ON(활성)/OFF
MA20DEV_HOT  = float(os.environ.get("BRK_MA20DEV_HOT", "25.0"))            # 이 이격%↑=과열(ON시 강한체결강도만 허용)
MA20DEV_CSV  = r"C:\stock_bot\data\ma20dev_shadow.csv"
# [MA-EXIT 2026-06-29 친구님 구조기반청산 "5% 토해내는거 싫어·고수전략"] 레이어 청산: 1번 체결강도(기존 seller1·빠르게)·2번 5일선이탈+체결약·3번 20일선이탈 하드.
#   백테: 5일선 청산 평균+0.27%·큰손실7%(2%트레일 -0.24/16%보다 우수)·20일선 하드 평균+0.56%. 체결강도가 -5%전에 끊어 토함 방지. 기본 NO=기존동작. 오버나잇은 별도(지금 EOD청산 유지).
MA_EXIT = (os.environ.get("BRK_MA_EXIT", "NO").strip().upper() == "YES"
           or os.environ.get("EXIT_MA_LAYER", "NO").strip().upper() == "YES")   # ★공통 마스터 EXIT_MA_LAYER(전 전략 똑같이) 또는 돌파전용 BRK_MA_EXIT
# [통일 매도 2026-07-01 친구님 "전 전략 체결량/수급으로 통일"] vol_exit: 1차=수급(매수/매도 우위)·안전장치=20선 무조건.
#   ON이면 매도우위 스마트감시·MA·트레일을 vol_exit로 대체(하드손절·돌파재이탈은 유지). 롤백 setx UNIFIED_VOL_EXIT NO.
UNIFIED_VOL_EXIT = os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES"
PEAK_DROP = float(os.environ.get("BRK_PEAK_DROP", "2.0"))         # ★2차 방어선: 고점(최고가)대비 -이%(친구님 6/23 3→2%·1차는 매도우위 스마트감시)
TP_PCT = float(os.environ.get("BRK_TP_PCT", "10.0"))              # +이% 익절
HARD_PCT = float(os.environ.get("BRK_HARD_PCT", "5.0"))          # -이% 하드손절
SELLER_GRACE = int(os.environ.get("BRK_SELLER_GRACE", "4"))      # ★1차 매도우위 유예(분)·친구님 6/24 "금방 사서 금방 매도우위로 파는 churn 문제": 매수 후 이 시간 동안은 매도우위(1차) 보류(하드/익절/고점-2%만 작동)→직후 노이즈 봉에 즉시청산 방지·강한돌파 타게. 끄려면 setx BRK_SELLER_GRACE 0
# [REAL-MICRO 2026-06-24] ★실시간 체결강도/호가(broker IPC snapshot) 읽어 1차 매도우위 확인 — 친구님 "체결강도 강하면 안 팔고 보유"
MICRO_USE = os.environ.get("BRK_MICRO_USE", "YES").strip().upper() == "YES"   # 끄면 봉신호만(기존). setx BRK_MICRO_USE NO
SELL_CHE_MAX = float(os.environ.get("BRK_SELL_CHE_MAX", "100"))  # 1차 매도: 체결강도 이 값 미만(매도우위)일 때만 매도확정. 강하면(≥) 보유→2차 트레일 위임
SELL_OB_MAX  = float(os.environ.get("BRK_SELL_OB_MAX", "0.8"))   # or 호가 imb(매수/매도총잔량) 이 값 미만(매도잔량 우위)이면 매도확정
MICRO_SNAP_FILE  = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
MICRO_WATCH_FILE = Path(r"C:\stock_bot\IPC\micro_watch_breakout.json")
# [REAL-MICRO 2026-06-24] ★매수 확신게이트(친구님: 체결강도>120·호가>1.5일 때 진짜돌파). 명백한 매도우위면 false돌파로 보고 매수보류.
ENTRY_CHE_CONFIRM = os.environ.get("BRK_ENTRY_CHE_CONFIRM", "YES").strip().upper() == "YES"   # 끄려면 setx BRK_ENTRY_CHE_CONFIRM NO
ENTRY_CHE_WEAK    = float(os.environ.get("BRK_ENTRY_CHE_WEAK", "95"))    # 체결강도 이 미만이면 매수보류(strict 원하면 setx 120)
ENTRY_OB_WEAK     = float(os.environ.get("BRK_ENTRY_OB_WEAK", "0.8"))    # 호가 imb(매수/매도총잔량) 이 미만(매도잔량 우위)이면 매수보류
ENTRY_CHE_STRONG  = float(os.environ.get("BRK_ENTRY_CHE_STRONG", "120")) # 체결강도 이 이상=확신(로그 표시)
# [RESTEP-CHE 2026-06-26 친구님 "재매수는 체결강도 110"] 같은종목 재매수(스텝업)는 첫매수(95)보다 엄격 — 체결강도 이 이상(매수확실히이김)일때만.
#   꼭대기서 찔끔 올라도(스텝업%) 체결강도 약하면 추가매수 안함=무너지는거 회피. 롤백 setx BRK_RESTEP_CHE 0(끔·기존동일).
RESTEP_CHE = float(os.environ.get("BRK_RESTEP_CHE", "110"))
# [SOFT-CAP 2026-06-29 친구님 "어느 지점부터 안되는게 박스돌파랑 충돌"] 시가대비 %캡을 '확인여부'에 연동.
#   ≤CHASE_SOFT: 기존대로. CHASE_SOFT~CHASE_CAP(소프트밴드): 체결강도 강+매수잔량 우위(=뚫고 버팀)일 때만 매수허용.
#   백테(6/26 추격>7%죽음)는 '미확인 추격'에만 적용·확인된 박스돌파(버팀)는 blow-off아니므로 +CHASE_CAP까지 허용.
CHASE_SOFT       = float(os.environ.get("BRK_CHASE_SOFT", "7.0"))    # 이 % 초과는 '확인된 박스돌파'만(체결강도강+매수우위)
ENTRY_OB_STRONG  = float(os.environ.get("BRK_ENTRY_OB_STRONG", "1.0"))  # 소프트밴드 진입조건: 호가 imb 이 이상(매수잔량 우위=버팀)
# [정배열 D 2026-06-29 친구님 "모든 전략은 정배열일 때만 매수"] 돌파=신고가전략→strict(MA5>MA20>MA60). 데이터없으면 통과(fail-open).
try:
    import trend_filter as _TF
except Exception:
    _TF = None
JEONGBAE_MODE_BRK = os.environ.get("BRK_JEONGBAE_MODE", "strict").strip().lower()
# [A 2분버팀 2026-06-29 친구님 "뚫는 순간 말고 뚫고 버티는 순간 산다"] 돌파 즉시진입은 ★직전 완성봉이 강세(buyers_win=양봉·종가상단·전봉위·VWAP위·거래량)일 때만 허용
#   = 직전 1분 이미 버팀 + 형성봉 신고가 = 2분 버팀 proxy. 스파이크 단발 뚫고 곧 꺼지는 가짜돌파 차단. 눌림은 미적용(즉시 유지). 롤백 setx BRK_HOLD_CONFIRM NO.
HOLD_CONFIRM = os.environ.get("BRK_HOLD_CONFIRM", "YES").strip().upper() == "YES"
# [B 재이탈손절 2026-06-29 친구님 "뚫고 다시 그 자리 밑으로 빠지면 돌파실패=손절"] 돌파레벨(뚫은 저항) 저장 → 현재가가 그 아래로 재이탈하면 즉시 청산. 롤백 setx BRK_REBREAK_STOP NO.
REBREAK_STOP = os.environ.get("BRK_REBREAK_STOP", "YES").strip().upper() == "YES"
BUY_CUTOFF = os.environ.get("BRK_BUY_CUTOFF", "1500")            # 하루종일 감시(15:00까지 신규진입·15:18 청산)
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"; print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True); io.open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _z(c): return str(c).zfill(6)
def _jload(p):
    try: return json.load(io.open(p, encoding="utf-8"))
    except Exception: return {}
def _jsave(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")          # [원자적쓰기 2026-06-29] 임시파일→os.replace = 쓰기중 크래시시 손상방지
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag):
    """검증된 NEW_PB 패턴 동일. BRK_LIVE=NO면 모의(주문0)."""
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (BRK_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"brk_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"BRK_{side}_{code}", screen_no="9714")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} → {str(r)[:100]}")
        _st = str((r or {}).get("status", "")).upper()
        # [BUGFIX 2026-06-30 #1 비대칭] 매수=OK|TIMEOUT 기록(미체결확인불가→재매수 중복위험 회피)·매도=OK만 완료(비OK는 OPEN유지 재시도)
        if side == "BUY":
            _ok = _st in ("OK", "TIMEOUT")
        else:
            _ok = (_st == "OK")
        if not _ok or _st != "OK":
            _log(f"[{tag}] 주문 status={_st or 'EMPTY'} → " + ("성공" if _ok else "실패처리") + (" (TIMEOUT=체결미확인·수동확인 권장)" if _st == "TIMEOUT" else ""))
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _gate_bars(bc, code):
    """[CENTRAL-1M 2026-06-24] ★opt10080 직접호출 폐지 → 중앙수집 DATA/prices_1m.csv 읽기(친구님: 조회 중복제거).
       반환형식 [(hm,o,h,l,c,v)]·해상도 1분봉 그대로·매수로직 무수정(데이터 출처만 교체). 호출은 collect_prices_1m만."""
    return _P1M.bars(code, log=_log, tag="돌파")


def _candidates(bc=None):
    """오늘 돌파후보 = 전날배수≥VRMIN 테마대장 watchlist. {code: (name, vr, theme)}."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        rows = list(csv.DictReader(io.open(WL, encoding="utf-8-sig", errors="replace")))
    except OSError:
        return {}
    def vrf(r):
        try: return float(r.get("vr") or 0)
        except ValueError: return 0
    day = [r for r in rows if r.get("next_date") == today]
    if not day:
        sds = sorted({r["signal_date"] for r in rows if r.get("signal_date", "") < today})
        if sds:
            day = [r for r in rows if r.get("signal_date") == sds[-1]]
    day = sorted(day, key=lambda r: -vrf(r))           # 배수 높은순
    strong = [r for r in day if vrf(r) >= VRMIN]        # 배수≥VRMIN 우선
    sel = (strong if len(strong) >= MAX_CAND else day[:MAX_CAND])[:MAX_CAND]   # 부족하면 상위로 채워 MAX_CAND개
    cands = {_z(r["code"]): (r.get("name", ""), vrf(r), r.get("theme", "")) for r in sel}
    # ★수렴 종목 통합(친구님 2026-06-23 "장전체 수렴 헌팅"): 스캐너 바닥수렴(px_vs_ma≤CONV_TOP)을 봇 후보 추가.
    #   봇은 opt10080 직접폴링이라 30개 수집기와 무관하게 어떤 종목이든 1분봉 본다. 천정수렴(위험)은 제외.
    if USE_CONVERGENCE:
        for code, nm, theme in _conv_zone_codes():
            if len(cands) < MAX_TOTAL:
                cands.setdefault(code, (nm, 0.0, theme))
    # ★세력매집형 셋업(친구님 2026-06-25): 한달베이스→거래량터짐→음봉소화→양봉재개 종목을 후보 병합(전일고가 돌파 진입)
    if USE_SETUP:
        for code, nm, theme in _setup_zone_codes():
            if len(cands) < MAX_TOTAL:
                cands.setdefault(code, (nm, 0.0, theme))
    # ★갑툭 당일매수(친구님 2026-06-26 "갑툭 바로 사야돼"): base_surge 횡보→거래량3배↑ 갑툭종목을 당일 후보 병합(돌파로직 진입)
    if USE_BASESURGE:
        for code, nm, theme in _basesurge_zone_codes():
            if len(cands) < MAX_TOTAL:
                cands.setdefault(code, (nm, 0.0, theme))
    # ★오늘 무버 추가(친구님): 오늘 장중 거래대금 급등주(opt10032)를 후보에 = 오늘 새 상한가/눌림도 봄(커버리지 구멍 메움)
    if bc is not None and USE_TODAY_MOVERS:
        for code, nm, chg in _today_movers(bc):
            if len(cands) >= MAX_TOTAL:
                break
            cands.setdefault(code, (nm, 0.0, "오늘무버"))
    return cands


def _leader_codes():
    """오늘 watchlist의 실제 테마 대장주(leader=1) 코드 집합 — 친구님 2026-06-24 "깊은 눌림은 진짜 대장주에서 나온다".
       기존 is_lead='수렴아니면 다 대장'은 엉성(키스트론 leader=0도 대장 취급) → 실제 leader 플래그 사용. 예외시 빈집합(fail-safe)."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        rows = list(csv.DictReader(io.open(WL, encoding="utf-8-sig", errors="replace")))
    except OSError:
        return set()
    day = [r for r in rows if r.get("next_date") == today]
    if not day:
        sds = sorted({r["signal_date"] for r in rows if r.get("signal_date", "") < today})
        if sds:
            day = [r for r in rows if r.get("signal_date") == sds[-1]]
    return {_z(r["code"]) for r in day if str(r.get("leader", "")).strip() == "1"}


def _today_movers(bc):
    """오늘 장중 급등주/상한가 [(code, name, chg)...]. ★opt10027(등락률상위)=상한가도 잡음(거래대금 작아도) + opt10032(거래대금상위) 보강.
       등락률 높은순(상한가 우선) MOVER_TOP개. 극단(>31%·신규상장/우선주 노이즈)·동전(<1000원) 제외."""
    movers = {}   # code -> (chg, name)
    def _pf(s):
        try: return float(str(s).replace("+", "").replace(",", ""))
        except (ValueError, TypeError): return 0.0
    # ① opt10027 등락률 상위 = 상한가/급등(거래대금 작아도 잡힘) — 핵심
    try:
        res = bc.tr("opt10027", inputs={"시장구분": "101", "정렬구분": "1", "거래량조건": "0000",
                                        "종목조건": "0", "신용조건": "0", "상하한포함": "1"},
                    output_fields=["종목코드", "종목명", "현재가", "등락률"], screen_no="9717", timeout_sec=8.0)
        for r in (((res or {}).get("data") or {}).get("records") or []):
            code = _z(str(r.get("종목코드", "")).lstrip("A"))
            if len(code) != 6:
                continue
            chg = _pf(r.get("등락률")); px = abs(int(_pf(r.get("현재가"))))
            if MOVER_MIN_CHG <= chg <= 31.0 and px >= 1000:
                movers[code] = (chg, (r.get("종목명", "") or code)[:9])
    except Exception as e:
        _log(f"오늘무버 opt10027 실패 {e}")
    # ② opt10032 거래대금 상위 급등 보강
    try:
        res = bc.tr("opt10032", inputs={"시장구분": "101", "관리종목포함": "0"},
                    output_fields=["종목코드", "종목명", "등락률"], screen_no="9716", timeout_sec=8.0)
        for r in (((res or {}).get("data") or {}).get("records") or []):
            code = _z(str(r.get("종목코드", "")).lstrip("A"))
            if len(code) != 6:
                continue
            chg = _pf(r.get("등락률"))
            if MOVER_MIN_CHG <= chg <= 31.0:
                movers.setdefault(code, (chg, (r.get("종목명", "") or code)[:9]))
    except Exception as e:
        _log(f"오늘무버 opt10032 실패 {e}")
    rows = sorted(((chg, c, nm) for c, (chg, nm) in movers.items()), reverse=True)  # 등락률 높은순=상한가 우선
    return [(c, nm, chg) for chg, c, nm in rows[:MOVER_TOP]]


def _conv_zone_codes():
    """최신 수렴 스캐너 CSV에서 바닥수렴(px_vs_ma ≤ CONV_TOP) 종목 [(code, name, theme)...]. 천정 제외."""
    import glob
    fs = sorted(glob.glob(r"C:\stock_bot\data\shadow\ma_convergence_*.csv"))
    if not fs:
        return []
    out = []
    try:
        for r in csv.DictReader(io.open(fs[-1], encoding="utf-8-sig", errors="replace")):
            try:
                pv = float(r.get("px_vs_ma") or 99)
            except (ValueError, TypeError):
                pv = 99
            if pv <= CONV_TOP:
                out.append((_z(r.get("code", "")), (r.get("name", "") or r.get("code", ""))[:9], "수렴:" + (r.get("theme", "") or "")[:7]))
    except OSError:
        pass
    return out


def _setup_zone_codes():
    """[SETUP-WIRE 2026-06-25] 최신 세력매집 셋업 CSV(base_thrust_setup_*.csv)에서 후보 [(code,name,theme)...].
       스크리너가 발행(한달베이스+거래량터짐+음봉소화+양봉재개). 실행기는 이들을 전일고가 돌파시 진입. 예외→[](fail-safe)."""
    import glob
    fs = sorted(glob.glob(r"C:\stock_bot\data\shadow\base_thrust_setup_*.csv"))
    if not fs:
        return []
    out = []
    try:
        for r in csv.DictReader(io.open(fs[-1], encoding="utf-8-sig", errors="replace")):
            code = _z(r.get("code", ""))
            if len(code) == 6:
                out.append((code, (r.get("name", "") or code)[:9], "매집:" + (r.get("theme", "") or "")[:7]))
            if len(out) >= SETUP_MAX:
                break
    except OSError:
        pass
    return out


def _basesurge_zone_codes():
    """[BASESURGE-WIRE 2026-06-26] base_surge 갑툭 감지종목(당일·거래량배수≥VMULT) → 돌파 후보.
       detect_log.csv: date,first_hm,code,name,tier,entry,chg,vmult,... 당일자만·3배↑. 예외→[](fail-safe)."""
    if not USE_BASESURGE:
        return []
    out = []
    try:
        import os as _os
        if not _os.path.exists(BASESURGE_CSV):
            return []
        today = datetime.now().strftime("%Y%m%d")
        for r in csv.DictReader(io.open(BASESURGE_CSV, encoding="utf-8-sig", errors="replace")):
            if str(r.get("date", "")).strip() != today:
                continue
            try:
                vm = float(r.get("vmult", "0") or 0)
            except ValueError:
                vm = 0
            if vm < BASESURGE_VMULT:
                continue
            code = _z(r.get("code", ""))
            if len(code) == 6:
                out.append((code, (r.get("name", "") or code)[:9], "갑툭:" + (r.get("theme", "") or "")[:7]))
    except OSError:
        pass
    return out


def _prior_highs(codes):
    """각 후보의 직전 고점(전일까지) {code:(hi52, hi60, prev_high)} — 신고가/전고점 돌파 판정용. 일자캐시."""
    today = datetime.now().strftime("%Y%m%d")
    c = _jload(HICACHE)
    if c.get("date") == today and all(k in c.get("h", {}) for k in codes):
        return {k: tuple(v) for k, v in c["h"].items()}
    out = {}
    try:
        import pandas as pd, numpy as np
        want = set(codes)
        e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=["date", "code", "market", "open", "high", "low", "close"], low_memory=False)
        e = e[e["market"] == "KOSDAQ"].copy(); e["code"] = e["code"].str.zfill(6)
        e = e[e["code"].isin(want)]
        for col in ["open", "high", "low", "close"]:
            e[col] = pd.to_numeric(e[col], errors="coerce")
        e = e[e["date"] < today].sort_values(["code", "date"])
        for code, g in e.groupby("code", sort=False):
            h = g["high"].values; cl = g["close"].values; op = g["open"].values; lo = g["low"].values
            if len(h) == 0:
                continue
            hi52 = float(np.nanmax(h[-250:])); hi60 = float(np.nanmax(h[-60:])); pvh = float(h[-1])
            hi40 = float(np.nanmax(h[-40:]))   # ★40일(2달) 전고점 — 우리데이터 신고가권 최강(친구님 2026-06-24)
            pvo = float(op[-1]); pvc = float(cl[-1]); pvl = float(lo[-1])
            body = (pvc - pvo) / pvo * 100 if pvo > 0 else 0
            rng = pvh - pvl
            prevbull = 1 if (pvc > pvo and (body >= PREV_BODY_MIN or (rng > 0 and (pvc - pvo) / rng >= 0.6))) else 0  # ★전일 장대양봉
            # ★5/20/60 이평선 수렴(친구님 최우선 #1): 전날 종가 기준 3선이 CONV_PCT% 이내로 모임
            converged = 0; ma_lvl = 0.0
            ma5_d = float(np.nanmean(cl[-5:])) if len(cl) >= 5 else 0.0   # [DIP-MA5-RISING] 일봉 5일선(직전 5종가평균) = 눌림 진입 기준선(현재가가 여기 만나면 진입)
            ma20_d = float(np.nanmean(cl[-20:])) if len(cl) >= 20 else 0.0  # [MA20-DEV] 일봉 20일선 = 이격% 부스터 기준선
            if len(cl) >= 60:
                ma5 = float(np.nanmean(cl[-5:])); ma20 = float(np.nanmean(cl[-20:])); ma60 = float(np.nanmean(cl[-60:]))
                mmin = min(ma5, ma20, ma60); ma_lvl = (ma5 + ma20 + ma60) / 3   # 수렴 가격대(제일 싸게 살 자리)
                if mmin > 0 and (max(ma5, ma20, ma60) - mmin) / mmin * 100 <= CONV_PCT:
                    converged = 1
            out[code] = (hi52, hi40, hi60, pvh, prevbull, converged, ma_lvl, ma5_d, ma20_d)
    except Exception as ex:
        _log(f"prior_highs 실패(보강 생략): {ex}")
    _jsave(HICACHE, {"date": today, "h": out})
    return out


def _newpb_held():
    """눌림(NEW_PB)이 현재 보유 중인 종목 set — 같은종목 매수 스킵(계좌 충돌방지)."""
    s = set()
    for p, key in ((NEWPB_POS, "status"), (RT_OPEN, None)):
        d = _jload(p)
        for code, v in (d.items() if isinstance(d, dict) else []):
            if not isinstance(v, dict):
                continue
            if key is None or v.get("status") == "OPEN":
                s.add(_z(code))
    return s


def _eod_held():
    """[CONFLICT 2026-06-27 ★6/26 3중매매 수정] 종가매수분(eod_gap·eod_pickup) 현재 보유 종목 set —
       돌파/NEW_PB가 같은종목 중복매수 차단(6/26 키스트론·삼익이 종가매수분과 동시보유=같은종목 자본 3배몰림).
       OPEN+qty>0만. eod_pickup은 nested{날짜:{코드:pos}}라 최근7일 날짜키만(오래된 stale OPEN 배제).
       env CONFLICT_EXCLUDE_EOD=NO로 끔. 실패→빈set(fail-safe·차단안함·기존동작)."""
    if os.environ.get("CONFLICT_EXCLUDE_EOD", "YES").strip().upper() != "YES":
        return set()
    s = set()
    try:
        d = _jload(EOD_GAP_POS)   # flat {code:pos}
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                    s.add(_z(c))
    except Exception:
        pass
    try:
        d = _jload(EOD_PICKUP_POS)   # nested {date:{code:pos}}
        if isinstance(d, dict):
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            for dt, codes in d.items():
                if not (isinstance(dt, str) and dt.isdigit() and dt >= cutoff and isinstance(codes, dict)):
                    continue
                for c, p in codes.items():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                        s.add(_z(c))
    except Exception:
        pass
    return s


def _typeb_signal(bars):
    """[TYPE-B] 정배열 5EMA 추세눌림 재돌파 — bars[-1]이 진입봉인지(백테 detect_B 동일).
       조건: 강한상승(고점≥시가+RUN_MIN) + 1분5EMA 우상향 + 직전 1~3봉이 5EMA 근접 눌림 + 거래량 감소 + Higher Low + 현재봉이 직전5봉 고점 재돌파 + 양봉.
       (rising 게이트는 호출측·체결강도는 엔진 매수게이트+che_exit 자동상속.) 데이터부족/예외=False(fail-safe)."""
    try:
        n = len(bars)
        if n < 8:
            return False
        o0 = bars[0][1]
        if o0 <= 0:
            return False
        k = 2.0 / (5 + 1); e = bars[0][4]; ema = []
        for b in bars:
            e = b[4] * k + e * (1 - k); ema.append(e)
        i = n - 1
        hm, o, h, l, c, v = bars[i]
        dh = max(b[2] for b in bars[:i])
        if (dh / o0 - 1) * 100 < TYPEB_RUN_MIN:                  # 강한 상승 있었나
            return False
        if ema[i] <= ema[i - 3]:                                # 5EMA 우상향(추세)
            return False
        pull = bars[i - 3:i]
        pull_low = min(b[3] for b in pull)
        if pull_low > ema[i] * (1 + TYPEB_EMA_NEAR / 100):       # 5EMA 근접까지 눌렸나
            return False
        rise_v = sum(b[5] for b in bars[i - 6:i - 3]) / 3.0; pull_v = sum(b[5] for b in pull) / 3.0
        if pull_v >= rise_v:                                     # 눌림 거래량 감소
            return False
        if pull_low <= min(b[3] for b in bars[i - 6:i - 3]):     # Higher Low
            return False
        if c <= max(b[2] for b in bars[i - 5:i]):                # 직전 고점 재돌파
            return False
        if c <= o:                                               # 양봉
            return False
        return True
    except Exception:
        return False


def _entry_signal(bars, converged=0, ma_lvl=0.0, hi40=0.0, vr=0.0, is_lead=False, ma5_d=0.0, rising=False):
    """★진입 신호. ①수렴돌파 ②눌림 ③아침돌파 ④이평수렴지지(3선 만난 자리서 오름세 전환·친구님 2026-06-24).
       매수자 우위(=오름세 전환) = 양봉 + 종가 봉상단(cpos≥CPOS_MIN) + 전봉 종가 위 + VWAP 위 + 거래량 늘기.
       이평수렴지지 = 위 + 바로앞 전고점 근처/돌파(near_ph). 6분 대기 폐지 — 전부 즉시진입.
       (진입가, 당일고점, 유형) or None."""
    if len(bars) < 3:
        return None
    now_hm = datetime.now().strftime("%H%M")          # ★완성봉 기준(친구님): 형성중인 현재 분 봉 제외
    live_bar = None
    if bars[-1][0] >= now_hm:
        live_bar = bars[-1]                           # ★형성 중인 현재봉 — 돌파 즉시진입용(완성 안 기다림)
        bars = bars[:-1]
    if len(bars) < 2:
        return None
    o0 = bars[0][1]
    if o0 <= 0:
        return None
    dayhigh = max(b[2] for b in bars)
    daylow = min(b[3] for b in bars)
    # [DEEP-CRASH 2026-06-27 친구님] 당일 일중고 대비 -DEEP_CRASH%↑ 급락 찍었으면 = 깊은V 회복(데드캣)이지
    #   깨끗한 돌파 아님 → 매수금지(그 바닥은 DEEPV가 잡음). 모헨즈 6/26 천정추격(-2.16%)이 이 케이스.
    #   롤백 env BRK_NO_DEEPCRASH=NO. 깨끗한 돌파(급락無)는 영향0.
    deep_crashed = NO_DEEPCRASH and dayhigh > 0 and (dayhigh - daylow) / dayhigh * 100 >= DEEP_CRASH
    allow_dip_ma5 = (DIP_MA5_RISING and rising)   # [DIP-MA5-RISING] 정배열(1/5/20)이면 DEEP_CRASH 면제하되 '눌림(5일선근접)' 경로만 통과(아래 not deep_crashed 가드가 나머지 차단)
    if deep_crashed and not allow_dip_ma5:
        return None
    hm, o, h, l, c, v = bars[-1]
    prev_c = bars[-2][4]
    gain = (c / o0 - 1) * 100
    cpos = (c - l) / (h - l) if h > l else 1.0
    vols = [b[5] for b in bars[:-1] if b[5] > 0]
    vmed = median(vols) if vols else 0
    vol_ok = (vmed <= 0 or v >= vmed * VOL_MULT)
    cum_pv = sum(b[4] * b[5] for b in bars); cum_v = sum(b[5] for b in bars)
    vwap = cum_pv / cum_v if cum_v > 0 else c
    prior_high = max(b[2] for b in bars[:-1]) if len(bars) > 1 else h   # 직전까지 당일고가(신고가 돌파 판정)
    buyers_win = (c > o and cpos >= CPOS_MIN and c > prev_c and c >= vwap and vol_ok)   # ★매수자가 매도자 이김(돌파/눌림 공통 관문)
    dd = (c / dayhigh - 1) * 100 if dayhigh > 0 else 0
    ran = (dayhigh / o0 - 1) * 100
    # ★즉시진입(친구님): 형성 중인 봉이 신호 내는 '순간' 봉완성 안기다리고 즉시 매수 = 수렴돌파·아침돌파·눌림·이평수렴지지 전부(6분 대기 폐지). 가짜방지=전고점돌파/턴업 + VWAP위 + 과열범위
    if INSTANT_BREAKOUT and live_bar is not None:
        lc = live_bar[4]; lv = live_bar[5]
        cv = cum_v + lv; vwap_live = (cum_pv + lc * lv) / cv if cv > 0 else lc
        gain_live = (lc / o0 - 1) * 100
        if lc > dayhigh and lc >= vwap_live and ENTRY_PCT <= gain_live <= CHASE_CAP and (not HOLD_CONFIRM or buyers_win) and not deep_crashed:   # 형성봉 현재가가 당일 전고점(완성봉) 돌파=신고가 + [A]직전봉 강세 버팀 확인 (deep_crash시 신고가추격 차단·눌림만 허용)
            if converged and ma_lvl > 0 and lc >= ma_lvl * (1 + CONV_CONFIRM / 100):
                return lc, live_bar[2], "수렴돌파"                                      # 수렴돌파 즉시진입
            if USE_NEWHIGH and hi40 > 0 and lc >= hi40 * (1 - NEWHIGH_NEAR / 100) and vr >= VRMIN:
                return lc, live_bar[2], "신고가돌파"                                     # ★40일 신고가 돌파 즉시진입(lc>dayhigh=당일신고가 동반·배수)
            if now_hm <= MORNING_CUTOFF and gain_live <= MORNING_CAP:
                return lc, live_bar[2], "아침돌파"                                       # 아침돌파 즉시진입
        # [EARLY_MOMENTUM_BREAK 2026-06-29 친구님] 조기돌파: 오전(EARLY_END이전) 직전1분봉 고가돌파 + VWAP위 + 상승2~7% + 직전저점미이탈 + 양봉우세 → 즉시진입(신고가·배수 불필요=아침돌파보다 빠른 조기포착). ★체결강도≥EARLY_CHE_MIN은 매수게이트에서 하드체크(거래량 대체·데이터없으면 매수금지). 미검증→shadow병행.
        if EARLY_LIVE and now_hm <= EARLY_END and not deep_crashed:
            _lo3 = (bars[-3:] if len(bars) >= 3 else bars) + [live_bar]
            _bull = sum(1 for _b in _lo3 if _b[4] > _b[1]) / len(_lo3)
            if (lc > bars[-1][2] and lc >= vwap_live and EARLY_UP_LO <= gain_live <= EARLY_UP_HI
                    and live_bar[3] >= bars[-1][3] * 0.999 and lc > live_bar[1] and _bull >= 0.66):
                return lc, live_bar[2], "조기돌파"
        # ★눌림 즉시진입(친구님 최우선·제일 큰수익): 아침 돌파→-8%눌림→1-2분만에 20~30% 급반등. 봉완성/대기하면 통째로 놓침. 형성봉에서 깊은눌림 반등시작(직전완성봉 종가 위로) 즉시 매수.
        #   ★VWAP 완화(친구님 2026-06-24): 깊은눌림은 VWAP 아래서 반등 시작 → VWAP 조건 빼고 'lc>c(반등 중)'만으로 진입(엑스게이트식 놓침 방지). lc>c가 falling knife 방지(반등 확인).
        dd_live = (lc / dayhigh - 1) * 100 if dayhigh > 0 else 0
        # [DIP-MA5-RISING] 정배열(rising) 모드: 형성봉이 일봉5일선 근접(만남) + 반등시작(lc>c) → 즉시 눌림진입(대장무관·깊이무관·deep_crash면제). 청산은 기존 che_exit(고점/체결강도).
        if DIP_MA5_RISING and rising:
            if _typeb_signal(bars + [live_bar]):    # [TYPE-B] 형성봉이 추세눌림 재돌파 → 즉시 눌림진입(체결강도는 매수게이트가 확인)
                return lc, live_bar[2], "눌림"
        elif (not DIP_LEADER_ONLY or is_lead) and ran >= RUN_MIN and -DIP_HI - 4 <= dd_live <= -DIP_LO and lc > c and ((DIP_NO_VWAP and is_lead) or lc >= vwap_live):
            return lc, live_bar[2], "눌림"
        # ★이평수렴지지 즉시진입(친구님 "그 전에 감지"): 3선 만난 자리 형성봉이 오름세로 턴(직전완성봉 위로+VWAP위) + 바로앞 전고점 근처/돌파
        if converged and ma_lvl > 0 and abs(lc / ma_lvl - 1) * 100 <= CONV_BUY_PCT and lc > c and lc >= vwap_live \
           and prior_high > 0 and lc >= prior_high * (1 - CONV_TURN_NEAR / 100) and not deep_crashed:
            return lc, live_bar[2], "이평수렴지지"
    # ★수익률 우선 순위(친구님 Q2): 눌림·수렴 동시 출현이면 더 잘버는 쪽 = ①수렴돌파 > ②눌림 > ③아침돌파 > ④이평수렴지지(미돌파·약함→최후)
    if buyers_win and not deep_crashed:   # [DIP-MA5-RISING] 신고가/돌파 경로는 deep_crash시 차단(정배열이어도 추격금지)·눌림(5일선근접)만 별도 허용

        # ① 수렴돌파(코일 돌파·최강 +10.95%): 수렴 + 가격이 수렴대 +CONV_CONFIRM% 위로 확인(가짜돌파 방지·친구님)
        if converged and ma_lvl > 0 and c >= ma_lvl * (1 + CONV_CONFIRM / 100) and ENTRY_PCT <= gain <= CHASE_CAP:
            return c, h, "수렴돌파"
        # ★40일(2달) 신고가 돌파(친구님 2026-06-24·매물대 뚫림·우리데이터 신고가권 최강 +5.65%): 40일 신고가 터치/직전(NEWHIGH_NEAR) + 당일신고가 동반(c>prior_high) + 거래대금 늘기(배수≥VRMIN) + 양봉턴(buyers_win)
        if USE_NEWHIGH and hi40 > 0 and c >= hi40 * (1 - NEWHIGH_NEAR / 100) and c > prior_high and vr >= VRMIN and ENTRY_PCT <= gain <= CHASE_CAP:
            return c, h, "신고가돌파"
        # ③ 아침돌파(친구님): 장초반 눌림없이 날아가는 당일신고가 돌파 + 일찍(낮은 gain=고가추격 X)
        if hm <= MORNING_CUTOFF and h > prior_high and ENTRY_PCT <= gain <= MORNING_CAP:
            return c, h, "아침돌파"
    # ② 눌림(완성봉·★VWAP 완화·친구님 2026-06-24): 깊은눌림은 VWAP 아래서 반등 시작 → buyers_win 블록 밖에서 별도 판정.
    #   반등 확인 = 양봉(c>o)+종가상단(cpos≥CPOS_MIN)+전봉위(c>prev_c)+거래량(vol_ok), VWAP은 DIP_NO_VWAP면 제외. (돌파 경로는 VWAP 유지)
    dip_reb = (c > o and cpos >= CPOS_MIN and c > prev_c and vol_ok and ((DIP_NO_VWAP and is_lead) or c >= vwap))
    # [DIP-MA5-RISING] 정배열(rising) 모드: 양봉턴(반등확인) + 현재가가 일봉5일선 근접(만남) → 눌림진입(대장무관·깊이무관·deep_crash면제). VWAP조건은 dip_reb에서 비대장이면 적용되므로 정배열눌림은 양봉턴만으로 충분.
    if DIP_MA5_RISING and rising:
        if _typeb_signal(bars):                     # [TYPE-B] 완성봉이 추세눌림 재돌파 → 눌림진입(체결강도는 매수게이트가 확인·매도는 che_exit)
            return c, h, "눌림"
    elif (not DIP_LEADER_ONLY or is_lead) and dip_reb and ran >= RUN_MIN and -DIP_HI - 4 <= dd <= -DIP_LO:
        return c, h, "눌림"
    # ④ 이평수렴지지 = 3선(5/20/60) 만난 자리에서 ★오름세로 돌아섬(친구님 2026-06-24): 바닥대기/터치 아님 — 거래량 늘기 시작 + 수급/매수자 생김(buyers_win) + 바로앞 전고점 근처/돌파(near_ph) = 턴업 확인 즉시.
    if converged and ma_lvl > 0 and abs(c / ma_lvl - 1) * 100 <= CONV_BUY_PCT and not deep_crashed:
        near_ph = prior_high > 0 and c >= prior_high * (1 - CONV_TURN_NEAR / 100)   # 바로앞 전고점 돌파했거나 그 직전(친구님 "그 전에 감지")
        if buyers_win and near_ph:                                                  # 오름세 전환 = 양봉+종가상단+전봉위+VWAP위+거래량늘기
            return c, h, "이평수렴지지"
    return None


def _append_trade(p):
    """완료 거래를 append-only 원장(brk_trades.csv)에 기록 — 같은종목 재매매해도 덮어쓰기 안됨(매매일지 정확)."""
    try:
        buy = float(p.get("buy_price", 0) or 0); sell = float(p.get("sell_price", 0) or 0); qty = int(p.get("qty", 0) or 0)
        pnl_pct = (sell / buy - 1) * 100 if buy > 0 and sell > 0 else 0.0
        pnl_won = round((sell - buy) * qty) if buy > 0 and sell > 0 else 0
        new = not TRADES.exists()
        with io.open(TRADES, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "code", "name", "type", "buy", "sell", "qty", "invest",
                            "pnl_pct", "pnl_won", "reason", "buy_hm", "sell_hm", "live"])
            w.writerow([p.get("date", ""), p.get("code", ""), p.get("name", ""), p.get("type", ""),
                        round(buy), round(sell), qty, round(buy * qty), round(pnl_pct, 2), pnl_won,
                        p.get("sell_reason", ""), p.get("buy_hm", ""), p.get("sell_hm", ""), 1 if p.get("live") else 0])
    except Exception as e:
        _log(f"거래기록 실패 {e}")


CONV_TYPES = ("이평수렴지지", "수렴돌파")                       # 수렴/3선 그룹(스텝업·3회) — 눌림/아침돌파와 구분
TYPE_RANK = {"수렴돌파": 5, "신고가돌파": 4, "눌림": 3, "아침돌파": 2, "조기돌파": 2, "이평수렴지지": 1}   # ★수익률 순위(친구님): 수렴돌파(코일+10.95)>신고가돌파(40일+5.65)>눌림>아침돌파≈조기돌파>이평수렴지지
TOP_RANK = max(TYPE_RANK.values())                            # 최고신호(수렴돌파)는 대기없이 즉시 매수


def _hm_to_min(hm):
    """HHMM 문자열 → 분(分). 대기시간 계산용."""
    try:
        s = str(hm).zfill(4); return int(s[:2]) * 60 + int(s[2:])
    except Exception:
        return 0


def _load_defer(today):
    """★대기 후 업그레이드 상태(친구님): {date, seen:{code:{rank,hm}}}. 날짜 바뀌면 리셋."""
    d = _jload(DEFER)
    if not isinstance(d, dict) or d.get("date") != today:
        return {"date": today, "seen": {}}
    d.setdefault("seen", {})
    return d


def _traded_today(today):
    """★오늘 이미 매매한 종목 = append-only 원장(brk_trades.csv)에서 타입별 집계 — held dict 덮어쓰기 면역.
       반환 {code: {"conv":수렴횟수, "dip":눌림횟수, "brk":아침돌파횟수, "max_buy":최고매수가}}.
       타입별 횟수=재진입 cap(수렴3·눌림2·돌파1) / max_buy=수렴 스텝업 게이트 기준(가장 비싼 진입 위로만)."""
    agg = {}
    try:
        if TRADES.exists():
            for r in csv.DictReader(io.open(TRADES, encoding="utf-8-sig", errors="replace")):
                if str(r.get("date", "")).strip() != str(today):
                    continue
                c = str(r.get("code", "")).strip().zfill(6)
                typ = str(r.get("type", "")).strip()
                try:
                    b = float(r.get("buy", 0) or 0)
                except ValueError:
                    b = 0.0
                a = agg.setdefault(c, {"conv": 0, "dip": 0, "brk": 0, "max_buy": 0.0})
                if typ in CONV_TYPES:
                    a["conv"] += 1
                elif typ == "눌림":
                    a["dip"] += 1
                else:
                    a["brk"] += 1
                a["max_buy"] = max(a["max_buy"], b)
    except Exception as e:
        _log(f"_traded_today 실패 {e}")
    return agg


def _seller_win(bars):
    """★1차 방어선(친구님): 매도자 우위(무너짐) = VWAP이탈·저점깸·매도세봉(음봉+종가하단)·고점돌파실패+거래량감소 중 2개+ (또는 VWAP이탈+저점깸). 완성봉 기준."""
    if len(bars) < 7:
        return False
    now_hm = datetime.now().strftime("%H%M")
    bb = bars[:-1] if bars[-1][0] >= now_hm else bars
    if len(bb) < 6:
        return False
    hm, o, h, l, c, v = bb[-1]
    cum_pv = sum(b[4] * b[5] for b in bb); cum_v = sum(b[5] for b in bb)
    vwap = cum_pv / cum_v if cum_v > 0 else c
    cpos = (c - l) / (h - l) if h > l else 1.0
    win = bb[-6:-1]
    recent_low = min(b[3] for b in win); recent_high = max(b[2] for b in win)
    vols = [b[5] for b in win if b[5] > 0]
    below_vwap = c < vwap                                  # VWAP 이탈
    break_low = c < recent_low                             # 저점 깨짐
    sell_bar = c < o and cpos < 0.4                        # 매도세 봉(음봉+종가 하단)
    vol_dry = bool(vols) and v < (sum(vols) / len(vols)) * 0.7
    no_new_high = h < recent_high                          # 고점 돌파 실패
    score = sum([below_vwap, break_low, sell_bar, (no_new_high and vol_dry)])
    return (below_vwap and break_low) or score >= 2


def _safe_float(x, default=0.0):
    """[BUGFIX 2026-06-30 #6] 스냅샷 che_str/imb가 문자열 등 비숫자여도 비교 전 안전 변환(TypeError로 사이클 abort 방지)."""
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _snap_price(code):
    """[BUGFIX 2026-06-30 #2] prices_1m 봉 누락시 실시간 스냅샷 현재가 폴백(보호공백 방지). 10분내 신선할때만 신뢰."""
    m = _read_micro(code)
    if not m:
        return 0.0
    cur = _safe_float(m.get("cur"), 0.0)
    if cur <= 0:
        return 0.0
    try:
        age = (datetime.now() - datetime.fromisoformat(str(m.get("ts")))).total_seconds()
        if age > 600:
            return 0.0
    except Exception:
        return 0.0
    return cur


def _read_micro(code):
    """★IPC live_micro_snapshot에서 종목 실시간 체결강도/호가 읽기(키움 직접호출 X·broker가 구독). 없으면 None."""
    try:
        d = json.loads(MICRO_SNAP_FILE.read_text(encoding="utf-8-sig"))
        return (d.get("codes") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _write_micro_watch(codes):
    """★보유+후보 코드를 micro_watch에 기록 → broker가 SetRealReg 실시간 구독(snapshot에 체결강도 채움)."""
    try:
        seen = []
        for c in codes:
            c = str(c).zfill(6)
            if c and c not in seen:
                seen.append(c)
        tmp = MICRO_WATCH_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"codes": seen[:80]}, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(MICRO_WATCH_FILE))
    except Exception:
        pass


def _exit_check(bc, hm, held):
    """보유 청산: 익절+TP% / 하드-HARD% / ★1차 매도우위(봉+실시간 체결강도) / ★2차 고점-PEAK_DROP%. 먼저 닿는 쪽."""
    for code, p in list(held.items()):
        if not (isinstance(p, dict) and p.get("status") == "OPEN"):
            continue
        bars = _gate_bars(bc, code)
        cur = bars[-1][4] if bars else 0
        if cur <= 0:                                   # [BUGFIX 2026-06-30 #2] 봉 누락→실시간 스냅 폴백(보호공백 방지)
            cur = _snap_price(code)
        buy = float(p.get("buy_price", 0))
        if cur <= 0 or buy <= 0:
            if buy > 0:                                # 봉·스냅 모두 없음=가격조회 완전실패 → 침묵 skip 대신 경고(무방비 보유 가시화)
                _log(f"{hm} ⚠️보호불가 {code}: 봉·스냅 현재가 모두 없음 → 이 사이클 청산판정 skip(다음사이클/EOD 재시도)")
            continue
        peak = max(float(p.get("peak", buy) or buy), cur)
        if peak != p.get("peak"):
            p["peak"] = peak; _jsave(POS, held)
        pnl = (cur / buy - 1) * 100
        trail_line = peak * (1 - PEAK_DROP / 100)
        hard_line = buy * (1 - HARD_PCT / 100)
        tp_line = buy * (1 + TP_PCT / 100)
        reason = None
        # ★1차 매도우위: 매수후 SELLER_GRACE분 경과 + 봉 매도신호. ★실시간 체결강도 확인(친구님): 체결강도 강하면(매수우위) 보유→2차로 위임
        seller1 = (_hm_to_min(hm) - _hm_to_min(str(p.get("buy_hm", hm)))) >= SELLER_GRACE and _seller_win(bars)
        if seller1 and MICRO_USE:
            m = _read_micro(code)
            che = _safe_float((m or {}).get("che_str"), None); imb = _safe_float((m or {}).get("imb"), None)   # [BUGFIX #6] 안전변환
            if che is not None:                                   # 실시간 체결강도 있음
                ob_sell = (imb is not None and imb < SELL_OB_MAX)  # 호가 매도잔량 우위
                if not (che < SELL_CHE_MAX or ob_sell):           # 체결강도 강(≥)이고 호가도 매도우위 아님 → 보유
                    _log(f"{hm} 1차 매도신호·체결강도 {che:.0f}(강)·imb {imb} → 보유(2차 위임) {code}")
                    seller1 = False
            # che None(미구독/스냅없음) → 봉신호만으로(기존 동작 유지)
        _mareason = None   # [MA-EXIT] 5일선/20일선 구조청산(BRK_MA_EXIT=YES일때만·미리 1회 계산)
        if MA_EXIT:
            try:
                import exit_ma as _DMA
                _m5 = _DMA.ma5(code); _m20 = _DMA.ma20(code)
                _cheN = _safe_float((_read_micro(code) or {}).get("che_str"), None) if MICRO_USE else None   # [BUGFIX #6] 안전변환
                _cheweak = (_cheN is None) or (_cheN < SELL_CHE_MAX)   # 체결강도 약(매도우위)=강하면 보유
                if _m20 > 0 and cur < _m20:
                    _mareason = "20일선이탈(하드)"
                elif _m5 > 0 and cur < _m5 and _cheweak:
                    _mareason = "5일선이탈+체결약"
            except Exception:
                _mareason = None
        if UNIFIED_VOL_EXIT:
            # [통일 매도 2026-07-01 친구님] 하드손절·돌파재이탈만 유지 → 수급/MA/트레일은 vol_exit(매수우위 보유·매도우위+20선 무조건 매도)
            if cur <= hard_line:
                reason = "하드-%g%%" % HARD_PCT
            elif REBREAK_STOP and float(p.get("breakout_level", 0) or 0) > 0 and cur < float(p["breakout_level"]) * 0.997:
                reason = "돌파레벨재이탈(돌파실패)"
            else:
                try:
                    import vol_exit as _VE
                    _che_v = _safe_float((_read_micro(code) or {}).get("che_str"), None) if MICRO_USE else None
                    _sell, _rs = _VE.decide(code, buy, peak, cur, ma20_hard=True, che=_che_v)
                    if _sell:
                        reason = _rs
                except Exception as _ve:
                    _log(f"{hm} vol_exit 오류({code}) → 하드/EOD만 적용: {_ve}")
        elif cur >= tp_line:
            reason = "익절+%g%%" % TP_PCT
        elif cur <= hard_line:
            reason = "하드-%g%%" % HARD_PCT
        elif REBREAK_STOP and float(p.get("breakout_level", 0) or 0) > 0 and cur < float(p["breakout_level"]) * 0.997:
            reason = "돌파레벨재이탈(돌파실패)"   # [B] 뚫은 저항 아래로 재이탈 → 즉시 청산(되돌림 토함 방지)
        elif seller1:
            reason = "매도우위(1차)"
        # [MA-EXIT 2026-06-29 친구님] 구조기반: 20일선이탈=하드청산(3번)·5일선이탈+체결약=단기추세깸(2번). 체결강도(seller1)가 위에서 먼저 빠르게 끊어 -5% 토함 방지.
        elif _mareason:
            reason = _mareason
        elif cur <= trail_line and peak > buy:           # ★2차 방어선: 고점-PEAK_DROP%(백스톱)
            reason = "고점-%g%%(2차)" % PEAK_DROP
        if reason:
            qty = int(p.get("qty", 0))
            _log(f"{hm} ★매도[{reason}] {code} {p.get('name','')[:8]} {pnl:+.2f}% (현재{cur:,}·고점{peak:,.0f}) x{qty}")
            if _order(bc, code, qty, "SELL", "EXIT"):
                p["status"] = "CLOSED"; p["sell_price"] = cur; p["sell_reason"] = f"{reason}({pnl:.1f}%)"
                p["sell_hm"] = hm; _jsave(POS, held)
                _append_trade(p)                          # ★원장 기록(재매매 안사라짐)
                _log(f"{hm} 매도완료 {code} @{cur:,} ({pnl:+.2f}%)")
            else:
                _log(f"{hm} 매도주문 실패 {code} — ★수동확인")


def mode_pick():
    hm = datetime.now().strftime("%H%M")
    today = datetime.now().strftime("%Y%m%d")
    held = _jload(POS)
    opens = {c: p for c, p in held.items() if isinstance(p, dict) and p.get("status") == "OPEN"}
    bc = _broker()
    if not bc:
        _log(f"{hm} broker dead → 중단"); return
    if opens:                                  # 보유중이면 먼저 전종목 청산체크(여러 종목 동시 보유 가능)
        _exit_check(bc, hm, held)
        held = _jload(POS)
        opens = {c: p for c, p in held.items() if isinstance(p, dict) and p.get("status") == "OPEN"}
    if hm > BUY_CUTOFF:
        return
    if len(opens) >= MAX_POS:                   # ★최대 동시보유 도달 → 신규매수 안함
        return
    # [GLOBAL-BUDGET 2026-06-28 친구님] 전 전략 합산 동시보유 상한(돌파는 사이클당 1매수)
    try:
        import position_budget as _gb
        if _gb.budget_on() and _gb.remaining_intraday() <= 0:   # [종가매수 보장 2026-06-29] EOD 예약분 제외
            _log(f"{hm} [GLOBAL-CAP] 전역 실보유 {_gb.total_open()}/{_gb.global_max()} 도달 → 신규매수 보류"); return
    except Exception as _ge:
        _log(f"{hm} [GLOBAL-BUDGET] skip({_ge})")
    cands = _candidates(bc)
    if not cands:
        _write_micro_watch(list(opens.keys()))   # 보유라도 실시간 구독 유지
        _log(f"{hm} 후보없음(전날배수≥{VRMIN:g})"); return
    _write_micro_watch(list(opens.keys()) + list(cands.keys()))   # ★보유+후보 broker 실시간 구독 요청(체결강도 채움)
    skip = _newpb_held() | set(opens.keys()) | _eod_held()    # 눌림 보유 + 돌파 보유 + 종가매수분 보유 제외(현재 보유·계좌 중복매수 방지)
    # ★한 종목 재진입 통제(친구님: 2번·3회까지·좋은조건만·그이상 금지) — 원장 기반(덮어쓰기 면역). {code:(횟수,최고매수가)}
    traded = _traded_today(today)
    defer = _load_defer(today)                  # ★대기후업그레이드: 약한신호 본 시각 기억(스캔간 유지)
    highs = _prior_highs(list(cands.keys()))
    leaders = _leader_codes()                   # ★실제 테마 대장주(leader=1)·친구님 "깊은눌림은 진짜 대장주에서"
    best = None; best_key = None
    for code, (nm, vr, theme) in cands.items():
        if code in skip:
            continue
        bars = _gate_bars(bc, code)
        hi52, hi40, hi60, pvh, prevbull, converged, ma_lvl, ma5_d, ma20_d = highs.get(code, (0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0))
        # ★[3분봉 MA 2026-06-30 친구님 "모든 이동평균선 3분봉·일봉 쓰면 시간 안맞음"] MA_TIMEFRAME=3MIN이면
        #   5/20/60·DIP-MA5·이격 기준선을 일봉(_prior_highs캐시)→당일 3분봉으로 덮어씀.
        #   전고점(hi*)·전일강함(prevbull)은 이동평균선이 아님→일봉 유지. 3분봉 부족(장초반)이면 MA진입경로 0=skip
        #   (신고가 돌파경로는 영향없음·fail-safe). 롤백 setx MA_TIMEFRAME DAILY.
        if os.environ.get("MA_TIMEFRAME", "3MIN").strip().upper() == "3MIN":
            try:
                import intraday_ma as _im3
                _m5, _m20, _m60 = _im3.ma5(code), _im3.ma20(code), _im3.ma60(code)
                ma5_d = _m5; ma20_d = _m20        # 부족시 0 → DIP-MA5/이격 경로 자동 skip
                if _m5 and _m20 and _m60:
                    _mmin = min(_m5, _m20, _m60)
                    ma_lvl = (_m5 + _m20 + _m60) / 3
                    converged = 1 if (_mmin > 0 and (max(_m5, _m20, _m60) - _mmin) / _mmin * 100 <= CONV_PCT) else 0
                else:
                    converged = 0; ma_lvl = 0.0   # 3분봉 60선 미형성 → 수렴경로 skip
            except Exception:
                pass
        is_lead = code in leaders   # ★진짜 대장주(눌림 VWAP완화는 대장주에만·친구님 "깊은눌림은 진짜 대장주에서")
        _is_rising = bool(_TF is not None and _TF.is_jeongbae(code, "rising")) if DIP_MA5_RISING else False   # [DIP-MA5-RISING] 1/5/20 우상향 정배열 여부(눌림 적극진입 게이트)
        sig = _entry_signal(bars, converged, ma_lvl, hi40, vr, is_lead, ma5_d, _is_rising)
        if not sig:
            continue
        px, dayhigh, typ = sig
        # [B 재이탈손절] 돌파레벨(뚫은 저항=돌파 직전까지의 당일 전고점) 계산 → 기록저장(현재가가 이 아래로 재이탈하면 청산). 눌림/수렴지지는 레벨없음(0).
        bo_level = 0.0
        if typ in ("신고가돌파", "수렴돌파", "아침돌파"):
            _done = bars[:-1] if (bars and bars[-1][0] >= hm) else bars
            if len(_done) >= 2:
                bo_level = max(b[2] for b in _done[:-1])
        # ★재진입 통제(친구님 타입별 룰): 수렴/3선=3회+위로스텝업 / 눌림=2회+바닥(스텝업X·3번절대금지) / 아침돌파=1회
        if code in traded:
            a = traded[code]
            if typ in CONV_TYPES:                         # 수렴/3선: 최대 CONV_MAX(3)번 + 직전최고가 +STEP_UP%↑(위로 멀티레그)
                if a["conv"] >= CONV_MAX:
                    continue                              # 3회 cap
                if not (a["max_buy"] > 0 and px > a["max_buy"] * (1 + STEP_UP_PCT / 100)):
                    continue                              # 스텝업 안되면(같거나 싼자리) 금지
            elif typ == "눌림":                            # 눌림: 최대 DIP_MAX(2)번·3번 절대금지. 바닥(싼값)에서 사므로 스텝업 조건 없음
                if a["dip"] >= DIP_MAX:
                    continue                              # 2회 cap — 깊은눌림+매수자우위(진입신호)가 품질 보장
            else:                                          # [UNLIMITED-STEPUP 2026-06-26 친구님 "기회마다 무제한"]
                # 아침돌파/돌파: 횟수무제한 + 직전최고가 +STEP_UP%↑(위로 스텝업할 때만) → churn차단·상투추격은 7%천장(CHASE/MORNING_CAP)이 막음.
                #   기존 BREAK_MAX(1)cap 폐지. BRK_BREAK_MAX 크게(99)면 사실상 무제한·스텝업게이트로 안전. 롤백: 백업복원 또는 setx BRK_BREAK_MAX 1.
                if a["brk"] >= BREAK_MAX:
                    continue                              # cap (기본 99=무제한)
                if not (a["max_buy"] > 0 and px > a["max_buy"] * (1 + STEP_UP_PCT / 100)):
                    continue                              # ★위로 스텝업 안되면(같거나 싼 자리) 금지 = churn차단
                # [RESTEP-CHE 2026-06-26 친구님] 재매수는 체결강도 RESTEP_CHE(110)↑ 일때만 = 꼭대기서 약한 찔끔돌파 추가매수 차단.
                if RESTEP_CHE > 0:
                    _rc = (_read_micro(code) or {}).get("che_str")
                    if _rc is not None and _rc < RESTEP_CHE:
                        _log(f"{hm} 재매수보류 {code}: 체결강도 {_rc:.0f}<{RESTEP_CHE:.0f}(매수약·꼭대기위험)")
                        continue
        # ★대기 후 업그레이드(친구님): 돌파·눌림은 즉시진입(시간임계·아침눌림 1-2분 급반등)·이평수렴지지(느린 바닥)만 WAIT_MIN분 대기 → 돌파로 업그레이드 노림
        rank = TYPE_RANK.get(typ, 0)
        if WAIT_MIN > 0 and typ not in ("수렴돌파", "아침돌파", "눌림", "이평수렴지지"):   # ★친구님 2026-06-24: 이평수렴지지도 즉시(6분대기 폐지) — 모든 타입 즉시 → defer 사실상 비활성
            seen = defer["seen"].get(code)
            if seen is None:
                defer["seen"][code] = {"rank": rank, "hm": hm}        # 처음 포착 → 대기 시작·이번 스캔 보류
                continue
            elif rank > int(seen.get("rank", 0)):
                pass                                                  # ★업그레이드(더 좋은 신호 등장) → 매수 진행
            elif _hm_to_min(hm) - _hm_to_min(seen.get("hm", hm)) >= WAIT_MIN:
                pass                                                  # ★대기시간 경과 → fallback 매수(안 놓침)
            else:
                if rank > int(seen.get("rank", 0)):
                    defer["seen"][code]["rank"] = rank                # 더 좋아졌으면 기록 갱신(다음 비교 기준)
                continue                                              # 아직 대기 중
        gain = (bars[-1][4] / bars[0][1] - 1) * 100
        nh40 = hi40 > 0 and px >= hi40          # ★40일(2달) 신고가 돌파 — 우리데이터 최강
        nh52 = hi52 > 0 and px >= hi52          # 52주(역사) 신고가 돌파
        nh60 = (not nh52) and hi60 > 0 and px >= hi60   # 60일 전고점 돌파
        # ★수익률 우선(친구님): 수렴돌파(코일돌파 최강)>신고가돌파>눌림>아침돌파>이평수렴지지. 데이터 기반 더 잘버는 순(cross-stock도 동일).
        tbonus = TYPE_RANK.get(typ, 0)
        is_lead = code in leaders   # ★실제 테마 대장주(leader=1)만 — 친구님 2026-06-24. 키스트론(leader=0)식 비대장은 +3 가점 안줌. 깊은눌림 정조준
        prio = (10 if converged else 0) + (3 if is_lead else 0) + tbonus + (3 if nh40 else 0) + (1 if (nh52 or nh60) else 0) + (2 if prevbull else 0)   # ★40일 신고가=+3(최강)·52주/60일=+1 보조
        key = (prio, gain)
        if best is None or key > best_key:
            best = (code, nm, px, gain, vr, typ, prevbull, nh52, nh60, converged, is_lead, bo_level, ma20_d); best_key = key
    _jsave(DEFER, defer)                        # ★대기상태 저장(다음 스캔이 기억해 업그레이드/fallback 판정)
    if not best:
        _log(f"{hm} 신호없음 (후보 {len(cands)}·눌림제외 {len(skip)}·대기 {len(defer['seen'])}) — 하루종일 감시중"); return
    code, nm, px, gain, vr, typ, prevbull, nh52, nh60, converged, is_lead, bo_level, ma20_d = best
    if px <= 0:
        return
    # [정배열 D 2026-06-29] 돌파=strict(MA5>MA20>MA60). [DIP-MA5-RISING] 눌림은 rising(1/5/20 우상향)으로 게이트(정배열 눌림 적극진입). 데이터없으면 통과(fail-open).
    _gate_mode = "rising" if (DIP_MA5_RISING and typ == "눌림") else JEONGBAE_MODE_BRK
    if _gate_mode == "rising" and _TF is None:   # [BUGFIX 2026-06-30 typeb] trend_filter 불가시 rising 확인불가 → 레거시 딥 오발화 차단(typeb전용 의도 보존)
        _log(f"{hm} 매수보류 {code} {nm[:8]}: typeb 눌림인데 trend_filter 불가 — rising 확인불가로 보류"); return
    if _TF is not None and not _TF.is_jeongbae(code, _gate_mode):
        _log(f"{hm} 매수보류 {code} {nm[:8]}: 정배열({_gate_mode}) 아님 — {'눌림=rising만' if _gate_mode=='rising' else '돌파=strict만'}"); return
    # ★매수 확신게이트(친구님 6/24): 실시간 체결강도/호가 — 명백한 매도우위(false돌파)면 매수보류. 데이터없으면 통과(fail-open=매매 안막힘)
    _che_now = None; _imb = None
    if ENTRY_CHE_CONFIRM:
        _mm = _read_micro(code); _che_now = _safe_float((_mm or {}).get("che_str"), None); _imb = _safe_float((_mm or {}).get("imb"), None)   # [BUGFIX #6] 안전변환
        if _che_now is not None and (_che_now < ENTRY_CHE_WEAK or (_imb is not None and _imb < ENTRY_OB_WEAK)):
            _log(f"{hm} 매수보류 {code} {nm[:8]}: 체결강도 {_che_now:.0f}·imb {_imb} (매도우위·false돌파 의심)")
            return
    # [EARLY_MOMENTUM_BREAK 2026-06-29] ★조기돌파는 체결강도가 전부 — 하드게이트(데이터 없거나 <EARLY_CHE_MIN이면 매수금지·거래량 대체). 미검증 전략의 유일 안전장치.
    if typ == "조기돌파":
        if _che_now is None or _che_now < EARLY_CHE_MIN:
            _log(f"{hm} 매수보류(조기돌파) {code} {nm[:8]}: 체결강도 {_che_now} < {EARLY_CHE_MIN:g} — 조기진입은 체결강도 확인 필수(없으면 매수안함)"); return
    # [SOFT-CAP 2026-06-29] 시가+CHASE_SOFT% 초과는 '확인된 박스돌파'(체결강도≥STRONG & 매수잔량 우위=뚫고버팀)만 허용. 미확인 추격 차단.
    if gain > CHASE_SOFT:
        _strong = (_che_now is not None and _che_now >= ENTRY_CHE_STRONG and (_imb is None or _imb >= ENTRY_OB_STRONG))
        if not _strong:
            _log(f"{hm} 매수보류 {code} {nm[:8]}: 시가+{gain:.1f}%(>{CHASE_SOFT:g}%) 추격인데 버팀 미확인(체결{_che_now}·imb{_imb}) — 박스돌파만 허용"); return
    conv = ("·★이평수렴" if converged else "") + ("·테마대장" if is_lead else "") + ("·52주신고가" if nh52 else ("·60일신고가" if nh60 else "")) + ("·전일장대양봉" if prevbull else "") + (("·체결강도%.0f강" % _che_now) if (_che_now is not None and _che_now >= ENTRY_CHE_STRONG) else "")
    # [FOREIGN-GATE 2026-06-28 친구님] 거래원 외국계 매도우세 게이트(env FOREIGN_GATE: LOG/BLOCK)
    try:
        import foreign_supply as _fs
        if not _fs.buy_gate(code, log=_log, tag=f"{hm} BRK"):
            return
    except Exception:
        pass
    # [MA20-DEV 부스터] 일봉 MA20 상방이격 분류 → shadow기록(LOG·매매무변경) / 활성(ON)시 25%+ 과열은 강한체결강도만 허용(추격제한).
    if MA20DEV_MODE != "OFF" and ma20_d and ma20_d > 0:
        _dev20 = (px / ma20_d - 1) * 100
        _band = ("아래" if _dev20 < 0 else "붙음0~3" if _dev20 < 3 else "초입3~5" if _dev20 < 5
                 else "스윗5~12" if _dev20 < 12 else "확장12~25" if _dev20 < MA20DEV_HOT else "과열25+")
        _hot = _dev20 >= MA20DEV_HOT
        _strong_che = (_che_now is not None and _che_now >= ENTRY_CHE_STRONG)
        _act = ("과열제한" if MA20DEV_MODE == "ON" else "과열(가정제한)") if (_hot and not _strong_che) else "통과"
        try:
            _newf = not os.path.exists(MA20DEV_CSV)
            with io.open(MA20DEV_CSV, "a", encoding="utf-8-sig", newline="") as _f:
                _w = csv.writer(_f)
                if _newf:
                    _w.writerow(["date", "hm", "code", "name", "type", "px", "ma20", "dev20", "band", "che", "action", "mode"])
                _w.writerow([today, hm, code, nm, typ, round(px), round(ma20_d), round(_dev20, 2), _band,
                             (round(_che_now, 1) if _che_now is not None else ""), _act, MA20DEV_MODE])
        except Exception:
            pass
        _log(f"{hm} [MA20-DEV] {code} {nm[:8]} 이격{_dev20:+.1f}%({_band}) che={_che_now} → {_act}")
        if MA20DEV_MODE == "ON" and _hot and not _strong_che:
            _log(f"{hm} 매수보류 {code} {nm[:8]}: MA20이격 {_dev20:+.1f}%(≥{MA20DEV_HOT:g}% 과열)·체결강도 미강 — 추격제한"); return
    qty = max(1, int(CAP // px))
    _log(f"{hm} ★{typ}매수 {code} {nm[:9]} 배수{vr:.1f} 시가+{gain:.1f}%{conv} @{px:,} x{qty}={qty*px:,}원 (LIVE={LIVE})")
    if not _order(bc, code, qty, "BUY", "PICK"):
        if LIVE: return
    held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px, "vr": vr, "peak": px,
                  "buy_hm": hm, "date": today, "status": "OPEN", "live": LIVE, "type": typ, "newhigh": prio,
                  "breakout_level": round(float(bo_level)) if bo_level and bo_level > 0 else 0}   # [B] 재이탈 청산 기준(0=눌림 등 미적용)
    _jsave(POS, held)
    defer["seen"].pop(code, None); _jsave(DEFER, defer)   # ★매수 완료 → 대기상태 해제


def mode_sell():
    _log(f"=== 돌파 EOD 청산 (LIVE={LIVE}) ===")
    held = _jload(POS)
    opens = {c: p for c, p in held.items() if isinstance(p, dict) and p.get("status") == "OPEN"}
    if not opens:
        _log("청산할 돌파 보유 없음"); return
    bc = _broker()
    if not bc and LIVE:
        _log("broker dead → 청산불가(★수동확인!)"); return
    hm = datetime.now().strftime("%H%M")
    for code, p in opens.items():
        bars = _gate_bars(bc, code) if bc else []
        cur = bars[-1][4] if bars else 0
        pnl = (cur / float(p["buy_price"]) - 1) * 100 if cur else 0
        if _order(bc, code, int(p["qty"]), "SELL", "EODSELL"):
            p["status"] = "CLOSED"; p["sell_price"] = cur; p["sell_reason"] = "장마감"; p["sell_hm"] = hm
            _jsave(POS, held)                             # [BUGFIX 2026-06-30 #5] 매도 즉시 저장(루프중간 예외시 재매도/오버셀 방지)
            _append_trade(p)                              # ★원장 기록(재매매 안사라짐)
            _log(f"청산 {code} {p.get('name','')[:8]} @{cur:,} ({pnl:+.2f}%)")
    _jsave(POS, held)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    try:
        _jsave(Path(r"C:\stock_bot\DATA\brk_runtime_config.json"), {
            "ts": datetime.now().isoformat(), "LIVE": LIVE, "CAP": CAP, "VRMIN": VRMIN,
            "ENTRY_PCT": ENTRY_PCT, "PEAK_DROP": PEAK_DROP, "TP_PCT": TP_PCT, "HARD_PCT": HARD_PCT,
            "BUY_CUTOFF": BUY_CUTOFF})
    except Exception:
        pass
    try:
        (mode_pick if mode == "pick" else mode_sell)()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)
