# -*- coding: utf-8 -*-
"""[2026-07-06 친구님] 돈흐름 전용 매매기 v1 — "돈 이기는 종목만 골라 탄다".
  진입: 돈흐름 선별판 🟢(이기는중=큰손매수+가격↑+체결강도강+레짐OK) 상위 → ★시장가 매수.
  청산: ★전 전략 공통 vol_exit.decide (하드-3 → 매수우위 끌기 / 매도우위 청산) + EOD.
  선별: money_flow_board_v1 재사용(보드 갱신). 던짐(smart_money) 이중차단.
철학: 돈흐름=패턴 진짜/가짜 판독기. "큰손 사는 게 이기고 있을 때"만 탄다. 급락장엔 🟢 없음=안 삼.
★[2026-07-07 2층 빠른루프] 매매가=실시간 푸시 스냅샷 파일(IPC/live_micro_snapshot.json·TR 0)이라 매도/진입을
  MF_LOOP_SEC(기본 8초)마다 반복 → 초단위 반응. 수급 보드(opt10059/opt90013≈40s TR)만 백그라운드 스레드로
  프로세스당 1회 갱신(매도루프 안 막음). 프로세스는 MF_RUN_SEC(기본 55초) 돌고 종료 → 1분 태스크가 재기동(자동복구).
  Windows 태스크 최소단위=1분이라 초단위는 내부루프로만 얻음. 끄기: MF_BOARD_REFRESH=NO(보드 안 돌림).
★안전: MF_EXEC_LIVE=NO(기본 그림자·주문0). 소액 CAP·최대보유 제한·킬스위치(config/manual_buy_block.flag=broker가 매수거부).
       fail-open·EOD 강제청산. 실전 setx MF_EXEC_LIVE YES.
"""
import os
import sys
import json
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
import capital_config
import position_budget

LIVE      = os.environ.get("MF_EXEC_LIVE", "NO").strip().upper() == "YES"     # 기본 그림자
COMMON_ORDER_QUANTITY = capital_config.get_order_quantity()
COMMON_CAPITAL_KRW = capital_config.get_limit("daily_total_max")
CAP       = COMMON_CAPITAL_KRW
MAX_POS   = int(os.environ.get("MF_EXEC_MAXPOS", "3"))
MIN_PRICE = int(float(os.environ.get("MF_MIN_PRICE") or os.environ.get("SAFEPLUS_MIN_PRICE") or "50000"))  # 돈흐름 전용 하한(MF_MIN_PRICE)·미설정시 SAFEPLUS_MIN_PRICE — 미만은 시도 안 함
# [2026-07-07 친구님 "3% 컷 삭제·바닥사냥꾼 통합"] 고정%컷 삭제 → 구조붕괴(저점이탈) 손절로 대체. 재앙방지 failsafe만 넓게 유지.
STRUCT_STOP   = os.environ.get("MF_STRUCT_STOP", "YES").strip().upper() == "YES"   # 구조붕괴 손절 — 바닥진입은 당일저점(LL) 이탈시 컷. 고정%보다 바닥에 여유.
STRUCT_BUF    = float(os.environ.get("MF_STRUCT_BUF", "0.5")) / 100.0              # 저점 이탈 버퍼(저점 대비 이 %↓ 뚫으면 붕괴). 0.5%
CHASE_BAND    = float(os.environ.get("MF_CHASE_BAND", "6"))                        # 바닥권 추격금지 — 저점반등 진입은 당일저점 +이%내만(추격 차단). 상승모멘텀 진입은 무관.
HARDCUT       = float(os.environ.get("MF_HARDCUT", "-2.0") or "0")                 # [7/7 친구님 "-2%는 살려야지·한없이 내려가면 큰손실"] 최대손실 하드컷. 하방(손실)만 캡·상방(수익)은 che되돌림이 끝까지 끌어 무제한. 구조붕괴가 더 일찍 컷할때 많음. 0=off
# [2026-07-09 친구님 "고점 추격 안 해 — 고점 모멘텀 진입로는 아예 끈다"] 상승(모멘텀) 경로 전면 차단 —
#   근거(7/9 실측): 모멘텀 진입 40건 -6.3만(평균 시가+5.9% 꼭대기 매수·10:30후 15연패·손절후 60분내 반등 71%)
#   vs 바닥 진입 1건 +4.2%. 같은 시각 대장주 20종목이 -8% 바닥→+9.3% 반등(평균 68분). 진입은 바닥(che저점반등)·MA전환만.
#   아침자유(~10:30) 슬롯무시로도 우회 불가(조건 자체 차단). 롤백: setx MF_MOMENTUM_OFF NO
MOMENTUM_OFF  = os.environ.get("MF_MOMENTUM_OFF", "YES").strip().upper() == "YES"
# [7/12 친구님 "눌림도 엔진 꺼놔 — 내일 안 해"] 바닥(=눌림·체결강도 저점반등) 역할 진입 차단.
#   ★역할 배정 지점에서만 막음(_rebound_ok 변수는 안 죽임) — 그 변수는 깊은바닥 예비 경로(:958)에서도 쓰여서
#   변수를 죽이면 나중에 MF_DEEP_NOCHE_ALL을 되돌릴 때 깊은바닥까지 같이 죽는다. 아침자유 슬롯무시로도 우회 불가.
#   깊은바닥(400만·4종목)·MA전환은 영향 없음. 롤백: setx MF_REBOUND_OFF NO
REBOUND_OFF   = os.environ.get("MF_REBOUND_OFF", "NO").strip().upper() == "YES"
# [7/10 친구님 "추세 주종 하고싶어 — 모멘텀 그림자 배선해·고"] 규칙달린 모멘텀 그림자(주문 0) —
#   차단된 모멘텀 경로에서 정배열 strict(5>20>60)+과열캡 통과 후보만 기록(종목당 하루 1회).
#   근거: 7/9 참사 45건은 60선 위/아래 모두 적자 = 위치 아닌 무규칙 추격이 문제 → 규칙판 승률을 그림자로 검증 후 재개 판단.
#   지수게이트(코스닥 -1.0%·7/9 검증완료 미배선)는 저녁 지수분봉 사후대조로 판정. 롤백: setx MF_MOMENTUM_SHADOW NO
MOMENTUM_SHADOW = os.environ.get("MF_MOMENTUM_SHADOW", "YES").strip().upper() == "YES"
MSHADOW_FILE = Path(r"C:\stock_bot\data\돈맥_모멘텀그림자.json")
def _mshadow_note(code, cur, big, dev, hm):
    """모멘텀 그림자 기록(주문 0·실패 무해)."""
    try:
        d = {}
        if MSHADOW_FILE.exists():
            d = json.loads(MSHADOW_FILE.read_text(encoding="utf-8-sig"))
        _td = datetime.now().strftime("%Y%m%d")
        if d.get("date") != _td:
            d = {"date": _td, "m": {}}
        if code in d.get("m", {}):
            return
        d.setdefault("m", {})[code] = {"hm": hm, "cur": cur, "big": big, "dev60": dev}
        MSHADOW_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        _log(f"[그림자] 모멘텀후보 {code} @{cur:,.0f} (정배열strict·60선이격{dev:+.1f}%·큰손{(big or 0)/100:+.0f}억)")
    except Exception:
        pass
# [2026-07-07 통합대장 통합 ②③ (친구님 번호별 타당성 합의)] 상승(모멘텀) 진입 품질 게이트. 백테: 60선위 +0.19% vs "20위·60아래" -0.42%(함정). 저점반등 경로는 무관.
MA60_GATE     = os.environ.get("MF_MA60_GATE", "YES").strip().upper() == "YES"     # ②일60선 위에서만 상승진입(추세확인). NO=off
OVERHEAT_CAP  = float(os.environ.get("MF_OVERHEAT_CAP", "8"))                      # ③과열 캡 — 60선 이격 이 %↑면 고점추격이라 상승진입 스킵(저점반등 경로엔 미적용)
# [2026-07-07 눌림 B (친구님 "문제없으면 통합")] 거래량 배수 재개확인 — 저점반등(재개) 진입은 당일 거래량 페이스가 평소↑여야(진짜 돈 들어옴·죽은반등 거름). 모멘텀 경로엔 미적용.
VOL_MULT_GATE = os.environ.get("MF_VOL_MULT_GATE", "YES").strip().upper() == "YES" # 거래량 배수 게이트 on/off
VOL_MULT      = float(os.environ.get("MF_VOL_MULT", "1.3"))                        # 당일 거래량페이스 / 20일평균 ≥ 이 값(눌림사냥꾼 1.3)
# [2026-07-07 친구님 MA전환 바닥 (백테검증 +0.8%/3일·+1.24%/5일·베이스 2배)] 5·20·60선 수렴→정배열전환→60선우상향 = 바닥 base 돌파. 큰손과 결합해 저가바닥 진입경로 추가.
MABASE_GATE   = os.environ.get("MF_MABASE_GATE", "YES").strip().upper() == "YES"   # MA전환 바닥 진입경로 on/off
MABASE_ALLDAY = os.environ.get("MF_MABASE_ALLDAY", "YES").strip().upper() == "YES" # [7/10] MA전환 오후까지(신호 희소)
# [2026-07-10 밤 친구님 "갑툭이 MA수렴하고 같이 넣자 — 둘 다 몇 개 안 나와"] 갑툭이 예비 익일 아침 진입.
#   전일 = 갑툭튀(15일 조용한 베이스 6~18%·일일+10%↑없음 → 완만 첫돌파 +3~6%·거래량1.5×) ∧ 5/20/60 수렴(이격≤4%).
#   1년 백테: 익일 갭다운/플랫 매수 +2.27%(승69%)·갭+2%↑ 추격 승률44% 최악 → 전일比 ≤MF_GAPTUK_MAX_CHG(0%)에서만.
#   MA전환과 같은 역할슬롯 공유(둘 다 희소)·아침창(R1)만·10:20 조항 등 기존 사다리 그대로. 롤백: setx MF_GAPTUK_GATE NO
GAPTUK_GATE    = os.environ.get("MF_GAPTUK_GATE", "YES").strip().upper() == "YES"
GAPTUK_MAX_CHG = float(os.environ.get("MF_GAPTUK_MAX_CHG", "0"))   # 전일比 이 %(기본 0=갭다운·눌림)이하만 매수
RECOIL_PT = float(os.environ.get("MF_RECOIL_PT", "12"))                     # [7/7 친구님 "실시간 che 꺾임으로 팔아"] che 되돌림 매도 — 보유중 che최고 대비 이만큼↓ 꺾이면 조기매도(진입 저점반등과 대칭·바닥사냥꾼 -12)
RECOIL_MINPEAK = float(os.environ.get("MF_RECOIL_MINPEAK", "100"))          # che최고가 이 값↑였을 때만 되돌림매도(매수우위였던 것만)·che약한건 vol_exit이 담당
# [2026-07-10 장중 친구님 "해결방법 적용해" — V초입 되돌림 휩쏘 방지] ①진입 후 GRACE분간 되돌림 매도 유예
#   (그동안 구조붕괴/하드-2%가 가격으로 방어 — 펩트론 1차 09:07진입→09:11 -0.8% 되돌림컷→직후 +3% 실증)
#   ②이익 +PROFIT_PCT% 이상 구간은 되돌림 눈금 -12→-PROFIT_PT(러너 숨쉴 틈·7/6 백테 "트레일이 정답·일찍 자르지마라").
#   롤백: setx MF_RECOIL_GRACE_MIN 0 · setx MF_RECOIL_PROFIT_PCT 999
# [2026-07-10 장중 친구님 "1.5~3%서 잡을수 있니→적용해"] 깊은바닥 돈유입 조회(probe) 가속 120→45초 —
#   probe는 턴+밴드 통과 종목(조건권 1~4개)만 도니 TR 부담 제한적. 지각 주범(돈유입 확인 2~3분)을 직접 단축
#   → 돈이 이미 들어온 종목은 저점+1.5~2.5%에서 진입. 롤백: setx MF_DEEP_PROBE_SEC 120
DEEP_PROBE_SEC    = float(os.environ.get("MF_DEEP_PROBE_SEC", "45"))
RECOIL_GRACE_MIN  = float(os.environ.get("MF_RECOIL_GRACE_MIN", "5"))
RECOIL_PROFIT_PCT = float(os.environ.get("MF_RECOIL_PROFIT_PCT", "2.0"))
RECOIL_PROFIT_PT  = float(os.environ.get("MF_RECOIL_PROFIT_PT", "20"))
def _hm_min(s):
    s = (str(s) or "").strip()
    return int(s[:2]) * 60 + int(s[2:4]) if len(s) >= 4 and s[:4].isdigit() else 0
MAX_ENTRIES = int(os.environ.get("MF_MAX_ENTRIES", "3"))                    # [7/7 친구님] 종목당 하루 최대 진입횟수(재진입 포함)·churn 상한
REENTRY_COOLDOWN = float(os.environ.get("MF_REENTRY_COOLDOWN", "180"))      # 매도후 재진입 쿨다운(초)·즉시 재매수 churn 방지
# [2026-07-08 친구님 "아침엔 기회 먼저 잡는 놈이 임자"] 아침 자유진입 창(기본 ~10:30) —
#   해제: 역할슬롯(통합대장2/바닥2/MA1 무시=선착순) + 종목당 하루 횟수제한(MAX_ENTRIES 무시).
#   유지: 진입확인(상승 or che저점반등=기회의 정의·낙하칼차단), 매도후 3분/실패 5분 쿨다운(churn·주문스팸 방지),
#         MAX_POS(자본한도=돈 없으면 대기했다 자리 나면 재진입). 롤백: set MF_MORNING_FREE=NO
MORNING_FREE = os.environ.get("MF_MORNING_FREE", "YES").strip().upper() == "YES"
MORNING_END  = os.environ.get("MF_MORNING_END", "1030")
# [2026-07-08 친구님 4대지시+정정] ①동시보유 제한 폐지(기회 우선권·MAXPOS는 cmd에서 99) ②횟수 무제한 —
#   **원금 200만 회전**: 지금 투입 중인 금액 ≤ 200만. 팔면 돈이 돌아와 그걸로 계속 재매수(로테이션·하루 누적 1000만도 가능).
#   "보급 없음" = 원금 200만 밖에서 새 돈 추가투입 금지. ③09:00~09:03 관찰, 단 급행(날아가는 놈)은 1분 포착.
DAILY_BUDGET = float(COMMON_CAPITAL_KRW)   # 공통 회전 원금 한도
# [7/11 친구님 "500만 재편"] 역할별 건당/풀 한도 — 깊은바닥 100만×4·그 외(눌림/바닥/MA전환/갑툭이) 20만×풀100만
DEEP_CAP   = float(COMMON_CAPITAL_KRW)
DEEP_POOL  = float(COMMON_CAPITAL_KRW)
OTHER_POOL = float(COMMON_CAPITAL_KRW)
OPEN_OBS_END = os.environ.get("MF_OPEN_OBSERVE_END", "0903")             # 개장 관찰 종료(이전엔 급행만)
FAST_MARGIN  = float(os.environ.get("MF_FAST_MARGIN_EOK", "10")) * 100.0 # 급행: 큰손 우위 최소(기본 10억=별표눈금·친구님 "아침 몇분에 30억 힘들다")
FAST_CHE     = float(os.environ.get("MF_FAST_CHE", "120"))               # 급행: 실시간 체결강도 최소(지금 매수가 이기는 중)
FAST_CHG     = float(os.environ.get("MF_FAST_CHG_PCT", "1.0"))           # 급행: 전일종가 대비 상승(%·바로 날아가는 중)


def _prev_close_map():
    """전일종가 맵(돈맥_전일상위풀.json·TR 0) — 개장 급행 '날아가는 중' 판정용."""
    if getattr(_prev_close_map, "_c", None) is not None:
        return _prev_close_map._c
    m = {}
    try:
        d = json.loads(Path(r"C:\stock_bot\data\돈맥_전일상위풀.json").read_text(encoding="utf-8"))
        for c, px, _v in d.get("rows", []):
            m[str(c).zfill(6)] = float(px)
    except Exception:
        pass
    _prev_close_map._c = m
    return m


def _prev_val_map():
    """★[7/15] 어제 거래대금 맵(억) — 돈맥_전일상위풀.json rows=[코드,전일종가,전일대금억]·TR 0.
       깊은바닥 유니버스를 '어제 대금 N억~M억'으로 좁힐 때 사용(MF_DEEP_PVAL_MIN/MAX)."""
    if getattr(_prev_val_map, "_c", None) is not None:
        return _prev_val_map._c
    m = {}
    try:
        d = json.loads(Path(r"C:\stock_bot\data\돈맥_전일상위풀.json").read_text(encoding="utf-8"))
        for c, _px, v in d.get("rows", []):
            m[str(c).zfill(6)] = float(v)      # 이미 억 단위
    except Exception:
        pass
    _prev_val_map._c = m
    return m


def _leader_codes():
    """[7/9 깊은바닥] 대장주 순위표 코드(감시 유니버스) — 일1회 캐시. 실패시 빈 리스트(깊은바닥층만 조용히 쉼)."""
    if getattr(_leader_codes, "_c", None) is not None:
        return _leader_codes._c
    try:
        _leader_codes._c = [str(c).zfill(6) for c in json.loads(LEADERS.read_text(encoding="utf-8-sig")).get("codes", [])]
    except Exception:
        _leader_codes._c = []
    return _leader_codes._c


_DU_WARNED = [False]
def _deep_universe(board):
    """★[7/12 친구님 "선별기에서 전체를 봐야 돼 — 던짐이나 선별된 거나 상관없어. 모두가 급락 후보자야.
       여기는 테마 대장주들이 거의 많이 들어와" + "선별판만 쓰게 해야 돼"]
    깊은바닥 감시 유니버스 = ★선별기 유니버스 전용(대장주 순위표 폴백 없음).
    기존: 대장주 순위표(daily_leader_board·66종목)만 봄 → 선별기 정원(200)에 든 급락 테마주를 통째로 놓침.
    변경: 선별판 univ_codes(깔때기 통과 전체·코스닥/대금/시총1000억/주가2만)만 사용. 등급·수급·던짐 무관.
    ★선별판이 없거나 비면 **빈 리스트** = 깊은바닥 그 사이클은 쉼(엉뚱한 유니버스로 사느니 안 산다).
      보드는 09:00 태스크, 매매기는 09:01 태스크라 정상이면 항상 앞서 있음. 없으면 로그 1회 경고.
    롤백: setx MF_DEEP_UNIV LEADER (대장주 순위표로 복귀)"""
    if os.environ.get("MF_DEEP_UNIV", "BOARD").strip().upper() == "LEADER":
        return _leader_codes()
    try:
        uc = board.get("univ_codes") if isinstance(board, dict) else None
        if uc:
            return [str(c).zfill(6) for c in uc]
    except Exception:
        pass
    if not _DU_WARNED[0]:
        _DU_WARNED[0] = True
        _log("⚠️ 선별판에 유니버스(univ_codes)가 없음 → 깊은바닥 대기(보드 기동 확인 필요)")
    return []


def _pmgap_map():
    """[7/9 친구님 "장전 상황 바로 참고"] 장전 예상갭 맵(data/premarket_gap.json·TR 0) — 참고표시 전용.
    ★진입조건 아님(미검증·동시호가 허수가능) — 매수로그/포지션에 기록만 해서 사후대조용. 당일 데이터 아니면 빈 맵·실패시 빈 맵(fail-open)."""
    if getattr(_pmgap_map, "_c", None) is not None:
        return _pmgap_map._c
    m = {}
    try:
        d = json.loads(Path(r"C:\stock_bot\data\premarket_gap.json").read_text(encoding="utf-8"))
        if str(d.get("date", "")) == datetime.now().strftime("%Y%m%d"):
            for _r in d.get("rows", []):
                m[str(_r.get("code", "")).zfill(6)] = (float(_r.get("gap_pct", 0) or 0), int(_r.get("gap_rank", 0) or 0))
    except Exception:
        pass
    _pmgap_map._c = m
    return m
# [2026-07-07 친구님 "바닥선 che 약하니 절대값 말고 저점반등으로"] 재진입 트리거 = che 저점반등(바닥사냥꾼 RUNIFIED_TRIG=REBOUND 방식).
#   근거: 급락 바닥에선 che가 100 못 참(58→66) = 절대값은 늦은확인. 당일 che저점 대비 +REB_PT 돌아서면 반등으로 봄. 첫매수는 큰손만(che게이트 없음).
CHE_STATE = Path(r"C:\stock_bot\data\돈흐름_che_state.json")                # 보드가 누적(code→{min,n,last})·저점반등 판정용
REB_PT    = float(os.environ.get("MF_REB_PT", "8"))                         # che 저점 대비 반등 포인트
REB_MINN  = int(os.environ.get("MF_REB_MINN", "5"))                         # min 계산 최소 표본수
# [2026-07-09 친구님 "1등 목표 = 9시 깊은바닥 반등 — -5%↓ 갔다 반등하는 놈. 저점에서 기관/외인/프로그램 돈 몰렸나
#   확인하고 사야 돼. 개인도 무시하지 말고 무조건 돈이 먼저 몰리는 것에"] 깊은바닥 후보층 —
#   선별판 🟢(큰손 합의) 입구와 별개(바닥에선 큰손이 보통 🔴/🟡라 🟢 입구론 못 들어옴 = 7/9 실증: 바닥반등 20종목 중 1건만 포착).
#   ①등재 = 대장주 순위표 전 종목 중 당일 저점(che_state lo)이 전일종가比 DEEP_DROP% 이하 (실시간 감시·TR 0)
#   ②저점확인 = 현재가가 당일저점 +CHASE_BAND% 이내(추격금지)  ③저점 매수세 = che 저점반등 +REB_PT & 거래량 VOL_MULT배
#   ④★저점 돈유입 = 기관/외인/프로그램/개인 중 1주체라도 순매수 ≥ DEEP_INFLOW_EOK — 진입순간 실시간(probe·60s캐시) 우선,
#     실시간 불가시만 보드 최신 실측 폴백, 둘 다 없으면 안 삼(빈반등 차단). 대량던짐 차단·구조붕괴 손절·10:20 전량청산 기존 그대로.
#   근거(7/9 실측): 대장주 63중 -5%↓저점 후 +3%반등 48종목·9시대 바닥 20종목 평균 -8.2%→+9.3%(68분·꼭지 평균 10:18).
#   롤백: setx MF_DEEP_BOTTOM NO
DEEP_ON     = os.environ.get("MF_DEEP_BOTTOM", "YES").strip().upper() == "YES"
DEEP_DROP   = float(os.environ.get("MF_DEEP_DROP_PCT", "-5.0"))             # 등재: 당일저점 전일종가比 이 % 이하
# ★[7/10 밤 친구님 "등락율 큰 놈들 체크" 검증→방향반전] 변동성 차등 등재 — 1년 일봉 검증: 고변동(20일평균폭 4%+)은
#   -4%서 이미 최고(+2.45%/71%·더 깊이 대기=건수만 손해) / 저변동(<4%)은 -4%가 얕음(+0.53%/43%·-6%면 +0.98%/52%)
#   → 저변동만 등재 문턱 -6% 요구·등재 경합시 고변동 우선 정렬. 롤백: setx MF_DEEP_DROP_LOWVOL -4 (차등 끔)
DEEP_LOWVOL_RNG  = float(os.environ.get("MF_DEEP_LOWVOL_RNG", "4.0"))       # 20일 평균 일중폭 이 % 미만 = 저변동
DEEP_DROP_LOWVOL = float(os.environ.get("MF_DEEP_DROP_LOWVOL", "-6.0"))     # 저변동 등재 문턱
DEEP_REB_MIN = float(os.environ.get("MF_DEEP_REB_MIN", "1.5"))              # 저점 확인: 저점서 이만큼 돌아서야 진입(폭포 한가운데 매수 방지·7/9 리플레이 +0.28→+6.72%p·구조붕괴 휩쏘 0)
DEEP_INFLOW = float(os.environ.get("MF_DEEP_INFLOW_EOK", "3")) * 100.0      # 돈유입 최소(억 단위 입력→내부 백만원)
SLOTS_DEEP  = int(os.environ.get("MF_SLOTS_DEEP", "3"))                     # 깊은바닥 역할 슬롯
# ★[7/15 친구님 "급락주 다시 테스트 — 어제 거래대금 300억~2조로 특정 · 잡주 다 치워"]
#   깊은바닥 유니버스를 '어제(전일) 거래대금 구간 + 전일종가 하한'으로 좁힌다. 전부 0 = 끔(옛 동작).
#   근거(7/14 09:00~09:30 실측): 어제대금 300억~2조·1만원↑ = 급락 11개(저점→10:20 평균 +8.7%·100% +3%↑반등)·
#     1,000억~2조는 4개로 슬롯 못 채움. 반등 질은 두 구간 동일 → 건수 많은 300억 채택.
#   ⚠️어제대금은 돈맥_전일상위풀.json(09:00 갱신·700종목)에서 읽음 → 700위 밖(어제 4억 미만)은 애초 유니버스에 없음.
#   롤백: setx MF_DEEP_PVAL_MIN 0  (구간·가격하한 셋 다 0으로 = 잡주 포함 옛 동작 복귀)
DEEP_PVAL_MIN = float(os.environ.get("MF_DEEP_PVAL_MIN", "0") or 0)         # 어제 거래대금 하한(억·0=끔)
DEEP_PVAL_MAX = float(os.environ.get("MF_DEEP_PVAL_MAX", "20000") or 0)     # 어제 거래대금 상한(억)
DEEP_PX_FLOOR = float(os.environ.get("MF_DEEP_PX_FLOOR", "0") or 0)         # 전일종가 하한(원·0=끔·잡주제거=10000)
# [7/13 밤 친구님 "잡주도 정배열 위주로 사고… 1만원 이상도 후순위로" → 데이터로 재단] ★잡주 개방 (선별판과 짝) —
#   3분봉 43일×207종목: 잡주(3천~1만원) 개방 시 하루 14,243원 → 29,008원. 단 ①시총 500억 완화 필수(선별판)
#   ②매수 우선권은 주지 않음(주면 -6,441원 — 늘어난 잡주가 전부 손실이고 좋은 1만원↑까지 슬롯서 밀어냄) ③아래 2개 관문 필요.
LOW_PX_EDGE     = float(os.environ.get("MF_LOW_PX_EDGE", "10000"))          # 잡주 경계(원) — 선별판과 동일값 유지
DEEP_REB_MIN_LOW = float(os.environ.get("MF_DEEP_REB_MIN_LOW", "0"))        # ★잡주 진입창 하한 = 저점+0%(1만원↑는 DEEP_REB_MIN=+1%)
LOW_V20_EOK     = float(os.environ.get("MF_LOW_V20_EOK", "2"))              # ★잡주 유동성 관문(억) — 그 시각까지 거래대금
_LOW_LIQ_SEEN   = set()                                                     # 잡주 유동성 보류 로그 중복 방지
# ★[7/14 친구님 "저점 +2~3%로 바꿔서 다시 테스트해봐" → 검증 후 배선] 1만원↑ 전용 진입창 상한.
#   🚨1만원↑는 저점에 바짝 붙어 사면 안 된다 — 1분봉 43일 실측(1만원↑ 단독):
#      저점 +1~2%(옛) 하루 -7,982원(승률 44%·손절 37%) → ★+2~3% 하루 +9,338원(승률 53%·손절 33%)
#      전체 합산(잡주 +0~2% 유지)도 -1,129원 → +11,586원 · 부트스트랩 1등 96%를 +1.5~3% 구간이 독식.
#   이유: 비싼 종목은 호가 한 칸이 커서 저점 근처는 아직 안 돌아섰고, 손절선(-2%)이 저점에 붙어 휩쏘에 잘린다.
#   ⚠️잡주는 정반대(저점 +0%가 최적·건당 +1.74%) → 상한도 가격대별로 나눈다(CHASE_BAND는 잡주 몫으로 유지).
#   ⚠️경계가 좁다: +2.5~3.5%는 다시 마이너스(-1,782원). 이 값을 함부로 넓히지 말 것.
#   롤백: setx MF_DEEP_BAND_HI 0  (=0이면 잡주와 같은 CHASE_BAND 사용 = 옛 동작) · setx MF_DEEP_REB_MIN 1
DEEP_BAND_HI    = float(os.environ.get("MF_DEEP_BAND_HI", "0") or 0)        # 1만원↑ 진입창 상한(0=CHASE_BAND 사용)
# ★[7/14 친구님 "매입 후 3분 버티기 · 안전장치 붙여서 테스트해봐"] 재난 손절 — 손절 유예를 12분으로 늘린 것과 세트.
#   유예(MF_DEEP_STOP_GRACE_MIN)는 진입 직후 흔들림에 안 털리려고 두는 것인데, 그 사이 진짜 폭락이 오면 무방비다.
#   → 유예를 무시하고 즉시 자르는 최종 방어선. 하드컷보다 선순위(유예 조건 없음).
#   1분봉 43일 실측: 유예 3분 → 12분이 핵심 약(하루 11,586 → 16,263원 · 최근 22일 -10,007 → -4,413원).
#     재난손절 -5%는 백테상 -927원 손해(103건 중 1건 발동·하필 회복할 놈)지만 하방을 -5%에서 봉쇄하는 보험값.
#     표본에 -6% 이상 폭락이 우연히 없었을 뿐 — 실전에서 오면 유예 12분이 통째로 맞는다.
#   0 = 끔. 롤백: setx MF_DEEP_DISASTER 0
DEEP_DISASTER   = float(os.environ.get("MF_DEEP_DISASTER", "0") or 0)       # 깊은바닥 재난손절(%·음수·유예 무시)
# [2026-07-09 밤 친구님 승인 "고" — 대칭안] "오르막 중간에 사고 내리막 중간에 판다" 수술(엘앤씨·에스엠 리플레이 검증):
#   ①아침 1차(10:00까지) 깊은바닥 진입은 거래량 1.3배 관문 면제 — 관문이 15분 지각시켜 바닥턴(+1.5%) 대신 +3.9%에 매수(엘앤씨 실증)
#   ②아침 1차 깊은바닥 보유분 매도 = vol_exit(절대 체결강도100 눈금·5선이탈 휩쏘) 대신 '반등소멸'(체결강도가 당일저점+PT 아래 복귀)
#   검증: 에스엠 -1.18%p→+3.66%(10:20 정답매도)·엘앤씨 -0.80→+0.55·7/9 등재 10종목 +0.68→+2.04%p(악화 0).
#   롤백: setx MF_DEEP_R1_NOVOL NO · setx MF_DEEP_R1_SYMEXIT NO
DEEP_R1_NOVOL   = os.environ.get("MF_DEEP_R1_NOVOL", "YES").strip().upper() == "YES"
DEEP_R1_SYMEXIT = os.environ.get("MF_DEEP_R1_SYMEXIT", "YES").strip().upper() == "YES"
SYMEXIT_PT      = float(os.environ.get("MF_SYMEXIT_PT", "3"))               # 반등소멸: 체결강도 ≤ 당일저점+이 값이면 매도
# [2026-07-10 새벽 친구님 "체결강도 말고 그날의 저점으로 — 수정해"] 아침 1차 깊은바닥 진입 = 가격만(그날 저점 기준 턴):
#   체결강도 저점반등 조건 제거. 10일 백테 +14.1→+50.6%p·승률 42→55%(V3). 이 모드에선 반등소멸 매도도 제외(V3 검증 그대로
#   — 진입이 체결강도 무관이라 소멸 판정이 무의미·구조붕괴/하드-2%/체결강도되돌림/10:20이 방어). 롤백: setx MF_DEEP_R1_NOCHE NO
DEEP_R1_NOCHE   = os.environ.get("MF_DEEP_R1_NOCHE", "YES").strip().upper() == "YES"
# ★[2026-07-10 저녁 친구님 "선별기 종목은 망할 회사 아냐 — 아침엔 돈던지기 무시하고 반등만 보고 사"]
#   아침 1차 깊은바닥 = 돈유입 3억 관문 + 던짐차단 면제(등재-4%·턴+1.5%·밴드·매도사다리·10:20청산은 유지).
#   근거: 7/10 등재 8종목 브로커 리플레이 = 턴만 7건 +21.7%p(에이직랜드+10.7·올릭스+5.4) / 돈유입 관문은 역선별
#   (프로+9억 통과 펩트론 -2.0% vs 프로 던짐 차단 올릭스 +5.4%) / 원백테(+50.6%p/55%)가 애초 가격턴만 측정.
#   2차 창(10:00~)은 돈유입·던짐차단 그대로. 롤백: setx MF_DEEP_R1_NOINFLOW NO
DEEP_R1_NOINFLOW = os.environ.get("MF_DEEP_R1_NOINFLOW", "YES").strip().upper() == "YES"
# [2026-07-10 개장전 친구님 "지금 수정해 — 저점으로"] 아침 1차 눌림(저점반등) 진입도 가격 저점 턴으로 —
#   체결강도 저점반등은 개장 직후 표본 설익음 + 체결강도저점과 가격저점 시각 어긋남(클래시스 7/9: che저점 09:0x,
#   가격저점 09:18 → 09:05 조기매수 -0.62% 왕복 리플레이 실증). 깊은바닥과 동일 눈금(저점+1.5%턴·+6%밴드).
#   롤백: setx MF_PULL_PRICE_TURN NO
PULL_PRICE_TURN = os.environ.get("MF_PULL_PRICE_TURN", "YES").strip().upper() == "YES"
# [2026-07-10 개장전 친구님 "지금 넣어 -2% 문턱도"] 눌림 최소 깊이 — 당일저점이 전일종가比 이 % 이하로
#   눌린 종목만 가격턴 진입(개장 얕은눌림 +1.5%턴 조기진입 차단·클래시스 7/9 리플레이: 09:05 -1.56% 왕복 제거,
#   09:23 진짜저점 진입 +2.02%만 남음). 전일종가 없으면 안 삼(fail-closed). 롤백: setx MF_PULL_MIN_DROP 0
PULL_MIN_DROP   = float(os.environ.get("MF_PULL_MIN_DROP", "-2.0"))
# [2026-07-10 장중 친구님 "백테 지금 돌려→지금 해 + 다른 전략에도 — 고"] 분할진입 + 분당 거래량 팽창 게이트 —
#   8일 백테(깊은바닥 턴 34건): 턴만 승률24%·합계-23.6%p → 턴+거래량팽창(×2.5·분당대금5천만+) 승률57%·+1.9%p.
#   ①선매수: 돈유입 확인 전이라도 턴+팽창이면 CAP×FRAC(기본 1/3)만 먼저(진짜 바닥턴 저점권 선취·에이직랜드 3.5%p 지각 해소)
#   ②본매수: 돈유입(1주체 3억) 확인시 나머지 채움(합산 CAP 이내·평단 병합) ③눌림(저점반등)에도 팽창 게이트(표본부족=통과).
#   거래량 데이터 = 실시간 푸시 누적거래량(TR 0) 사이드카 분당 기록. 롤백: setx MF_SPLIT_ENTRY NO · setx MF_PULL_VOLX_GATE NO
SPLIT_ENTRY  = os.environ.get("MF_SPLIT_ENTRY", "YES").strip().upper() == "YES"
SPLIT_FRAC   = float(os.environ.get("MF_SPLIT_FRAC", "0.33"))
SPLIT_VOLX   = float(os.environ.get("MF_SPLIT_VOLX", "2.5"))
SPLIT_MINKRW = float(os.environ.get("MF_SPLIT_MIN_KRW", "50000000"))
PULL_VOLX_GATE = os.environ.get("MF_PULL_VOLX_GATE", "YES").strip().upper() == "YES"
# [7/10 친구님 "역배열(5<20<60)은 바닥만 예외 — RFHIC 어째 샀지"] 눌림 역배열 차단 — 깊은바닥 예외·60일 미만 통과
PULL_REV_BLOCK = os.environ.get("MF_PULL_REV_BLOCK", "YES").strip().upper() == "YES"
_DOOMED_SEEN = set()   # [7/12] 망한무리 차단 로그 중복 방지(분 프로세스 단위)
_STRUCT_HOLD_SEEN = set()   # [7/13] 구조붕괴 유예(매수벽 받침) 로그 중복 방지
_ENTRY_IMB_SEEN   = set()   # [7/13] 진입 호가관문 보류(매도벽 우세) 로그 중복 방지
_ENTRY_IMB_NONE_SEEN = set()  # [7/13 OB-FIX] 호가 결측 → 가격조건만으로 진행한 종목 기록(사후 대조용)
_DEEP_REV_SEEN    = set()   # [7/13 저녁] 깊은바닥 역배열 차단 로그 중복 방지
_ENTRY_POS_SEEN   = set()   # [7/13] 진입 꼬리관문 보류(종가위치 부족) 로그 중복 방지
_R1_HOLD_SEEN     = set()   # [7/13] 10:20 1차마감 유예(상승 중) 로그 중복 방지
_WICK_HOLD_SEEN   = set()   # [7/14] 꼭지매도 보류(직전 꼬리세 강함) 로그 중복 방지
BARS_1M = Path(r"C:\stock_bot\data\돈맥_1분봉.json")   # [7/13] 기록기(상주)가 공급하는 1분봉 — ★진입(바닥확인)용
BARS_3M = Path(r"C:\stock_bot\data\돈맥_3분봉.json")   # [7/14] 기록기가 공급하는 3분봉 — ★매도(꼭지)용


def _grid3(hm):
    """HHMM → 그 시각이 속한 3분 블록의 시작 HHMM (09:00 격자·기록기와 동일 규칙)."""
    try:
        m = int(hm[:2]) * 60 + int(hm[2:])
        b = m - (m - 540) % 3
        return f"{b // 60:02d}{b % 60:02d}"
    except Exception:
        return hm


def _bar3m(code):
    """[7/14 친구님 "깊은바닥 그대로 이식하고 바닥 잡는 것만 1분봉으로"] 그 순간의 3분봉 — ★꼭지매도 판정용.
       🚨1분봉 꼬리로 팔면 꼭지가 아닌데도 판다 — 207종목×43일 실측: 꼭지매도 수익 1분봉 +2.24% vs 3분봉 +2.88%
         (하루 -16,275원 → -1,237원). 진입(바닥확인)은 1분봉 그대로.
       반환 {o,h,l,c,pos,bull} · 없거나 낡았으면 None(→ 꼭지매도 안 함 = 다른 매도 규칙이 받는다)."""
    try:
        d = json.loads(BARS_3M.read_text(encoding="utf-8-sig"))
        if str(d.get("hm", "")) != _grid3(datetime.now().strftime("%H%M")):   # 이번 3분 블록이 아니면 무효
            return None
        return (d.get("m") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _bar3m_ready(code):
    """🚨★[7/14 장중 친구님 "원익 왜 벌써 팔았지?" → 진짜 버그 발견] 3분봉이 '거의 완성된' 순간에만 반환.
       문제: _bar3m()은 **진행 중**인 3분봉을 준다 → 매매기가 8초마다 그걸 보고 판정 →
             3분 블록 한복판의 순간적 밀림을 '위꼬리(꼭지)'로 오판해서 팔았다.
             에이프릴바이오 실증(7/14): 09:31 진행중 봉 pos 0.20 → 매도(24,400).
             그 봉이 완성됐을 땐 pos 0.875(강한 아래꼬리)였고 곧바로 24,600으로 올랐다.
       ★백테는 '3분봉 완성 시각'에만 판정했는데 엔진은 매 순간 판정 = 프레임 불일치.
         1분봉 43일 실측: 진행중봉 판정 하루 2,215원(꼭지수익 +1.63%·보유 19분)
                          → ★완성봉 판정 4,106원(+2.38%·29분)  = 거의 두 배
       처방: 블록의 **마지막 분**(09:02·09:05…)의 끝자락(SEC초 이후)에만 봉을 준다 = 사실상 완성봉.
             매매기는 매분 새로 떠서 55초에 죽으므로 40~55초 창에 8초 루프가 1~2회 들어온다.
             놓쳐도 다음 블록에서 다시 판정하니 손실 없음(3분 지연).
       롤백: setx MF_TOP_SELL_READY NO (=진행중 봉 판정으로 복귀)"""
    if os.environ.get("MF_TOP_SELL_READY", "YES").strip().upper() != "YES":
        return _bar3m(code)
    now = datetime.now()
    m = now.hour * 60 + now.minute
    if (m - 540) % 3 != 2:                                          # 블록의 마지막 분이 아니면 판정 안 함
        return None
    if now.second < int(os.environ.get("MF_TOP_SELL_SEC", "40")):   # 그 분의 끝자락에만(봉 ~90% 완성)
        return None
    return _bar3m(code)


def _wick_strong(code):
    """★[7/14 장중 친구님 "몇 분 전의 꼬리세가 강할 때는 매도를 하지 않는 게 낫지 않니?"]
       직전 K분 1분봉의 평균 종가위치가 P 이상이면 '아직 밑에서 받아올리는 중' → 꼭지매도 보류.
       근거: 에이프릴 09:29~09:31 종가위치 1.00/0.67/0.80(평균 0.82)로 매수세가 계속 받치고 있었는데 팔았다.
       실측(완성봉 판정 위에서): 보류 없음 4,106원 → ★직전3분 종가위치≥0.7 보류 4,295원.
       재료(봉·prev) 없으면 False = 판다(fail-safe). 롤백: setx MF_WICK_HOLD_POS 0 (=끔)"""
    p = float(os.environ.get("MF_WICK_HOLD_POS", "0") or 0)
    if p <= 0:
        return False
    k = int(os.environ.get("MF_WICK_HOLD_N", "3") or 3)
    b = _bar1m(code)
    if not b:
        return False
    poss = []
    if b.get("pos") is not None:
        poss.append(float(b["pos"]))
    for pb in reversed(b.get("prev") or []):          # 최근 완성봉 → 과거 순
        if len(poss) >= k:
            break
        try:
            _o, _h, _l, _c = float(pb[0]), float(pb[1]), float(pb[2]), float(pb[3])
            _rr = _h - _l
            poss.append(((_c - _l) / _rr) if _rr > 0 else 0.5)
        except Exception:
            break
    if len(poss) < k:
        return False                                  # 봉이 모자라면 판다(fail-safe)
    return (sum(poss[:k]) / k) >= p


def _bar1m(code):
    """[7/13] 그 순간의 1분봉 — deep_bottom_signal_recorder(상주·5초)가 만든 파일에서 읽음(TR 0).
       반환 {o,h,l,c,pos,bull} · 없거나 낡았으면 None(→ 매수 금지 fail-safe).
       ★매매기는 55초마다 프로세스가 죽어(MF_RUN_SEC) 자체 봉 누적이 불가해서 파일로 받는다."""
    try:
        d = json.loads(BARS_1M.read_text(encoding="utf-8-sig"))
        if str(d.get("hm", "")) != datetime.now().strftime("%H%M"):   # 이번 분 봉이 아니면 무효
            return None
        return (d.get("m") or {}).get(str(code).zfill(6))
    except Exception:
        return None
MINVOL_FILE  = Path(r"C:\stock_bot\data\돈맥_분당거래량.json")
_MINVOL = {"d": None}
def _minvol_note(code, cumvol, hm):
    """분당 누적거래량 기록(사이드카·TR 0·hm당 1회·최근 15개). 실패 무해."""
    try:
        if _MINVOL["d"] is None:
            _MINVOL["d"] = {}
            if MINVOL_FILE.exists():
                j = json.loads(MINVOL_FILE.read_text(encoding="utf-8-sig"))
                if j.get("date") == datetime.now().strftime("%Y%m%d"):
                    _MINVOL["d"] = j.get("m", {})
        if not cumvol or cumvol <= 0:
            return
        arr = _MINVOL["d"].setdefault(code, [])
        if not arr or arr[-1][0] != hm:
            arr.append([hm, float(cumvol)])
            del arr[:-15]
            try:
                MINVOL_FILE.write_text(json.dumps({"date": datetime.now().strftime("%Y%m%d"), "m": _MINVOL["d"]},
                                                  ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
def _minvol_expand(code, cur):
    """분당 거래량 팽창 판정 — True=그 분 거래량 ≥ SPLIT_VOLX×직전평균 & 분당대금 ≥ SPLIT_MINKRW / False=아님 / None=표본부족.
    연속(1분 간격) 표본만 사용(빠진 분 왜곡 방지)."""
    try:
        arr = (_MINVOL.get("d") or {}).get(code) or []
        if len(arr) < 5:
            return None
        difs = []
        for i in range(1, len(arr)):
            if _hm_min(arr[i][0]) - _hm_min(arr[i-1][0]) == 1:
                dv = arr[i][1] - arr[i-1][1]
                if dv >= 0:
                    difs.append(dv)
        if len(difs) < 4:
            return None
        curv, base = difs[-1], difs[:-1]
        avg = sum(base) / len(base)
        if avg <= 0:
            return None
        return bool(curv >= SPLIT_VOLX * avg and curv * cur >= SPLIT_MINKRW)
    except Exception:
        return None
LEADERS     = Path(r"C:\stock_bot\data\daily_leader_board.json")            # 감시 유니버스(전일 거래대금 상위·08:35 생성)
# [2026-07-07 친구님 "바닥 확인하고 잡아야"] 진입 확인 = 상승(모멘텀) OR che 저점반등(바닥확인). 큰손만으론 안 삼(낙하칼 차단). NO면 큰손만(구동작).
ENTRY_CONFIRM = os.environ.get("MF_ENTRY_CONFIRM", "YES").strip().upper() == "YES"
# [2026-07-07 밤 친구님 "역할이 게이트라 선별기 1등 거름·슬롯 공유" 수정] 역할별 슬롯 — 통합대장/바닥/MA전환이
#   각자 슬롯으로 선별기 순위에서 독립 픽(한 역할이 슬롯 다 먹어 다른 역할 굶는 것 방지). 합이 MAX_POS보다 커도 글로벌캡이 최종제한.
SLOTS_UP  = int(os.environ.get("MF_SLOTS_UP",  "2"))   # 통합대장(상승·60선위) 슬롯
SLOTS_REB = int(os.environ.get("MF_SLOTS_REB", "2"))   # 바닥+눌림(저점반등) 슬롯
SLOTS_MA  = int(os.environ.get("MF_SLOTS_MA",  "1"))   # MA전환 바닥 슬롯
INCLUDE_RISK = os.environ.get("MF_INCLUDE_RISK", "NO").strip().upper() == "YES"  # 🟡(레짐위험)도 후보에(기본 NO=급락장 전면방어)
ENTRY_END = os.environ.get("MF_EXEC_ENTRY_END", "1300")   # [7/9 친구님 "13시까지만 하자"] 1개월 조사: 13시 저점부터 반등성공 52%로 꺾임(9~12시 78~100%) → 신규진입 13:00 마감
EOD_HM    = os.environ.get("MF_EXEC_EOD", "1518")
# [2026-07-09 친구님 "1차 매매는 10시20분까지 다 매도한다·프로그램에 고정"] 아침 1차 회전 —
#   신규진입은 R1_ENTRY_END(10:00)까지·R1_CLOSE(10:20)에 남은 보유 전량 시장가 청산(매도사다리 최우선·큰손유예도 무시).
#   근거(7/9 실측): 코스닥 10:20 꼭지 후 폭포, 10:30 이후 진입 15연패 / 아침창+10시대 청산 시뮬 -6.3만→+0.8만 /
#   21일 3분봉: 고점추격형이 플러스인 구간은 "9시대+지수건강"뿐. 2차(오후 강조건 진입)는 미구현 —
#   붙기 전까지 R1_ENTRY_END 이후 신규매수 없음. 롤백: setx MF_R1_CLOSE "" (빈값=1차마감 끔·ENTRY_END 1430로 복귀)
R1_ENTRY_END = os.environ.get("MF_R1_ENTRY_END", "1000")
R1_CLOSE_HM  = os.environ.get("MF_R1_CLOSE", "1020").strip()
# [2026-07-09 친구님 "2차 창도 열어 — 정오 폭포도 잡아야지"] 2차 창 = R1 진입마감(10:00) 이후 ~ENTRY_END(14:30)
#   ★깊은바닥 역할만 진입 허용(모멘텀·🟢큰손순위 진입은 계속 금지). 10:20 전량청산은 "그 전에 산 것"만 —
#   2차(10:20 이후 매수) 포지션은 기존 매도사다리(구조붕괴>하드-2%>che되돌림>vol_exit>EOD)가 관리.
#   지수게이트는 2차에 안 검(정오 폭포땐 지수 꺾임이 당연 — 걸면 7/9 리플레이 7건 전부 차단). 롤백: setx MF_R2_DEEP NO
R2_DEEP      = os.environ.get("MF_R2_DEEP", "YES").strip().upper() == "YES"
BOARD     = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
POS       = Path(r"C:\stock_bot\data\돈흐름_포지션.json")
LOG       = Path(r"C:\stock_bot\data\LOG\돈흐름매매.log")
RT_OPEN   = Path(r"C:\stock_bot\data\rt_open_positions.json")


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    try:
        print(s, flush=True)
    except Exception:
        # 콘솔 코드페이지(cp949 등)가 이모지(🟢)를 못 찍어도 실주문 루프가 죽으면 안 됨 → ascii 폴백
        try:
            print(s.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _jload(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, p)


def _order(bc, code, qty, side, tag):
    if not LIVE:
        _log(f"[그림자] {side} {code} x{qty} ({tag})"); return True
    try:
        ai = bc.account_info("ACCNO")
        accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []  # [7/7] 통합대장과 동일 ACCNO 폴백
        if isinstance(accs, str):
            accs = [a for a in accs.split(";") if a]
        acc = (accs[0] if isinstance(accs, list) and accs else "") or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()
        if not acc:
            _log(f"[{tag}] 계좌없음"); return False
        r = bc.send_order_real(idempotency_key=f"mflow_{side.lower()}_{code}_{uuid.uuid4()}", account=acc,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"MFLOW_{side}_{code}", screen_no="9745")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[LIVE] {side} {code} x{qty} status={st} → {'성공' if ok else '실패'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _cur(bc, code):
    try:
        snap = json.loads(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json").read_text(encoding="utf-8-sig"))
        return float((snap.get("codes", {}).get(str(code).zfill(6)) or {}).get("cur", 0) or 0)
    except Exception:
        return 0.0


def _che(bc, code):
    try:
        snap = json.loads(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json").read_text(encoding="utf-8-sig"))
        v = (snap.get("codes", {}).get(str(code).zfill(6)) or {}).get("che_str")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None


def _imb(bc, code):
    """[7/12] 호가잔량비율(매수총잔량/매도총잔량·실시간 스냅샷·TR 0) — 하드컷 -4% 유예 판정용. 없으면 None."""
    try:
        snap = json.loads(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json").read_text(encoding="utf-8-sig"))
        v = (snap.get("codes", {}).get(str(code).zfill(6)) or {}).get("imb")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None


def _cumvol(bc, code):
    """당일 누적 거래량(스냅샷). [2026-07-07 눌림 B: 거래량 배수 재개확인용]"""
    try:
        snap = json.loads(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json").read_text(encoding="utf-8-sig"))
        return float((snap.get("codes", {}).get(str(code).zfill(6)) or {}).get("cum_vol", 0) or 0)
    except Exception:
        return 0.0


def _refresh_board():
    """수급 보드 1회 갱신 (opt10059/opt90013 ≈40s). 백그라운드 스레드로 호출돼 매도루프를 안 막음."""
    try:
        import money_flow_board_v1 as MFB
        MFB.run()
    except Exception as e:
        _log(f"보드 갱신 실패 {e}")


# [7/9 친구님 "큰손이 담고 있으면 매수해야·체결량보다 우위"] 큰손 유지 중 연성매도 유예 스위치. 롤백: setx MF_BIG_HOLD_EXIT NO
BIG_HOLD_EXIT = os.environ.get("MF_BIG_HOLD_EXIT", "YES").strip().upper() == "YES"
_BB = {"ts": 0.0, "m": {}}
_DEFER_LOGGED = set()
_DEEP_SEEN  = set()   # [7/9 깊은바닥] 등재 로그 1회용(스팸 방지)
_DEEP_PROBE = {}      # [7/9 깊은바닥] code→마지막 실시간 수급조회 시각(120s 스로틀·TR 보호)


def _board_big(code):
    """선별판의 현재 큰손 순매수(백만원·20초 캐시). 판에 없거나 읽기실패 = None(모름=유예 안함·기존 매도 유지)."""
    try:
        if time.time() - _BB["ts"] > 20:
            d = json.loads(BOARD.read_text(encoding="utf-8"))
            _BB["m"] = {str(r.get("code", "")).zfill(6): float(r.get("big", 0) or 0) for r in (d.get("rows") or [])}
            _BB["ts"] = time.time()
        return _BB["m"].get(str(code).zfill(6))
    except Exception:
        return None


_CHEST = {"ts": 0.0, "m": {}}
def _che_min_today(code):
    """[7/9 대칭안] 당일 체결강도 저점(보드가 누적한 돈흐름_che_state min·10s 캐시). 없으면 None(반등소멸 판정 skip)."""
    try:
        if time.time() - _CHEST["ts"] > 10:
            _CHEST["m"] = _jload(CHE_STATE); _CHEST["ts"] = time.time()
        v = (_CHEST["m"].get(str(code).zfill(6)) or {}).get("min")
        return float(v) if v is not None else None
    except Exception:
        return None


def _exits(bc, pos, hm, mode):
    """청산 (전 전략 공통 vol_exit) — 매매가/체결강도는 실시간 푸시 스냅샷 파일 읽기(TR 0).
    pos 딕셔너리 in-place 갱신. 변경 있으면 True."""
    try:
        import vol_exit as VE
    except Exception:
        VE = None
    changed = False
    for c, p in list(pos.items()):
        if not isinstance(p, dict) or p.get("status") != "HOLDING":
            continue
        cur = _cur(bc, c)
        if cur <= 0:
            continue
        buy = float(p.get("buy_price", 0) or 0)
        peak = max(float(p.get("peak", buy) or buy), cur)
        if peak != p.get("peak"):
            p["peak"] = peak; changed = True
        che = _che(bc, c)
        if che is not None:                          # 보유중 che 최고점 추적(되돌림 매도용)
            pkche = max(float(p.get("peak_che", 0) or 0), che)
            if pkche != p.get("peak_che"):
                p["peak_che"] = pkche; changed = True
        # ★[7/11 친구님 "시가 저항 정보 사다리에 반영"] 낮(10시 이후) 매수 깊은바닥 = 당일 시가가 천장 역할.
        #   근거(24일·2,312건): 낮 저점의 시가 회복률 15~28%·꼭지 중앙 시가比 -1.8~-2.7% / 9시 저점은 회복률 81%
        #   (통과역)이라 미적용 — 아침 매수분은 어차피 10:20 청산이 최우선이라 자연 제외. 시가는 opt10001로
        #   보유종목당 1회 조회 후 포지션에 캐시(TR ≤보유수). 롤백: setx MF_OPEN_RESIST NO / 여유폭 MF_OPEN_RESIST_BUF(0.5%)
        _dop = 0.0
        if (os.environ.get("MF_OPEN_RESIST", "YES").strip().upper() == "YES"
                and str(p.get("role", "")) == "깊은바닥"
                and str(p.get("buy_hm", "") or "") > R1_ENTRY_END):
            _dop = float(p.get("day_open", 0) or 0)
            if _dop <= 0 and time.time() - float(_DEEP_PROBE.get(f"open_{c}", 0) or 0) >= 120:
                _DEEP_PROBE[f"open_{c}"] = time.time()
                try:
                    _ro = bc.tr("opt10001", inputs={"종목코드": c}, output_fields=["시가"],
                                timeout_sec=5.0, screen_no="3250")
                    _dop = abs(float(str((((_ro or {}).get("data") or {}).get("records") or [{}])[0].get("시가", 0) or 0).replace(",", "") or 0))
                    if _dop > 0:
                        p["day_open"] = _dop; changed = True
                except Exception:
                    _dop = 0.0
        sell = None
        _slo = float(p.get("struct_low", 0) or 0)   # 바닥진입시 구조 저점(당일 LL)
        # [7/12 친구님 "-3 하되 매수/매도 확인해서 매수세 우세하면 -4 인정해주고 올라가자" + "호가잔량으로 쉽게 결정되겠네"]
        #   깊은바닥 하드컷 동적화 — 기본 -3%(23일 스윕: 승자 88% 꼭지 생존·수지 최적 동률) ·
        #   그 순간 ★호가잔량 매수우위(imb≥1·매수총잔량≥매도총잔량)면 -4%까지 유예.
        #   판정 지표 = 호가잔량(선행·대기 벽/받침 — 7/12 검증에서 유일하게 방향 맞은 신호·체결강도 버전보다 근소 우위).
        #   (V반등은 중앙 3파동·최고꼭지 전 눌림 75%분위 -2.09% — -2% 그물이 승자 26%를 찢던 문제의 해법.)
        #   호가 데이터 없으면 연장 없음(fail-safe)·그 외 역할은 기존 -2% 유지·구조붕괴/사다리/10:20은 그대로.
        #   롤백: setx MF_DEEP_HARDCUT -2 (동적 전체 해제) / setx MF_DEEP_HC_EXT_IMB 999 (연장만 끔)
        # [7/13 친구님 교정] 역할별 하드컷 —
        #   ★깊은바닥 = 무조건 -2%. 유예 없음("깊은 바닥은 무조건 -2% 하드컷이야").
        #     (7/12에 -3%+매수우위 -4%연장이 들어가 있었으나 국면 오적용 → 연장 기본 끔 999)
        #   ★눌림(바닥) = -3%. 단 그 순간 호가 매수우위(imb ≥ MF_PULL_HC_EXT_IMB)면 -4%까지 유예
        #     ("눌림목은 하드컷이 3%야 · 매수자가 많을 때는 -4%까지 유예해주는 거고").
        #   그 외 역할 = MF_HARDCUT(-2%) 그대로. imb = 스냅샷 파일(TR 0)·없으면 유예 없음(fail-safe).
        #   롤백: setx MF_PULL_HARDCUT -2 (눌림도 -2%) / setx MF_PULL_HC_EXT_IMB 999 (눌림 유예만 끔)
        # [7/13 친구님 "매수할 때 매도할 때 양봉 음봉 꼬리를 두 개 다에 적용해봐"]
        #   ★매도 유예 판정 = 진입 관문과 대칭. 호가(매수벽 받침) ∧ 꼬리(종가위치) 둘 다여야 유예.
        #   근거: 친구님 "호가는 가짜도 많아서" → 호가만 믿고 안 팔면 허수벽에 속아 더 크게 물린다.
        #   꼬리는 실제 체결된 가격이 만든 것이라 못 속임 → 호가를 꼬리로 교차검증.
        #   (양봉 조건은 22일 백테에서 무용: 종가위치0.6 단독 41.3% vs +양봉 40.5% — 종가위치가 이미 담고 있음)
        #   재료(호가·봉) 없으면 유예 없음 = 판다(fail-safe).
        #   롤백: setx MF_SELL_HOLD_POS 0 (꼬리 안 봄·호가만) / setx MF_STRUCT_HOLD_IMB 999 (구조붕괴 유예 끔)
        def _hold_ok(_code):
            """매도 유예 가능? — 호가 매수우위 ∧ 꼬리(종가위치) 양호. 재료 없으면 False(=컷)."""
            _iv2 = _imb(bc, _code)
            if _iv2 is None or _iv2 < float(os.environ.get("MF_SELL_HOLD_IMB", "1.0")):
                return False, _iv2, None
            _b2 = _bar1m(_code)
            _p2 = _b2.get("pos") if _b2 else None
            if _p2 is None or float(_p2) < float(os.environ.get("MF_SELL_HOLD_POS", "0.6")):
                return False, _iv2, _p2
            return True, _iv2, _p2
        _hc = HARDCUT; _hc_ext = False
        _role_now = str(p.get("role", ""))
        if _role_now == "깊은바닥":
            # 깊은바닥 = 무조건 -2%(친구님). 연장 문턱 999 = 유예 없음.
            _hc = float(os.environ.get("MF_DEEP_HARDCUT", "-2.0") or 0)
            # [7/13 저녁 STOP-B 친구님 "돈 버는 게 우선 · -2%를 줄일 수 있는 방법"]
            #   ★변동성 비례 하드컷 — 낙폭이 깊은 종목은 하루 변동폭 자체가 커서 -2%가 노이즈에 걸린다.
            #     낙폭 -4%  → 손절 -2.0%   (얕게 빠진 놈은 타이트하게)
            #     낙폭 -10% → 손절 -2.6%
            #     낙폭 -24% → 손절 -4.0%   (-24% 빠진 HLB 같은 놈은 하루 5%씩 흔든다)
            #   43일·슬롯3·마감09:20·정배열우선권·건당166만·비용0.35% 실측(자본 500만):
            #     현행(-2% 고정·유예0)        하루 53,012원 · 손절 45% · 승률 45% · 최악의 날 -261,083원
            #     ★유예3분 + 변동성비례        하루 56,615원 · 손절 41% · 승률 50% · 최악의 날 -176,273원
            #   → 돈·손절률·승률·최악의날 넷 다 개선. 최악의 날이 32% 개선된 게 가장 크다.
            #   ⚠️종가 기준 손절(휩쏘 방어)은 재앙이었음(하루 4,934원·최악 1건 -107,279원) — 넣지 말 것.
            #   ⚠️분할진입도 손절률은 36%로 줄지만 절반만 사서 수익도 절반(하루 9,616원) — 넣지 말 것.
            #   롤백: setx MF_DEEP_HARDCUT_VOL NO
            if os.environ.get("MF_DEEP_HARDCUT_VOL", "YES").strip().upper() == "YES":
                _dp = float(p.get("depth", 0) or 0)          # 진입 시점 낙폭(음수)
                if _dp < 0:
                    _hcv = float(os.environ.get("MF_DEEP_HC_VOL_BASE", "-2.0"))   # 낙폭 -4%일 때 손절
                    _hcx = float(os.environ.get("MF_DEEP_HC_VOL_MAX",  "-4.0"))   # 최대 확장 한도
                    _slope = float(os.environ.get("MF_DEEP_HC_VOL_SLOPE", "0.10"))
                    _hc = max(_hcx, min(_hcv, _hcv + (_dp + 4.0) * _slope))
            if _hc < 0 and float(os.environ.get("MF_DEEP_HC_EXT_IMB", "999")) < 900:
                _ok2, _iv2, _p2 = _hold_ok(c)
                if _ok2:
                    _hc = float(os.environ.get("MF_DEEP_HC_EXT", "-4.0") or _hc); _hc_ext = True
        elif _role_now == "바닥":
            # 눌림 = -3% · 매수벽 ∧ 꼬리 둘 다 좋으면 -4%까지 유예(친구님).
            _hc = float(os.environ.get("MF_PULL_HARDCUT", "-3.0") or 0)
            if _hc < 0:
                _ok2, _iv2, _p2 = _hold_ok(c)
                if _ok2:
                    _hc = float(os.environ.get("MF_PULL_HC_EXT", "-4.0") or _hc); _hc_ext = True
        # [7/13 친구님 "구조붕괴 지점에 매수자/매도자 확인을 넣어라 — 이러면 꼬리에 계속 당한다"]
        #   저점 이탈 = 무조건 컷이었음 → 그래서 7/12에 넣은 하드컷의 호가받침 연장(L505)이 발동조차 못했다
        #   (구조붕괴가 -2.5%에서 먼저 잘라서 -3% 하드컷까지 못 감).
        #   ★이제: 저점을 뚫어도 호가 매수벽이 받치면(imb ≥ MF_STRUCT_HOLD_IMB) 컷 유예 = 꼬리(휩쏘)에 안 썰림.
        #   매도벽이 두꺼우면(imb < 문턱) 그대로 컷 = 진짜 붕괴. 호가 없으면 컷(fail-safe·기존 동작 유지).
        #   유예되면 아래 하드컷(-3%·매수우위면 -4%)이 최종 방어선. imb는 스냅샷 파일(TR 0).
        #   롤백: setx MF_STRUCT_HOLD_IMB 999 (=유예 절대 안 함 = 7/12 동작과 완전 동일)
        _struct_hold = False
        if (STRUCT_STOP and _slo > 0 and cur < _slo
                and float(os.environ.get("MF_STRUCT_HOLD_IMB", "1.0")) < 900):
            _struct_hold, _siv, _spos = _hold_ok(c)   # 호가 매수벽 ∧ 꼬리(종가위치) 둘 다여야 유예
            if _struct_hold and c not in _STRUCT_HOLD_SEEN:
                _STRUCT_HOLD_SEEN.add(c)
                _log(f"🛡️ {c} 구조붕괴 유예 — 저점{_slo:,.0f} 이탈했으나 매수벽 받침(호가잔량 {_siv:.2f}) "
                     f"+ 꼬리 되받음(종가위치 {float(_spos):.2f}) · 하드{_hc:g}%가 최종방어")
        # [7/13 친구님 "1번 상승중이면 매도 유예"] 10:20 1차마감 —
        #   호가 매수벽 ∧ 꼬리 되받음(=아직 상승 중)이면 청산 유예. 매 틱 재판정 → 꺾이는 순간 청산.
        #   유예해도 구조붕괴·하드-2%·체결강도되돌림·거울상꼭지는 살아있어 하방은 막힌다.
        #   ⚠️10:20 전량청산은 7/9 '10:20 꼭지 폭포일' 부검 산물 — 유예 시 그 폭포에 재노출 가능.
        #   롤백: setx MF_R1_HOLD_ON NO (=무조건 청산·7/9 동작)
        _r1_hold = False
        if (R1_CLOSE_HM and hm >= R1_CLOSE_HM
                and str(p.get("buy_hm", "") or "") <= R1_ENTRY_END
                and os.environ.get("MF_R1_HOLD_ON", "YES").strip().upper() == "YES"):
            _r1_hold, _r1iv, _r1pos = _hold_ok(c)
            if _r1_hold and c not in _R1_HOLD_SEEN:
                _R1_HOLD_SEEN.add(c)
                _log(f"🛡️ {c} 1차마감({R1_CLOSE_HM}) 유예 — 아직 상승 중"
                     f"(호가잔량 {_r1iv:.2f} + 종가위치 {float(_r1pos):.2f}) · 꺾이면 즉시 청산")
        # [7/13 친구님 "거울상 적용도 해줘"] ★꼭지 매도 = 진입 신호의 정확한 거울상.
        #   진입: 종가위치 ≥0.6(밑에서 받아 올림) ∧ 호가 매수우위  →  산다
        #   꼭지: 종가위치 ≤0.4(올라갔다 매도벽에 밀림=위꼬리) ∧ 호가 매도우위  →  판다
        #   ★수익 중일 때만(cur > buy) — 손실 구간은 구조붕괴/하드컷 담당(이중 컷 방지).
        #   진입 후 GRACE분 유예(진입 직후 봉 하나로 즉시 청산되는 오작동 방지).
        #   ⚠️미검증 — 과거 호가 데이터가 없어 백테 불가. 오늘 기록기가 실측 수집.
        #   롤백: setx MF_TOP_SELL_ON NO
        _top_sell = ""
        if (os.environ.get("MF_TOP_SELL_ON", "YES").strip().upper() == "YES"
                and buy > 0 and cur > buy
                and _hm_min(hm) - _hm_min(p.get("buy_hm", "")) >= float(os.environ.get("MF_TOP_GRACE_MIN", "5"))):
            # ★[7/14 친구님 "깊은바닥 그대로 이식하고 바닥 잡는 것만 1분봉으로 · 꼭지점 매도 방법을 이식해"]
            #   꼭지 판정 = 3분봉 꼬리. 1분봉 꼬리는 너무 자주 떠서 꼭지가 아닌데도 팔았다.
            #   207종목×43일 1분봉 실측(엔진 실제 프레임): 꼭지매도 건당 1분봉 +2.24% → 3분봉 +2.88%,
            #   하루 -16,275원 → -1,237원(+15,038). 진입(바닥확인)은 1분봉 그대로 둔다.
            #   3분봉 결측이면 꼭지매도만 쉬고 다른 매도 규칙이 받는다. 롤백: setx MF_TOP_SELL_BAR 1
            # ★[7/14] _bar3m() → _bar3m_ready() : 진행 중 봉이 아니라 '거의 완성된' 3분봉으로만 판정.
            #   진행중 봉으로 팔던 옛 동작은 하루 2,215원 · 완성봉 판정은 4,106원(43일 1분봉 실측).
            _tb = _bar1m(c) if os.environ.get("MF_TOP_SELL_BAR", "3").strip() == "1" else _bar3m_ready(c)
            _tpos = _tb.get("pos") if _tb else None
            _tiv = _imb(bc, c)
            # [7/13 저녁 친구님 "호가 빼고 꼬리만 봐"] ★꼭지매도에서 호가 조건 제거.
            #   ①호가는 검증에서 무효였다 — 7/13 기록기 31건: 진입 순간 호가 매수우위(≥1.0) 21건 중
            #     81%가 저점 재이탈(매도우위 5건은 60%). 진입 관문에선 이미 뺐는데(MF_DEEP_ENTRY_IMB=0)
            #     매도엔 그대로 남아 있었다.
            #   ②★더 위험: `_tiv is not None` 때문에 호가가 결측이면 꼭지매도가 아예 안 됐다.
            #     꼭지매도는 하루 수익의 전부다(빼면 하루 32,155원 → 350원으로 붕괴). 못 팔면 끝장.
            #   ③꼬리(종가위치)는 실제 체결된 가격이 만든 것이라 못 속인다. 호가는 허수가 많다.
            #   ④43일 시뮬은 꼬리만 보고 냈다(하루 80,216원) — 호가 조건을 빼야 시뮬과 일치한다.
            #   MF_TOP_SELL_IMB >= 900 이면 호가 조건 자체를 건너뛴다(꼬리만).
            #   롤백: setx MF_TOP_SELL_IMB 1.0  (=호가 매도우위도 함께 요구)
            _timb_thr = float(os.environ.get("MF_TOP_SELL_IMB", "1.0"))
            _timb_ok = (_timb_thr >= 900) or (_tiv is not None and _tiv < _timb_thr)
            if (_tpos is not None and float(_tpos) <= float(os.environ.get("MF_TOP_SELL_POS", "0.4"))
                    and _timb_ok and _wick_strong(c)):
                # ★[7/14 친구님] 위꼬리가 떴어도 직전 3분간 밑에서 계속 받아올리는 중이면 안 판다.
                if c not in _WICK_HOLD_SEEN:
                    _WICK_HOLD_SEEN.add(c)
                    _log(f"🤚 {c} 꼭지매도 보류 — 위꼬리(종가위치 {float(_tpos):.2f})지만"
                         f" 직전 {os.environ.get('MF_WICK_HOLD_N','3')}분 꼬리세가 강함(밑에서 받아올리는 중)")
            elif (_tpos is not None and float(_tpos) <= float(os.environ.get("MF_TOP_SELL_POS", "0.4"))
                    and _timb_ok):
                _top_sell = (f"꼭지(위꼬리 종가위치{float(_tpos):.2f}"
                             + (f"·매도벽 호가잔량{_tiv:.2f})" if (_timb_thr < 900 and _tiv is not None)
                                else (f"·호가{_tiv:.2f} 참고)" if _tiv is not None else ")")))
        if (R1_CLOSE_HM and hm >= R1_CLOSE_HM
                and str(p.get("buy_hm", "") or "") <= R1_ENTRY_END
                and not _r1_hold):                                            # ★1차마감: 10:00까지 매수분 10:20 청산 — 단 상승 중이면 유예
            sell = f"1차마감({R1_CLOSE_HM[:2]}:{R1_CLOSE_HM[2:]})"          #   [7/9 2차창] 10:00 이후 매수(2차 깊은바닥·눌림)는 매도사다리+EOD가 관리. buy_hm 없으면 1차 간주(fail-safe)
        elif STRUCT_STOP and _slo > 0 and cur < _slo and not _struct_hold:   # ★구조붕괴: 진입 저점 이탈 + 매도벽 두꺼움 = 바닥 실패 → 컷
            sell = f"구조붕괴(저점{_slo:,.0f}이탈)"
        elif (DEEP_DISASTER < 0 and _role_now == "깊은바닥" and buy > 0
              and (cur / buy - 1) * 100 <= DEEP_DISASTER):
            # ★[7/14] 재난 손절 — 손절 유예(12분)를 무시하고 즉시 자른다. 유예의 하방 봉쇄선.
            #   유예는 '진입 직후 흔들림'을 견디려는 것이지 '진짜 폭락'을 견디려는 게 아니다.
            sell = f"재난손절{DEEP_DISASTER:g}%(유예무시)"
        elif (_hc < 0 and buy > 0 and (cur / buy - 1) * 100 <= _hc
              # [7/13 저녁 STOP-B] ★손절 유예 — 진입 후 이 시간 동안은 하드컷을 걸지 않는다.
              #   진입 직후의 흔들림(노이즈)에 털리던 것을 막는다. 걸릴 놈은 3분 뒤에도 걸리고,
              #   살아날 놈은 살아난다. 실측: 하루 53,012 → 58,513원 · 승률 45 → 48%.
              #   ★구조붕괴(저점 이탈)와 10:20 청산은 유예 없음 — 진짜 붕괴는 즉시 자른다(위 가지가 선순위).
              #   롤백: setx MF_DEEP_STOP_GRACE_MIN 0
              and _hm_min(hm) - _hm_min(p.get("buy_hm", "")) >= float(
                  os.environ.get("MF_DEEP_STOP_GRACE_MIN", "3") or 0)):   # ★하드컷: 최대손실 캡
            sell = f"하드{_hc:g}%" + ("(호가받침연장)" if _hc_ext else "")
        elif (che is not None and float(p.get("peak_che", 0) or 0) >= RECOIL_MINPEAK
              and che <= float(p.get("peak_che", 0) or 0)
                        - (RECOIL_PROFIT_PT if (buy > 0 and (cur / buy - 1) * 100 >= RECOIL_PROFIT_PCT) else RECOIL_PT)
              and _hm_min(hm) - _hm_min(p.get("buy_hm", "")) >= RECOIL_GRACE_MIN):
            # ★che 되돌림: 고점 대비 꺾임 → 조기매도. [7/10] 진입 GRACE분내 유예(buy_hm 없으면 0=유예없음 fail-open)
            #   ·이익 +PROFIT_PCT%↑면 눈금 -PROFIT_PT로 완화(V초입 숨고르기 휩쏘 방지·구조붕괴/하드-2%는 그대로 선순위)
            sell = f"che되돌림(고점{float(p['peak_che']):.0f}→{che:.0f})"
        elif _top_sell:
            # ★[7/13] 거울상 꼭지 매도 — 위꼬리(올라갔다 밀림) + 매도벽 = 매수세 소진 → 실현
            sell = _top_sell
        elif (_dop > 0 and buy > 0 and cur > buy
              and cur >= _dop * (1 - float(os.environ.get("MF_OPEN_RESIST_BUF", "0.5")) / 100.0)):
            # ★[7/11] 시가저항 실현 — 낮 매수 깊은바닥이 수익 중 당일 시가(저항선)에 접근하면 실현
            #   [7/13 친구님 "5번 삭제 — 위로 갈 수도 있잖아"] setx MF_OPEN_RESIST NO 로 끔(_dop=0 → 이 가지 비활성)
            sell = f"시가저항({_dop:,.0f} 접근 실현)"
        elif (DEEP_R1_SYMEXIT and str(p.get("role", "")) == "깊은바닥"
              and str(p.get("buy_hm", "") or "") <= R1_ENTRY_END):
            # ★[7/9 밤 친구님 승인 대칭매도] 아침 1차 깊은바닥 보유분 — vol_exit(체결강도 절대100 눈금)이 바닥 보유분을
            #   1~3분 휩쏘(에스엠 3왕복 -1.18%p 실증) → '산 이유 소멸'로 교체: 체결강도가 당일저점+PT 아래로 복귀시만 연성매도.
            #   구조붕괴/하드-2%/che되돌림/10:20 전량청산은 위에서 그대로(안전장치 유지). 롤백: setx MF_DEEP_R1_SYMEXIT NO
            # [7/10 새벽 가격만 진입(NOCHE) 모드] 반등소멸 판정 제외 — 진입이 체결강도 무관이라 진입 직후 체결강도가
            #   저점권이면 오작동 즉시매도가 됨(10일 백테 V3 = 반등소멸 없이 +50.6%p 검증). NOCHE=NO 롤백시에만 반등소멸 사용.
            if not DEEP_R1_NOCHE:
                _cm = _che_min_today(c)
                if che is not None and _cm is not None and che <= _cm + SYMEXIT_PT:
                    sell = f"반등소멸(체결{che:.0f}≤저점{_cm:.0f}+{SYMEXIT_PT:g})"
        # [7/13 장중 친구님 "근본적으로 뺑뺑이 못 하게 해야 되는 거 아니니" → "둘 다 넣어"]
        #   ★깊은바닥은 vol_exit(연성매도) 자체를 끈다. 5분 유예 같은 임시방편이 아니라 경로를 제거.
        #   실측 사고: 10:06:19 BUY 178320 → 10:06:29 SELL(+0.4% "매도우위+5일선이탈") = 10초 뺑뺑이.
        #             200710도 동일(10초). 기존 유예는 '큰손 순매수(+)'일 때만 걸려 큰손 매도 종목엔 무력.
        #   ★근거: vol_exit은 백테에 아예 없던 경로다. 백테(하루 +1,675원)는 꼭지매도·구조붕괴·하드-2%
        #     ·10:20청산만으로 계산했다 → 실전에만 붙어 있던 vol_exit이 백테-실전 괴리의 원인.
        #     깊은바닥 매도는 이미 4중(구조붕괴·하드-2%·꼭지매도·10:20)이라 중복이다.
        #   ⚠️그 외 역할(눌림·MA전환 등)은 vol_exit 그대로 유지(매도 통일정책 존중).
        #   롤백: setx MF_VE_OFF_DEEP NO (=깊은바닥도 vol_exit 다시 사용)
        elif (VE is not None
              and not (_role_now == "깊은바닥"
                       and os.environ.get("MF_VE_OFF_DEEP", "YES").strip().upper() == "YES")):
            try:
                s, _rr = VE.decide(c, buy, peak, cur, ma20_hard=True, che=che)
                if s:
                    # [7/9 친구님 "큰손이 담고 있으면 체결량보다 우위"] 큰손 순매수 유지(+)면 연성매도(vol_exit
                    #   매도우위+5선이탈 등) 유예 — 10초 뺑뺑이 방지. 구조붕괴/하드-2%/che되돌림/EOD는 위에서 그대로 발동.
                    #   판에 없음/읽기실패(None)·0이하 = 유예 안함(fail-safe). 롤백: setx MF_BIG_HOLD_EXIT NO.
                    _bb = _board_big(c) if BIG_HOLD_EXIT else None
                    if _bb is not None and _bb > 0:
                        if c not in _DEFER_LOGGED:
                            _DEFER_LOGGED.add(c)
                            _log(f"⏸ {c} 매도유예({_rr}) — 큰손 +{_bb/100:.0f}억 유지중(던지면 매도 재개)")
                        s = None
                    if s:
                        sell = _rr or "vol_exit"   # ★사유 문자열 기록(예전 =s(True) 버그 → 로그에 'True'로 찍힘)
            except Exception:
                pass
        if not sell and hm >= EOD_HM:
            sell = "EOD청산"
        if sell:
            if _order(bc, c, int(p.get("qty", 0) or 0), "SELL", sell):
                p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = sell; p["sell_hm"] = hm; p["sell_ts"] = time.time()
                changed = True
                _log(f"{mode} SELL {c} @{cur:,.0f} ({(cur/buy-1)*100:+.1f}%) {sell}")
                if LIVE:
                    try:
                        import rt_registry as _RT; _RT.remove(c)
                    except Exception:
                        pass
    return changed


_MA60 = None
_VOL20 = None
_MABASE = None
_REVAL = None
_JB = None
_RNG20 = None   # [7/10] 20일 평균 일중폭%(변동성 차등 등재용)
_GAPTUK = None  # [7/10 밤] 갑툭이 예비(전일 갑툭튀∧수렴 → 익일 아침 눌림 진입 후보)
_MA20POS = None # [7/12] 전일종가 vs 20일선 위치%(망한무리 차단용)
def _ma60_map():
    """[2026-07-07 통합대장②/눌림B/MA전환바닥] 일60선(ma)+20일평균거래량(vol20)+MA전환신호(mabase) 코드별 맵. 일1회 파일캐시(돈흐름_ma60.json). 조회0(eod_daily_bars 파일)."""
    global _MA60, _VOL20, _MABASE, _REVAL, _JB, _RNG20, _GAPTUK, _MA20POS
    if _MA60 is not None:
        return _MA60
    today = datetime.now().strftime("%Y%m%d")
    cache = Path(r"C:\stock_bot\data\돈흐름_ma60.json")
    try:
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("date") == today and "gaptuk" in d and "ma20pos" in d:   # [7/10 밤] gaptuk / [7/12] ma20pos 없는 구캐시는 재계산
                _MA60 = d.get("ma", {}); _VOL20 = d.get("vol20", {}); _MABASE = d.get("mabase", {})
                _REVAL = d.get("reval", {}); _JB = d.get("jb", {}); _RNG20 = d.get("rng20", {})
                _GAPTUK = d.get("gaptuk", {}); _MA20POS = d.get("ma20pos", {}); return _MA60
    except Exception:
        pass
    ma = {}; vol20 = {}; mabase = {}; reval = {}; jb = {}; rng20 = {}; gaptuk = {}; ma20pos = {}
    try:
        import csv as _csv, io as _io
        closes = {}; vols = {}; hilos = {}
        with _io.open(r"C:\stock_bot\data\eod_daily_bars.csv", encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                c = str(r["code"]).zfill(6)
                try:
                    closes.setdefault(c, []).append((r["date"], float(r["close"])))
                    vols.setdefault(c, []).append((r["date"], float(r.get("volume") or 0)))
                    hilos.setdefault(c, []).append((r["date"], float(r.get("high") or 0), float(r.get("low") or 0)))
                except Exception:
                    pass
        for c, lst in closes.items():
            lst.sort()
            cl = [x[1] for x in lst]; L = len(cl)
            if L >= 20:
                _m20v = sum(cl[-20:]) / 20.0
                if _m20v > 0:
                    ma20pos[c] = round((cl[-1] / _m20v - 1) * 100, 2)   # [7/12] 전일종가 vs 20일선 위치%
            if L >= 60:
                ma[c] = round(sum(cl[-60:]) / 60.0, 2)
                # [7/10 친구님 "역배열은 바닥만 예외 → 5·20선이 60선 아래면 매수금지 테스트"(RFHIC 실증)] —
                #   백테(8일): 깊은바닥은 60선아래가 오히려 +2.3%p(예외 정당) / 눌림은 이 정의로 차단.
                #   정의 확장: 엄격 역배열(5<20<60) → 5·20선 모두 60선 아래(데드캣 교차까지 커버). 60일 미만 신규주 통과.
                _m5 = sum(cl[-5:]) / 5.0; _m20 = sum(cl[-20:]) / 20.0
                if _m5 < ma[c] and _m20 < ma[c]:
                    reval[c] = True
                if _m5 > _m20 > ma[c]:      # [7/10 추세 주종] 정배열 strict(5>20>60) — 모멘텀 그림자용
                    jb[c] = True
            if L >= 65:   # [MA전환 바닥·백테검증 +0.8%/3일] 수렴(≤4%)→정배열전환(fresh)→60선우상향
                m5 = sum(cl[L-5:L]) / 5; m20 = sum(cl[L-20:L]) / 20; m60 = sum(cl[L-60:L]) / 60
                m60p = sum(cl[L-65:L-5]) / 60                                   # 5일 전 60선(우상향 판정)
                m5b = sum(cl[L-8:L-3]) / 5; m20b = sum(cl[L-23:L-3]) / 20; m60b = sum(cl[L-63:L-3]) / 60  # 3일 전(fresh)
                if (m60 > 0 and m5 > m20 > m60 and (max(m5, m20, m60) - min(m5, m20, m60)) / m60 <= 0.04
                        and m60 > m60p and not (m5b > m20b > m60b)):
                    mabase[c] = True
        for c, lst in vols.items():
            lst.sort()
            vv = [x[1] for x in lst[-20:] if x[1] > 0]
            if len(vv) >= 10:
                vol20[c] = round(sum(vv) / len(vv), 1)
        for c, lst in hilos.items():   # [7/10 변동성 차등 등재] 20일 평균 일중폭%
            lst.sort()
            rr = [(h / l - 1) * 100 for _, h, l in lst[-20:] if l > 0 and h >= l]
            if len(rr) >= 10:
                rng20[c] = round(sum(rr) / len(rr), 2)
        # [7/10 밤 친구님 "갑툭이 MA수렴하고 같이"] 전일 = 갑툭튀∧수렴 → 익일(오늘) 아침 눌림 진입 예비군
        for c, lst in closes.items():
            cl = [x[1] for x in lst]; L = len(cl)
            hl = hilos.get(c) or []; vv = vols.get(c) or []
            if L < 66 or len(hl) != L or len(vv) != L:
                continue
            if cl[-2] <= 0 or not (3.0 <= (cl[-1] / cl[-2] - 1) * 100 < 6.0):   # 전일 완만 첫돌파 +3~6%
                continue
            if cl[-1] < 20000 or (vv[-1][1] if len(vv) == L else 0) * cl[-1] < 2e9:
                continue                                                        # 백테 유니버스: 2만+·돌파일 대금 20억+(잡주 차단)
            _bh = max(x[1] for x in hl[L-16:L-1]); _bl = min(x[2] for x in hl[L-16:L-1])
            if _bl <= 0 or not (0.06 <= _bh / _bl - 1 <= 0.18):                 # 15일 베이스 6~18%
                continue
            if any(cl[j] / cl[j-1] - 1 >= 0.10 for j in range(L-15, L-1) if cl[j-1] > 0):
                continue                                                        # 베이스 조용(일일 +10%↑ 없음)
            _bvz = [x[1] for x in vv[L-16:L-1]]
            _bva = sum(_bvz) / len(_bvz) if _bvz else 0
            if not (_bva > 0 and vv[-1][1] >= 1.5 * _bva):                      # 돌파일 거래량 1.5×
                continue
            g5 = sum(cl[L-6:L-1]) / 5; g20 = sum(cl[L-21:L-1]) / 20; g60 = sum(cl[L-61:L-1]) / 60
            if g60 <= 0 or (max(g5, g20, g60) - min(g5, g20, g60)) / g60 > 0.04:   # 돌파 전일 기준 수렴
                continue
            gaptuk[c] = True
    except Exception:
        pass
    try:
        cache.write_text(json.dumps({"date": today, "ma": ma, "vol20": vol20, "mabase": mabase, "reval": reval, "jb": jb, "rng20": rng20, "gaptuk": gaptuk, "ma20pos": ma20pos}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    _MA60 = ma; _VOL20 = vol20; _MABASE = mabase; _REVAL = reval; _JB = jb; _RNG20 = rng20; _GAPTUK = gaptuk; _MA20POS = ma20pos
    return _MA60


def _ma20pos_map():
    """[7/12 망한무리 차단] 전일종가 vs 20일선 위치% 맵(_ma60_map과 동일 캐시)."""
    if _MA20POS is None:
        _ma60_map()
    return _MA20POS or {}


def _vol20_map():
    """20일 평균 일거래량 맵(_ma60_map과 동일 캐시)."""
    if _VOL20 is None:
        _ma60_map()
    return _VOL20 or {}


def _reval_map():
    """[7/10] 일봉 역배열/60선아래 코드 맵(_ma60_map과 동일 캐시) — 눌림 차단용."""
    if _REVAL is None:
        _ma60_map()
    return _REVAL or {}


def _rng20_map():
    """[7/10] 20일 평균 일중폭% 맵(_ma60_map과 동일 캐시) — 변동성 차등 등재용."""
    if _RNG20 is None:
        _ma60_map()
    return _RNG20 or {}


def _jb_map():
    """[7/10 추세 주종] 일봉 정배열 strict(5>20>60) 코드 맵(동일 캐시) — 모멘텀 그림자용."""
    if _JB is None:
        _ma60_map()
    return _JB or {}


def _gaptuk_map():
    """[7/10 밤 갑툭이] 전일 갑툭튀∧수렴 예비군 코드 맵(_ma60_map과 동일 캐시)."""
    if _GAPTUK is None:
        _ma60_map()
    return _GAPTUK or {}
def _mabase_map():
    """[MA전환 바닥] 수렴→정배열전환→60선우상향 코드 맵(_ma60_map과 동일 캐시)."""
    if _MABASE is None:
        _ma60_map()
    return _MABASE or {}


def _entries(bc, pos, hm, today, mode):
    """진입 (🟢 이기는중 상위 → 시장가). 매번 캐시된 보드 재로드 → 백그라운드가 갱신하면 즉시 반영.
    pos in-place 갱신. 변경 있으면 True."""
    if hm > ENTRY_END:
        return False
    _r2 = bool(R1_CLOSE_HM) and hm > R1_ENTRY_END   # [7/9 친구님 "2차 창도 열어"] 2차 창(10:00~ENTRY_END) — 깊은바닥만 허용
    if _r2 and not (R2_DEEP and DEEP_ON):
        return False
    held = sum(1 for p in pos.values() if isinstance(p, dict) and p.get("date") == today and p.get("status") == "HOLDING")
    if held >= MAX_POS:
        return False
    # 전역 상한
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            return False
    except Exception:
        pass
    # ★[7/11 친구님 "전에 큰돈이 무한정 빠져나간 적 있어 — 딱 500만 한도 내에서만"] 일일 손실 서킷브레이커.
    #   원금 노출 500만은 풀 게이트+전역벽(동시 보유원가)이 지키지만, 회전 체제는 누적 '손실'에 벽이 없었음
    #   (-2%컷 반복 시 이론상 계속 누수) → 오늘 실현손실이 한도(기본 15만=원금의 3%)에 닿으면 당일 신규매수
    #   전면 중단. 매도/보유관리는 계속 돈다(탈출은 항상 가능). 롤백: setx MF_DAILY_LOSS_LIMIT_KRW 0 (0=끔)
    _loss_lim = float(os.environ.get("MF_DAILY_LOSS_LIMIT_KRW", "150000") or 0)
    if _loss_lim > 0:
        _pnl_today = sum((float(p.get("sell_price", 0) or 0) - float(p.get("buy_price", 0) or 0)) * float(p.get("qty", 0) or 0)
                         for p in pos.values()
                         if isinstance(p, dict) and p.get("date") == today and p.get("status") == "DONE"
                         and float(p.get("sell_price", 0) or 0) > 0)
        if _pnl_today <= -_loss_lim:
            if time.time() - float(_DEEP_PROBE.get("losslock_log", 0) or 0) >= 600:
                _DEEP_PROBE["losslock_log"] = time.time()
                _log(f"🛑 일일 손실한도 도달(실현 {_pnl_today:,.0f}원 ≤ -{_loss_lim:,.0f}) — 당일 신규매수 중단(매도는 계속)")
            return False
    # [7/8 친구님 정정] 원금 200만 회전 — 게이트 = "지금 투입 중인 금액"(보유분 매수금 합). 팔면 자동으로 한도 회복.
    #   _budget 장부는 하루 회전 누적(보고용·게이트 아님).
    _invested = sum(float(p.get("buy_price", 0) or 0) * float(p.get("qty", 0) or 0) for p in pos.values()
                    if isinstance(p, dict) and p.get("date") == today and p.get("status") == "HOLDING")
    # [7/11 친구님 "500만 재편 — 깊은바닥 100만×4종목·눌림/MA전환 100만"] 역할별 회전 풀 분리
    #   깊은바닥 풀 400만(건당 100만=동시 최대 4종목·팔면 회복) / 그 외 풀 100만(건당 20만 유지).
    #   전체 상한 = MF_DAILY_BUDGET_KRW(500만)·전역 안전망 = SAFEPLUS_GLOBAL_BUDGET_KRW(500만).
    #   롤백: setx MF_DEEP_CAP_KRW 200000 · MF_DEEP_POOL_KRW 2000000 · MF_OTHER_POOL_KRW 2000000 · 예산 200만 복귀
    _invested_deep = sum(float(p.get("buy_price", 0) or 0) * float(p.get("qty", 0) or 0) for p in pos.values()
                         if isinstance(p, dict) and p.get("date") == today and p.get("status") == "HOLDING"
                         and str(p.get("role", "")) == "깊은바닥")
    _bud = pos.get("_budget") if isinstance(pos.get("_budget"), dict) else None
    if not _bud or _bud.get("date") != today:
        _bud = {"date": today, "spent": 0.0}
        pos["_budget"] = _bud
    board = _jload(BOARD)
    rows = board.get("rows", []) if isinstance(board, dict) else []
    excl = {str(k).zfill(6) for k, v in _jload(RT_OPEN).items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
    che_st = _jload(CHE_STATE)   # 보드가 누적한 che 저점(min)/표본(n) — 재진입 저점반등 판정용
    ma60_map = _ma60_map() if MA60_GATE else {}   # [통합대장②] 일60선 맵(상승진입 추세게이트용)
    vol20_map = _vol20_map() if VOL_MULT_GATE else {}   # [눌림B] 20일평균거래량 맵(저점반등 거래량배수용)
    mabase_map = _mabase_map() if MABASE_GATE else {}   # [MA전환바닥] 수렴→정배열전환→60선우상향 코드
    gaptuk_map = _gaptuk_map() if GAPTUK_GATE else {}   # [7/10 밤 갑툭이] 전일 갑툭튀∧수렴 예비군
    # [2026-07-07 밤] 선별기 순위 순서대로 후보(🟢 매수세). INCLUDE_RISK면 🟡(레짐위험)도(기본 NO=방어).
    greens = [r for r in rows if str(r.get("grade", "")).startswith("🟢")
              or (INCLUDE_RISK and str(r.get("grade", "")).startswith("🟡"))]
    # ★[2026-07-09 친구님 "1등 목표"] 깊은바닥 후보 — 등급 무관 별도 입구(대장주 중 전일比 -5%↓ 저점 찍은 놈).
    #   보드 row 있으면 수급 필드 승계(돈유입 폴백용)·순서 = "돈이 먼저 몰리는 것"(보드 큰손합 내림차순)·깊은바닥이 🟢보다 먼저.
    cands = greens
    _deep_new = [False]   # 새 등재 발생 → 포지션파일 저장 트리거(등재 로그 하루 1회 영속)
    if DEEP_ON:
        _pcm = _prev_close_map()
        _pvm = _prev_val_map() if DEEP_PVAL_MIN > 0 else {}   # ★[7/15] 어제 거래대금 필터용
        _row_by = {str(_r.get("code", "")).zfill(6): _r for _r in rows}
        _deep = []
        for _dc in _deep_universe(board):      # [7/12] 대장주66 → 선별기 유니버스 전체(정원 200)
            _dpc = _pcm.get(_dc)
            _dcs = che_st.get(_dc) if isinstance(che_st.get(_dc), dict) else {}
            _dlo = float(_dcs.get("lo", 0) or 0)
            if not _dpc or _dpc <= 0 or _dlo <= 0:
                continue
            # ★[7/15 급락주 특정] 잡주 제거(전일종가 하한) + 어제 거래대금 구간
            if DEEP_PX_FLOOR > 0 and _dpc < DEEP_PX_FLOOR:
                continue
            if DEEP_PVAL_MIN > 0:
                _dpv = _pvm.get(_dc, 0.0)
                if not (DEEP_PVAL_MIN <= _dpv <= DEEP_PVAL_MAX):
                    continue
            _dth = DEEP_DROP   # [7/10 변동성 차등] 저변동(20일평균폭<4%)은 -4%가 얕음 → -6% 요구(고변동은 -4% 유지)
            if _rng20_map().get(_dc, 99.0) < DEEP_LOWVOL_RNG:
                _dth = min(DEEP_DROP, DEEP_DROP_LOWVOL)
            if (_dlo / _dpc - 1) * 100 > _dth:
                continue
            _br = _row_by.get(_dc) or {}
            # ★[7/15 친구님 "갭하락 우선권이다"] 등재 시점에 갭 계산 — 시가(che_state 'o')가 전일종가 대비 몇 %인가.
            #   갭하락(시가 전일比 GAP_FREE%↓) = 정렬 맨 앞 우선권. 시가 미기록(_dob=0)이면 갭없음 취급(우선권 없음).
            _dob = float(_dcs.get("o", 0) or 0)
            _dgap = ((_dob / _dpc - 1) * 100) if _dob > 0 else 0.0
            _gapdown = _dob > 0 and _dgap <= float(os.environ.get("MF_DEEP_GAP_FREE", "-3"))
            _deep.append({"code": _dc, "grade": "🕳깊은바닥", "_deep": True,
                          "big": _br.get("big"), "chg": _br.get("chg"), "inst": _br.get("inst"),
                          "frgn": _br.get("frgn"), "prog": _br.get("prog"), "indiv": _br.get("indiv"),
                          "acc10": bool(_br.get("acc10")),   # [7/11 🤝] 외인&프로 10일 동반매집(보드 계산 승계)
                          "gap": round(_dgap, 2), "gapdown": bool(_gapdown),   # ★[7/15] 갭하락 우선권용
                          "depth": round((_dlo / _dpc - 1) * 100, 2)})   # [7/11] 당일저점 전일比 깊이(%·음수)
            if _dc not in _DEEP_SEEN:
                _DEEP_SEEN.add(_dc)
                # 등재 로그는 하루 1회 — 1분 태스크가 새 프로세스라 메모리셋만으론 매분 반복(14:06 실증) → 포지션파일에 영속
                _dsn = pos.get("_deep_seen") if isinstance(pos.get("_deep_seen"), dict) else {}
                if _dsn.get("date") != today:
                    _dsn = {"date": today, "codes": []}
                if _dc not in (_dsn.get("codes") or []):
                    _dsn.setdefault("codes", []).append(_dc)
                    pos["_deep_seen"] = _dsn
                    _deep_new[0] = True
                    _log(f"🕳 깊은바닥 등재 {_dc} — 당일저점 {_dlo:,.0f}(전일比 {(_dlo/_dpc-1)*100:+.1f}%) · 저점 매수세+돈유입 감시 시작"
                         + (" 🤝동반매집(우선)" if _br.get("acc10") else ""))
                    # [7/10 장중 친구님 "돈유입 확인 중요 — 지금 배선해"] 등재 순간 즉시 수급 1발(하루 종목당 1회) —
                    #   저점 시점 수급 기준점 확보 + smart_money 60s캐시 웜업 → 턴 도달시 최신치 즉시판정(45초 대기 생략).
                    #   비용 ~2TR/등재(하루 ~10건). 실패 무해. _DEEP_PROBE는 건드리지 않음(진입검사 첫 조회 스로틀 안 걸리게).
                    try:
                        import smart_money as _SMB
                        _bv = _SMB.probe(bc, _dc, _cur(bc, _dc) or _dlo)
                        _log(f"🕳 {_dc} 등재시점 수급(기관/외인/프로/개인·백만원): {list(_bv[:4])}")
                    except Exception:
                        pass
        _rgm = _rng20_map()   # [7/10 변동성 차등] 등재 경합 = 고변동 우선(모든 깊이서 수익·승률 최고) → 동률이면 큰손합
        # [7/11 🤝 진입가점 — 친구님 "진입 관문에도 가점"] 🤝(외인&프로 10일 동반매집)를 경합 맨 앞에.
        #   근거: 매매기 프레임 백테(217종목×100일) — 깊은바닥급(-4%↓) 저점→종가 반등 🤝 +4.45% vs 일반 +3.65%(+0.80%p)·
        #   눌림급 +1.00%p. 상위3 선택 시뮬 🤝우선 +5.46% vs 고변동우선 +5.44% = 손해없음 보증(🤝 희소 7.9%라 없는 날은 현행 그대로).
        #   관문 문턱(등재깊이·가격턴·돈유입)은 무변경 — 순서 가점만. 롤백: setx MF_ACCUM10_ENTRY NO
        # [7/11 친구님 "깊게 떨어지는 놈에게 우선권"] 등재 경합 = 🤝동반매집 → ★깊이(깊은 순) → 고변동 → 큰손합.
        #   근거(1개월 3분봉): 깊을수록 회생·성적 좋음(-5~-7% +0.33% < -7~-10% +0.52% < -10%↓ +1.18%·회복 72%).
        #   롤백: setx MF_DEEP_DEPTH_SORT NO (깊이 우선권만 끔·고변동 우선 복귀)
        _acc_on = os.environ.get("MF_ACCUM10_ENTRY", "YES").strip().upper() == "YES"
        _depth_on = os.environ.get("MF_DEEP_DEPTH_SORT", "YES").strip().upper() == "YES"
        # [7/13 저녁 친구님 "정배열에 종목이 없을 때는 역배열에서 골라 사는 건 어떨까?"]
        #   ★역배열을 '차단'하지 말고 '우선순위 뒤로' 밀자 — 슬롯이 남을 때만 역배열이 들어온다.
        #   43일·슬롯3·건당166만·비용0.35%·마감09:20 실측:
        #      정배열만(역배열 차단)          하루 46,531원 · 승률 44% · 손절 44% · 부트스트랩 1등 12.0%
        #      ★역배열 허용 + 정배열 우선권    하루 56,246원 · 승률 47% · 손절 41% · 부트스트랩 1등 81.4%
        #      역배열 허용 + 우선권 없음(시간순) 하루 11,746원  ← ★우선권이 없으면 정반대로 재앙
        #   왜: 역배열이 먼저 와서 슬롯을 차지하면 나중에 오는 정배열을 못 산다.
        #       우선권을 주면 정배열이 슬롯을 먼저 갖고, 남는 자리만 역배열이 채운다(실측 역배열 비중 11%).
        #   역배열 = 일봉 5일선·20일선이 모두 60일선 아래. 60일 미만 신규주는 맵에 없어 정배열 취급.
        #   짝: MF_DEEP_REV_BLOCK=NO 로 하드 차단은 끔(차단보다 우선권이 우월).
        #   롤백: setx MF_DEEP_REV_PRIORITY NO  (우선권 끔 = 기존 깊이 우선)
        _rev_prio = os.environ.get("MF_DEEP_REV_PRIORITY", "YES").strip().upper() == "YES"
        _revm = _reval_map() if _rev_prio else {}

        # ★[7/15 친구님 "갭하락 우선권이다" + "정배열 → 깊이 → 고변동 → 동반매집 → 큰손"]
        #   최종 순서 = ★갭하락 → 정배열 → 깊이 → 고변동 → 🤝동반매집 → 큰손.
        #   갭하락(시가 전일比 -3%↓)을 맨 앞으로 = "무조건 잡고" 지시의 정렬판(성공 86~92% 실측·희소해 평소 미발동).
        #   기존 스위치(_rev_prio/_depth_on/_acc_on) 그대로 살림. 롤백: setx MF_DEEP_GAP_PRIORITY NO
        _gap_prio = os.environ.get("MF_DEEP_GAP_PRIORITY", "YES").strip().upper() == "YES"

        def _deep_key(x):
            k = []
            if _gap_prio:
                k.append(0 if x.get("gapdown") else 1)        # 0. ★갭하락 먼저(우선권)
            if _rev_prio:
                k.append(1 if _revm.get(x["code"]) else 0)    # 1. 정배열(0) 먼저 · 역배열(1) 뒤로
            if _depth_on:
                k.append(float(x.get("depth") or 0))          # 2. ★깊이 — 음수 깊을수록 작음 = 먼저
            k.append(-(float(_rgm.get(x["code"], 0) or 0)))   # 3. 고변동 우선(7/10 검증)
            if _acc_on:
                k.append(0 if x.get("acc10") else 1)          # 4. 🤝동반매집
            k.append(-(float(x.get("big") or 0)))             # 5. 큰손합
            return tuple(k)

        _deep.sort(key=_deep_key)
        _dset = {d["code"] for d in _deep}
        cands = _deep + [g for g in greens if str(g.get("code", "")).zfill(6) not in _dset]
    # 역할별 현재 보유 수(슬롯 관리) — 한 역할이 슬롯 다 먹어 다른 역할 굶는 것 방지.
    held_role = {"통합대장": 0, "바닥": 0, "MA전환": 0, "깊은바닥": 0}
    for _p in pos.values():
        if isinstance(_p, dict) and _p.get("date") == today and _p.get("status") == "HOLDING":
            _rr = _p.get("role")
            if _rr in held_role:
                held_role[_rr] += 1
    changed = _deep_new[0]   # 새 깊은바닥 등재도 저장(로그 반복 방지)
    for r in cands:
        if held >= MAX_POS:
            break
        # [7/9 친구님 "돈맥에 눌림은 켜놓자 — 내일 바닥하고 눌림 두 개만 보자"] 2차 창 = 깊은바닥 + 눌림(저점반등).
        #   🟢 후보도 2차에 흐르되 역할은 저점반등(눌림)만 가능(모멘텀 전역차단·MA전환은 아래서 1차 한정).
        #   눌림 노른자=13시대(7/5 조사) 커버. 롤백(2차 깊은바닥 전용으로): 이 주석 아래 두 줄을 원복.
        code = str(r.get("code", "")).zfill(6)
        if code in excl:
            continue
        # [2026-07-07 친구님 "바닥 확인하고 잡아야"] 진입 확인 = 상승(모멘텀) OR che 저점반등(바닥확인). 첫매수·재진입 공통.
        #   오르는 종목(디앤디 +12%)=큰손뜨면 바로(반등불필요) / 빠지는 종목(제주 -7%)=che 저점반등 확인돼야(낙하칼 차단).
        _chg = r.get("chg")
        _rche = _che(bc, code)
        _cs = che_st.get(code) if isinstance(che_st.get(code), dict) else {}
        _cmin = _cs.get("min"); _cn = int(_cs.get("n", 0) or 0)
        _lo = float(_cs.get("lo", 0) or 0)                       # 당일 저점(LL·보드 누적)
        _rebound = (_rche is not None and _cmin is not None and _cn >= REB_MINN and _rche >= float(_cmin) + REB_PT)
        _up = (_chg is not None and _chg > 0)
        he = pos.get(code)
        if isinstance(he, dict) and he.get("date") == today:
            _st = he.get("status")
            if _st == "HOLDING":
                # [7/10 분할진입] 선매수 보유분(깊은바닥·1차창)은 돈유입 확인시 본매수(나머지 채움) 위해 통과
                if not (SPLIT_ENTRY and he.get("split_pre") and not he.get("topped_up")
                        and he.get("role") == "깊은바닥" and hm <= R1_ENTRY_END):
                    continue
            # [2026-07-07] 매수실패 쿨다운 — 실패 주문 8초 무한재시도(키움 '과도한 조회' 차단 유발) 방지.
            if _st == "FAILED" and (time.time() - float(he.get("fail_ts", 0) or 0)) < float(os.environ.get("MF_FAIL_COOLDOWN", "300")):
                continue
            # [2026-07-08 친구님 정정 "같은 종목 무제한 하지마 — 2번만"] 같은 종목은 하루 MAX_ENTRIES(2)회 상시.
            #   서로 다른 종목 로테이션은 계속 유효(전역 '서로다른종목' 상한 20이 최종 한도).
            if _st == "DONE":
                if int(he.get("entries", 1) or 1) >= MAX_ENTRIES:
                    continue
                if (time.time() - float(he.get("sell_ts", 0) or 0)) < REENTRY_COOLDOWN:
                    continue
        cur = _cur(bc, code)
        if cur <= 0:
            continue
        if cur < MIN_PRICE:      # 저가주 하한(2만) → 시도 자체를 안 함(ERROR 스팸 방지)
            continue
        _minvol_note(code, _cumvol(bc, code), hm)   # [7/10 분할] 후보 분당 거래량 기록(TR 0)
        _pre_buy = False                             # [7/10 분할] 이번 매수가 선매수(1/3)인지
        # [7/8 친구님 정정→7/11 500만 재편] 두 풀(깊은바닥 400만·그 외 100만) 모두 찼을 때만 스캔 중단.
        #   한쪽만 찼으면 계속 순회(역할별 체크는 매수 직전에서). 팔리면 자동 회복 → 재매수.
        if _invested >= DAILY_BUDGET:
            _log(f"공통 원금 한도 대기 — {_invested:,.0f}/{DAILY_BUDGET:,.0f} (매도로 회수되면 재개)")
            break
        # [7/8 친구님] 09:00~09:03 관찰 — 단 '기관/외인 달고 바로 날아가는' 놈은 급행(1분 이내 포착).
        #   급행 3중확인: 큰손우위 ≥30억(확실) & 실시간 체결강도 ≥120(지금 매수가 이김) & 전일比 +1%↑(날아가는 중)
        if hm < OPEN_OBS_END:
            _pc = _prev_close_map().get(code)
            _fche = _che(bc, code)
            _fly = bool(_pc and _pc > 0 and (cur / _pc - 1) * 100 >= FAST_CHG)
            if not ((r.get("big") or 0) >= FAST_MARGIN and _fche is not None and _fche >= FAST_CHE and _fly):
                continue     # 급행 아님 → 09:03까지 관찰
        # [2026-07-07 친구님 통합] 바닥권 추격금지 — 저점반등(하락) 진입은 당일저점 +CHASE_BAND%내만(추격 차단).
        # [2026-07-10 친구님 "저점으로"] 아침 1차 저점반등 판정 = 가격턴(당일저점서 +DEEP_REB_MIN% 돌아섬)으로 교체.
        #   체결강도 반등은 오후(2차·현재 폐쇄)에만 잔존. 롤백: setx MF_PULL_PRICE_TURN NO
        if PULL_PRICE_TURN and hm <= ENTRY_END:   # [7/10 오후 친구님 "눌림 열어봐 테스트"] 가격턴 규칙을 진입창 전체로(오전한정 해제)
            _pcf = _prev_close_map().get(code)
            _deep_enough = (PULL_MIN_DROP >= 0) or bool(
                _pcf and _pcf > 0 and _lo > 0 and (_lo / _pcf - 1) * 100 <= PULL_MIN_DROP)
            _rebound = (_deep_enough and _lo > 0 and cur >= _lo * (1 + DEEP_REB_MIN / 100.0))
            # [7/10 친구님 "다른 전략에도"] 눌림에도 분당 거래량 팽창 게이트 — 팽창 없는 턴 = 죽은반등 차단
            #   (8일 백테: 턴만 승률24% → 턴+팽창 57%). 표본부족(None)은 통과(fail-open). 롤백: setx MF_PULL_VOLX_GATE NO
            if PULL_VOLX_GATE and _rebound and not r.get("_deep"):
                # [7/10 12:2x 친구님 "횡보 구간에 사는 것 같아서(수동차단)"] 표본부족(None)도 차단으로 —
                #   12:15 개방 직후 게이트 워밍업 공백으로 나간 3건이 정확히 '턴만' 코호트(백테 승률24%).
                #   눌림은 팽창 확인 전엔 안 삼(fail-closed). 깊은바닥은 돈유입 관문이 별도라 무관.
                if _minvol_expand(code, cur) is not True:
                    _rebound = False
            # [7/10 친구님 "역배열은 바닥만 예외"(RFHIC 5<20<60 실증)] 눌림은 일봉 역배열 매수 금지 —
            #   깊은바닥(-4% 등재)은 예외(바닥은 역배열이 정상). 롤백: setx MF_PULL_REV_BLOCK NO
            if PULL_REV_BLOCK and _rebound and not r.get("_deep") and _reval_map().get(code):
                _rebound = False
        _rebound_ok = _rebound and (_lo <= 0 or cur <= _lo * (1 + CHASE_BAND / 100.0))
        # [눌림 B] 거래량 배수 재개확인 — 저점반등(재개)은 당일 거래량 페이스 ≥VOL_MULT×20일평균이어야(죽은반등 거름). 데이터없으면 통과(fail-open).
        #   [7/9 밤 대칭안] 아침 1차 깊은바닥은 면제 — 관문이 바닥턴을 15분 지각시킴(엘앤씨 +1.5%자리 대신 +3.9% 매수 실증).
        if _rebound_ok and VOL_MULT_GATE and not (DEEP_R1_NOVOL and r.get("_deep") and hm <= R1_ENTRY_END):
            _v20 = vol20_map.get(code); _cv = _cumvol(bc, code)
            if _v20 and _v20 > 0 and _cv > 0:
                _elapsed = max(0.1, min(1.0, (datetime.now().hour * 60 + datetime.now().minute - 540) / 390.0))  # 09:00=540분
                if (_cv / (_v20 * _elapsed)) < VOL_MULT:
                    _rebound_ok = False   # 거래량 페이스 부족 = 죽은 반등 → 대기
        # [통합대장 ②60선위 ③과열캡] 상승(모멘텀) 진입 품질 — 일60선 위 & 이격 ≤OVERHEAT_CAP%. 저점반등 경로엔 미적용(바닥은 60선 아래가 정상).
        _up_ok = _up
        _ma60 = ma60_map.get(code)
        if _up and MA60_GATE and _ma60:
            # [7/9 친구님 "상승은 거의 60선 아래서 시작·저점 상승은 매수/매도 우위로 판단"] '60선 위' 조건 제거 —
            #   원조 통합대장 ②개장로켓(OR경로) 복원 취지. 과열캡(일60선 +8% 초과 추격금지)만 유지.
            #   롤백: 이 줄을 (cur > _ma60) and (이격<=캡) 으로 복원.
            _up_ok = ((cur / _ma60 - 1) * 100 <= OVERHEAT_CAP)   # 과열 아님(60선 아래 포함 통과)
        if MOMENTUM_OFF:
            # [7/10 추세 주종 그림자] 차단 직전에 규칙판 후보만 기록(정배열 strict & 과열캡 통과·주문 0)
            if MOMENTUM_SHADOW and _up_ok and _jb_map().get(code):
                try:
                    _dev = ((cur / _ma60 - 1) * 100) if _ma60 else 0.0
                    _mshadow_note(code, cur, float(r.get("big") or 0), _dev, hm)
                except Exception:
                    pass
            _up_ok = False   # [7/9 친구님 "고점 모멘텀 진입로는 아예 끈다"] 상시 차단 — 아침자유 슬롯무시로도 우회 불가
        # [MA전환 바닥] 큰손 + 5·20·60 수렴→정배열전환→60선우상향(백테검증). che반등과 별개로 구조전환 바닥 진입.
        _mabase_ok = MABASE_GATE and bool(mabase_map.get(code))
        # [7/10 밤 갑툭이] 전일 갑툭튀∧수렴 예비 + 오늘 갭다운/눌림(전일比 ≤0%)일 때만 — 갭2%↑ 추격은 백테 승률44% 최악
        _gaptuk_ok = False
        if GAPTUK_GATE and gaptuk_map.get(code):
            _pcg = _prev_close_map().get(code)
            _gaptuk_ok = bool(_pcg and _pcg > 0 and (cur / _pcg - 1) * 100 <= GAPTUK_MAX_CHG)
        # [2026-07-07 밤 친구님 "역할별로·순서대로"] 역할 배정 = 선별기 순위 순서대로, 각 역할이 자기 슬롯 안에서 픽.
        #   한 역할(예 통합대장)이 슬롯 다 먹어도 다른 역할(바닥/눌림)은 자기 슬롯으로 순위에서 계속 픽 → "각자의 역할" 독립.
        #   맞는 역할 없음 = 낙하칼(순매수 크지만 상승·반등·MA전환 아님) → 차단 유지. ENTRY_CONFIRM=NO면 역할무시·순매수순(글로벌캡만).
        # [2026-07-08 아침자유 ~10:30] 역할슬롯 무시=선착순(기회 되는 놈 먼저)·MAX_POS(자본)만 한도. 이후엔 슬롯 복귀.
        _morning_free = MORNING_FREE and hm < MORNING_END
        if r.get("_deep"):
            # [2026-07-09 친구님] 깊은바닥 전용 관문 — ①저점 매수세(저점+6%내·저점+1.5% 턴) 필수
            #   ②★저점 돈유입: 기관/외인/프로/개인 중 1주체 순매수 ≥ DEEP_INFLOW. 실시간(probe·60s캐시·120s스로틀) 우선,
            #   실시간 응답이 있는데 유입 없으면 그걸로 확정(빈반등=안 삼)·실시간 불가시만 보드 최신 실측 폴백.
            # ★[2026-07-10 새벽 친구님 "체결강도 말고 그날의 저점 — 수정해"] 아침 1차 = 가격만(그날 저점 기준):
            #   바닥권에선 체결강도가 낮은 게 물리라 체결강도 반등 대기 = 오르막 중간 매수(지각). 10일 백테:
            #   체결강도+8 88회 +14.1%p(42%) → 가격만(저점+1.5%턴) 97회 +50.6%p(55%). 롤백: setx MF_DEEP_R1_NOCHE NO
            # [7/11 친구님 "고 통일해·바닥은 14시까지"] ①가격 턴만 판정을 종일 통일(2차의 체결강도 반등 조건 제거 —
            #   7/9 검증: 바닥권 체결강도 대기=지각·가격만 +50.6%p vs 체결강도 +14.1%p / 오늘 1개월 조사도 가격턴 기준 전 구간 플러스)
            #   ②깊은바닥 진입 마감 14:00(14시 이후 급락 회복률 30%=금지구간·24일 실측). 롤백: setx MF_DEEP_NOCHE_ALL NO / setx MF_DEEP_ENTRY_END 1430
            if hm > os.environ.get("MF_DEEP_ENTRY_END", "1400").strip():
                continue
            # [7/13 저녁 친구님 "60선 아래 역배열은 매수 금지 · 단 09:00~09:20은 예외 — 추세추종할려고 해"]
            #   역배열 = 일봉 5일선·20일선이 모두 60일선 아래(데드캣 교차까지 커버). 60일 미만 신규주는 맵에 없어 통과.
            #   ★키움 3분봉 130종목×43일·슬롯5 실측(저점+0~2%·10:00마감·꼭지매도):
            #      차단 없음      하루 8.0매수 · 승률 54% · 건당 +0.505% · 하루 +4.05%
            #      종일 차단      하루 7.3매수 · 승률 52% · 건당 +0.531% · 하루 +3.91%  ← 기회를 너무 버림
            #      ★09:20 예외   하루 7.7매수 · 승률 55% · 건당 +0.534% · 하루 +4.10%  ← 세 지표 모두 개선
            #   아침(09:00~09:20)은 추세와 무관하게 급락 반등이 가장 강한 구간(저점→60분 +8.96%)이라 예외.
            #   그 이후엔 역배열 = 하락추세 한복판이라 바닥이 바닥이 아님 → 매수 금지.
            #   눌림(role 바닥)의 역배열 차단은 별도로 이미 존재(L1045 PULL_REV_BLOCK·깊은바닥은 그쪽 대상 아님).
            #   롤백: setx MF_DEEP_REV_BLOCK NO   (예외시각 변경: setx MF_DEEP_REV_EXEMPT_END 0930)
            if (os.environ.get("MF_DEEP_REV_BLOCK", "YES").strip().upper() == "YES"
                    and hm > os.environ.get("MF_DEEP_REV_EXEMPT_END", "0920").strip()
                    and _reval_map().get(code)):
                if code not in _DEEP_REV_SEEN:
                    _DEEP_REV_SEEN.add(code)
                    _log(f"📉 {code}(깊은바닥) 매수금지 — 일봉 역배열(5·20선이 60선 아래)"
                         f" · 09:20 이후는 하락추세 한복판이라 바닥 아님")
                continue
            _noche_all = os.environ.get("MF_DEEP_NOCHE_ALL", "YES").strip().upper() == "YES"
            if _noche_all or (DEEP_R1_NOCHE and hm <= R1_ENTRY_END):
                # ★[7/14] 추격밴드(진입창 상한)도 가격대별 — 1만원↑는 DEEP_BAND_HI(3%) · 잡주는 CHASE_BAND(2%).
                _band = DEEP_BAND_HI if (DEEP_BAND_HI > 0 and cur >= LOW_PX_EDGE) else CHASE_BAND
                if not (_lo <= 0 or cur <= _lo * (1 + _band / 100.0)):   # 추격밴드(저점+밴드%내)만 — 체결강도 조건 없음
                    continue
            elif not _rebound_ok:
                continue
            # ★[7/13 밤] 가격대별 진입창 — 잡주는 저점+0~2% · 1만원↑는 +1~2%.
            #   근거: 비싼 종목은 호가 단위가 커서(3만원대 50원=0.17%) 저점에 바짝 붙이면 호가 한두 칸 흔들림에 손절선이 걸린다.
            #   잡주는 반대로 +1%를 기다리면 반등을 놓친다(3분봉 43일 실측). 롤백: setx MF_DEEP_REB_MIN_LOW 1
            _reb_min = DEEP_REB_MIN_LOW if cur < LOW_PX_EDGE else DEEP_REB_MIN
            if _lo > 0 and cur < _lo * (1 + _reb_min / 100.0):   # 저점 확인 — 저점서 이만큼 돌아선 뒤에만(떨어지는 칼 한가운데 매수 방지)
                continue
            # ★[7/13 밤] 잡주 유동성 관문 — 그 시각까지 거래대금이 얇으면 매수 금지.
            #   잡주 백테 수익의 상당분이 "09:20까지 거래대금 0~2억" 종목에서 났는데 그건 실제로 못 산다
            #   (건당 166만원이 그 시각 거래대금의 100%↑ = 호가를 통째로 뚫음).
            #   실측(잡주 매수 48건): 09:20 거래대금 중앙 7.4억 · 하위 15%가 2억 미만 → 2억을 문턱으로.
            #   ★모르면 안 삼(fail-closed) — 잡주는 선택지지 필수가 아니다. 롤백: setx MF_LOW_V20_EOK 0
            if cur < LOW_PX_EDGE and LOW_V20_EOK > 0:
                _v20 = _cumvol(bc, code) * cur / 1e8      # 누적거래량 × 현재가 = 그 시각까지 거래대금(억·TR 0)
                if _v20 < LOW_V20_EOK:
                    if code not in _LOW_LIQ_SEEN:
                        _LOW_LIQ_SEEN.add(code)
                        _log(f"💧 {code}(잡주 {cur:,.0f}원) 매수보류 — 그 시각 거래대금 {_v20:.1f}억"
                             f" < {LOW_V20_EOK:.0f}억 · 호가가 얇아 우리 주문이 통째로 뚫는다")
                    continue
            # [7/12 친구님 "망한무리 조건 넣어서 사지 말자 — 슬금슬금 피하고·갭하락은 무조건 잡고·-6%부터·20일선 아래 -5% 부근은 죽을 놈"]
            #   망한무리 3중 차단 — 근거(24일 아침저점 1,672건 해부+스윕):
            #   ①당일낙폭 -6% 미달 차단(-6%↓ 성공 84% vs -4~-6% 72%·슬롯4 총합도 우위)
            #   ②20일선 어중간 밴드(-6~-3%) 차단 = 성공 62%·턴매수 -0.35%/승29%(전 구간 유일 대형 마이너스·"하락 초입 급락")
            #   ③슬금슬금(하락속도<0.10%/분) 차단 = 성공중앙 0.27 vs 망함 0.07·차단분 696건 평균 -0.53%
            #   ★갭하락(시가 전일比 -3%↓·보드 09:05 첫관측 근사 o) = 3중 전부 면제("무조건 잡고"·성공 86%)
            #   데이터 없으면 통과(fail-open)·시가 모르면 면제 아님. 차단은 로그+CSV 기록(doomed_block_log.csv).
            #   롤백: setx MF_DEEP_MIN_DEPTH -4 / setx MF_DEEP_MA20_BLOCK NO / setx MF_DEEP_SLOW_MIN 0
            _pcd2 = _prev_close_map().get(code)
            _dpv = ((_lo / _pcd2 - 1) * 100) if (_pcd2 and _lo > 0) else None
            _ob = float(_cs.get("o", 0) or 0)
            _lts = str(_cs.get("lo_ts") or "")
            _gap_free = bool(_pcd2 and _ob > 0
                             and (_ob / _pcd2 - 1) * 100 <= float(os.environ.get("MF_DEEP_GAP_FREE", "-3")))
            # [7/12 친구님 "배선하자 — 물량 많으니 좋은 거 쓰는 게 낫지"] 갭면제 시간조건 — 저점이 09:30 이후에도
            #   갱신되는 갭하락은 면제 취소(3중 검문 정상 적용). 근거: 갭하락 310건 = 저점 09:15 이전 성공 97%
            #   vs 09:30 이후 67%("갭 뜨고도 바닥 못 찾는 놈"이 갭하락 실패의 본체) · 시간조건 추가시 망함 차단 81→87%·
            #   갭면제로 새는 망함 12→1건. lo_ts 미기록(보드 지각 등)이면 기본 면제 유지(지시 원형 존중).
            #   롤백: setx MF_DEEP_GAP_FREE_END 1600 (=시간조건 해제·무조건 면제 복귀)
            if _gap_free and len(_lts) == 4 and _lts.isdigit() \
                    and _lts > os.environ.get("MF_DEEP_GAP_FREE_END", "0930").strip():
                _gap_free = False
            _mp = _ma20pos_map().get(code)
            _spd = None
            if _dpv is not None and len(_lts) == 4 and _lts.isdigit():
                _spd = abs(_dpv) / max(int(_lts[:2]) * 60 + int(_lts[2:]) - 540, 3)
            if not _gap_free:
                _why = ""
                if _dpv is not None and _dpv > float(os.environ.get("MF_DEEP_MIN_DEPTH", "-6")):
                    _why = f"얕음{_dpv:.1f}%"
                if not _why and os.environ.get("MF_DEEP_MA20_BLOCK", "YES").strip().upper() == "YES" and _mp is not None \
                        and float(os.environ.get("MF_DEEP_MA20_LO", "-6")) <= _mp <= float(os.environ.get("MF_DEEP_MA20_HI", "-3")):
                    _why = f"20선어중간{_mp:+.1f}%"
                if not _why:
                    _slowmin = float(os.environ.get("MF_DEEP_SLOW_MIN", "0.10") or 0)
                    if _slowmin > 0 and _spd is not None and _spd < _slowmin:
                        _why = f"슬금슬금{_spd:.2f}%/분"
                if _why:
                    if code not in _DOOMED_SEEN:
                        _DOOMED_SEEN.add(code)
                        _log(f"🚷 {code} 망한무리 차단 [{_why}]")
                        try:
                            _dlp = Path(r"C:\stock_bot\data\shadow\doomed_block_log.csv")
                            _dnew = not _dlp.exists()
                            with _dlp.open("a", encoding="utf-8-sig", newline="") as _dfp:
                                if _dnew:
                                    _dfp.write("date,time,code,reason,ma20pos,depth,speed\n")
                                _dfp.write(f"{datetime.now():%Y%m%d},{datetime.now():%H%M%S},{code},{_why},{_mp},{_dpv},{_spd}\n")
                        except Exception:
                            pass
                    continue
            # [7/12 친구님 "아침에는 이놈들(이른저점∪갭하락)만 목표로 잡자"] 아침 1차 노른자 한정 —
            #   저점이 09:15 이전 형성(이후 갱신 없음·보드 lo_ts) 또는 갭하락 면제(-3%↓·저점 09:30 내)만 매수.
            #   근거(23일 686건): 이른저점 성공 97%·시가회복 81% / 갭하락 92% / 늦은저점 43%·시가회복 10~18%
            #   · 합집합 13.2개/일(중앙 7)=슬롯4 충분. 실전판정 검증: 아침 매수의 나쁜 꼬리 22%(평균 -0.42%) 제거.
            #   ⚠️진입 순간 판정이라 '이른 저점'이 이후 깨질 수 있음 — 그건 구조붕괴/하드컷 담당.
            #   lo_ts 미기록(보드 지각)=통과(fail-open). 낮 2차 창은 기존 그대로. 롤백: setx MF_DEEP_R1_PRIME NO
            # [7/13 장중 친구님 "15분 넘으면 모든 종목 허용이라고 바꿔"] 노른자 한정 적용 구간을
            #   09:00~10:00 전체 → ★09:15까지로 축소(MF_DEEP_R1_PRIME_END). 09:15 이후엔 저점 형성 시각을
            #   따지지 않고 전 종목 허용(망한무리 3중 차단·호가 관문은 그대로 유효).
            #   이유: 09:15 이후 새로 바닥을 찍는 급락주가 통째로 차단돼 실전에서 매수 기회가 사라짐.
            #   ⚠️7/12 백테 근거(이른저점 성공 97% vs 늦은저점 43%)와 상충 — 실전 성적으로 재검증 필요.
            #   롤백: setx MF_DEEP_R1_PRIME_END 1000 (=기존·10:00까지 노른자 한정)
            if (os.environ.get("MF_DEEP_R1_PRIME", "YES").strip().upper() == "YES"
                    and hm <= os.environ.get("MF_DEEP_R1_PRIME_END", "0915").strip()
                    and not _gap_free
                    and len(_lts) == 4 and _lts.isdigit()
                    and _lts > os.environ.get("MF_DEEP_R1_LOW_BY", "0915").strip()):
                # [7/12 친구님 "없을 때는 2차로 문 열어봐"] 노른자 가뭄 폴백 — 09:25(MF_DEEP_R1_FALLBACK)까지
                #   깊은바닥 매수 0건이면 비노른자(일반 아침 후보)도 허용(망한무리 3중 차단은 그대로 통과해야 함).
                #   노른자를 하나라도 샀으면 문 다시 닫힘(그날은 노른자 장). 롤백: setx MF_DEEP_R1_FALLBACK 2400(=폴백 끔)
                _fb = (hm >= os.environ.get("MF_DEEP_R1_FALLBACK", "0925").strip()
                       and held_role["깊은바닥"] == 0)
                if not _fb:
                    if code not in _DOOMED_SEEN:
                        _DOOMED_SEEN.add(code)
                        _log(f"🌙 {code} 아침 노른자 아님(저점 {_lts[:2]}:{_lts[2:]} 형성·갭면제 아님) → 대기")
                    continue
                if code not in _DOOMED_SEEN:
                    _DOOMED_SEEN.add(code)
                    _log(f"🌗 {code} 노른자 가뭄 폴백 — 2차 문 개방(09:25+·깊은바닥 보유 0)")
            if not (_morning_free or held_role["깊은바닥"] < SLOTS_DEEP):
                continue
            _in_ok = False; _in_src = ""; _rt_seen = False
            # [7/11 친구님 "돈유입 무시해 — 던짐인데 뭐하러 돈유입을 따져·바닥에서 따져야지"] 깊은바닥 돈유입 관문
            #   시간 무관 면제(아침면제의 종일 확장·던짐해제 MF_DEEP_DUMP_FREE와 세트). 진입 판단 = 등재깊이(-4%)
            #   + 저점+1.5% 턴 + 추격밴드만·방어 = 하드-2%+구조붕괴+매도사다리+10:20(1차분).
            #   부수효과: 진입시 수급 probe 생략 = 지각/TR 절감. 롤백: setx MF_DEEP_NOINFLOW_ALL NO (아침만 면제 복귀)
            if os.environ.get("MF_DEEP_NOINFLOW_ALL", "YES").strip().upper() == "YES":
                _in_ok = True; _in_src = "아침면제(반등만)" if hm <= R1_ENTRY_END else "면제(반등만·종일)"
            elif DEEP_R1_NOINFLOW and hm <= R1_ENTRY_END:
                _in_ok = True; _in_src = "아침면제(반등만)"   # [7/10 저녁] 1차 창은 돈유입 관문 생략 — 턴+밴드+사다리가 방어
            if not _in_ok and time.time() - float(_DEEP_PROBE.get(code, 0) or 0) >= DEEP_PROBE_SEC:   # [7/10] 120→45초 가속(조건권만)
                _DEEP_PROBE[code] = time.time()
                try:
                    import smart_money as _SMP
                    _iv = _SMP.probe(bc, code, cur)   # (기관,외인,프로,개인,imb)·백만원·60s캐시
                    for _nm, _v in zip(("기관", "외인", "프로", "개인"), _iv[:4]):
                        if _v is None:
                            continue
                        _rt_seen = True
                        if _v >= DEEP_INFLOW:
                            _in_ok = True; _in_src = f"{_nm}+{_v/100:.0f}억"; break
                except Exception:
                    pass
            if not _in_ok and not _rt_seen:            # 실시간 못 봤을 때만 보드 최신 실측 폴백
                for _nm, _k in (("기관", "inst"), ("외인", "frgn"), ("프로", "prog"), ("개인", "indiv")):
                    _v = r.get(_k)
                    if _v is not None and float(_v) >= DEEP_INFLOW:
                        _in_ok = True; _in_src = f"{_nm}+{float(_v)/100:.0f}억(보드)"; break
            # [7/10 분할진입 ②본매수] 선매수 보유분 + 돈유입 확인 → 나머지 채움(합산 CAP 이내·평단 병합·entries 미증가)
            if (isinstance(he, dict) and he.get("status") == "HOLDING"
                    and he.get("split_pre") and not he.get("topped_up")):
                if _in_ok:
                    _q0 = int(he.get("qty", 0) or 0)
                    _q2 = max(0, COMMON_ORDER_QUANTITY - _q0)
                    if (_q2 >= 1
                            and _invested + _q2 * cur <= DAILY_BUDGET
                            and position_budget.can_open_krw(_q2 * cur)):
                        if _order(bc, code, _q2, "BUY", f"돈흐름 분할본매수 {_in_src}"):
                            if LIVE:
                                try:
                                    import rt_registry as _RT2; _RT2.register(code, _q2, cur, "MFLOW")
                                except Exception:
                                    pass
                            _b0 = float(he.get("buy_price", 0) or 0)
                            he["buy_price"] = round((_b0 * _q0 + cur * _q2) / (_q0 + _q2), 2)
                            he["qty"] = _q0 + _q2; he["topped_up"] = True
                            he["grade"] = f"🕳깊은바닥·{_in_src}"
                            pos[code] = he; changed = True
                            _invested += _q2 * cur; _invested_deep += _q2 * cur; _bud["spent"] += _q2 * cur
                            _log(f"{mode} BUY {code} @{cur:,.0f} x{_q2} [분할본매수·{_in_src}·평단 {he['buy_price']:,.0f}]")
                continue                               # 본매수 처리 끝(신규매수 경로로 안 내려감)
            if not _in_ok:
                # [7/10 분할진입 ①선매수] 돈유입 미확인이라도 턴+분당 거래량 팽창이면 CAP×FRAC 선취
                #   (백테: 팽창 동반 턴 승률 57%·본전+ — 돈이 늦게 오는 승자(에이직랜드형) 저점권 선취용)
                if SPLIT_ENTRY and hm <= R1_ENTRY_END and _minvol_expand(code, cur) is True:
                    _pre_buy = True
                    _in_src = "선매수(턴+거래량팽창)"
                else:
                    continue                           # 돈 안 몰린 반등(빈반등) → 대기
            # [7/12 친구님 "기록할 방법 없나"] 매수 로그·장부(grade)에 20일선 위치/하락속도/저점→진입 지연 병기 — 실측 축적용(비용 0)
            try:
                _tags = []
                if _mp is not None:
                    _tags.append(f"20선{_mp:+.1f}")
                if _spd is not None:
                    _tags.append(f"속도{_spd:.2f}")
                if len(_lts) == 4 and _lts.isdigit():
                    _tags.append(f"턴지연{(int(hm[:2]) * 60 + int(hm[2:])) - (int(_lts[:2]) * 60 + int(_lts[2:]))}분")
                if _gap_free:
                    _tags.append("갭면제")
                if _tags:
                    _in_src += "·" + "·".join(_tags)
            except Exception:
                pass
            role = "깊은바닥"
            r["grade"] = f"🕳깊은바닥·{_in_src}"        # 매수 로그에 돈유입 출처 표시
        elif not ENTRY_CONFIRM:
            role = "매수세"
        elif _up_ok and (_morning_free or held_role["통합대장"] < SLOTS_UP):
            role = "통합대장"
        elif _rebound_ok and not REBOUND_OFF and (_morning_free or held_role["바닥"] < SLOTS_REB):
            role = "바닥"
        elif ((_mabase_ok and (MABASE_ALLDAY or not _r2)) or (_gaptuk_ok and hm <= R1_ENTRY_END)) \
                and (_morning_free or held_role["MA전환"] < SLOTS_MA):
            # [7/10 저녁 친구님 "이건 오후까지 가야 돼 — 잘 안 나와"] MA전환은 신호 희소(전시장 ~12종목)라
            #   진입창 전체(~ENTRY_END) 허용. 오후 매수분은 매도사다리+EOD 15:18이 관리(10:20 조항 미적용).
            #   롤백: setx MF_MABASE_ALLDAY NO (1차 한정 복귀)
            # [7/10 밤 갑툭이] 전일 갑툭튀∧수렴 예비는 아침창(R1)·갭다운/눌림에서만 같은 슬롯으로 진입(둘 다 희소).
            role = "MA전환"
            if _gaptuk_ok and not _mabase_ok:
                r["grade"] = "⚡갑툭이(수렴돌파 익일눌림)"
        else:
            continue      # 맞는 역할 없거나 그 역할 슬롯 참 → 선별기 다음 순위로
        _bottom_entry = (role in ("바닥", "깊은바닥"))   # 바닥성 진입은 구조붕괴(저점이탈) 손절 대상(모멘텀은 트레일/che로)
        # [7/13 친구님 "매도자가 많을 때 안 사는 게 더 중요해 — 그래야 하드컷을 안 당해"
        #             + "매수 매도 우위가 있으니까 사면 돼" + "눌림목도 여기도 똑같이 넣고"]
        #   ★진입 호가 관문 — 바닥성 진입(깊은바닥·눌림) 공통. 매수총잔량 ≥ 매도총잔량(imb ≥ MF_DEEP_ENTRY_IMB)일 때만 매수.
        #   매도벽이 두꺼우면 이번 틱 보류 → 8초 루프가 매도벽 얇아지는 순간까지 대기
        #   (진입창(저점+1~2%) 안에 머무는 동안 매 틱 재확인 → 얇아지면 그때 진입).
        #   ★우위를 확인 못하면(호가 데이터 없음) 안 산다 = fail-safe. "우위가 있으니까 산다"가 지시.
        #   근본 목적 = 애초에 안 물리는 것(하드-2% 회피). imb = 스냅샷 파일(TR 0).
        #   짝: 매도쪽 구조붕괴 유예(L517·저점 뚫려도 매수벽 받치면 홀드)도 바닥성 진입 공통 적용.
        #   롤백: setx MF_DEEP_ENTRY_IMB 0  (0 = 관문 끔 = 기존 동작)
        # [OB-FIX 2026-07-13 친구님 "호가 없으면 안 산다를, 가격 확인되고 매수조건에 맞으면 사자.
        #                        우리는 깊은 바닥이 최고 우선이여"]
        #   ★기존 fail-safe(호가 없으면 매수금지)가 배관 결함과 겹쳐 실전 매수를 통째로 죽이고 있었다.
        #   원인: 키움 화면당 실시간 100종목 한계 — 120을 한 화면에 몰아넣어 뒤쪽 호가가 잘림(broker_gateway OB-FIX 참조).
        #   실측(7/13 장중 40초): 등록 120 중 뒤 20종목은 호가생존 5/20 → 445090·399720 종일 매수불가(조건은 충족).
        #   ★이제: 호가 '결측'(None) = 판단재료 없음 = 가격조건(낙폭·저점반등·꼬리)만으로 매수 진행.
        #          호가가 '있는데' 매도벽 우세(imb < 문턱)면 → 종전대로 보류(이건 진짜 신호라 유지).
        #   배관은 같은 날 고쳤으므로 결측 자체가 드물어야 정상 — 결측 진입은 로그로 남겨 사후 대조.
        #   롤백: setx MF_ENTRY_IMB_FAILOPEN NO  (=호가 없으면 다시 안 삼)
        if _bottom_entry:
            _eimb_thr = float(os.environ.get("MF_DEEP_ENTRY_IMB", "1.0") or 0)
            if _eimb_thr > 0:
                _eiv = _imb(bc, code)
                _failopen = os.environ.get("MF_ENTRY_IMB_FAILOPEN", "YES").strip().upper() == "YES"
                if _eiv is None and _failopen:
                    if code not in _ENTRY_IMB_NONE_SEEN:
                        _ENTRY_IMB_NONE_SEEN.add(code)
                        _log(f"📭 {code}({role}) 호가 결측 — 가격조건만으로 진행(호가관문 면제·OB-FIX)")
                elif _eiv is None or _eiv < _eimb_thr:
                    if code not in _ENTRY_IMB_SEEN:
                        _ENTRY_IMB_SEEN.add(code)
                        _log(f"⏸️ {code}({role}) 매수 보류 — 매도벽 우세(호가잔량 "
                             f"{('%.2f' % _eiv) if _eiv is not None else 'N/A'} < {_eimb_thr:g}) · 얇아지면 진입")
                    continue
            # [7/13 친구님 "가격을 넣고 꼬리 양봉을 넣으면 되지" · "0.6으로 하고 봉 없으면 사지 마"]
            #   ★진입 봉 꼬리 관문 — 그 순간 1분봉의 종가위치 = (종가-저가)/(고가-저가).
            #   1에 가까울수록 "밑으로 밀렸다가 누군가 받아서 종가를 위로 올려놓은 것" = 매수 우위의 가격 증거.
            #   22일 백테(진입 377건): 가격만 승률 31.6%/가짜바닥 67.1% → 종가위치 ≥0.6 승률 41.3%/가짜바닥 54.8%.
            #   ★봉 없으면 매수 금지(fail-safe·친구님 지시) — 판단 재료가 없으면 안 산다.
            #   봉 공급 = deep_bottom_signal_recorder(상주·5초) → 돈맥_1분봉.json (매매기는 55초마다 죽어 자체 누적 불가).
            #   롤백: setx MF_DEEP_ENTRY_POS 0  (0 = 관문 끔 = 봉 없어도 매수)
            #   ★[7/14 친구님 "양봉3 위꼬리 필터도 배선해"] 1분봉 실측(207종목×43일)으로 문턱 교체 —
            #   3분봉 시절의 0.6은 독이었으나(봉 꼭대기에서 사게 됨) 1분봉에선 **0.90**(위꼬리 ≤10%)이 정답.
            #   승률 42% → 57% · 손절률 44% → 23% · 하루 -17,435원 → +183원. 매수는 6.5건 → 1.4건으로 준다.
            _epos_thr = float(os.environ.get("MF_DEEP_ENTRY_POS", "0.6") or 0)
            _bull_n   = int(os.environ.get("MF_DEEP_BULL_N", "0") or 0)
            if _epos_thr > 0 or _bull_n > 0:
                _bar = _bar1m(code)
                if not _bar:
                    if code not in _ENTRY_POS_SEEN:
                        _ENTRY_POS_SEEN.add(code)
                        _log(f"⏸️ {code}({role}) 매수 보류 — 1분봉 없음(판단불가·fail-safe)")
                    continue
                # ① 위꼬리 소멸 — 종가위치 ≥ 0.90 = 위꼬리 ≤ 10% (봉 꼭대기 근처에서 마감 = 매수세가 밀리지 않음)
                _bpos = _bar.get("pos")
                if _epos_thr > 0 and (_bpos is None or float(_bpos) < _epos_thr):
                    if code not in _ENTRY_POS_SEEN:
                        _ENTRY_POS_SEEN.add(code)
                        _log(f"⏸️ {code}({role}) 매수 보류 — 종가위치 {float(_bpos or 0):.2f} < {_epos_thr:g}"
                             f" (위꼬리 남음 = 아직 위에서 밀리고 있다)")
                    continue
                # ② ★양봉 N개 연속 — 현재 봉 + 직전 완성봉들이 전부 양봉(종가>시가)이어야 한다.
                #   기록기가 prev(직전 완성봉 [o,h,l,c] · 오래된 것→최근 순)를 함께 넘겨준다.
                #   봉이 모자라면 안 삼(fail-closed) — 장 초반 09:00~09:02는 자연히 매수 안 됨.
                #   롤백: setx MF_DEEP_BULL_N 0
                if _bull_n > 0:
                    _seq = [1 if _bar.get("bull") else 0]                      # 현재 봉
                    for _pb in reversed(_bar.get("prev") or []):               # 최근 → 과거 순으로 거슬러
                        try:
                            _seq.append(1 if float(_pb[3]) > float(_pb[0]) else 0)   # c > o
                        except Exception:
                            break
                    if len(_seq) < _bull_n or not all(_seq[:_bull_n]):
                        if code not in _ENTRY_POS_SEEN:
                            _ENTRY_POS_SEEN.add(code)
                            _log(f"⏸️ {code}({role}) 매수 보류 — 1분봉 양봉 {_bull_n}개 연속 아님"
                                 f" (최근봉 {''.join('양' if x else '음' for x in _seq[:_bull_n]) or '없음'})")
                        continue
        # 던짐 이중차단 (실시간·60s캐시) — [7/10 저녁] 아침 1차 깊은바닥은 면제(친구님 "아침 돈던지기 무시")
        # [7/11 친구님 "투매=개미털기 — 던짐 차단은 스스로를 감옥에 가두는 것·깊은저점 빠지면 들어가야·-2% 컷이 방어"]
        #   깊은바닥은 시간 무관 던짐차단 면제. 근거(1개월 3분봉 782건·14시 이전): 던짐 종목 턴매수 +0.94%(승 67.3)
        #   vs 관문통과 +0.43% — 던짐만 해제(A안) = 건수 253→331(+31%)·평균 +0.43→+0.52%·승률 57.7→58.9%.
        #   돈유입(1주체 3억) 관문은 유지(완전면제 B안은 평균 희석이라 기각). 눌림·MA전환 등 다른 경로는 차단 유지.
        #   롤백: setx MF_DEEP_DUMP_FREE NO (아침 1차만 면제로 복귀)
        _dump_free = (os.environ.get("MF_DEEP_DUMP_FREE", "YES").strip().upper() == "YES" and role == "깊은바닥")
        if not (_dump_free or (DEEP_R1_NOINFLOW and role == "깊은바닥" and hm <= R1_ENTRY_END)):
            try:
                import smart_money as SM
                blk, smi = SM.dumping(bc, code, cur)
                if blk:
                    _log(f"⛔ {code} 던짐차단 [{smi}]"); continue
            except Exception:
                pass
        # 모든 전략과 같은 공통 목표수량을 쓴다. 선매수는 그 목표 안에서만 분할하고,
        # 본매수를 포함한 최종 보유수량도 COMMON_ORDER_QUANTITY를 넘지 않는다.
        qty = (
            max(1, int(COMMON_ORDER_QUANTITY * SPLIT_FRAC))
            if _pre_buy else COMMON_ORDER_QUANTITY
        )
        if (_invested + qty * cur > DAILY_BUDGET
                or not position_budget.can_open_krw(qty * cur)):
            continue
        _pm = _pmgap_map().get(code)   # [7/9] 장전 예상갭 참고(없으면 None·매수판단 무영향)
        if _order(bc, code, qty, "BUY", f"돈흐름진입 {r.get('grade')}"):
            if LIVE:
                try:
                    import rt_registry as _RT; _RT.register(code, qty, cur, "MFLOW")
                except Exception:
                    pass
            pos[code] = {"code": code, "status": "HOLDING", "buy_price": cur, "qty": qty, "peak": cur,
                         "date": today, "buy_hm": hm, "grade": r.get("grade"), "big": r.get("big"), "live": LIVE,
                         "pm_gap": (_pm[0] if _pm else None),   # [7/9] 장전 예상갭(참고·사후대조용)
                         "pm_rank": (_pm[1] if _pm else None),
                         "role": role,   # [2026-07-07] 역할 태그(통합대장/바닥/MA전환/매수세) — 슬롯관리·로그구분
                         "entries": int((he or {}).get("entries", 0) or 0) + 1,   # 재진입 횟수 누적(청산분 재매수 카운트)
                         "split_pre": _pre_buy, "topped_up": False,   # [7/10 분할] 선매수 표식(본매수 대기)

                         "struct_low": (round(_lo * (1 - STRUCT_BUF), 2) if (_bottom_entry and _lo > 0) else 0),  # 바닥진입시 구조 저점(이탈=붕괴손절)
                         # [7/13 저녁 STOP-B] 진입 시점 낙폭(당일저점 vs 전일종가 %) — 매도 때 '변동성 비례 하드컷' 계산용.
                         #   깊게 빠진 놈은 하루 변동폭 자체가 커서 -2%가 노이즈에 걸린다 → 깊이만큼 손절선을 넓혀준다.
                         "depth": round(float(r.get("depth") or 0), 2)}
            if role in held_role:
                held_role[role] += 1
            held += 1; changed = True
            _invested += qty * cur       # 투입중 금액(회전 게이트)
            if role == "깊은바닥":
                _invested_deep += qty * cur   # [7/11 500만] 깊은바닥 풀 추적
            _bud["spent"] += qty * cur   # 하루 회전 누적(보고용)
            _log(f"{mode} BUY {code} @{cur:,.0f} x{qty} [{role}·{r.get('grade')}·큰손{(r.get('big') or 0)/100:+.0f}억"
                 + (f"·장전갭{_pm[0]:+.1f}%({_pm[1]}위)" if _pm else "")
                 + f"·투입중 {_invested:,.0f}·회전누적 {_bud['spent']:,.0f}원]")
        else:
            # 매수 실패 → 쿨다운 기록(재시도 스팸 방지). 쿨다운(MF_FAIL_COOLDOWN·기본 300s) 후 재시도 허용.
            pos[code] = {"code": code, "status": "FAILED", "date": today, "fail_hm": hm, "fail_ts": time.time()}
            changed = True
            _log(f"⚠️ {code} 매수실패 → {int(float(os.environ.get('MF_FAIL_COOLDOWN','300')))}s 쿨다운(재시도 스팸 방지)")
    return changed


def run():
    now = datetime.now(); hm0 = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    _force = os.environ.get("MF_EXEC_FORCE", "").strip().upper() == "YES"   # 수동/장외 테스트 강제실행(LIVE 게이트와 무관)
    if (hm0 < "0901" or hm0 > "1530") and not _force:
        return
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            _log("broker dead → skip"); return
        bc = BrokerClient()
    except Exception as e:
        _log(f"broker 연결실패 {e}"); return
    mode = "[LIVE]" if LIVE else "[그림자]"

    # 수급 보드 갱신을 백그라운드로 → 매도 빠른루프(아래)를 안 막음. 매 프로세스 1회(≈40s TR).
    if os.environ.get("MF_BOARD_REFRESH", "YES").strip().upper() == "YES":
        try:
            threading.Thread(target=_refresh_board, daemon=True).start()
        except Exception as e:
            _log(f"보드 스레드 실패 {e}"); _refresh_board()

    # ★빠른 루프: 매도/진입을 LOOP초마다 (매매가=실시간 푸시 스냅샷·TR 0).
    #   RUN초까지 돌고 프로세스 종료 → 1분 뒤 태스크가 재기동(멈춰도 자동복구). Windows 태스크 최소단위=1분이라
    #   초단위 반응은 이 내부루프로만 얻음. 매도는 스냅샷 파일 읽기라 몇 초마다 봐도 브로커 TR 0.
    LOOP = float(os.environ.get("MF_LOOP_SEC", "8"))
    RUN  = float(os.environ.get("MF_RUN_SEC", "55"))
    deadline = time.monotonic() + RUN
    n = 0
    while True:
        hm = datetime.now().strftime("%H%M")
        pos = _jload(POS)
        ch1 = _exits(bc, pos, hm, mode)
        ch2 = _entries(bc, pos, hm, today, mode)
        if ch1 or ch2:
            _jsave(POS, pos)
        n += 1
        if time.monotonic() >= deadline or (hm > "1530" and not _force):
            break
        time.sleep(LOOP)
    _log(f"{mode} 사이클 종료 (루프 {n}회)")


if __name__ == "__main__":
    try:
        run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
