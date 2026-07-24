# -*- coding: utf-8 -*-
"""🏔️📈 골짜기 사냥꾼 저점 앵커 매수 판정 — 순수 판정 모듈 (주문 없음·브로커 연결 없음)
   [2026-07-18 신설 → 밤 저점 로직 전면 교체(2분+재반등리셋) → 2026-07-19 매수 로직 재정리
    → -5%조건 재부활+정배열 필터 추가 → 3분봉을 1분봉에서 직접 합성(거래량 포함)으로 교체
    → 2026-07-19 밤 경로① 절대체결비율(105) 폐기, 반등품질(변화량 추세) 판정으로 교체
    → 2026-07-19 심야 통합패치: 3분봉 로직 전부 삭제(완성 1분봉만 사용), 하락기준 -5% 단일화,
      매수시간 09:30~14:30, 재매수손절 -2.5%로 통합
    → 2026-07-20 골짜기+급락주 게이트 통합: IDLE 진입조건에 Gate1(09:00~09:30·전일종가-5%,
      entry_gate="MORNING_CRASH") 추가 — 09:30~는 기존 Gate2(entry_gate="VALLEY_PEAK") 그대로.
      저점탐색·반등품질·매도는 게이트 무관 100% 공통(급락주 원본 은퇴 전 그림자 검증용, 지침서 참고)]

   ⚠️ 이 파일이 valley_low_buy_v1.py다 — crash_flow_live_v1.py / low_anchor_buy_v1.py 원본은 건드리지 않았다.

■ 매수 확정은 완전히 독립적인 두 경로 중 하나만 맞아도 된다(OR, AND 아님).
   경로① 저점 반등 + 반등품질(체결강도·매수체결량·매도체결량·거래량의 "변화량" 추세)
   경로② 5일선 또는 10일선을 만나거나(터치) 돌파 — 단, 현재가가 20일선 위에 있을 때만 작동
         (횡보구간에서 이평선을 오르락내리락하며 잘못 사는 걸 막기 위한 필터)

■ 저점(observation_low) 확정 절차 — 전부 AND로 충족해야 관찰 시작:
  1. 5일선 위에서 형성된 고점(ma5_above_peak) 대비 -3.0%(VLA_PEAK_DROP_PCT·★7/20 -5→-3) 이상 하락
     (횡보 구간 차단용 — ★2026-07-19 심야 통합패치로 이게 유일한 하락 기준. 유니버스 단의
     "당일 등락률 -4%" 필터는 중복이라 valley_hunter_live_v1.py에서 삭제했다).
  2. 현재가가 일봉 5일선 아래인 상태에서, **완성된 1분봉**이 3개(VLA_BEARISH_3M_N) 연속 음봉으로
     나온 뒤 그 다음 완성 1분봉이 양봉으로 전환되는 순간 = 저점 확정 후보("음봉 끝에 양봉").
     observation_low = 그 3음봉 구간의 최저가. ★이 순간이 곧 아래 ④의 "RESET 시점"이다.
     ★2026-07-19 심야: 3분봉 합성(_sync_bar3m/_grid3) 전부 삭제 — 완성된 1분봉만 쓴다.
  3. 그 양봉(마지막 캔들)이 직전 캔들(3번째 음봉)보다 거래량이 크고, 몸통(종가-시가)도 직전
     음봉 몸통보다 커야 한다 — 매수우위가 확실한 강한 반전만 인정(거래량만 크고 몸통이 작으면
     매수/매도가 팽팽히 맞선 것뿐이라 배제).
  4. 저점 확정 순간, 체결강도·매수체결량·매도체결량·거래량 4개 지표를 전부 RESET(그 순간을
     기준점 삼아 이후 "변화량"만 본다 — 절대값 비교는 더 이상 안 함).
  5. RESET 후 VLA_WATCH_MIN(60)초는 "최소 관찰기간"이다 — 이 동안은 매수/재탐색 판정을 하지
     않고 트렌드 데이터만 쌓는다(너무 이른 판단 방지용 워밍업). 60초 이후로는 신저가가 나오지
     않는 한 시간제한 없이 계속 관찰한다(저점의 90.9%가 결국 반등했다는 실측 근거 — 60초는
     "너무 이른 판단" 방지용 워밍업일 뿐 "포기 데드라인"이 아니다).
  6. VLA_WATCH_MIN 경과 후, 저점 대비 +1.0%~+1.5%(VLA_OBS_PCT_LO~HI) 반등 구간 안에서
     매 폴링마다 관찰기록을 전반부/후반부로 이등분해 4개 지표의 추세를 비교한다(_trend_judge):
       - 체결강도(che) 확연히 증가  - 매수체결량(seg_buy 구간증가분) 확연히 증가
       - 거래량(cum_vol 구간증가분) 확연히 증가  - 매도체결량(seg_sell 구간증가분) 확연히 감소
     ↑ 4개 전부 충족 → 경로①로 매수 확정.
     반대로 4개 전부(체결강도↓·매수↓·거래량↓·매도↑)면 → 그 저점을 포기하고 IDLE로 되돌아가
     "2차 하락지점"을 재탐색한다(RESET 이벤트). "확연히"의 기준은 VLA_TREND_MARGIN_PCT(10%) —
     전반부 대비 후반부가 이 비율 이상 차이 나야 증가/감소로 판정, 그 안쪽은 "보합"(계속 관찰).
     혼재(4개 중 일부만 유리/불리)도 계속 관찰 — 매수도 재탐색도 하지 않는다.
  7. 관찰 중 신저가가 나오면 observation_low를 그 값으로 즉시 갱신, RESET(4개 지표+트렌드
     기록 전부 초기화, 대기시간 없음 — 새 저점 기준으로 처음부터 다시 관찰).
  8. 경로②는 위 4~6과 별개로, WATCHING_LOW 상태인 동안 현재가가 20일선 위에 있으면
     5일선/10일선에 닿거나 넘는 조건이 연속 2개(VLA_MA_CONFIRM) **1분봉** 동안 유지돼야
     매수한다(반등폭·체결비율 조건은 없음). ★2026-07-19 심야: 3분봉 삭제로 확인시간이
     6분→2분으로 단축됨(원래 26일 백테스트는 3분봉 기준이었으므로 재검증 필요). 조건이
     중간에 깨지면 확인 카운트가 0으로 리셋되고 처음부터 다시 쌓아야 한다.
  9. 매수 후 재관찰: 매수가 대비 -2.5%(VLA_REBUY_STOP) 떨어지면 즉시 매도 후 1~8단계를 다시
     밟아 신저점을 찾는다(★2026-07-19 심야: 구 -2%재매수손절/-4%재난손절 이원 체제를 -2.5%
     단일 하드손절로 통합 — 원래 -2%가 항상 먼저 걸려 -4%는 도달 불가능한 죽은 조건이었다).
     재매수는 종목당 최대 VLA_REBUY_MAX(1)회까지(총 2번=최초+재매수1, 배선은
     valley_hunter_live_v1.py).
  10. 신규 매수는 09:30~14:30(VLA_ENTRY~VLA_ENTRY_END)만 허용. 14:30 이후로는 새 저점을
     찾아도 매수하지 않는다(보유 종목 매도는 계속 작동 — valley_hunter_live_v1.py 참고).

  ⚠️ 매수/매도 체결량 자체는 "이번 폴링 사이 늘어난 누적거래량을, 가격이 오르면 매수/내리면 매도로
     분류"하는 근사다. 체결강도(che)만 실제 키움 값(호출측이 조회해 feed()에 넘겨줌)이고 나머지
     3개는 근사치다. 임계값(1~1.5%/-5%/3연속음봉/60초/10%마진/-2.5%/재매수1회)은 전부 원칙 기반
     추정치이며 진짜 검증은 실전 로그(valley_low_buy_live.csv)로 해야 한다.

■ 사용법 (실전 엔진에 붙일 때)
    la = LowAnchor(code)
    ...매 폴링마다(2초 권장)...
    ev = la.feed(hm, cur, cum_vol, now_ts, daily_ma5, bar1m, daily_ma10, daily_ma20, daily_ma60, che)
    if ev and ev["signal"] == "BUY":
        ...매수 주문은 호출측(valley_hunter_live_v1 등)이 처리...
    che는 호출측이 별도 조회해 넘기는 실제 키움 체결강도(예: valley_hunter_live_v1._che(code)) —
    안 넘기면(기본 0.0) 경로①은 체결강도 조건이 항상 "보합" 취급돼 매수가 나지 않는다.

■ 스위치 (환경변수 — 전부 VLA_ 접두어로 급락주 LA_*와 완전 분리)
  VLA_PEAK_DROP_PCT=-3.0   ma5_above_peak 대비 이 이상(%) 빠져야 저점 관찰 후보(횡보 차단·★7/20 -5→-3)
  VLA_BEARISH_3M_N=3       완성 1분봉 연속 음봉 요구 개수(그 다음 양봉 1개 필요·이름은 유지)
  VLA_OBS_PCT_LO=1.0       매수구간(경로①) 하한(%) — 저점 대비 반등폭
  VLA_OBS_PCT_HI=1.5       매수구간(경로①) 상한(%)
  VLA_WATCH_MIN=60         RESET(저점확정/갱신) 후 최소 관찰기간(초) — 이 안에는 매수/재탐색 판정 안 함(워밍업).
                           경과 후엔 시간제한 없이 신저가가 나올 때까지 계속 관찰(★90초 타임아웃
                           제거 결론과 동일 정신 — 데드라인이 아니라 "너무 이른 판단" 방지용).
  VLA_TREND_MARGIN_PCT=10  관찰기록을 전반/후반으로 나눠 비교할 때 "확연히" 증가/감소로 볼 차이(%).
                           이 안쪽 차이는 보합(계속 관찰, 매수도 재탐색도 안 함).
  VLA_REBUY_STOP=-2.5      매수가 대비 이만큼(%) 떨어지면 즉시 매도 후 재관찰(하드손절 문턱)
  VLA_REBUY_MAX=1          재매수 최대 허용 횟수(1=최초매수+재매수1회=총 2번만)
  VLA_MA_CONFIRM=2         경로② 5/10일선 돌파 조건이 연속 유지돼야 하는 1분봉 수(0=즉시매수·휩쏘취약)
  VLA_ENTRY=0930 VLA_ENTRY_END=1430   신규 매수를 허용하는 시각 구간
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List

try:                                     # 콘솔 코드페이지(cp949)가 —/≥ 같은 문자를 못 받아 죽는 것 방지
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★[2026-07-19 심야 통합패치] PEAK_DROP_PCT 기본값 -3→-5로 통일(사용자 지시 — 하락기준을
#   "5일선위 고점 대비 -5%" 단일 기준으로 통합). BEARISH_3M_N은 이름은 남기지만 이제 "1분봉" 개수다
#   (3분봉 로직 전부 삭제).
# ★[2026-07-20 개장전 사용자 지시] -5 → -3 되돌림(횡보 차단 깊이 완화 — 관찰 후보 확대).
#   Gate1의 전일종가 -5%(GATE1_ARM_PCT)는 별개 파라미터로 그대로 -5.
PEAK_DROP_PCT = float(os.environ.get("VLA_PEAK_DROP_PCT", "-3.0"))
BEARISH_3M_N  = int(os.environ.get("VLA_BEARISH_3M_N", "3"))   # ★이름은 유지, 실제로는 완성 1분봉 연속음봉 개수
OBS_PCT_LO    = float(os.environ.get("VLA_OBS_PCT_LO", "1.0"))
OBS_PCT_HI    = float(os.environ.get("VLA_OBS_PCT_HI", "1.5"))
WATCH_MIN     = float(os.environ.get("VLA_WATCH_MIN", "60"))    # RESET 후 최소 관찰기간(초) — 데드라인 아님, 워밍업
TREND_MARGIN_PCT = float(os.environ.get("VLA_TREND_MARGIN_PCT", "10"))   # 전반/후반 비교 "확연히" 판정 마진(%)
ENTRY_HM      = os.environ.get("VLA_ENTRY", "0900")   # ★[7/19 구조 정상화 8] 기본값=운영값(Gate1 09:00) 정렬
ENTRY_END     = os.environ.get("VLA_ENTRY_END", "1430")
# ★[2026-07-19 심야] -2%/-4% 이원 손절 폐기, -2.5% 단일 하드손절로 통합(valley_hunter_live_v1.py에서 사용).
REBUY_STOP    = float(os.environ.get("VLA_REBUY_STOP", "-2.5"))   # valley_hunter_live_v1.py 배선용(하드손절 문턱)
REBUY_MAX     = int(os.environ.get("VLA_REBUY_MAX", "1"))       # valley_hunter_live_v1.py 배선용
MA_CONFIRM    = int(os.environ.get("VLA_MA_CONFIRM", "2"))      # 경로② 돌파 확인 1분봉 수(★3분봉 삭제로 6분→2분 단축. 원 26일 백테스트는 3분봉 기준이었음 — 재검증 필요)
# ★[2026-07-20 골짜기+급락주 게이트 통합] Gate1 — 09:00~09:30엔 급락주 원본 기준(전일종가 대비 -5%)으로도
#   저점 관찰을 시작할 수 있다(entry_gate="MORNING_CRASH"). 09:30 이후는 기존 Gate2(entry_gate="VALLEY_PEAK",
#   5일선위고점 대비 -5%) 그대로. 어느 게이트로 무장되든 그 뒤 저점탐색(1분봉 패턴·반등품질 판정)은 100% 동일.
#   급락주 원본의 90초 저점확정·체결강도105 절대값·90초 타임아웃·전용 매도·09:20 강제청산은 이식하지 않는다.
# ★[2026-07-19 자금유입 게이트] 경로② 매수 직전 검사 스위치
MG_CHASE_PCT  = float(os.environ.get("VLA_MG_CHASE_PCT", "1.5"))   # 이평선 대비 이 %(초과)면 추격 금지
MG_WIN_SEC    = float(os.environ.get("VLA_MG_WIN_SEC", "60"))      # 돈유입 판정 창(초·전/후반 이등분 비교)
GATE1_START   = os.environ.get("VLA_GATE1_START", "0900")
GATE1_END     = os.environ.get("VLA_GATE1_END", "0930")
GATE1_ARM_PCT = float(os.environ.get("VLA_GATE1_ARM_PCT", "-5"))


def trend_pct_changes(trend_log):
    """judge_trend와 같은 전반/후반 비교를 "방향(-1/0/1)"이 아니라 실제 변화율(%)로 반환한다.
    로그 기록용(실측 매도패턴 학습 — valley_hunter_live_v1.py의 SELL_LOG). che는 평균값 변화율,
    buy/sell/vol은 구간증가분(속도) 변화율. 표본 부족(n<4)이면 전부 None."""
    n = len(trend_log)
    if n < 4:
        return {"che_pct": None, "buy_pct": None, "sell_pct": None, "vol_pct": None}
    mid = n // 2
    first, second = trend_log[:mid], trend_log[mid:]

    def _avg(rows, i):
        return sum(r[i] for r in rows) / len(rows)

    def _delta(rows, i):
        return (rows[-1][i] or 0.0) - (rows[0][i] or 0.0)

    def _pct(a, b):
        base = max(abs(a), 1e-9)
        return (b - a) / base * 100.0

    che_f, che_s = _avg(first, 1), _avg(second, 1)
    buy_f, buy_s = _delta(first, 2), _delta(second, 2)
    sell_f, sell_s = _delta(first, 3), _delta(second, 3)
    vol_f, vol_s = _delta(first, 4), _delta(second, 4)
    return {"che_pct": round(_pct(che_f, che_s), 1), "buy_pct": round(_pct(buy_f, buy_s), 1),
            "sell_pct": round(_pct(sell_f, sell_s), 1), "vol_pct": round(_pct(vol_f, vol_s), 1)}


def direction_persists(trend_log, field_idx, want_sign, min_run=2):
    """judge_trend(전후반 평균비교="가속도")를 보완하는 방향성 지속 판정.
    field_idx의 누적값에서 "폴링간 증분"을 뽑아, 최근 min_run+1개가 want_sign 방향으로 계속
    유지되는지 본다(가속 없이 일정한 속도로만 흘러도 잡아냄 — judge_trend는 전반과 후반의 "속도차"가
    커야만 반응하므로, 일정속도로 계속 한쪽으로만 흐르는 완만한 추세는 놓친다).
    want_sign<0: 매수감소 — 증분이 비증가로 연속 유지되면 인정(활동 자체가 0인 것도 "감소의 극한"으로 인정).
    want_sign>0: 매도증가 — 증분이 비감소로 연속 유지"되고 실제로 그 방향 활동이 있어야"(마지막 증분>0)
    인정한다 — 그냥 등호(<=/>=)만 쓰면 "그 방향 활동이 계속 0(아예 없음)"인 등속 구간도 통과해버려서
    (예: 반등 중이라 매도가 전혀 없는데 "매도증가"로 오판) 매수/매도 규칙을 비대칭으로 둔다.
    ★valley_hunter_live_v1.py 매도 판정에서 judge_trend와 OR로 결합해 쓴다(둘 중 하나만 충족해도 인정)."""
    vals = [r[field_idx] for r in trend_log]
    if len(vals) < min_run + 2:
        return False
    inc = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    tail = inc[-(min_run + 1):]
    if want_sign < 0:
        monotone = all(tail[i] <= tail[i - 1] for i in range(1, len(tail)))
        has_real_drop = any(tail[i] < tail[i - 1] for i in range(1, len(tail)))
        return monotone and (tail[-1] <= 1e-9 or has_real_drop)
    monotone = all(tail[i] >= tail[i - 1] for i in range(1, len(tail)))
    return monotone and tail[-1] > 1e-9


def judge_trend(trend_log, margin_pct):
    """관찰기록((t,che,buy_cum,sell_cum,vol_cum) 튜플 리스트)을 전반/후반으로 이등분해
    체결강도·매수체결량·매도체결량·거래량 4개 지표의 "확연한" 증감을 판정한다.
    che는 순간값이라 구간평균, 나머지 3개는 누적값이라 구간증가분(끝값-처음값)으로 비교한다.
    ★valley_hunter_live_v1.py의 매도(고점앙커 관찰)도 이 함수를 그대로 재사용한다 — 매수/매도
    양쪽에서 "확연한 증감"의 정의가 갈리면 왜 다른지 설명할 수 없어야 하는 판정이라 공유한다.
    반환: {"che":1|0|-1, "buy":.., "sell":.., "vol":..} (1=확연히증가 -1=확연히감소 0=보합) 또는 None(표본부족)."""
    n = len(trend_log)
    if n < 4:
        return None
    mid = n // 2
    first, second = trend_log[:mid], trend_log[mid:]

    def _avg(rows, i):
        return sum(r[i] for r in rows) / len(rows)

    def _delta(rows, i):
        return (rows[-1][i] or 0.0) - (rows[0][i] or 0.0)

    def _dir(a, b):
        base = max(abs(a), 1e-9)
        margin = margin_pct / 100.0
        if b >= a + base * margin:
            return 1
        if b <= a - base * margin:
            return -1
        return 0

    che_f, che_s = _avg(first, 1), _avg(second, 1)
    buy_f, buy_s = _delta(first, 2), _delta(second, 2)
    sell_f, sell_s = _delta(first, 3), _delta(second, 3)
    vol_f, vol_s = _delta(first, 4), _delta(second, 4)
    return {"che": _dir(che_f, che_s), "buy": _dir(buy_f, buy_s),
            "sell": _dir(sell_f, sell_s), "vol": _dir(vol_f, vol_s)}


def _hm_minus1(hm):
    """HHMM에서 1분 뺀 HHMM."""
    try:
        m = int(hm[:2]) * 60 + int(hm[2:]) - 1
        if m < 0:
            m += 24 * 60
        return f"{m // 60:02d}{m % 60:02d}"
    except Exception:
        return hm


@dataclass
class LowAnchor:
    """종목 1개짜리 저점 앵커 매수 판정 상태기계. 주문 없음 — 판정만 반환한다.
       상태 = IDLE(대기) → WATCHING_LOW(저점 관찰중) → done(매수 확정)."""
    code: str
    peak_drop_pct: float = PEAK_DROP_PCT
    bearish_n: int = BEARISH_3M_N
    obs_pct_lo: float = OBS_PCT_LO
    obs_pct_hi: float = OBS_PCT_HI
    watch_min: float = WATCH_MIN
    trend_margin_pct: float = TREND_MARGIN_PCT
    ma_touch_margin_pct: float = 0.0   # ★경로② 이평선 접촉 판정을 "이평선 대비 이만큼(%) 더 위"로 강화(스윕용, 기본 0=마진없음)
    ma_touch_confirm_bars: int = MA_CONFIRM   # ★경로② 돌파를 몇 번의 1분봉 동안 더 유지해야 확정 매수할지(기본 VLA_MA_CONFIRM=2, ★2026-07-19 심야 3분봉→1분봉 전환으로 실질 확인시간이 6분→2분으로 짧아짐)

    ma5_above_peak: Optional[float] = field(default=None, init=False)   # 5일선 위에서 형성된 당일 고점
    state: str = field(default="IDLE", init=False)   # IDLE / WATCHING_LOW
    observation_low: Optional[float] = field(default=None, init=False)

    bar1m_hist: List[list] = field(default_factory=list, init=False)   # 완성 1분봉 [hm,o,h,l,c,vol] (최근 15개)
    last_captured_1m_hm: Optional[str] = field(default=None, init=False)

    reset_ts: Optional[float] = field(default=None, init=False)   # RESET(저점확정/갱신) 시각 — VLA_WATCH_MIN 경과 판정용
    ma_touch_confirmed_bars: int = field(default=0, init=False)   # 경로② 돌파조건이 연속으로 유지된 1분봉 수

    seg_buy: float = field(default=0.0, init=False)
    seg_sell: float = field(default=0.0, init=False)
    last_cum_vol: Optional[float] = field(default=None, init=False)
    last_px: Optional[float] = field(default=None, init=False)
    last_dir: int = field(default=0, init=False)

    trend_log: List[tuple] = field(default_factory=list, init=False)   # RESET 이후 (t,che,seg_buy,seg_sell,cum_vol) 스냅샷 — 전반/후반 추세비교용

    decided: bool = field(default=False, init=False)   # 이번 저점에서 이미 WAIT 로그를 냈는가(중복 억제용)
    done: bool = field(default=False, init=False)       # 매수 확정 후에는 더 이상 판정 안 함(한 종목 1회)
    entry_gate: Optional[str] = field(default=None, init=False)   # "MORNING_CRASH"(Gate1) 또는 "VALLEY_PEAK"(Gate2) — 어느 게이트로 무장됐는지(승률·기대값 비교용)
    # ★[2026-07-20] Gate1 전용 — 급락주 원본처럼 -5%로 한 번 무장되면(3연속음봉 조건 없이) 그 뒤
    #   최저가만 계속 추적하다가, 완성 1분봉이 양봉이기만 하면 그 추적해온 최저가로 확정한다.
    #   (3연속음봉+거래량/몸통비교는 Gate2 전용 조건 — 사용자 지시로 Gate1에서 분리)
    gate1_armed: bool = field(default=False, init=False)
    gate1_cand_low: Optional[float] = field(default=None, init=False)
    # ★[2026-07-19 친구님 지시4] -5% 무장 순간의 시각·가격 기록(실시간 2초 폴링 시점)
    gate1_armed_ts: Optional[float] = field(default=None, init=False)
    gate1_armed_px: Optional[float] = field(default=None, init=False)

    def _reset_seg(self, cur, cum_vol, now_ts):
        self.seg_buy = self.seg_sell = 0.0
        self.last_cum_vol = cum_vol
        self.last_px = cur
        self.last_dir = 0
        self.decided = False
        self.reset_ts = now_ts
        self.trend_log = []

    def _trend_judge(self):
        """RESET 이후 관찰기록을 전반/후반으로 이등분해 4개 지표의 추세를 판정.
        반환: {"che":1|0|-1, "buy":.., "sell":.., "vol":..} (1=확연히증가 -1=확연히감소 0=보합) 또는 None(표본부족)."""
        return judge_trend(self.trend_log, self.trend_margin_pct)

    def _seg_update(self, cur, cum_vol):
        """매 폴링마다 저점 구간 매수/매도 체결량(근사) 누적 — 이번 폴링 사이 늘어난 누적거래량을,
           가격이 오르면 매수/내리면 매도로 분류한다."""
        if self.last_px is not None and cum_vol is not None and self.last_cum_vol is not None:
            dv = max(0.0, cum_vol - self.last_cum_vol)
            d = self.last_dir
            if cur > self.last_px:
                d = 1
            elif cur < self.last_px:
                d = -1
            if d > 0:
                self.seg_buy += dv
            elif d < 0:
                self.seg_sell += dv
            self.last_dir = d
        self.last_px = cur
        if cum_vol is not None:
            self.last_cum_vol = cum_vol

    def _capture_bar1m(self, hm, bar1m) -> bool:
        """이번 분(hm)이 직전 폴링과 다르면(분이 바뀌면) 방금 완성된 분(bar1m["prev"][-1]/["pv"][-1])을
           1분봉 히스토리에 쌓는다. 최근 15개만 유지.
           반환: 이번 호출에서 새 완성봉을 캡처했으면 True(=1분봉이 막 완성된 시점), 아니면 False.
           ★[2026-07-19 심야] 3분봉 합성(_sync_bar3m/_grid3) 전부 삭제 — 저점확정·경로② 확인봉수
           전부 이 1분봉 완성 시점 기준으로 판정한다(사용자 지시: 3분봉 로직 전부 삭제)."""
        if not bar1m or hm == self.last_captured_1m_hm:
            self.last_captured_1m_hm = hm
            return False
        prev = bar1m.get("prev") or []
        pv = bar1m.get("pv") or []
        captured = False
        if prev and pv:
            try:
                o, h, l, c = [float(x) for x in prev[-1][:4]]
                v = float(pv[-1])
                prev_hm = _hm_minus1(hm)
                if not self.bar1m_hist or self.bar1m_hist[-1][0] != prev_hm:
                    self.bar1m_hist.append([prev_hm, o, h, l, c, v])
                    self.bar1m_hist = self.bar1m_hist[-15:]
                    captured = True
            except Exception:
                pass
        self.last_captured_1m_hm = hm
        return captured

    def feed(self, hm: str, cur: float, cum_vol: Optional[float], now_ts: float,
             daily_ma5: float, bar1m: Optional[Dict] = None,
             daily_ma10: Optional[float] = None, daily_ma20: Optional[float] = None,
             daily_ma60: Optional[float] = None, che: float = 0.0,
             prev_close: Optional[float] = None, money_flow: bool = False) -> Optional[Dict]:
        """매 폴링(권장 2초)마다 호출.
        hm="HHMM", cur=현재가, cum_vol=누적거래량(방향분류용), now_ts=time.time(),
        daily_ma5=일봉 5일선, bar1m=이번 분 1분봉 전체 dict({o,h,l,c,prev,v,pv,...} — peak추적·저점확정용),
        daily_ma10/20/60=일봉 10/20/60일선(경로② 판정·20일선 필터용, ma60은 현재 미사용),
        che=현재 체결강도(호출측이 조회해 넘김·경로①의 반등품질 판정에 씀),
        prev_close=전일종가(Gate1·09:00~09:30 전용 — 없으면 그 시간대엔 관찰 자체가 시작 안 됨).
        money_flow=True면 셋째 진입경로 MONEY_FLOW_ENTRY(2026-07-21, valley_hunter_live_v1.py의
        Money Flow TOP5+MONEY_START 후보에서만 True로 넘어옴) — Gate1/Gate2 조건과 무관하게 저점관찰을 시작.
        Gate1(MORNING_CRASH)·Gate2(VALLEY_PEAK) 판정 로직은 이 인자와 완전히 무관·무변경.
        반환: None(관망 지속) 또는 이벤트 dict
        {"signal": "WATCH_START"|"WAIT"|"RESET"|"BUY", "observation_low", "entry_px",
         "seg_buy", "seg_sell", "trend", "quality_desc", "reason", "entry_gate", "hm"}"""
        if self.done or cur <= 0:
            return None
        if hm < ENTRY_HM or hm > ENTRY_END:
            return None
        in_gate1_window = GATE1_START <= hm < GATE1_END
        # ★[2026-07-20] 09:30 경계 강제 컷 — Gate1(MORNING_CRASH)로 armed된 채 아직 미체결로 경계를
        #   넘으면 그 사이클을 즉시 폐기하고 IDLE로 되돌린다. ★[2026-07-19 테스트 교정] 아래
        #   daily_ma5 필수검사보다 먼저 수행 — ma5 결측 종목이 경계컷에 못 닿던 순서 결함 수정.
        if self.entry_gate == "MORNING_CRASH" and not self.done and hm >= GATE1_END:
            self.state = "IDLE"
            self.observation_low = None
            self.entry_gate = None
            self.ma_touch_confirmed_bars = 0
            self.gate1_armed = False
            self.gate1_cand_low = None
            self.gate1_armed_ts = None
            self.gate1_armed_px = None
            # 이번 폴링은 그대로 흘러 아래 IDLE 분기가 Gate2 기준으로 즉시 재평가한다(신호 유실 없음)
        # ★[2026-07-20] Gate1(전일종가 기준)은 daily_ma5가 없어도 성립해야 한다 — daily_ma5는
        #   Gate2(5일선위고점 기준)와 아래 고점추적 전용 필수데이터다. 결측(신규상장 등)으로
        #   Gate1 자체가 막히면 안 됨(필수 데이터 조건 분리).
        if not in_gate1_window and (not daily_ma5 or daily_ma5 <= 0):
            return None

        # ── 5일선 위 최고점 추적 — 5일선 아래에서 형성된 고가는 반영하지 않는다(횡보구간 차단용) ──
        bar1m_h = float(bar1m["h"]) if bar1m and bar1m.get("h") is not None else None
        cand = max(cur, bar1m_h) if bar1m_h else cur
        if cand > daily_ma5:
            if self.ma5_above_peak is None or cand > self.ma5_above_peak:
                self.ma5_above_peak = cand

        # ── Gate1(09:00~09:30) 후보저점 실시간 추적 — 급락주 원본처럼 한 번 -5%로 무장되면(gate1_armed)
        #    3연속음봉 조건 없이 이후 계속 최저가만 갱신한다. IDLE 상태에서만 추적(WATCHING_LOW 진입 후엔
        #    그쪽 저점 갱신 로직이 대신함). 사용자 지시(2026-07-20)로 Gate2의 3연속음봉 조건과 분리. ──
        if self.state == "IDLE" and GATE1_START <= hm < GATE1_END and prev_close and prev_close > 0:
            if not self.gate1_armed:
                if (cur / prev_close - 1) * 100 <= GATE1_ARM_PCT:
                    self.gate1_armed = True
                    self.gate1_cand_low = cur
                    self.gate1_armed_ts = now_ts    # ★[지시4] 무장 시각·가격 기록(반등해 -5% 위로 가도 유지=지시5)
                    self.gate1_armed_px = cur
            elif self.gate1_cand_low is None or cur < self.gate1_cand_low:
                self.gate1_cand_low = cur

        new_bar1 = self._capture_bar1m(hm, bar1m)

        # ★[2026-07-19 심야] "3분봉 로직 전부 삭제" 지시로 3분봉 합성을 제거하고 완성된 1분봉만
        #   쓴다. 저점 확정(IDLE→WATCHING_LOW)과 경로②(이평선 돌파 확인봉수)는 1분봉이 막 완성된
        #   시점에만 판정한다. 경로①(반등품질 변화량 판정)은 60초 관찰이라는 실시간 스케일이 필요해
        #   이 1분봉 게이트에서 분리했다(아래 WATCHING_LOW 블록 참고) — 신저가 감지도 반등%가
        #   정확해야 하므로 함께 실시간화.
        if self.state == "IDLE":
            if not new_bar1:
                return None
            entry_gate = None
            drop = None
            if money_flow:
                # ── MONEY_FLOW_ENTRY(2026-07-21 골짜기 연동 최종패치) — Money Flow가 이미
                #    TOP5 AND MONEY_START=True로 걸러서 넘긴 종목만 money_flow=True로 들어온다.
                #    Gate1(5%무장+양봉전환)·Gate2(5일선-5%+3연속음봉) 조건 전혀 없음 — 새 점수·새
                #    상태머신·새 랭킹 추가 안 함(지시). 진입은 즉시 저점관찰 시작뿐, 그 이후
                #    판단(반등품질·체결강도·손절·매도)은 전부 아래 기존 골짜기 공통 로직이 그대로
                #    수행한다(저점형성·저점재이탈없음도 공통 WATCHING_LOW 블록 재사용 — 새 로직 없음).
                _lhm, lo, lh, ll, lc, lv = self.bar1m_hist[-1]
                entry_gate = "MONEY_FLOW"
                self.observation_low = min(ll, cur)
            elif GATE1_START <= hm < GATE1_END:
                # ── Gate1(09:00~09:30) — 급락주 원본 기준: 전일종가 대비 -5%로 무장(gate1_armed,
                #    위 실시간 블록에서 세팅)된 뒤, 3연속음봉 선행조건 없이 완성 1분봉이 양봉이기만
                #    하면 그 즉시 무장 후 추적해온 최저가를 저점으로 확정한다(사용자 지시 2026-07-20
                #    — 3연속음봉+거래량/몸통비교는 Gate2 전용 조건이라 여기선 쓰지 않는다). ──
                if not self.gate1_armed:
                    return None   # 아직 -5% 무장 안 됨
                _lhm, lo, lh, ll, lc, lv = self.bar1m_hist[-1]
                if not (lc > lo):
                    return None   # 방금 완성된 봉이 양봉 아니면 계속 대기(무장 상태는 유지)
                entry_gate = "MORNING_CRASH"
                self.observation_low = self.gate1_cand_low if self.gate1_cand_low is not None else min(ll, cur)
                drop = (self.observation_low / prev_close - 1) * 100 if prev_close else None
                armed_px, armed_ts = self.gate1_armed_px, self.gate1_armed_ts   # WATCH_START 이벤트로 보고 후 소거
                self.gate1_armed = False
                self.gate1_cand_low = None
                self.gate1_armed_ts = None
                self.gate1_armed_px = None
            else:
                # ── Gate2(09:30~) — 기존 골짜기 사냥꾼 기준: 5일선위고점 대비 -5% + 3연속음봉후양봉전환 ──
                if self.ma5_above_peak is None:
                    return None   # 5일선 위 최고점 자체가 없음 — 관찰 금지
                if cur >= daily_ma5:
                    return None   # 아직 5일선 위 — 대상 아님
                drop = (cur / self.ma5_above_peak - 1) * 100
                if drop > self.peak_drop_pct:
                    return None   # 최고점 대비 낙폭이 아직 문턱(기본 -5%) 미만(횡보 구간 차단)
                need = self.bearish_n + 1   # N개 연속 음봉(1분봉) + 그 다음 양봉 1개 — Gate2 전용
                if len(self.bar1m_hist) < need:
                    return None
                lastn = self.bar1m_hist[-need:]   # [hm,o,h,l,c,vol]
                bears, bull = lastn[:-1], lastn[-1]
                if not all(c < o for (_hm, o, h, l, c, vol) in bears):
                    return None   # N연속 음봉 조건 미충족
                _bhm, bo, bh, bl, bc, bvol = bull
                if not (bc > bo):
                    return None   # 그 다음 봉이 양봉으로 전환 안 함
                # ★거래량이 직전 캔들(N번째 음봉)보다 크고, 몸통도 직전 음봉 몸통보다 커야 함
                _phm, prev_o, prev_h, prev_l, prev_c, prev_vol = bears[-1]
                bull_body = bc - bo
                prev_body = prev_o - prev_c
                if not (bvol > prev_vol and bull_body > prev_body):
                    return None
                entry_gate = "VALLEY_PEAK"
                # (전환 양봉 저가 포함안은 친구님 재지시로 미반영 — 백테 A/B 비교 후 결정. 관찰 중
                #  실시간 신저가 갱신이 완화 장치로 이미 작동)
                self.observation_low = min(l for (_hm, o, h, l, c, vol) in bears)
            # ── 공통: 전 조건 충족 → 저점 관찰 시작 ──
            self.state = "WATCHING_LOW"
            self.entry_gate = entry_gate
            self._reset_seg(cur, cum_vol, now_ts)
            base_pct = -GATE1_ARM_PCT if entry_gate == "MORNING_CRASH" else -self.peak_drop_pct
            base_desc = "전일종가" if entry_gate == "MORNING_CRASH" else "5일선위고점"
            candle_desc = "양봉전환" if entry_gate == "MORNING_CRASH" \
                else f"5일선아래{self.bearish_n}연속1분음봉후양봉전환(거래량·몸통확대)"
            if entry_gate == "MONEY_FLOW":   # 위 두 줄(MORNING_CRASH/VALLEY_PEAK)은 무변경 — 로그 표기만 덮어씀
                base_pct, base_desc, candle_desc = 0.0, "MoneyFlowTOP5+MONEY_START", "저점형성"
            return {"signal": "WATCH_START", "observation_low": self.observation_low,
                    "ma5_above_peak": self.ma5_above_peak,
                    "drop_pct": (round(drop, 2) if drop is not None else None),
                    "entry_gate": entry_gate,
                    "armed_px": (armed_px if entry_gate == "MORNING_CRASH" else None),
                    "armed_ts": (armed_ts if entry_gate == "MORNING_CRASH" else None),
                    "reason": f"[{entry_gate}]{base_desc}대비{base_pct:.0f}%하락+{candle_desc}",
                    "hm": hm}

        # ── state == WATCHING_LOW ──
        if cur < self.observation_low:
            self.observation_low = cur
            self._reset_seg(cur, cum_vol, now_ts)   # 신저가 — 대기시간 없이 즉시 저점 갱신·카운터·시계 리셋
            return None

        # ── 경로② : 현재가가 20일선 위에 완전히 올라서 있을 때만("우상향 중"의 실질 기준),
        #    5일선/10일선 접촉·돌파 시 반등폭·품질과 무관하게 즉시 매수. 경로①과 완전히
        #    별개(OR). ★[2026-07-19] 정배열(5>20>60 이평선끼리의 순서)에서 "현재가>20일선"으로
        #    교체 — 이평선 순서보다 가격이 실제로 20일선 위에 있는지가 우상향 판정의 핵심이었음.
        #    20일선 아래면 이 경로 자체가 꺼짐(횡보구간에서 이평선 오르락내리락하며 잘못 사는 문제 차단).
        #    ★[2026-07-19 심야] 확인봉수(ma_touch_confirm_bars)는 이제 "1분봉 수"다(3분봉 삭제로
        #    실질 확인시간이 6분→2분으로 짧아짐) — 1분봉이 막 완성된 시점에만 갱신한다(안 그러면
        #    실시간 폴링마다 카운터가 순식간에 넘쳐 휩쏘취약 즉시매수와 같아져버림). ──
        # ★[2026-07-19 통합지침서] 경로②(이평선 터치)는 Gate2 전용 — Gate1(MORNING_CRASH)에선 절대
        #   사용하지 않는다(같은 날 "공용 유지" 결정을 지침서가 뒤집음 — 최신 지시 우선).
        # ★[2026-07-19 기술결함 수정 — 전략 로직 무변경(친구님 재지시: 교차 조건은 백테 비교 후)]
        #   ⑴판정은 실시간 현재가가 아니라 **완성봉 종가**(pc1) — "새 분 첫 틱" 오판 제거 (결함6)
        #   ⑵Off-by-One 수정 — 확인봉 N이면 정확히 N번째 조건충족 봉에서 매수 (결함4)
        #   조건 자체(이평선 위면 인정·교차 불요)는 기존 방식 그대로 유지 — 교차 방식은 전략3 백테에서 비교.
        if new_bar1 and self.entry_gate != "MORNING_CRASH" and self.bar1m_hist:
            pc1 = float(self.bar1m_hist[-1][4])   # 방금 완성된 봉 종가
            m = 1.0 + self.ma_touch_margin_pct / 100.0
            above_ma20 = (daily_ma20 is not None and daily_ma20 > 0 and pc1 > daily_ma20)
            touched_ma = ((daily_ma5 is not None and daily_ma5 > 0 and pc1 >= daily_ma5 * m)
                          or (daily_ma10 is not None and daily_ma10 > 0 and pc1 >= daily_ma10 * m))
            if above_ma20 and touched_ma:
                self.ma_touch_confirmed_bars += 1
                if self.ma_touch_confirmed_bars >= max(1, self.ma_touch_confirm_bars):
                    # ★[2026-07-19 자금유입 게이트(친구님 지시·"맞는 것만")] 매수 직전 2중 검사 —
                    #   ⑥추격금지: 완성봉 종가가 (밟고 선) 이평선보다 +MG_CHASE_PCT% 이상 위면 매수 금지
                    #     (실측: 저점比 +13.5% 위치 매수들이 경로② 손실 주범). 카운터는 유지 — 눌리면 재평가.
                    #   ④돈유입: 최근 MG_WIN_SEC(60초) 전/후반 비교(경로①과 같은 judge_trend·마진 10%)
                    #     체결강도↑ ∧ 매수체결↑ ∧ (거래량↑ ∨ 매도체결↓) 3조건 — 미충족 시 매수 보류(관찰 계속).
                    #   ※교차 필수·횡보 필터는 백테(14일)에서 골짜기 內 거래 전멸(1→0건)이라 미채택.
                    lines = [x for x in (daily_ma5, daily_ma10) if x and x > 0 and pc1 >= x * m]
                    near = max(lines) if lines else 0.0
                    if near <= 0 or pc1 > near * (1 + MG_CHASE_PCT / 100.0):
                        return None    # 이평선 위 +1.5% 초과 = 추격 금지
                    mg_win = [r for r in self.trend_log if now_ts - r[0] <= MG_WIN_SEC]
                    tr2 = judge_trend(mg_win, self.trend_margin_pct)
                    if not tr2 or not (tr2["che"] > 0 and tr2["buy"] > 0
                                       and (tr2["vol"] > 0 or tr2["sell"] < 0)):
                        return None    # 돈 유입 미확인 — 매수 보류(다음 폴링/봉에서 재평가)
                    self.done = True
                    return {"signal": "BUY", "observation_low": self.observation_low, "entry_px": cur,
                            "rebound_pct": round((cur / self.observation_low - 1) * 100, 2), "trend": tr2,
                            "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                            "entry_gate": self.entry_gate,
                            "reason": f"20일선위5/10일선돌파+자금유입(체결강도·매수↑·"
                                      f"{self.ma_touch_confirmed_bars}봉확인·이평선+{MG_CHASE_PCT:.1f}%이내)",
                            "hm": hm}
            else:
                self.ma_touch_confirmed_bars = 0   # 돌파조건이 깨지면 확인 카운트 리셋(처음부터 다시)

        # ── 경로① : 저점 대비 +1.0~1.5%(VLA_OBS_PCT_LO~HI) 반등 구간에서, RESET(저점확정/갱신)
        #    시점 대비 "체결강도·매수체결량·매도체결량·거래량 변화량 추세"로 반등품질을 판정한다.
        #    절대 문턱(구 VLA_BUY_RATIO=105)은 안 씀. ★매 폴링(실시간)마다 트렌드 기록을 쌓는다
        #    (1분봉 게이트 밖 — 60초 관찰이 1분봉 스케일보다도 촘촘해야 의미가 있어서). ──
        self._seg_update(cur, cum_vol)
        if che and che > 0:
            self.trend_log.append((now_ts, che, self.seg_buy, self.seg_sell,
                                    cum_vol if cum_vol is not None else 0.0))
            if len(self.trend_log) > 900:   # 장마감까지 무제한 대기해도 메모리 안전(최근 표본만 유지)
                self.trend_log = self.trend_log[-900:]

        rebound_pct = (cur / self.observation_low - 1) * 100.0
        in_zone = self.obs_pct_lo <= rebound_pct <= self.obs_pct_hi
        elapsed = now_ts - (self.reset_ts if self.reset_ts is not None else now_ts)

        if in_zone and elapsed >= self.watch_min:
            tr = self._trend_judge()
            if tr is not None:
                if tr["che"] > 0 and tr["buy"] > 0 and tr["vol"] > 0 and tr["sell"] < 0:
                    self.done = True
                    return {"signal": "BUY", "observation_low": self.observation_low, "entry_px": cur,
                            "rebound_pct": round(rebound_pct, 2), "trend": tr,
                            "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                            "entry_gate": self.entry_gate,
                            "reason": "체결강도·매수체결량·거래량증가+매도체결량감소(반등품질확인)", "hm": hm}
                if tr["che"] < 0 and tr["buy"] < 0 and tr["vol"] < 0 and tr["sell"] > 0:
                    # ── "2차 하락지점을 찾는다" — 이 저점은 포기하고 IDLE로 되돌아가 재탐색 ──
                    prev_low = self.observation_low
                    prev_gate = self.entry_gate
                    self.state = "IDLE"
                    self.observation_low = None
                    self.entry_gate = None
                    self.gate1_armed = False   # Gate1이었다면 재탐색은 -5% 무장부터 다시(2차 하락지점 원칙과 동일)
                    self.gate1_cand_low = None
                    self.gate1_armed_ts = None
                    self.gate1_armed_px = None
                    return {"signal": "RESET", "observation_low": prev_low, "entry_px": cur,
                            "rebound_pct": round(rebound_pct, 2), "trend": tr, "entry_gate": prev_gate,
                            "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                            "reason": "체결강도·매수체결량·거래량감소+매도체결량증가(반등품질실패)", "hm": hm}

        # ★[2026-07-19] 시간 데드라인 없음 — 저점판정 자체는 90.9%가 반등하는 것으로 확인됐으니
        #   (22건 중 20건), 그 저점을 시간 제한으로 포기하지 않고 신저가가 나오지 않는 한 장마감까지
        #   계속 그 저점 기준으로 반등을 기다린다(VLA_WATCH_MIN은 워밍업일 뿐 포기 데드라인이 아님).

        if not self.decided:
            self.decided = True   # 같은 저점에서 WAIT 로그 반복 억제
            return {"signal": "WAIT", "observation_low": self.observation_low, "entry_px": cur,
                    "rebound_pct": round(rebound_pct, 2), "trend": self._trend_judge(), "entry_gate": self.entry_gate,
                    "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                    "reason": ("반등구간초과대기" if rebound_pct > self.obs_pct_hi
                               else ("관찰기간워밍업" if elapsed < self.watch_min else "반등품질혼재")),
                    "hm": hm}
        return None   # 관찰 지속


# ────────────────────────────────────────────────────────────────────────
# ★골짜기 사냥꾼 실전 유니버스에 붙는 live 모드 — 판정만 로그, 주문 없음
# ────────────────────────────────────────────────────────────────────────
LEDGER   = Path(os.environ.get("VLA_LEDGER") or r"C:\stock_bot\data\valley_low_buy_ledger.json")
CSVLOG   = Path(os.environ.get("VLA_CSV") or r"C:\stock_bot\LOG\valley_low_buy_live.csv")
LOG      = Path(r"C:\stock_bot\data\LOG\valley_low_buy_live.log")
LOOP_SEC = float(os.environ.get("VLA_LOOP_SEC", "2"))
RUN_SEC  = float(os.environ.get("VLA_RUN_SEC", "55"))

COLS = ["일자", "시각", "종목코드", "종목명", "판정", "저점", "5일선위최고점", "진입가",
        "반등률", "반등품질", "매수량", "매도량", "사유"]


def _trend_desc(tr):
    """trend dict({'che','buy','sell','vol'}: 1/0/-1)를 사람이 읽는 문자열로 축약."""
    if not tr:
        return ""
    lbl = {1: "↑", 0: "-", -1: "↓"}
    return f"체결{lbl[tr['che']]}매수{lbl[tr['buy']]}매도{lbl[tr['sell']]}거래량{lbl[tr['vol']]}"


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
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


def _csv_row(r):
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


LEDGER_FIELDS = ["ma5_above_peak", "state", "observation_low", "bar1m_hist", "last_captured_1m_hm",
                  "reset_ts", "seg_buy", "seg_sell",
                  "last_cum_vol", "last_px", "last_dir", "trend_log", "decided", "done", "entry_gate",
                  "gate1_armed", "gate1_cand_low", "gate1_armed_ts", "gate1_armed_px",
                  "ma_touch_confirmed_bars"]   # ★[7/19 구조 정상화 5] 재기동 시 확인봉 카운터 유지


def la_from_ledger(code, entry):
    """valley_hunter_live_v1.py 등 호출측이 재사용하는 헬퍼 — 장부(dict)에서 LowAnchor 복원."""
    la = LowAnchor(code=code)
    for k in LEDGER_FIELDS:
        if k in entry:
            setattr(la, k, entry[k])
    return la


def la_to_ledger(la):
    """valley_hunter_live_v1.py 등 호출측이 재사용하는 헬퍼 — LowAnchor 상태를 장부(dict)로 저장."""
    return {k: getattr(la, k) for k in LEDGER_FIELDS}


def _la_from_ledger(code, entry):   # 하위호환 별칭(이 파일 안 live_main 용)
    return la_from_ledger(code, entry)


def _la_to_ledger(la):
    return la_to_ledger(la)


def live_main():
    """★골짜기 사냥꾼 실전 유니버스(valley_hunter_live_v1._crash_map)에 저점앵커 판정을 붙인다.
       매수/매도 주문은 절대 내지 않는다 — 로그만 남긴다. valley_hunter_live_v1.py 자체가 이미
       실전 주문을 내므로, 이 함수는 예약작업으로 따로 돌리지 않는 독립 확인용이다."""
    sys.path.insert(0, r"C:\stock_bot\RUN")
    from valley_hunter_live_v1 import _crash_map, _cur, _cum_vol, _ma5_daily, _ma10_daily, \
        _ma20_daily, _ma60_daily, _bar1m, _che

    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < ENTRY_HM or hm > ENTRY_END:
        return
    _log("=" * 70)
    _log(f"🏔️📈 골짜기 저점 앵커 매수 판정(그림자·주문0) — 5일선위고점-{-PEAK_DROP_PCT:.0f}%+"
         f"5일선아래{BEARISH_3M_N}연속음봉후양봉전환(거래량·몸통확대) 관찰폭+{OBS_PCT_LO:.1f}~{OBS_PCT_HI:.1f}% "
         f"{WATCH_MIN:.0f}초워밍업 반등품질=체결강도·매수·거래량↑+매도↓(추세비교·마진{TREND_MARGIN_PCT:.0f}%) · "
         f"경로②=20일선위+5/10일선접촉돌파{MA_CONFIRM}봉확인매수")

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "codes": {}}
        _jsave(LEDGER, L)
    ma5d = _ma5_daily()
    ma10d = _ma10_daily()
    ma20d = _ma20_daily()
    ma60d = _ma60_daily()

    deadline = time.monotonic() + RUN_SEC
    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > ENTRY_END:
            break
        dirty = False
        cm = _crash_map()
        t = time.time()
        for code, info in cm.items():
            entry = L["codes"].get(code) or {}
            if entry.get("done"):
                continue
            la = _la_from_ledger(code, entry)
            cur = _cur(code); cv = _cum_vol(code); che = _che(code)
            if cur <= 0:
                continue
            b1 = _bar1m(code)
            ev = la.feed(hm, cur, cv, t, ma5d.get(code, 0), b1,
                         ma10d.get(code, 0), ma20d.get(code, 0), ma60d.get(code, 0), che,
                         prev_close=info.get("pc"))
            L["codes"][code] = _la_to_ledger(la)
            dirty = True
            if ev:
                nm = info.get("name", code)
                icon = {"BUY": "💰", "WATCH_START": "🏁", "RESET": "🔄"}.get(ev["signal"], "⏳")
                obs_low = ev.get("observation_low") if ev["signal"] == "RESET" else la.observation_low
                _log(f"  {icon}{ev['signal']} {nm}({code}) 저점{obs_low or 0:,.0f} "
                     f"5일선위고점{la.ma5_above_peak or 0:,.0f} [{ev['reason']}]")
                _csv_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": nm, "판정": ev["signal"], "저점": round(obs_low or 0),
                          "5일선위최고점": round(la.ma5_above_peak or 0),
                          "진입가": round(ev.get("entry_px") or cur),
                          "반등률": ev.get("rebound_pct"), "반등품질": _trend_desc(ev.get("trend")),
                          "매수량": ev.get("seg_buy"), "매도량": ev.get("seg_sell"), "사유": ev["reason"]})
        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    try:
        live_main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
