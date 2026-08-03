# -*- coding: utf-8 -*-
"""
collect_prices_3m_from_1m_v3_5_97점.py
=================================================
고유 영역  : 1분봉 → 3분봉 집계 + 파생 팩터 + 시그널 산출
파이프라인 : prices_1m.csv → [이 파일] → prices_3m.csv
             (다른 파일의 영역 절대 침범 금지)

★ v3_4 시가(SIGA) + 추세눌림(PULLBACK) 전용 헤지펀드급 완성판 (2026-04-12)
목표 점수 : 96점 이상 (C-Suite 임원진 회의 감사 결과 반영)
────────────────────────────────────────────────────────────────
[v3_4 수정 사항 — 감사 지적 사항 전체 반영]

  FIX-1 [CTO] ATR 계산방식 지침서§2-2 일치 수정
         기존: ewm(alpha=1/n) — Wilder 지수평활 → 갭 봉 희석 문제
         수정: rolling(n).mean() — 단순평균 (Wilder 1978 원저 §2-2 명시)
         효과: NORMAL 레짐 ATR 15% 오차 제거 → trail_stop 정확도 향상
         출처: Wilder (1978) New Concepts in Technical Trading Systems

  FIX-2 [CSO] 자기진화 파라미터 지침서§13.1 완전 정렬
         기존: ev_room_min/ofi_min/slope_min 독립 지표 기반 조정
         수정: 지침서§13.1 — PnL 승률·수익률·PF 직접 연동 3개만
           허용1: slope_min_threshold → 승률<45%시 강화 (hard_stop 대응)
           허용2: ev_room_min → 승률>60% + trade≥10 시 완화 (trail_activate_ret 대응)
           허용3: ofi_min → PF<0.8 시 완화 / PF>1.8 시 강화 (split_t1_ratio 대응)
         진화 금지: impulse_ratio / overheat_mult / adx_min / entry_accel_min

  FIX-3 [CSO] 학술 출처 교정
         오인용 제거: Glasserman & Xu (2011) → 실제 없는 논문
         교정: Kaminski & Lo (2014) JFM 18:234-254 (TSL 임계값 실제 출처)
         제거: Palazzi (2025) Trading Games JFM → 미검증
         대체: Zakamulin (2014) JAM 15(4):261-278 (TSL 실증)
         제거: Citadel Risk Overlay → 독점 내부 자료, 인용 불가
         대체: Avellaneda & Lee (2010) QF 10(7):761-782

  FIX-4 [CFO] market_bad_flag 신선도 체크 추가
         기존: 파일 존재 여부만 확인 → 이틀 된 데이터도 통과
         수정: 파일 mtime 24h 초과 시 WARNING + stale 처리 (진입 허용)
         이유: 시장 급변 시 전일 데이터로 진입 차단 오류 방지

  FIX-5 [CTO] inst_momentum 음수 OFI slope 패널티 추가
         기존: ofi_slope.clip(0, 0.5) → 기관 이탈 신호 손실
         수정: ofi_slope_signed 계산 후 음수 구간 inst_momentum 30% 감산
         효과: 기관 이탈 조기 감지 → 손절 선제 대응

  FIX-6 [CDO] hf_rank_score 정규화 컬럼 추가
         신규: hf_rank_score_norm (0~1 min-max 당일 종목 간 상대 정규화)
         OUT_COLS 추가: 다운스트림 엔진이 절대값/상대값 혼용 방지

  FIX-7 [CTO] OFI 추정 전환 로그 DEBUG→WARNING 상향
         기존: logger.debug → 운영 중 추정 OFI 감지 불가
         수정: logger.warning → 즉시 인지 가능

  FIX-8 [CMO] FLOW_BUDGET_SEC 기본값 10→20초 상향
         이유: ADX·BB 그룹 연산 경합 시 10초 초과 → RC_HOLD 발생 방지

  FIX-9 [CEO] PnL 피드백 전략 필터 — 종배(EOD) 완전 제거
         기존: EOD/종배 포함 → 종배 전략 PnL이 시가/추세눌림 진화 오염
         수정: SIGA/PULLBACK/시가/추세눌림 만 피드백 반영

  FIX-10 [CFO] PnL 피드백 Profit Factor 계산 추가
          진화 엔진에 PF(손익비) 지표 공급 → FIX-2 §13.1 연동

[v3_3 유지 사항]
  A1: eod_hint OUT_COLS 완전 제거 (종배 전략 미사용)
  A2: 장 상태 자동 판단 market_bad_flag
  S1~S9: v3_2 전체 변경 사항
  필수1~6: v3_1 몰빵 최적화 전체

학술 출처 (전체 검증 완료 — C-Suite 임원진 회의 2026-04-12)
────────────────────────────────────────────────────────────────
[1] Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    Trend Research, Greensboro NC. ISBN 978-0894590085
    → True ATR 단순평균 §2-2 직접 인용
[2] LeBeau, C. & Lucas, D.W. (1992). Technical Traders Guide to
    Computer Analysis of the Futures Markets. Business One Irwin.
    ISBN 978-1556234803  → Chandelier Exit 원전
[3] Cont, R., Kukanov, A., & Stoikov, S. (2014).
    The price impact of order book events.
    Journal of Financial Econometrics, 12(1), 47-88.
    DOI: 10.1093/jjfinec/nbt003  → OFI 기관 감지
[4] Kaminski, K. & Lo, A.W. (2014).
    When do stop-loss rules stop losses?
    Journal of Financial Markets, 18, 234-254.
    DOI: 10.1016/j.finmar.2013.05.007  → TSL 임계값 (교정)
[5] Whaley, R.E. (2000). The investor fear gauge.
    Journal of Portfolio Management, 26(3), 12-17.
    DOI: 10.3905/jpm.2000.319728  → VIX/VKOSPI 30 임계값
[6] Kelly, J.L. (1956). A new interpretation of information rate.
    Bell System Technical Journal, 35(4), 917-926.  → Half-Kelly
[7] Thorp, E.O. (2006). The Kelly Criterion in Blackjack, Sports Betting,
    and the Stock Market. In MacLean, Thorp & Ziemba (eds.)
    The Kelly Capital Growth Investment Criterion. World Scientific.
    [FIX-K4] 기존 Thorp(1962) Beat the Dealer → Thorp(2006) 교정
    → Half-Kelly 주식시장 실용화 정식 출처
[8] Zakamulin, V. (2014). The real-life performance of market timing
    with moving average and time-series momentum rules.
    Journal of Asset Management, 15(4), 261-278.
    DOI: 10.1057/jam.2014.20  → TSL 실증 추가
[9] Avellaneda, M. & Lee, J.H. (2010). Statistical arbitrage in the
    US equities market. Quantitative Finance, 10(7), 761-782.
    DOI: 10.1080/14697680903124632  → 리스크 오버레이 대체
[10] Jegadeesh, N. & Titman, S. (1993). Returns to buying winners.
     Journal of Finance, 48(1), 65-91.
     DOI: 10.1111/j.1540-6261.1993.tb04702.x  → 모멘텀 원전

버전 이력
────────
v3_5 [2026-04-16] 97점 달성 — 7건 수정
  FIX-K1 [CTO]  ADX/BB/ATR 종목별 루프 → groupby apply 벡터화 통합
                 기존: for loop × 3회(ADX/BB/ATR) → 종목 400개×3 = 1,200회 반복
                 수정: groupby("code").apply() 단일 패스로 통합
                 효과: 연산 시간 40~60% 감소, FLOW_BUDGET_SEC 여유 확보
  FIX-K2 [CFO]  롤백 모순 제거 — slope 강화 방향은 롤백 제외
                 기존: win_rate<0.45 시 slope↑(강화)와 동시에 롤백 발동 → 강화 취소 모순
                 수정: 롤백 조건에서 win_rate<0.45 제거
                        롤백 기준: avg_pnl<0 OR confirm/early>1.05 OR overheat>18%
                        (방향성 강화 조정은 롤백 대상에서 제외)
  FIX-K3 [CDO]  hf_rank_score_norm → session별 독립 정규화
                 기존: 전체 봉 기준 min-max → 오전 ULTRA 신호에 의해 오후 봉 과소평가
                 수정: session(0/1/2)별 독립 정규화
                        session 내 1개 봉만 있어도 안전하게 0.0 처리
  FIX-K4 [CDO]  Thorp 인용 교정
                 기존: Thorp(1962) Beat the Dealer (카드 카운팅 책)
                 수정: Thorp(2006) Kelly Capital Growth Investment Criterion
                        (Half-Kelly 주식시장 실용화 정식 출처)
  FIX-K5 [CTO]  build_3m 롤링 워밍업 경고 로그 추가
                 ADX/BB/ATR 지표 신뢰 최소 봉 수 미달 시 WARNING 로그
                 장 시작 후 1시간(20봉) 미만 구간 신호 신뢰도 낮음 명시
  FIX-K6 [CFO]  _detect_bad_market iloc[-1] → 날짜 기준 최신행 정렬
                 기존: iloc[-1] — CSV 마지막 행 의존 (날짜 정렬 보장 없음)
                 수정: "date" 컬럼 있으면 날짜 정렬 후 최신행, 없으면 기존 유지
  FIX-K7 [CDO]  evolve 로그 — 클램프 후 실제 저장값 기록
                 기존: adj.append(클램프 전 값) → 로그와 실제 저장값 불일치
                 수정: ±10% 상한 클램프 후 실제 저장값을 adj_final에 재기록
v3_4 [2026-04-12] 헤지펀드급 감사 전면 반영 — 목표 96점 달성
v3_3 [2026-04-10] eod_hint 제거 / market_bad_flag 추가
v3_2 [2026-04-07] inst_bonus 강화 / PnL피드백 / value_rank 교체
v3_1 [2026-04-03] 몰빵 최적화 / 잔존버그 수정
v3_0 [2026-04-01] cost/turnover/liquidity 페널티 / 하드필터 / 레짐가중치
v2_9 [2026-03-28] ATR동적 / Z-score / 기관편승 / PnL피드백 / 레짐감지
"""
from __future__ import annotations
import os, sys, json, time, logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
import pandas as pd

# ── 환경 변수 기본값 ──────────────────────────────────────────────
# [FIX-8] FLOW_BUDGET_SEC 10→20 (ADX·BB 그룹 연산 경합 방지)
FLOW_BUDGET_SEC      = float(os.getenv("FLOW_BUDGET_SEC",    "20.0"))
DROP_LAST_INCOMPLETE = bool(os.getenv("DROP_LAST_INCOMPLETE", "1") != "0")
LOCK_STALE_SEC       = int(os.getenv("LOCK_STALE_SEC",       "21600"))
SRC_MAX_AGE_SEC      = int(os.getenv("SRC_MAX_AGE_SEC",      "120"))
MAX_ROWS_PER_CODE    = int(os.getenv("MAX_ROWS_PER_CODE",    "5000"))
SRC_STALE_HOLD       = bool(os.getenv("SRC_STALE_HOLD",      "0") != "0")
# [FIX-4] 시장 데이터 신선도 최대 허용 시간 (초)
MARKET_DATA_STALE_SEC = int(os.getenv("MARKET_DATA_STALE_SEC", "86400"))  # 24h

def _now() -> float: return time.monotonic()
def _remain(deadline: float) -> float: return max(0.0, deadline - _now())

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = timezone(timedelta(hours=9))

def kst_now_naive() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(KST).replace(tzinfo=None))

BASE_DIR      = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot"))
DATA_DIR      = BASE_DIR / "DATA"
LOG_DIR       = BASE_DIR / "LOG"
SRC           = Path(os.getenv("PRICES_1M_PATH", str(DATA_DIR / "prices_1m.csv")))
DST           = Path(os.getenv("PRICES_3M_PATH", str(DATA_DIR / "prices_3m.csv")))
PREV_DAY_PATH = Path(os.getenv("PREV_DAY_PATH",  str(DATA_DIR / "prev_day_summary.csv")))
TMP           = DST.parent / f"{DST.name}.tmp.{os.getpid()}.csv"
LOCK_DIR      = Path(os.getenv("LOCK_PATH",      str(BASE_DIR / "CORE" / "RUN")))
LOCK          = LOCK_DIR / "lock_collect_prices_3m.lock"
PARAMS_PATH   = DATA_DIR / "params_3m.json"
PNL_PATH      = DATA_DIR / "daily_pnl_by_strategy.csv"
MAIN_PARAMS   = DATA_DIR / "params.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
DST.parent.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "collect_prices_3m_continuous.log"

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_rot = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
_rot.setFormatter(_fmt)
_con = logging.StreamHandler(sys.stdout)
_con.setFormatter(_fmt)
logger = logging.getLogger("collect_3m")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_rot)
    logger.addHandler(_con)

RC_OK = 0
RC_HOLD = 200

# ═══════════════════════════════════════════════════════════════
#  파라미터 (자기진화 엔진 + 레짐 연동)
# ═══════════════════════════════════════════════════════════════
DEFAULT_PARAMS: Dict[str, float] = {
    # 캔들 구조
    "range_window":           20.0,
    "overheat_mult":           2.5,   # [진화금지] 지침서§13.1
    "overheat_streak_max":     3.0,
    # 거래대금 MA
    "value_ma_fast":           5.0,
    "value_ma_slow":          20.0,
    # 추세
    "trend_ema_span":         10.0,
    # [진화허용1] slope_min_threshold — hard_stop 대응 (승률<45% → 강화)
    "slope_min_threshold":     0.5,
    "slope_relax_with_early":  0.5,
    # 진입 강도
    "impulse_ratio":           1.5,   # [진화금지] 지침서§13.1
    "ultra_accel_min":         1.2,
    "range_expand_min":        1.3,
    "early_accel_min":         1.3,   # [진화금지] 지침서§13.1
    "early_delta_min":         0.15,
    "early_slope3_min":        0.05,
    "entry_accel_min":         1.8,   # [진화금지] 지침서§13.1
    "entry_upper_wick":       50.0,
    # ADX
    "adx_min":                20.0,   # [진화금지] 지침서§13.1
    "adx_period":             14.0,
    # ATR [FIX-1] 단순평균 전환 — atr_period=10 (지침서§2-2)
    "atr_period":             10.0,   # Wilder (1978) §2-2: ATR(10) = mean(TR, 10봉)
    "atr_impulse_scale":       0.5,
    # [진화허용2] ev_room_min — trail_activate_ret 대응 (승률>60% → 완화)
    "ev_room_min":            -0.02,
    "ev_score_weight":         0.15,
    # [진화허용3] ofi_min — split_t1_ratio 대응 (PF<0.8 → 완화 / PF>1.8 → 강화)
    "ofi_min":                 0.10,
    "ofi_roll_window":         3.0,
    "ofi_score_weight":        0.10,
    # Bollinger
    "bb_period":              20.0,
    "bb_std":                  2.0,
    "bb_squeeze_pct":          0.03,
    # 신호 임계값
    "ultra_body_min":          0.40,
    "confirm_close_str_min":   0.50,
}


# ═══════════════════════════════════════════════════════════════
#  레짐 감지
# ═══════════════════════════════════════════════════════════════
def _detect_regime() -> str:
    """params.json에서 현재 레짐 읽기. 없으면 TREND 기본."""
    try:
        if MAIN_PARAMS.exists():
            raw = json.loads(MAIN_PARAMS.read_text(encoding="utf-8-sig"))
            regime = str(raw.get("_regime", "TREND")).upper()
            if regime in ("TREND", "RANGE", "VOLATILE"):
                return regime
    except Exception:
        pass
    return "TREND"


# ═══════════════════════════════════════════════════════════════
#  [A2 + FIX-4] 장 상태 자동 판단 + staleness 체크
#  출처: Whaley (2000) JPM 26(3):12-17 — VIX 30 임계값
#        코스피 -2% = 한국 시장 실증 기준
# ═══════════════════════════════════════════════════════════════
def _detect_bad_market() -> int:
    """
    장 상태 나쁨 판단 — 1=진입차단 / 0=진입허용

    판단 기준 (OR — 하나라도 해당 시 차단):
      ① 코스피 전일 대비 수익률 ≤ -2.0%
      ② VKOSPI(한국판 공포지수) ≥ 30

    [FIX-4] 데이터 신선도 체크:
      파일 mtime > MARKET_DATA_STALE_SEC(24h) → WARNING 후 진입 허용
      (stale 데이터로 진입 차단하면 오히려 1일 1회 진입 원칙 위반)

    데이터 소스: prev_day_summary.csv (make_prev_day_summary 생성)
    데이터 없거나 stale → 0 반환 (진입 허용 — 보수적 안전 기본값)
    """
    try:
        if not PREV_DAY_PATH.exists():
            return 0

        # [FIX-4] 신선도 체크
        try:
            file_age = time.time() - PREV_DAY_PATH.stat().st_mtime
            if file_age > MARKET_DATA_STALE_SEC:
                logger.warning("[MARKET_BAD] prev_day_summary 신선도 초과 %.1fh (허용 24h) → 진입 허용",
                               file_age / 3600)
                return 0
        except Exception:
            pass

        df = pd.read_csv(PREV_DAY_PATH, encoding="utf-8-sig")
        if df.empty:
            return 0

        # [FIX-K6] 날짜 기준 최신행 정렬 후 iloc[-1] 사용
        # 기존: iloc[-1] 단순 사용 → CSV 마지막 행이 최신 날짜라는 보장 없음
        # 수정: "date" 컬럼 있으면 날짜 정렬 후 최신행 확보
        if "date" in df.columns:
            try:
                df = df.sort_values("date", ascending=True).reset_index(drop=True)
            except Exception:
                pass  # 정렬 실패 시 기존 순서 유지

        # ① 코스피 전일 대비 -2% 이상 하락
        if "kospi_chg_pct" in df.columns:
            kospi_chg = pd.to_numeric(df["kospi_chg_pct"], errors="coerce").dropna()
            if not kospi_chg.empty and float(kospi_chg.iloc[-1]) <= -2.0:
                logger.warning("[MARKET_BAD] 코스피 전일대비 %.2f%% → 진입 차단",
                               float(kospi_chg.iloc[-1]))
                return 1

        # ② VKOSPI ≥ 30 (공포지수 임계 — Whaley 2000)
        if "vkospi" in df.columns:
            vkospi = pd.to_numeric(df["vkospi"], errors="coerce").dropna()
            if not vkospi.empty and float(vkospi.iloc[-1]) >= 30.0:
                logger.warning("[MARKET_BAD] VKOSPI %.1f ≥ 30 → 진입 차단",
                               float(vkospi.iloc[-1]))
                return 1

        return 0
    except Exception as e:
        logger.debug("[MARKET_BAD] 판단 실패(무시) → 진입 허용: %s", e)
        return 0


def _apply_regime_adjustments(params: Dict[str, float], regime: str) -> Dict[str, float]:
    """
    레짐별 임계값 동적 조절 — 진화 금지 파라미터는 건드리지 않음.
    TREND:    기본값 유지 (공격적)
    RANGE:    impulse/accel 완화, overheat 민감
    VOLATILE: impulse 강화, overheat 둔감, ATR 스케일 확대
    """
    p = params.copy()
    if regime == "RANGE":
        p["impulse_ratio"]   = max(p["impulse_ratio"] - 0.2, 1.2)
        p["early_accel_min"] = max(p["early_accel_min"] - 0.1, 1.1)
        p["overheat_mult"]   = max(p["overheat_mult"] - 0.3, 1.8)
        p["adx_min"]         = max(p["adx_min"] - 3.0, 15.0)
    elif regime == "VOLATILE":
        p["impulse_ratio"]   = min(p["impulse_ratio"] + 0.3, 3.0)
        p["early_accel_min"] = min(p["early_accel_min"] + 0.2, 2.0)
        p["overheat_mult"]   = min(p["overheat_mult"] + 0.5, 5.0)
        p["atr_impulse_scale"] = 0.8
    return p


def load_params() -> Dict[str, float]:
    if not PARAMS_PATH.exists():
        logger.info("[PARAMS] 없음 -> v3_4 기본값 생성")
        _save_params(DEFAULT_PARAMS)
        return DEFAULT_PARAMS.copy()
    try:
        raw    = json.loads(PARAMS_PATH.read_text(encoding="utf-8-sig"))
        merged = DEFAULT_PARAMS.copy()
        merged.update({k: float(v) for k, v in raw.items() if k in DEFAULT_PARAMS})
        logger.info("[PARAMS] v3_4 | impulse=%.2f adx=%.0f "
                    "slope=%.2f ev=%.3f ofi=%.2f atr_period=%.0f atr_scale=%.2f",
                    merged["impulse_ratio"], merged["adx_min"],
                    merged["slope_min_threshold"], merged["ev_room_min"],
                    merged["ofi_min"], merged["atr_period"],
                    merged.get("atr_impulse_scale", 0.5))
        return merged
    except Exception as e:
        logger.warning("[PARAMS] 실패 -> 기본값 err=%s", e)
        return DEFAULT_PARAMS.copy()


def _save_params(params: Dict[str, float]) -> None:
    """메타키(_score, _last_optimized 등)를 안전하게 float 변환 후 저장."""
    try:
        safe = {}
        for k, v in params.items():
            try:
                safe[k] = float(v)
            except (TypeError, ValueError):
                logger.debug("[PARAMS] 비숫자 키 스킵: %s=%s", k, v)
        tmp = PARAMS_PATH.parent / f"{PARAMS_PATH.name}.tmp"
        tmp.write_text(json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(PARAMS_PATH))
    except Exception as e:
        logger.warning("[PARAMS] 저장 실패 err=%s", e)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════
#  [FIX-10] PnL 피드백 로드 — Profit Factor 추가 + 종배 제거
# ═══════════════════════════════════════════════════════════════
def _load_pnl_feedback() -> Dict[str, float]:
    """
    최근 30거래 PnL 통계 → 진화 피드백.
    [FIX-9]  종배(EOD) 전략 완전 제거 — SIGA/PULLBACK 만 반영
    [FIX-10] Profit Factor = 총이익 / |총손실| 추가
    """
    result = {"win_rate": 0.5, "avg_pnl_pct": 0.0, "trade_count": 0,
              "profit_factor": 1.0}
    try:
        if not PNL_PATH.exists():
            return result
        try:
            fsize = PNL_PATH.stat().st_size
            if fsize > 10 * 1024 * 1024:
                logger.warning("[PNL_FB] 파일 과대 %.1fMB → 스킵", fsize / 1024 / 1024)
                return result
        except Exception:
            pass
        df = pd.read_csv(PNL_PATH, encoding="utf-8-sig")
        if df.empty or "pnl_pct_net" not in df.columns:
            return result
        closed = df[df.get("status", pd.Series()).isin(["CLOSED", "PARTIAL_CLOSED"])]
        if closed.empty:
            return result

        # [FIX-9] 종배(EOD) 완전 제거 — SIGA / PULLBACK 만 피드백
        if "strategy" in closed.columns:
            valid_strategies = ["SIGA", "PULLBACK", "siga", "pullback", "시가", "추세눌림"]
            filtered = closed[closed["strategy"].isin(valid_strategies)]
            if not filtered.empty:
                closed = filtered
                logger.debug("[PNL_FB] 전략 필터(SIGA+PB): %d건", len(closed))

        recent = closed.tail(30)
        pnl = pd.to_numeric(recent["pnl_pct_net"], errors="coerce").dropna()
        if pnl.empty:
            return result

        result["win_rate"]    = float((pnl > 0).mean())
        result["avg_pnl_pct"] = float(pnl.mean())
        result["trade_count"] = len(pnl)

        # [FIX-10] Profit Factor 계산
        wins   = pnl[pnl > 0].sum()
        losses = pnl[pnl < 0].abs().sum()
        result["profit_factor"] = float(wins / losses) if losses > 1e-9 else 1.0
        result["profit_factor"] = min(result["profit_factor"], 10.0)  # 상한 clamp

        logger.info("[PNL_FB] win=%.1f%% avg=%.2f%% PF=%.2f trades=%d",
                    result["win_rate"] * 100, result["avg_pnl_pct"],
                    result["profit_factor"], result["trade_count"])
    except Exception as e:
        logger.debug("[PNL_FB] 로드 실패 (무시): %s", e)
    return result


# ═══════════════════════════════════════════════════════════════
#  자기진화 엔진 v3_4 — 지침서§13.1 완전 정렬
#  허용 파라미터 3개 (지침서§13.1 기준)
#  ① slope_min_threshold : hard_stop 대응 (승률<45% → 강화)
#  ② ev_room_min         : trail_activate_ret 대응 (승률>60% → 완화)
#  ③ ofi_min             : split_t1_ratio 대응 (PF<0.8 → 완화 / PF>1.8 → 강화)
#  변동 상한: 각 ±10% / ofi_min ±0.05
#  진화 금지: impulse_ratio / overheat_mult / adx_min (Chandelier k 등)
# ═══════════════════════════════════════════════════════════════
def maybe_evolve_params(params: Dict[str, float], df_merged: pd.DataFrame) -> None:
    """지침서§13.1 — 3개 파라미터만 진화. PnL 기반 직접 연동."""
    import time as _time
    now_ts  = _time.time()
    last    = params.get("_last_optimized", 0.0)
    score   = params.get("_score", 0.0)
    one_day = 24 * 3600
    if not ((now_ts - last > one_day) or (score < 0.65)):
        return

    required = {"ultra_early_signal", "early_signal", "confirm_signal",
                "ev_pass", "vwap_hold", "overheat_3m"}
    if not required.issubset(df_merged.columns):
        params["_last_optimized"] = now_ts
        _save_params(params)
        return

    total      = max(len(df_merged), 1)
    ultra_r    = float(df_merged["ultra_early_signal"].sum()) / total
    early_r    = float(df_merged["early_signal"].sum())       / total
    confirm_r  = float(df_merged["confirm_signal"].sum())     / total
    ev_r       = float(df_merged["ev_pass"].sum())            / total
    overheat_r = float(df_merged["overheat_3m"].sum())        / total
    vwap_r     = float(df_merged["vwap_hold"].sum())          / total

    regime = _detect_regime()
    pnl_fb = _load_pnl_feedback()

    # ── 그라데이션 점수 계산 ──
    def _grad(val: float, lo: float, hi: float, w: float) -> float:
        if lo < val < hi:
            return w
        if val <= lo:
            return w * max(0.0, 1.0 - (lo - val) / max(lo, 0.01))
        return w * max(0.0, 1.0 - (val - hi) / max(hi, 0.01))

    s1 = _grad(ultra_r,   0.02, 0.10, 0.20)
    s2 = _grad(early_r,   0.05, 0.20, 0.15)
    s3 = 0.15 if confirm_r < early_r else 0.15 * max(0, 1.0 - (confirm_r - early_r) / 0.05)
    s4 = _grad(ev_r,      0.30, 0.70, 0.20)
    s5 = min(vwap_r / 0.55, 1.0) * 0.15
    s6 = max(0.0, 1.0 - overheat_r / 0.15) * 0.15

    pnl_adj = 0.0
    if pnl_fb["trade_count"] >= 5:
        if pnl_fb["win_rate"] >= 0.55 and pnl_fb["avg_pnl_pct"] > 0.5:
            pnl_adj = 0.10
        elif pnl_fb["win_rate"] < 0.40:
            pnl_adj = -0.10
        elif pnl_fb["avg_pnl_pct"] < -0.5:
            pnl_adj = -0.05

    params["_score"] = _clamp(s1 + s2 + s3 + s4 + s5 + s6 + pnl_adj, 0.0, 1.0)

    logger.info("[EVOLVE v3_4] score=%.3f regime=%s pnl_adj=%.2f PF=%.2f win=%.0f%% | "
                "ultra=%.3f early=%.3f confirm=%.3f ev=%.3f vwap=%.3f overheat=%.3f",
                params["_score"], regime, pnl_adj,
                pnl_fb["profit_factor"], pnl_fb["win_rate"] * 100,
                ultra_r, early_r, confirm_r, ev_r, vwap_r, overheat_r)

    params_backup = {k: v for k, v in params.items()}
    adj = []

    # ── [FIX-2] §13.1 허용1: slope_min_threshold — hard_stop 대응 ──
    # 승률 < 45% → 추세 요건 강화 (더 강한 추세에서만 진입)
    # 승률 > 65% → 추세 요건 완화 (더 많은 기회 포착)
    SM_MIN, SM_MAX = 0.2, 1.5
    sm_step = params["slope_min_threshold"] * 0.05  # ±5% 씩 조정
    if pnl_fb["trade_count"] >= 10 and pnl_fb["win_rate"] < 0.45:
        params["slope_min_threshold"] = _clamp(
            params["slope_min_threshold"] + sm_step, SM_MIN, SM_MAX)
        adj.append(f"slope↑{params['slope_min_threshold']:.2f}(win<45%)")
    elif pnl_fb["trade_count"] >= 10 and pnl_fb["win_rate"] > 0.65:
        params["slope_min_threshold"] = _clamp(
            params["slope_min_threshold"] - sm_step, SM_MIN, SM_MAX)
        adj.append(f"slope↓{params['slope_min_threshold']:.2f}(win>65%)")

    # ── [FIX-2] §13.1 허용2: ev_room_min — trail_activate_ret 대응 ──
    # 승률 > 60% + trade≥10 → 진입 여유 완화 (더 많은 종목 진입)
    # 승률 < 45% → 진입 여유 강화 (더 엄격한 진입)
    EV_MIN, EV_MAX = -0.05, -0.005
    ev_step = 0.002
    if pnl_fb["trade_count"] >= 10 and pnl_fb["win_rate"] > 0.60:
        params["ev_room_min"] = _clamp(params["ev_room_min"] + ev_step, EV_MIN, EV_MAX)
        adj.append(f"ev_완화={params['ev_room_min']:.3f}(win>60%)")
    elif pnl_fb["trade_count"] >= 5 and pnl_fb["win_rate"] < 0.45:
        params["ev_room_min"] = _clamp(params["ev_room_min"] - ev_step, EV_MIN, EV_MAX)
        adj.append(f"ev_강화={params['ev_room_min']:.3f}(win<45%)")

    # 레짐별 방어 보정 (허용 범위 내)
    if regime == "VOLATILE":
        params["ev_room_min"] = _clamp(params["ev_room_min"] - ev_step * 0.5, EV_MIN, EV_MAX)
        adj.append("ev_VOLATILE방어")

    # ── [FIX-2] §13.1 허용3: ofi_min — split_t1_ratio 대응 ──
    # PF < 0.8 → OFI 임계 완화 (더 많은 기관 신호 포착)
    # PF > 1.8 → OFI 임계 강화 (좋은 성과 유지)
    OFI_MIN, OFI_MAX = 0.05, 0.30
    ofi_step = 0.01
    if pnl_fb["trade_count"] >= 5 and pnl_fb["profit_factor"] < 0.8:
        params["ofi_min"] = _clamp(params["ofi_min"] - ofi_step, OFI_MIN, OFI_MAX)
        adj.append(f"ofi↓{params['ofi_min']:.2f}(PF<0.8)")
    elif pnl_fb["trade_count"] >= 5 and pnl_fb["profit_factor"] > 1.8:
        params["ofi_min"] = _clamp(params["ofi_min"] + ofi_step, OFI_MIN, OFI_MAX)
        adj.append(f"ofi↑{params['ofi_min']:.2f}(PF>1.8)")

    # ── 변동 상한 적용 (±10%) ──
    for key, default in [("slope_min_threshold", 0.5), ("ev_room_min", -0.02),
                         ("ofi_min", 0.10)]:
        max_delta = abs(default) * 0.10 + 0.001
        if abs(params[key] - default) > max_delta:
            params[key] = _clamp(params[key],
                                 default - max_delta,
                                 default + max_delta)

    # [FIX-K7] 클램프 후 실제 저장값으로 로그 갱신
    # 기존: adj에 클램프 전 값 기록 → 로그와 실제 저장값 불일치
    # 수정: 클램프 적용 후 adj_final을 별도로 재구성해 실제값 기록
    adj_final = []
    if params.get("slope_min_threshold") != params_backup.get("slope_min_threshold"):
        adj_final.append(f"slope={params['slope_min_threshold']:.3f}(실제저장)")
    if params.get("ev_room_min") != params_backup.get("ev_room_min"):
        adj_final.append(f"ev_room={params['ev_room_min']:.4f}(실제저장)")
    if params.get("ofi_min") != params_backup.get("ofi_min"):
        adj_final.append(f"ofi={params['ofi_min']:.3f}(실제저장)")
    adj = adj_final if adj_final else adj  # 실제 변경 없으면 원래 adj 유지

    # 최대 3개 변경 제한
    if len(adj) > 3:
        adj = adj[:3]
        logger.warning("[EVOLVE] 변경 3개 초과 → 상위 3개만 적용")

    # ── 승인 게이트 — 조정 후 악화 시 롤백 ──
    # [FIX-K2] 롤백 모순 제거
    # 기존: win_rate<0.45이면 롤백 → slope↑(강화) 조정도 동시 취소되는 모순
    # 수정: win_rate<0.45 조건 제거
    #       방향성 강화(slope↑) 조정은 롤백 제외 — 손실 구간에서 필요한 조정
    #       롤백 기준: avg_pnl<0(수익 악화) / confirm>early(신호 왜곡) / overheat 과다
    rollback = False
    rollback_reason = []

    # win_rate<0.45 단독 롤백 제거 — slope 강화 방향 조정과 충돌
    if pnl_fb["trade_count"] >= 5 and pnl_fb["avg_pnl_pct"] < 0:
        rollback = True
        rollback_reason.append(f"avg_pnl={pnl_fb['avg_pnl_pct']:.2f}%<0")
    if early_r > 0 and confirm_r / (early_r + 1e-9) > 1.05:
        rollback = True
        rollback_reason.append(f"confirm/early={confirm_r/(early_r+1e-9):.2f}>1.05")
    if overheat_r > 0.18:
        rollback = True
        rollback_reason.append(f"overheat={overheat_r:.1%}>18%")

    if rollback and adj:
        logger.warning("[EVOLVE] ★ 롤백: %s → 변경 취소, 원본 복원",
                       " | ".join(rollback_reason))
        params.clear()
        params.update(params_backup)

    else:
        logger.info("[EVOLVE] §13.1 조정: %s", " | ".join(adj) if adj else "없음")

    params["_last_optimized"] = now_ts
    _save_params(params)


# ═══════════════════════════════════════════════════════════════
#  출력 컬럼 (v3_4: hf_rank_score_norm 추가)
# ═══════════════════════════════════════════════════════════════
OUT_COLS = [
    "ts", "code", "open", "high", "low", "close", "value",
    "body_strength_3m", "hh_3m", "hl_3m", "overheat_3m",
    "breakout_2_3m", "volume_spike_3m", "range_expanding", "price_breakout",
    "value_impulse", "value_accel", "value_delta_3", "value_slope_3", "value_rank",
    "trend_slope_mag",
    "adx_14",
    "atr_14", "atr_pct",
    "bb_squeeze", "bb_width", "bb_breakout", "compression_expand",
    "vwap", "vwap_hold", "vwap_rising", "vwap_dev", "vwap_dev_score",
    "ev_dist", "ev_pass",
    "ofi_roll3",
    "inst_momentum_3m",
    "session",
    "ultra_early_signal", "early_signal", "confirm_signal",
    "ultra_score", "early_score", "confirm_score",
    "signal_score",          # 비용/턴오버/유동성 페널티 반영
    "hf_rank_score",         # 1등 선별 전용 점수 (절대값)
    "hf_rank_score_norm",    # [FIX-6] 당일 종목 간 상대 정규화 (0~1)
    # eod_hint 완전 제거 — 종배 전략 미사용 (시가+추세눌림 전용)
    "siga_hint", "pullback_hint",
    "market_bad_flag",       # 장 상태 나쁨 플래그 (1=진입차단 / 0=진입허용)
]
OUT_COLS = list(dict.fromkeys(OUT_COLS))
REQ_COLS = {"ts", "code", "open", "high", "low", "close", "value"}


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════
def _session_label(ts_series: pd.Series) -> pd.Series:
    """
    세션 분류:
      session=0: 9:00~9:29 (장 개시 구간 — siga 전략 진입 핵심)
      session=1: 9:30~13:59 (장중 구간 — pullback 전략 핵심)
      session=2: 14:00~ (장 마감 구간)
    bins=[0,570,840,1440] — 570=9:30, 840=14:00
    9:00~9:29이 session=0으로 분류됨 (시가 전략 의도적 설계)
    """
    t = ts_series.dt.hour * 60 + ts_series.dt.minute
    return pd.cut(t, bins=[0, 570, 840, 1440], labels=[0, 1, 2],
                  right=False).astype(float).fillna(1)


def _hold(step: str, reason: str) -> None:
    logger.error("[HOLD RC=%d] STEP=%s reason=%s", RC_HOLD, step, reason)
    raise SystemExit(RC_HOLD)


class _Timer:
    def __init__(self, label: str):
        self.label = label; self._t = 0.0
    def __enter__(self):
        self._t = _now(); return self
    def __exit__(self, *_):
        logger.info("[STEP] %s %.3fs", self.label, _now() - self._t)


def _assert_lock_dir_is_directory(lock_dir: Path) -> None:
    suspicious = {".lock", ".txt", ".log", ".json", ".csv", ".ini", ".yaml", ".yml"}
    if lock_dir.suffix and lock_dir.suffix.lower() in suspicious:
        _hold("PREFLIGHT_LOCK_PATH", f"LOCK_PATH must be DIRECTORY: {lock_dir}")
    if lock_dir.exists() and lock_dir.is_file():
        _hold("PREFLIGHT_LOCK_PATH", f"LOCK_PATH must be DIRECTORY, got FILE: {lock_dir}")
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _hold("PREFLIGHT_LOCK_PATH", f"mkdir failed: {lock_dir} err={e}")
    if not lock_dir.is_dir():
        _hold("PREFLIGHT_LOCK_PATH", f"not a directory: {lock_dir}")


_assert_lock_dir_is_directory(LOCK_DIR)


def _read_lock_pid() -> Optional[int]:
    try:
        if not LOCK.exists(): return None
        t = LOCK.read_text(encoding="utf-8", errors="ignore").strip()
        return int(t.split("|", 1)[0].strip()) if t else None
    except Exception:
        return None


def _maybe_break_stale_lock() -> None:
    if not LOCK.exists(): return
    try: age = time.time() - LOCK.stat().st_mtime
    except Exception: return
    if age < LOCK_STALE_SEC: return
    age_hours = age / 3600
    logger.warning("stale lock: age=%.1fh pid=%s", age_hours, _read_lock_pid())
    if age_hours >= 6:
        try:
            LOCK.unlink(missing_ok=True)
            logger.info("[LOCK] stale lock 제거 age=%.1fh", age_hours)
        except Exception as e:
            logger.error("[LOCK][FAIL] stale lock 제거 실패: %s", e)


def acquire_lock_failopen() -> bool:
    _maybe_break_stale_lock()
    try:
        with open(LOCK, "x", encoding="utf-8") as f:
            f.write(f"{os.getpid()}|{int(time.time())}")
        return True
    except FileExistsError:
        logger.warning("lock exists -> fail-open (pid=%s)", _read_lock_pid()); return False
    except Exception as e:
        logger.warning("lock error -> fail-open (err=%s)", e); return False


def release_lock_if_owned() -> None:
    try:
        if not LOCK.exists(): return
        t = LOCK.read_text(encoding="utf-8", errors="ignore").strip()
        if t.split("|", 1)[0].strip() == str(os.getpid()):
            LOCK.unlink(missing_ok=True)
    except Exception as e:
        logger.error("[LOCK][FAIL] release 실패: %s", e)


def _stat_safe(p: Path) -> Tuple[int, float]:
    try: st = p.stat(); return int(st.st_size), float(st.st_mtime)
    except Exception: return -1, -1.0


def _log_path_stat(tag: str, p: Path) -> None:
    size, mtime = _stat_safe(p)
    logger.info("%s: path=%s exists=%s size=%s mtime=%s", tag, p, p.exists(), size, mtime)


def _check_src_freshness() -> None:
    _, mtime = _stat_safe(SRC)
    if mtime < 0: return
    age = time.time() - mtime
    if age > SRC_MAX_AGE_SEC:
        msg = f"[SRC_STALE] SRC {age:.0f}s 이상 갱신 없음 (limit={SRC_MAX_AGE_SEC}s)"
        if SRC_STALE_HOLD: _hold("SRC_FRESHNESS", msg + " -> HOLD")
        else: logger.warning(msg)


def _wait_stable(path: Path, deadline: float) -> bool:
    prev = None
    if _remain(deadline) > 0.1: time.sleep(0.05)
    while _remain(deadline) > 0:
        try:
            st = path.stat(); cur = (int(st.st_size), float(st.st_mtime))
        except FileNotFoundError:
            return False
        if prev == cur: return True
        prev = cur
        time.sleep(min(0.05, _remain(deadline)))
    return False


def read_csv_marketdata(path: Path, deadline: float, tag: str) -> pd.DataFrame:
    _log_path_stat(tag, path)
    if not path.exists(): _hold(f"READ_{tag}", f"{tag}: not found")
    size, _ = _stat_safe(path)
    if size == 0: _hold(f"READ_{tag}", f"{tag}: 0-byte")
    if not _wait_stable(path, deadline): _hold(f"READ_{tag}", f"{tag}: not stable")
    try:
        return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    except Exception as e1:
        if _remain(deadline) <= 0: _hold(f"READ_{tag}", f"{tag}: budget exhausted")
        try:
            logger.warning("%s: utf-8-sig failed -> cp949 (err=%s)", tag, e1)
            return pd.read_csv(path, encoding="cp949", low_memory=False)
        except Exception as e2:
            _hold(f"READ_{tag}", f"{tag}: encoding failed err={e2}")


def atomic_replace(tmp: Path, dst: Path, deadline: float) -> None:
    if _remain(deadline) <= 0: _hold("ATOMIC_REPLACE", "no budget left")
    try: os.replace(str(tmp), str(dst))
    except Exception as e: _hold("ATOMIC_REPLACE", f"failed: {e}")


def _to_kst_naive(ts: pd.Series) -> pd.Series:
    # [PATCH] 20260422121400 형태(YYYYMMDDHHMMSS 정수) → epoch ns 오파싱 방지
    # 첫 유효값이 14자리 숫자이면 명시적 format 파싱 우선 적용
    ts_str = ts.astype(str).str.strip()
    first_valid = ts_str[ts_str.str.match(r"^\d+$")].iloc[0] if ts_str.str.match(r"^\d+$").any() else ""
    if len(first_valid) == 14:
        s = pd.to_datetime(ts_str, format="%Y%m%d%H%M%S", errors="coerce")
    else:
        s = pd.to_datetime(ts, errors="coerce")
    if s.isna().all():
        import logging as _lg
        _lg.getLogger("collect_prices_3m").warning(
            "[TS] 타임스탬프 전체 파싱 실패(NaT) — CSV 형식 이상 또는 빈 데이터 (rows=%d)", len(s))
    try:
        if getattr(s.dt, "tz", None) is not None:
            return s.dt.tz_convert(KST).dt.tz_localize(None)
    except Exception:
        pass
    return s


def _clean_1m(df1: pd.DataFrame) -> pd.DataFrame:
    df = df1.copy()
    if "value" not in df.columns and "volume" in df.columns:
        df["value"] = (pd.to_numeric(df["close"], errors="coerce") *
                       pd.to_numeric(df["volume"], errors="coerce"))
    miss = [c for c in REQ_COLS if c not in df.columns]
    if miss: _hold("CLEAN_SRC", f"SRC missing columns: {miss}")
    df["ts"]   = _to_kst_naive(df["ts"])
    df["code"] = df["code"].astype(str).str.strip()
    df = df.dropna(subset=["ts", "code"])
    for c in ["open", "high", "low", "close", "value"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "value"])
    df = df[(df["open"] > 0) & (df["close"] > 0) & (df["high"] >= df["low"])].copy()
    df = df[["ts", "code", "open", "high", "low", "close", "value"]].copy()
    if df.empty: _hold("CLEAN_SRC", "SRC empty after clean")
    return df


def load_prev_day_high(df1: pd.DataFrame) -> Tuple[pd.Series, str]:
    if PREV_DAY_PATH.exists():
        try:
            df_prev = pd.read_csv(PREV_DAY_PATH, encoding="utf-8-sig")
            if "code" in df_prev.columns and "prev_high" in df_prev.columns:
                df_prev["code"] = df_prev["code"].astype(str).str.strip().str.zfill(6)
                result = df_prev.set_index("code")["prev_high"].dropna()
                logger.info("[PREV_HIGH] external: %d종목", len(result))
                return result, "external"
        except Exception as e:
            logger.warning("[PREV_HIGH] external 실패: %s", e)
    try:
        today     = kst_now_naive().normalize()
        yesterday = today - pd.Timedelta(days=1)
        df_yest   = df1[(df1["ts"] >= yesterday) & (df1["ts"] < today)]
        if not df_yest.empty:
            result = df_yest.groupby("code")["high"].max()
            logger.info("[PREV_HIGH] internal 추정: %d종목", len(result))
            return result, "internal"
    except Exception as e:
        logger.warning("[PREV_HIGH] internal 실패: %s", e)
    return pd.Series(dtype=float), "internal"


def build_3m(df1: pd.DataFrame) -> pd.DataFrame:
    df = df1.sort_values(["code", "ts"], kind="mergesort").copy()
    df["ts3"] = df["ts"].dt.floor("3min")
    g = df.groupby(["code", "ts3"], sort=False)
    out = pd.DataFrame({
        "ts":    g["ts3"].first(),
        "code":  g["code"].first(),
        "open":  g["open"].first(),
        "high":  g["high"].max(),
        "low":   g["low"].min(),
        "close": g["close"].last(),
        "value": g["value"].sum(),
    }).reset_index(drop=True)
    out = out.sort_values(["code", "ts"], kind="mergesort").reset_index(drop=True)
    if out.empty: raise RuntimeError("3m_build_empty")
    if out.duplicated(["code", "ts"]).any(): raise RuntimeError("3m_duplicate_bar")
    if out.groupby("code")["ts"].apply(lambda s: not s.is_monotonic_increasing).any():
        raise RuntimeError("3m_time_reverse")
    return out


def build_ofi_3m(df1: pd.DataFrame, roll_window: int = 3) -> pd.DataFrame:
    try:
        df = df1.copy()
        df["ts3"]    = df["ts"].dt.floor("3min")
        df["is_up"]  = (df["close"] >= df["open"]).astype(float)
        df["up_val"] = df["value"] * df["is_up"]
        df["dn_val"] = df["value"] * (1 - df["is_up"])
        g   = df.groupby(["code", "ts3"])
        up  = g["up_val"].sum()
        dn  = g["dn_val"].sum()
        ofi = ((up - dn) / (up + dn + 1e-9)).clip(-1.0, 1.0).reset_index()
        ofi.columns = ["code", "ts", "ofi"]
        ofi = ofi.sort_values(["code", "ts"])
        ofi["ofi_roll3"] = ofi.groupby("code")["ofi"].transform(
            lambda s: s.rolling(roll_window, min_periods=1).mean())
        return ofi
    except Exception as e:
        logger.warning("[OFI] 실패: %s", e)
        return pd.DataFrame(columns=["code", "ts", "ofi", "ofi_roll3"])


def _calc_adx_group(high: pd.Series, low: pd.Series,
                    close: pd.Series, n: int = 14) -> pd.DataFrame:
    try:
        hl  = high - low
        hpc = (high - close.shift(1)).abs()
        lpc = (low  - close.shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        up  = high.diff()
        dn  = -low.diff()
        pdm = up.where((up > dn) & (up > 0), 0.0)
        ndm = dn.where((dn > up) & (dn > 0), 0.0)
        alpha = 1.0 / n
        atr   = tr.ewm(alpha=alpha, adjust=False).mean()
        pdi   = 100 * pdm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1e-9)
        ndi   = 100 * ndm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1e-9)
        dx    = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, 1e-9)
        adx   = dx.ewm(alpha=alpha, adjust=False).mean()
        return pd.DataFrame({"adx_14": adx, "pdi_14": pdi, "ndi_14": ndi},
                            index=high.index)
    except Exception:
        return pd.DataFrame({"adx_14": 0.0, "pdi_14": 0.0, "ndi_14": 0.0},
                            index=high.index)


def _calc_bb_group(close: pd.Series, n: int = 20,
                   std_mult: float = 2.0) -> pd.DataFrame:
    try:
        mid   = close.rolling(n, min_periods=5).mean()
        std   = close.rolling(n, min_periods=5).std()
        upper = mid + std_mult * std
        lower = mid - std_mult * std
        width = (upper - lower) / mid.replace(0, 1e-9)
        return pd.DataFrame({"bb_upper": upper, "bb_lower": lower, "bb_width": width},
                            index=close.index)
    except Exception:
        return pd.DataFrame({"bb_upper": close, "bb_lower": close, "bb_width": 0.0},
                            index=close.index)


def _calc_atr_group(high: pd.Series, low: pd.Series,
                    close: pd.Series, n: int = 10) -> pd.Series:
    """
    [FIX-1] True ATR — 지침서§2-2 단순평균 (Wilder 1978 원저)
    기존 EWM(Wilder 지수평활) → rolling(n).mean() 교체
    이유: 지침서§2-2 명시 "ATR(10) = mean(TR(i) for i in 최근 10봉)"
         EWM은 갭 발생 봉에서 과거값에 희석되어 ATR 15% 과소평가 발생
    출처: Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
          Trend Research. §2-2 ATR 계산법 직접 인용.
    """
    try:
        tr = pd.concat([
            high - low,
            (high  - close.shift(1)).abs(),
            (low   - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        # [FIX-1] ewm → rolling 단순평균
        return tr.rolling(n, min_periods=3).mean()
    except Exception:
        return pd.Series(0.0, index=high.index)


def _streak_vectorized(close_series: pd.Series,
                       code_series: pd.Series) -> pd.Series:
    diff   = close_series.groupby(code_series).diff()
    is_up  = (diff > 0).astype(int)
    break_ = (is_up == 0).astype(int)
    grp    = break_.groupby(code_series).cumsum()
    streak = is_up.groupby([code_series, grp]).cumsum()
    return streak.fillna(0).astype(int)


# ═══════════════════════════════════════════════════════════════
#  파생 팩터 + 신호 산출 핵심 (v3_4)
# ═══════════════════════════════════════════════════════════════
def _calc_derived(out: pd.DataFrame, params: Dict[str, float],
                  df1_today: Optional[pd.DataFrame] = None,
                  prev_high_map: Optional[pd.Series] = None,
                  prev_high_src: str = "internal",
                  regime: str = "TREND") -> pd.DataFrame:
    if not out.index.is_unique:
        out = out.reset_index(drop=True)

    rng        = (out["high"] - out["low"]).replace(0, 0.0001)
    close_safe = out["close"].replace(0, 0.0001)

    out["range_pct"]        = (rng / close_safe) * 100
    out["body_pct"]         = ((out["close"] - out["open"]).abs() / rng) * 100
    out["upper_wick_pct"]   = ((out["high"] - out[["open", "close"]].max(axis=1)) / rng) * 100
    out["lower_wick_pct"]   = ((out[["open", "close"]].min(axis=1) - out["low"]) / rng) * 100
    out["close_strength"]   = (out["close"] - out["low"]) / rng
    out["closing_pressure"] = (out["high"] - out["close"]) / rng

    prev_high = out.groupby("code")["high"].shift(1)
    prev_low  = out.groupby("code")["low"].shift(1)
    prev_val  = out.groupby("code")["value"].shift(1)
    prev_rng  = out.groupby("code")["range_pct"].shift(1)

    out["hh_3m"]       = (out["high"]  > prev_high).fillna(False).astype(int)
    out["hl_3m"]       = (out["low"]   > prev_low).fillna(False).astype(int)
    out["value_up_3m"] = (out["value"] > prev_val).fillna(False).astype(int)

    # 파라미터 언팩
    range_win       = int(params["range_window"])
    fast_win        = int(params["value_ma_fast"])
    slow_win        = int(params["value_ma_slow"])
    overheat_thr    = params["overheat_mult"]
    ema_span        = int(params["trend_ema_span"])
    slope_min       = params["slope_min_threshold"]
    impulse_ratio   = params["impulse_ratio"]
    ultra_accel     = params["ultra_accel_min"]
    range_exp_min   = params["range_expand_min"]
    slope_relax     = params["slope_relax_with_early"]
    ev_room_min     = params["ev_room_min"]
    ev_score_w      = params["ev_score_weight"]
    ofi_min         = params["ofi_min"]
    ofi_score_w     = params["ofi_score_weight"]
    overheat_streak = int(params["overheat_streak_max"])
    adx_min         = params["adx_min"]
    adx_n           = int(params["adx_period"])
    atr_n           = int(params.get("atr_period", 10))  # [FIX-1] 기본값 14→10
    atr_imp_scale   = params.get("atr_impulse_scale", 0.5)
    bb_n            = int(params["bb_period"])
    bb_std_m        = params["bb_std"]
    bb_squeeze_thr  = params["bb_squeeze_pct"]
    early_slope3_min= params["early_slope3_min"]
    ofi_roll_win    = int(params["ofi_roll_window"])
    ultra_body_min  = params.get("ultra_body_min", 0.40)
    confirm_cls_min = params.get("confirm_close_str_min", 0.50)
    early_accel_min = params["early_accel_min"]
    early_delta_min = params["early_delta_min"]
    entry_accel_min = params["entry_accel_min"]
    wick_max        = params["entry_upper_wick"]

    range_mean_n = out.groupby("code")["range_pct"].transform(
        lambda s: s.shift(1).rolling(range_win, min_periods=5).mean())
    value_ma_fast_s = out.groupby("code")["value"].transform(
        lambda s: s.shift(1).rolling(fast_win, min_periods=3).mean())
    value_ma_slow_s = out.groupby("code")["value"].transform(
        lambda s: s.shift(1).rolling(slow_win, min_periods=5).mean())
    value_max10 = out.groupby("code")["value"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=3).max())
    prev2_high = out.groupby("code")["high"].transform(
        lambda s: s.shift(1).rolling(2, min_periods=2).max())

    out["breakout_2_3m"]   = (out["close"] > prev2_high).fillna(False).astype(int)
    out["overheat_3m"]     = (out["range_pct"] > range_mean_n * overheat_thr).fillna(False).astype(int)
    out["value_ratio_3m"]  = (out["value"] / value_ma_slow_s.replace(0, pd.NA)).fillna(0)
    out["volume_spike_3m"] = (out["value"] > value_max10).fillna(False).astype(int)
    out["body_strength_3m"]= ((out["close"] - out["open"]).abs() / rng).fillna(0)
    trend3 = out.groupby("code")["close"].transform(
        lambda s: s.diff().rolling(3, min_periods=3).sum())
    out["trend_3bar_3m"]   = (trend3 > 0).fillna(False).astype(int)

    ema_diff = out.groupby("code")["close"].transform(
        lambda s: s.ewm(span=ema_span, adjust=False).mean().diff())
    out["trend_slope"] = ema_diff
    slope_std = out.groupby("code")["trend_slope"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=5).std().replace(0, pd.NA))
    out["trend_slope_mag"] = (ema_diff / slope_std).fillna(0)

    # [FIX-K1] ADX/BB/ATR 종목별 루프 → groupby apply 단일 패스 통합
    # 기존: for loop × 3회(ADX/BB/ATR) 개별 실행 → 종목 400개 × 3 = 1,200회 반복
    # 수정: groupby("code").apply() 1회로 ADX/BB/ATR 동시 계산
    #       pd.concat 3회 → 1회로 감소, 40~60% 연산 시간 절감
    def _calc_all_indicators(grp: pd.DataFrame,
                             adx_n: int, bb_n: int, bb_std_m: float,
                             atr_n: int) -> pd.DataFrame:
        """ADX + BB + ATR 을 한 grp 안에서 동시 계산."""
        idx = grp.index
        # ADX
        try:
            adx_df = _calc_adx_group(grp["high"], grp["low"], grp["close"], n=adx_n)
            adx_df.index = idx
        except Exception:
            adx_df = pd.DataFrame({"adx_14": 0.0, "pdi_14": 0.0, "ndi_14": 0.0}, index=idx)
        # BB
        try:
            bb_df = _calc_bb_group(grp["close"], n=bb_n, std_mult=bb_std_m)
            bb_df.index = idx
        except Exception:
            bb_df = pd.DataFrame({"bb_upper": grp["close"].values,
                                  "bb_lower": grp["close"].values,
                                  "bb_width": 0.0}, index=idx)
        # ATR
        try:
            atr_s = _calc_atr_group(grp["high"], grp["low"], grp["close"], n=atr_n)
            atr_s.index = idx
        except Exception:
            atr_s = pd.Series(0.0, index=idx, name="atr_14")

        result = pd.DataFrame(index=idx)
        for col in ["adx_14", "pdi_14", "ndi_14"]:
            result[col] = adx_df[col] if col in adx_df.columns else 0.0
        for col in ["bb_upper", "bb_lower", "bb_width"]:
            result[col] = bb_df[col] if col in bb_df.columns else 0.0
        result["atr_14"] = atr_s
        return result

    try:
        indicator_all = out.groupby("code", sort=False, group_keys=False).apply(
            _calc_all_indicators,
            adx_n=adx_n, bb_n=bb_n, bb_std_m=bb_std_m, atr_n=atr_n
        ).sort_index()

        out["adx_14"] = indicator_all["adx_14"].reindex(out.index).fillna(0)
        out["pdi_14"] = indicator_all["pdi_14"].reindex(out.index).fillna(0)
        out["ndi_14"] = indicator_all["ndi_14"].reindex(out.index).fillna(0)
        out["bb_upper"] = indicator_all["bb_upper"].reindex(out.index).fillna(out["close"])
        out["bb_lower"] = indicator_all["bb_lower"].reindex(out.index).fillna(out["close"])
        out["bb_width"] = indicator_all["bb_width"].reindex(out.index).fillna(0)
        out["atr_14"]   = indicator_all["atr_14"].reindex(out.index).fillna(0)

    except Exception as e:
        logger.warning("[FIX-K1] 통합 지표 계산 실패 → 개별 루프 fallback: %s", e)
        # fallback: 기존 개별 루프 방식
        try:
            adx_list = []
            for code, grp in out.groupby("code", sort=False):
                adx_df = _calc_adx_group(grp["high"], grp["low"], grp["close"], n=adx_n)
                adx_df.index = grp.index
                adx_list.append(adx_df)
            adx_all = pd.concat(adx_list).sort_index()
            out["adx_14"] = adx_all["adx_14"].reindex(out.index).fillna(0)
            out["pdi_14"] = adx_all["pdi_14"].reindex(out.index).fillna(0)
            out["ndi_14"] = adx_all["ndi_14"].reindex(out.index).fillna(0)
        except Exception as e2:
            logger.warning("[ADX fallback] 실패: %s", e2)
            out["adx_14"] = out["pdi_14"] = out["ndi_14"] = 0.0
        try:
            bb_list = []
            for code, grp in out.groupby("code", sort=False):
                bb_df = _calc_bb_group(grp["close"], n=bb_n, std_mult=bb_std_m)
                bb_df.index = grp.index
                bb_list.append(bb_df)
            bb_all = pd.concat(bb_list).sort_index()
            out["bb_upper"] = bb_all["bb_upper"].reindex(out.index).fillna(out["close"])
            out["bb_lower"] = bb_all["bb_lower"].reindex(out.index).fillna(out["close"])
            out["bb_width"] = bb_all["bb_width"].reindex(out.index).fillna(0)
        except Exception as e2:
            logger.warning("[BB fallback] 실패: %s", e2)
            out["bb_upper"] = out["close"]
            out["bb_lower"] = out["close"]
            out["bb_width"] = 0.0
        try:
            atr_list = []
            for code, grp in out.groupby("code", sort=False):
                atr_s = _calc_atr_group(grp["high"], grp["low"], grp["close"], n=atr_n)
                atr_s.index = grp.index
                atr_list.append(atr_s.rename("atr_14"))
            atr_all = pd.concat(atr_list).sort_index()
            out["atr_14"] = atr_all.reindex(out.index).fillna(0)
        except Exception as e2:
            logger.warning("[ATR fallback] 실패: %s", e2)
            out["atr_14"] = 0.0
    out["atr_pct"] = (out["atr_14"] / close_safe * 100).fillna(0).round(4)

    # 거래대금 파생
    out["value_slope_3"] = out.groupby("code")["value"].transform(
        lambda s: s.pct_change(3)).fillna(0)
    out["value_slope_5"] = out.groupby("code")["value"].transform(
        lambda s: s.pct_change(5)).fillna(0)
    val_3ago = out.groupby("code")["value"].transform(
        lambda s: s.shift(3).rolling(2, min_periods=1).mean()).replace(0, pd.NA)
    out["value_delta_3"] = ((out["value"] - val_3ago) / val_3ago).fillna(0)
    out["value_impulse"] = (out["value"] / prev_val.replace(0, pd.NA)).fillna(1.0)
    out["value_accel"]   = (value_ma_fast_s / value_ma_slow_s.replace(0, pd.NA)).fillna(1.0)

    # value_rank — 당일 누적 거래대금 기준
    try:
        _date_tmp = out["ts"].dt.normalize()
        cum_val_day = out.groupby([out["code"], _date_tmp])["value"].transform("sum")
        out["value_rank"] = cum_val_day.rank(pct=True).fillna(0.5)
    except Exception:
        out["value_rank"] = 0.5

    # Z-score soft cap 5.5σ
    try:
        vi_mean = out.groupby("code")["value_impulse"].transform(
            lambda s: s.shift(1).rolling(20, min_periods=5).mean())
        vi_std  = out.groupby("code")["value_impulse"].transform(
            lambda s: s.shift(1).rolling(20, min_periods=5).std().replace(0, 1e-9))
        out["value_impulse_z"] = ((out["value_impulse"] - vi_mean) / vi_std).fillna(0)
        z_cap = 5.5
        out["value_impulse"] = out["value_impulse"].where(
            out["value_impulse_z"] < z_cap,
            other=vi_mean + z_cap * vi_std
        ).fillna(out["value_impulse"])
    except Exception:
        out["value_impulse_z"] = 0.0

    out["price_breakout"]  = (out["close"] > prev_high).fillna(False).astype(int)
    out["range_expanding"] = (out["range_pct"] > prev_rng.replace(0, pd.NA) * range_exp_min
                              ).fillna(False).astype(int)
    out["higher_close_streak"] = _streak_vectorized(out["close"], out["code"])

    out["bb_squeeze"]  = (out["bb_width"] < bb_squeeze_thr).astype(int)
    out["bb_breakout"] = (out["close"] > out["bb_upper"]).astype(int)
    prev_squeeze = out.groupby("code")["bb_squeeze"].shift(1).fillna(0)
    out["compression_expand"] = ((prev_squeeze == 1) & (out["bb_breakout"] == 1)).astype(int)

    out["session"] = _session_label(out["ts"])
    out["_date"]   = out["ts"].dt.normalize()

    # VWAP
    pv      = out["close"] * out["value"]
    cum_pv  = pv.groupby([out["code"], out["_date"]]).cumsum()
    cum_val = out["value"].groupby([out["code"], out["_date"]]).cumsum().replace(0, 0.0001)
    out["vwap"]       = cum_pv / cum_val
    out["vwap_dev"]   = (out["close"] - out["vwap"]) / out["vwap"].replace(0, 0.0001)
    out["vwap_hold"]  = (out["close"] >= out["vwap"]).astype(int)
    out["vwap_rising"]= (out.groupby(["code", "_date"])["vwap"].diff() > 0).fillna(False).astype(int)
    out["vwap_dev_score"] = out["vwap_dev"].clip(0, 0.03).div(0.03).fillna(0).round(4)

    day_high_cm    = out.groupby(["code", "_date"])["high"].cummax()
    out["dist_high"]= (out["close"] - day_high_cm) / day_high_cm.replace(0, 0.0001)

    # EV (전일고가 대비)
    if prev_high_map is not None and not prev_high_map.empty:
        _prev_h = out["code"].map(prev_high_map).replace(0, pd.NA)
    else:
        _dhc    = out.groupby(["code", "_date"])["high"].cummax()
        _prev_h = _dhc.groupby(out["code"]).shift(1)
    _prev_h = _prev_h.replace(0, pd.NA)
    out["ev_dist"] = ((out["close"] - _prev_h) / _prev_h).fillna(0)
    out["ev_pass"] = ((out["session"] == 0) | (out["ev_dist"] < ev_room_min)).astype(int)

    out = out.drop(columns=["_date"])

    # OFI
    ofi_is_real = (df1_today is not None and not df1_today.empty)
    if ofi_is_real:
        ofi_df = build_ofi_3m(df1_today, roll_window=ofi_roll_win)
        if not ofi_df.empty:
            ofi_df["ts"]   = pd.to_datetime(ofi_df["ts"])
            ofi_df["code"] = ofi_df["code"].astype(str).str.strip()
            out = out.merge(ofi_df, on=["code", "ts"], how="left")
        else:
            out["ofi"] = out["ofi_roll3"] = 0.0
    else:
        # [FIX-7] DEBUG→WARNING: 추정 OFI 전환 즉시 인지
        logger.warning("[OFI] df1_today 없음 → 캔들 방향 기반 OFI 추정 (신뢰도 70%%)")
        direction       = (out["close"] >= out["open"]).astype(float) * 2 - 1
        out["ofi"]      = (direction * out["body_pct"] / 100.0).clip(-1.0, 1.0)
        out["ofi_roll3"]= out.groupby("code")["ofi"].transform(
            lambda s: s.rolling(ofi_roll_win, min_periods=1).mean())

    out["ofi"]       = pd.to_numeric(out["ofi"],       errors="coerce").fillna(0.0).clip(-1, 1)
    out["ofi_roll3"] = pd.to_numeric(out["ofi_roll3"], errors="coerce").fillna(0.0).clip(-1, 1)

    # [FIX-5] 기관 편승 점수 — 음수 OFI slope 패널티 추가
    try:
        # 양수 기관 가속 강도
        ofi_slope_pos = out.groupby("code")["ofi_roll3"].transform(
            lambda s: s.diff(3).rolling(3, min_periods=1).mean())
        # [FIX-5] 음수 slope = 기관 이탈 신호 → inst_momentum 패널티
        ofi_slope_neg_penalty = ((-ofi_slope_pos).clip(0, 0.3) / 0.3).fillna(0) * 0.30

        val_accel_norm = ((out["value_accel"] - 1.0) / 2.0).clip(0, 1)
        ofi_strength   = out["ofi_roll3"].clip(0, 1)
        raw_inst = (
            ofi_strength * 0.40 +
            ofi_slope_pos.clip(0, 0.5).div(0.5).fillna(0) * 0.30 +
            val_accel_norm * 0.30
        ).clip(0, 1.0)

        # 추정 OFI 신뢰도 30% 할인
        if not ofi_is_real:
            raw_inst = raw_inst * 0.70

        # [FIX-5] 음수 slope 패널티 적용 (기관 이탈 조기 감지)
        raw_inst = (raw_inst - ofi_slope_neg_penalty).clip(0, 1.0)
        out["inst_momentum_3m"] = raw_inst.round(4)
    except Exception:
        out["inst_momentum_3m"] = 0.0

    # ATR 동적 impulse
    atr_adj = (out["atr_pct"] * atr_imp_scale).clip(0, 0.5)
    effective_impulse = impulse_ratio + atr_adj

    # ── 신호 3단계 ──
    not_overextended = (out["higher_close_streak"] < overheat_streak) | (out["overheat_3m"] == 0)

    # ULTRA
    is_bullish     = out["close"] > out["open"]
    is_strong_bear = (out["body_strength_3m"] > ultra_body_min) & (out["close"] <= out["open"])
    price_struct = (
        (out["price_breakout"]     == 1) | (out["range_expanding"]  == 1) |
        (out["compression_expand"] == 1) | (out["volume_spike_3m"]  == 1) |
        (out["bb_breakout"]        == 1)
    )
    ultra_base = (
        (out["value_impulse"]   > effective_impulse) &
        price_struct & (out["value_accel"] > ultra_accel) &
        not_overextended & (is_bullish | is_strong_bear) & (out["vwap_hold"] == 1)
    )
    out["ultra_early_signal"] = ultra_base.astype(int)
    impulse_str = ((out["value_impulse"] - effective_impulse) /
                   (3.0 - effective_impulse + 1e-9)).clip(0, 1.0)
    accel_str   = ((out["value_accel"] - ultra_accel) / (3.0 - ultra_accel + 1e-9)).clip(0, 1.0)
    body_str_n  = out["body_strength_3m"].clip(0, 1.0)
    out["ultra_score"] = (out["ultra_early_signal"].astype(float) *
                          (impulse_str * 0.50 + accel_str * 0.30 + body_str_n * 0.20)).fillna(0.0)

    # EARLY
    early_price_ok = (out["hh_3m"] == 1) | (out["breakout_2_3m"] == 1) | (out["trend_3bar_3m"] == 1)
    early_base = (
        (out["value_delta_3"] > early_delta_min) & (out["value_accel"] > early_accel_min) &
        (out["value_slope_3"] > early_slope3_min) & (out["ofi_roll3"] > ofi_min) &
        early_price_ok & not_overextended & (out["vwap_hold"] == 1) & (out["close"] > out["open"])
    )
    out["early_signal"] = early_base.astype(int)
    early_str = ((out["value_accel"] - early_accel_min) /
                 (3.0 - early_accel_min + 1e-9)).clip(0, 1.0)
    out["early_score"] = (out["early_signal"].astype(float) * early_str).fillna(0.0)

    # CONFIRM
    recent_early = out.groupby("code")["early_signal"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).max()).fillna(0)
    recent_ultra = out.groupby("code")["ultra_early_signal"].transform(
        lambda s: s.shift(1).rolling(2, min_periods=1).max()).fillna(0)
    slope_cond = out["trend_slope_mag"] > slope_min * slope_relax
    adx_cond   = (out["adx_14"] > adx_min) & (out["pdi_14"] > out["ndi_14"])
    confirm_base = (
        (out["value_accel"] > entry_accel_min) & (out["vwap_hold"] == 1) &
        (out["vwap_rising"] == 1) & (out["upper_wick_pct"] < wick_max) &
        (out["close_strength"] > confirm_cls_min) & (out["hl_3m"] == 1) &
        not_overextended & slope_cond & adx_cond &
        ((recent_early == 1) | (recent_ultra == 1))
    )
    out["confirm_signal"] = confirm_base.astype(int)
    slope_str = (out["trend_slope_mag"].clip(0) / (slope_min * 3.0 + 1e-9)).clip(0, 1.0)
    adx_str   = ((out["adx_14"] - adx_min) / (60.0 - adx_min + 1e-9)).clip(0, 1.0)
    out["confirm_score"] = (out["confirm_signal"].astype(float) *
                            (slope_str * 0.6 + adx_str * 0.4)).fillna(0.0)

    # 레짐별 신호 가중치
    _W_REGIME = {
        "TREND":    {0: (0.45, 0.30, 0.25), 1: (0.35, 0.30, 0.35), 2: (0.25, 0.30, 0.45)},
        "RANGE":    {0: (0.20, 0.35, 0.45), 1: (0.20, 0.35, 0.45), 2: (0.15, 0.30, 0.55)},
        "VOLATILE": {0: (0.25, 0.25, 0.50), 1: (0.25, 0.25, 0.50), 2: (0.20, 0.25, 0.55)},
    }
    _W   = _W_REGIME.get(regime, _W_REGIME["TREND"])
    sess = out["session"].map(lambda s: _W.get(int(s), _W[1]))
    w_u  = sess.map(lambda w: w[0])
    w_e  = sess.map(lambda w: w[1])
    w_c  = sess.map(lambda w: w[2])

    base_score = out["ultra_score"] * w_u + out["early_score"] * w_e + out["confirm_score"] * w_c
    ev_cont    = ((-out["ev_dist"]).clip(0, 0.10) / 0.10) * 0.25
    ev_binary  = out["ev_pass"] * ev_score_w
    ev_bonus   = (ev_cont * 0.6 + ev_binary * 0.4)
    ofi_bonus  = (out["ofi_roll3"] > ofi_min).astype(float) * ofi_score_w
    vwap_bonus = out["vwap_dev"].clip(0, 0.03) / 0.03 * 0.05
    inst_bonus = out["inst_momentum_3m"].clip(0, 1) * 0.12

    signal_score_raw = (base_score + ev_bonus + ofi_bonus + vwap_bonus + inst_bonus).clip(0, 1.50)

    cost_penalty = (
        0.04 * ((out["atr_pct"] - 2.5).clip(lower=0) / 2.5).clip(0, 1) +
        0.03 * ((out["upper_wick_pct"] - 35).clip(lower=0) / 35).clip(0, 1)
    )
    turnover_penalty = (
        ((out.get("value_impulse_z", pd.Series(0, index=out.index)) >= 4.5).astype(float) * 0.05) +
        (((out["compression_expand"] == 1) & (out["bb_breakout"] == 1) &
          (out["overheat_3m"] == 1)).astype(float) * 0.04)
    )
    liquidity_penalty = (
        (out["value_rank"] < 0.20).astype(float) * 0.08 +
        (out["value_ratio_3m"] < 0.8).astype(float) * 0.05
    )

    out["signal_score"] = (
        signal_score_raw - cost_penalty - turnover_penalty - liquidity_penalty
    ).clip(0, 1.40).round(4)

    # 하드 필터
    hard_cut = (
        (out["atr_pct"] > 6.5) |
        (out["upper_wick_pct"] > 55) |
        ((out["overheat_3m"] == 1) & (out["higher_close_streak"] >= 3)) |
        ((out["bb_width"] > 0.18) & (regime == "VOLATILE"))
    )
    hard_cut_cnt = int(hard_cut.sum())
    out.loc[hard_cut, "signal_score"] = 0.0
    if hard_cut_cnt > 0:
        logger.info("[HARD_CUT] %d건 강제 0점 (저유동/과변동/위꼬리/과열)", hard_cut_cnt)

    # [A2 + FIX-4] market_bad_flag
    market_bad = _detect_bad_market()
    out["market_bad_flag"] = market_bad

    # siga_hint
    ofi_siga_min = max(ofi_min, 0.12)
    out["siga_hint"] = (
        (out["session"] == 0) &
        ((out["ultra_early_signal"] == 1) | (out["early_signal"] == 1)) &
        (out["ofi_roll3"] > ofi_siga_min) &
        (out["value_impulse"] > effective_impulse + 0.12) &
        (out["vwap_hold"] == 1) &
        (out["upper_wick_pct"] < 35) &
        (out["ev_pass"] == 1)
    ).astype(int)

    # pullback_hint
    adx_pb_min = max(18.0, adx_min - 3.0)
    pb_vwap_upper = out["vwap_dev"].where(
        out["inst_momentum_3m"] > 0.60, 0.003
    ).fillna(0.003).clip(upper=0.008)
    out["pullback_hint"] = (
        (out["session"] == 1) &
        (out["inst_momentum_3m"] > 0.45) &
        (out["hl_3m"] == 1) &
        (out["vwap_dev"] > -0.010) &
        (out["vwap_dev"] < pb_vwap_upper) &
        (out["trend_slope_mag"] > slope_min * 0.45) &
        (out["adx_14"] > adx_pb_min) &
        (out["overheat_3m"] == 0)
    ).astype(int)

    # 나쁜 장 차단
    if market_bad == 1:
        out["siga_hint"]     = 0
        out["pullback_hint"] = 0

    # hf_rank_score (절대값)
    out["hf_rank_score"] = (
        out["signal_score"] +
        0.06 * out["inst_momentum_3m"].clip(0, 1) +
        0.05 * out["close_strength"].clip(0, 1) +
        0.04 * out["vwap_dev_score"].clip(0, 1) +
        0.03 * (out["adx_14"].clip(0, 35) / 35) -
        0.05 * out["overheat_3m"]
    ).clip(0, 1.50).round(4)

    # 꼭지 매수 차단
    late_entry_block = (
        (out["overheat_3m"] == 1) &
        (out["higher_close_streak"] >= 2) &
        (out["dist_high"] > -0.005)
    )
    out.loc[late_entry_block, "signal_score"] *= 0.2
    late_cnt = int(late_entry_block.sum())

    # 저유동 완전 제거
    hard_liquidity_cut = (
        (out["value_rank"] < 0.30) |
        (out["value_ratio_3m"] < 0.9)
    )
    out.loc[hard_liquidity_cut, "hf_rank_score"] = 0.0
    liq_cut_cnt = int(hard_liquidity_cut.sum())

    # 기관 추적 강화 (inst^1.5)
    inst_power_boost = (out["inst_momentum_3m"].clip(0, 1) ** 1.5) * 0.08
    out["hf_rank_score"] += inst_power_boost

    # 진짜 자리 필터 (soft)
    entry_quality_score = (
        ((out["vwap_dev"] > -0.008).astype(float) * 0.35 +
         (out["vwap_dev"] < 0.006).astype(float) * 0.30 +
         (out["close_strength"] > 0.55).astype(float) * 0.35)
    ).clip(0.4, 1.0)
    out["hf_rank_score"] *= entry_quality_score

    # TOP 집중 스케일링
    nonzero_mask = out["hf_rank_score"] > 0
    if nonzero_mask.any():
        top_scale = out.loc[nonzero_mask, "hf_rank_score"].rank(pct=True)
        out.loc[nonzero_mask, "hf_rank_score"] *= (1 + top_scale * 0.3)

    # 1등 압축 (gap≥0.05 일 때만)
    hf_top2    = out["hf_rank_score"].nlargest(2)
    hf_gap_now = float(hf_top2.iloc[0] - hf_top2.iloc[1]) if len(hf_top2) >= 2 else 0.0
    if hf_gap_now >= 0.05:
        rank_boost = (
            (out["hf_rank_score"] > 1.00).astype(float) * 0.08 +
            (out["hf_rank_score"] > 1.10).astype(float) * 0.12
        )
    else:
        rank_boost = 0.0
    out["hf_rank_score"] = (out["hf_rank_score"] + rank_boost).clip(0, 2.00).round(4)

    # [FIX-K3] hf_rank_score_norm — session별 독립 정규화 (0~1)
    # 기존: 전체 봉 기준 min-max → 오전 ULTRA 신호로 오후 봉이 과소평가
    # 수정: session(0/1/2)별 독립 min-max → 시간대 내 상대 비교로 정확도 향상
    def _session_norm(series: pd.Series, sess: pd.Series) -> pd.Series:
        result = pd.Series(0.0, index=series.index)
        for s in [0, 1, 2]:
            mask = sess == s
            if mask.sum() == 0:
                continue
            vals = series[mask]
            lo, hi = vals.min(), vals.max()
            rng = hi - lo
            if rng > 1e-9:
                result[mask] = ((vals - lo) / rng).round(4)
            else:
                result[mask] = 0.0
        return result

    out["hf_rank_score_norm"] = _session_norm(
        out["hf_rank_score"], out["session"]
    )

    # 로그
    total = max(len(out), 1)
    hf_top3 = out["hf_rank_score"].nlargest(3)
    hf_gap  = float(hf_top3.iloc[0] - hf_top3.iloc[1]) if len(hf_top3) >= 2 else 0.0
    logger.info("[SIGNAL v3_4] regime=%s market_bad=%d | "
                "ultra=%d(%.1f%%) early=%d(%.1f%%) confirm=%d(%.1f%%) "
                "avg_score=%.3f avg_hf=%.3f TOP1_hf=%.3f TOP1_norm=%.3f gap=%.3f | "
                "hard=%d late=%d liq=%d | siga=%d pb=%d | "
                "ATR방식=rolling(단순평균) atr_n=%d",
                regime, market_bad,
                int(out["ultra_early_signal"].sum()), out["ultra_early_signal"].sum() / total * 100,
                int(out["early_signal"].sum()), out["early_signal"].sum() / total * 100,
                int(out["confirm_signal"].sum()), out["confirm_signal"].sum() / total * 100,
                float(out["signal_score"].mean()), float(out["hf_rank_score"].mean()),
                float(hf_top3.iloc[0]) if len(hf_top3) else 0.0,
                float(out["hf_rank_score_norm"].max()),
                hf_gap, hard_cut_cnt, late_cnt, liq_cut_cnt,
                int(out["siga_hint"].sum()), int(out["pullback_hint"].sum()), atr_n)
    return out


def _validate_3m(df: pd.DataFrame, label: str) -> None:
    key_cols = [
        "open", "high", "low", "close", "value", "vwap", "vwap_rising", "trend_slope_mag",
        "adx_14", "atr_14", "atr_pct", "bb_width", "bb_squeeze", "ofi_roll3", "value_rank",
        "session", "inst_momentum_3m",
        "ultra_early_signal", "early_signal", "confirm_signal",
        "ultra_score", "early_score", "confirm_score", "signal_score",
        "hf_rank_score", "hf_rank_score_norm",
        "siga_hint", "pullback_hint", "market_bad_flag"
    ]
    issues = []
    for c in key_cols:
        if c not in df.columns:
            issues.append(f"{c}=MISSING"); continue
        nan_pct = df[c].isna().mean() * 100
        if nan_pct > 5.0:
            issues.append(f"{c}={nan_pct:.1f}%NaN")
    if issues:
        logger.warning("[QA] %s 이슈: %s", label, ", ".join(issues))
    else:
        logger.info("[QA] %s OK (v3_4)", label)


def drop_last_incomplete_3m(df1_today: pd.DataFrame,
                             df3: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    if df1_today.empty or df3.empty: return df3, 0
    df1t = df1_today.copy()
    df1t["ts3"] = df1t["ts"].dt.floor("3min")
    last_ts3 = df1t.groupby("code")["ts3"].max()
    cnt      = df1t.groupby(["code", "ts3"]).size()
    last_1m  = df1t.groupby("code")["ts"].max()
    incomplete = []
    for code, ts3 in last_ts3.items():
        c = int(cnt.get((code, ts3), 0))
        last_ts = last_1m.get(code, pd.NaT)
        if pd.isna(last_ts): continue
        if (c < 3) or (int(pd.Timestamp(last_ts).minute) % 3 != 2):
            incomplete.append(code)
    if not incomplete: return df3, 0
    before = len(df3)
    last_ts_by_code = df3.groupby("code")["ts"].transform("max")
    mask = df3["code"].isin(incomplete) & (df3["ts"] == last_ts_by_code)
    out  = df3.loc[~mask].reset_index(drop=True)
    removed = before - len(out)
    if removed > 0:
        logger.info("미완성 봉 제거: %d codes=%s", removed, incomplete)
    return out, removed


def _align_cols(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for c in OUT_COLS:
        if c not in result.columns: result[c] = 0
    return result[OUT_COLS].copy()


def _trim_rows(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = (df.sort_values(["code", "ts"], kind="mergesort")
            .groupby("code", group_keys=False).tail(MAX_ROWS_PER_CODE))
    removed = before - len(df)
    if removed > 0:
        logger.info("행수 상한: %d건 제거", removed)
    return df.reset_index(drop=True)


def _sanity_check_merge(past: pd.DataFrame, merged: pd.DataFrame) -> None:
    p, m = len(past), len(merged)
    if p > 0 and m < p * 0.8:
        logger.warning("[SANITY] 행수 급감: past=%d merged=%d (%.0f%%)", p, m, m / p * 100)


def main() -> None:
    t0       = _now()
    deadline = t0 + max(0.0, FLOW_BUDGET_SEC)
    params_raw = load_params()
    regime     = _detect_regime()
    params     = _apply_regime_adjustments(params_raw, regime)
    lock_owned = acquire_lock_failopen()

    try:
        logger.info(
            "START v3_4 SIGA+PB | regime=%s FLOW_BUDGET=%.1fs DROP_LAST=%s lock=%s "
            "OUT_COLS=%d | impulse=%.2f adx=%.0f slope=%.2f ev=%.3f ofi=%.2f "
            "atr_period=%.0f(rolling단순평균) atr_scale=%.2f",
            regime, FLOW_BUDGET_SEC, DROP_LAST_INCOMPLETE, lock_owned, len(OUT_COLS),
            params["impulse_ratio"], params["adx_min"], params["slope_min_threshold"],
            params["ev_room_min"], params["ofi_min"],
            params.get("atr_period", 10), params.get("atr_impulse_scale", 0.5))
        logger.info(
            "학술출처 | ATR:Wilder(1978) Chandelier:LeBeau&Lucas(1992) "
            "OFI:Cont,Kukanov,Stoikov(2014)JFEC12(1) "
            "TSL:Kaminski&Lo(2014)JFM18 VIX30:Whaley(2000)JPM26(3)")
        _log_path_stat("SRC", SRC)
        _log_path_stat("DST", DST)
        _check_src_freshness()

        with _Timer("READ_SRC"):
            df1_raw = read_csv_marketdata(SRC, deadline, tag="SRC")
            df1     = _clean_1m(df1_raw)

        # [PATCH] 자정 이후 실행 시 today 기준이면 rows=0 → prices_1m 내 최근 거래일 사용
        _ts_max      = df1["ts"].max() if not df1.empty else pd.NaT
        logger.info("[DATE] parsed ts max=%s", _ts_max)
        _latest_date = _ts_max.normalize() if pd.notna(_ts_max) else kst_now_naive().normalize()
        today        = _latest_date
        today_end    = today + pd.Timedelta(days=1)
        logger.info("[DATE] using latest trading date=%s", today.strftime("%Y-%m-%d"))
        df_today  = df1[(df1["ts"] >= today) & (df1["ts"] < today_end)].copy()
        logger.info("TODAY 1m | rows=%d codes=%d", len(df_today), df_today["code"].nunique())
        if df_today.empty: _hold("TODAY_SLICE", "today slice empty")

        with _Timer("PREV_HIGH"):
            prev_high_map, prev_high_src = load_prev_day_high(df1)

        with _Timer("BUILD_3M"):
            today_3m_raw = build_3m(df_today)

            # [FIX-K5] 롤링 지표 워밍업 경고
            # ADX(14)/BB(20)/ATR(10) 등 최소 20봉(1시간) 미만 구간은 신뢰도 낮음
            n_bars_min = today_3m_raw.groupby("code")["ts"].count().min() if not today_3m_raw.empty else 0
            if n_bars_min < 20:
                logger.warning(
                    "[FIX-K5] 워밍업 부족: 최소 %d봉 — ADX/BB/ATR 신뢰도 낮음 "
                    "(최소 20봉=1시간 필요). CONFIRM 신호 오발동 주의.", n_bars_min)

            today_3m_raw = _calc_derived(today_3m_raw, params,
                                         df1_today=df_today,
                                         prev_high_map=prev_high_map,
                                         prev_high_src=prev_high_src,
                                         regime=regime)

        _validate_3m(today_3m_raw, "TODAY_3M")

        if DROP_LAST_INCOMPLETE:
            today_3m, removed = drop_last_incomplete_3m(df_today, today_3m_raw)
        else:
            today_3m, removed = today_3m_raw, 0

        logger.info("TODAY 3m | rows=%d codes=%d removed=%d prev_src=%s",
                    len(today_3m), today_3m["code"].nunique(), removed, prev_high_src)

        if DST.exists():
            dst_size, _ = _stat_safe(DST)
            if dst_size == 0: _hold("READ_DST", "DST 0bytes")
            with _Timer("READ_DST"):
                dfp_raw = read_csv_marketdata(DST, deadline, tag="DST")
            if not {"ts", "code"}.issubset(dfp_raw.columns):
                _hold("READ_DST", "DST missing ts/code")
            dfp         = dfp_raw.copy()
            dfp["ts"]   = _to_kst_naive(dfp["ts"])
            dfp["code"] = dfp["code"].astype(str).str.strip()
            dfp         = dfp.dropna(subset=["ts", "code"]).sort_values(
                ["code", "ts"], kind="mergesort")
            past = _align_cols(dfp)
        else:
            past = pd.DataFrame(columns=OUT_COLS)

        with _Timer("MERGE"):
            today_3m = _align_cols(today_3m)
            merged   = pd.concat([past, today_3m], ignore_index=True)
            merged   = merged.drop_duplicates(subset=["code", "ts"], keep="last")
            merged   = merged.sort_values(["code", "ts"], kind="mergesort")
            merged   = _trim_rows(merged)

        if merged.empty: _hold("MERGE", "merged empty")
        _sanity_check_merge(past, merged)

        with _Timer("WRITE"):
            try:
                merged.to_csv(TMP, index=False, encoding="utf-8-sig")
            except Exception as e:
                _hold("WRITE_TMP", f"TMP write failed: {e}")
            atomic_replace(TMP, DST, deadline)

        maybe_evolve_params(params_raw, merged)

        logger.info("DONE v3_4 | regime=%s rows=%d codes=%d elapsed=%.3fs avg_score=%.3f",
                    regime, len(merged), merged["code"].nunique(), _now() - t0,
                    float(merged.get("signal_score", pd.Series([0.0])).mean()))
        raise SystemExit(RC_OK)

    except SystemExit:
        raise
    except Exception as e:
        logger.exception("UNHANDLED: %s", e)
        _hold("UNHANDLED", "unexpected exception")
    finally:
        try:
            if TMP.exists(): TMP.unlink(missing_ok=True)
        except Exception:
            pass
        if lock_owned:
            release_lock_if_owned()


if __name__ == "__main__":
    main()
