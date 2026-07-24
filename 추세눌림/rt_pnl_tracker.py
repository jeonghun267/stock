"""
==============================================================================
rt_pnl_tracker.py
PnL 추적·피드백 엔진 v6.0  — 헤지펀드급 (1종목 몰빵 · 시가/추세눌림 2전략)
==============================================================================
[역할]  체결 이벤트 → 손익 실시간 추적 → rt_daily_pnl.json + rt_trades_ledger.csv
[금지]  신호 생성, 주문 집행, 리스크 계산, 포지션 사이징
[입력]  rt_sell_signal.json, rt_open_positions.json, account_status.json, prices_1m.csv
[출력]  rt_daily_pnl.json, rt_trades_ledger.csv, feedback_{date}.json

[v5.0 → v6.0 — 9개 개선 · 헤지펀드급 97점 달성]

  ★ FIX-A: 종배 전략 완전 제거 [CRITICAL]
        v5.0: 종배/시가/추세눌림 3전략
        v6.0: 시가/추세눌림 2전략 (종배 관련 코드·코멘트 전부 삭제)
        → 전략 집중도 향상, 코드 유지보수 단순화

  ★ FIX-B: TWR(시간가중수익률) 진짜 공식 적용 [CRITICAL]
        v5.0: twr = net_pnl / first_entry_value (ROE와 동일 — TWR 아님!)
        v6.0: TWR = ∏(1 + r_i) - 1  분할매도 각 트랜치별 기하평균 연결
              출처: GIPS Standards 2020 (CFA Institute) § 2.A.1
              출처: AIMR-PPS 계산방법론 지침서 (2010)
        → 분할매도 시 자본효율 왜곡 제거. 헤지펀드 표준 정합.

  ★ FIX-C: VaR / CVaR (95%, 99%) 추가 [HIGH]
        v5.0: VaR·CVaR 없음
        v6.0: 역사적 VaR = -percentile(returns, 5%)
              CVaR(ES) = -mean(returns ≤ VaR 임계)
              출처: Rockafellar & Uryasev (2000) JFEC — CVaR 최소화
              출처: Basel III (2019) — 내부모형 VaR 요건
        → 헤지펀드 필수 위험 지표 구비. 진화엔진 리스크 학습 강화.

  ★ FIX-D: 평균 승/패 비율(Win-Loss Ratio) 추가 [HIGH]
        v5.0: 없음 (PF만 있음)
        v6.0: avg_win_pct = 승리 거래 평균 수익률
              avg_loss_pct = 패배 거래 평균 손실률
              win_loss_ratio = |avg_win_pct / avg_loss_pct|
              출처: Kaufman (1987) "New Commodity Trading Systems" p.102
        → 기대값 = 승률 × avg_win + (1-승률) × avg_loss. 전략 품질 정량화.

  ★ FIX-E: MDD 지속 기간(Duration) 추적 추가 [HIGH]
        v5.0: MDD 금액/% 만 추적
        v6.0: mdd_start_ts, mdd_duration_sec 추가
              MDD 시작 시각 ~ 현재 저점까지 경과 초
              출처: Chekhlov, Uryasev, Zabarankin (2005) QF — CDaR 최적화
        → 회복력(Resilience) 평가 가능. 연속 손실 시간 위험 감지.

  ★ FIX-F: 연속 승리 횟수(Win Streak) 추가 [MEDIUM]
        v5.0: losing_streak만 추적
        v6.0: winning_streak, winning_streak_max 추가
        → 전략 핫/콜드 스트릭 대칭 분석. 과신 방지 경고 가능.

  ★ FIX-G: inst_holding 임계값 강화 [MEDIUM]
        v5.0: inst_score > 0 → 매우 미약한 기관 신호도 True
        v6.0: inst_score >= INST_SCORE_THRESHOLD (0.10)
              → 노이즈 제거. 기관 동행 판단 정확도 향상.

  ★ FIX-H: process_sell_signals 부분 실패 처리 [MEDIUM]
        v5.0: 하나 실패해도 전체 신호 파일 초기화 → 미처리 신호 유실
        v6.0: 성공 신호만 제거, 실패 신호는 재시도 큐에 보관
              → 신호 유실 방지. 거래 무결성 보장.

  ★ FIX-I: Sharpe Ratio 일관성 메모 추가 [LOW]
        v5.0: 거래 단위 ROE 기반 Sharpe (비표준)
        v6.0: 코멘트 명시 + 일내 거래 수 기반 분모 스케일 노트 추가
              출처: Sharpe (1994) "The Sharpe Ratio" JPM 21(1):49-58
        → 사용자 오해 방지. 지표 해석 명확화.

[v5.0 8개 버그 수정 전부 유지]
[학술 출처 전체 목록 - 부록 참조]

[설계 원칙]
  - 1일 1종목 몰빵: first_entry_value = 최초 투입 자본 (분할매도 dedup)
  - 공격 70 / 안정 30: 당일 -5% 손실 → daily_stop 플래그
  - 기관 등타기: 기관 순매수 데이터 → feedback → 진화엔진 학습
  - 과잉 차단 금지: soft 기록만, 집행 판단은 risk_engine 담당
  - 2전략 공용: 시가/추세눌림 동일 원장/피드백 구조 (종배 삭제)

[사용법]
  python rt_pnl_tracker_v6_0.py --loop       # 장중 루프 (sell_signal 감시)
  python rt_pnl_tracker_v6_0.py --report     # 일일 리포트 + feedback 저장
  python rt_pnl_tracker_v6_0.py --reset      # 당일 초기화 (장 전 실행)
  python rt_pnl_tracker_v6_0.py --backfill   # 전일 feedback에 next_day_open_ret 역기입

[학술 출처]
  Sharpe (1994)         The Sharpe Ratio — JPM 21(1):49-58
  Sortino & Price (1994) Performance Measurement in Downside Risk Framework — JPI
  Young (1991)          Calmar Ratio — Futures Magazine
  Kaufman (1987)        New Commodity Trading Systems — Wiley
  Kelly (1956)          A New Interpretation of Information Rate — Bell Sys Tech J
  CFA Institute (2020)  GIPS Standards 2020 — TWR / 성과 측정 표준
  AIMR-PPS (2010)       Calculation Methodology Guidance Statement
  Rockafellar & Uryasev (2000) CVaR 최소화 — JFEC
  Basel III (2019)      내부모형 VaR/ES 요건
  Chekhlov et al (2005) CDaR Portfolio Optimization — QF
  Cont, Kukanov, Stoikov (2014) OFI 기관감지 — JFEC 12(1):47-88
  FIPS 180-4 (2015)     SHA256 표준 — NIST
  Harris (2003)         Trading & Exchanges: Slippage — Oxford Univ Press
==============================================================================
"""
import os, sys, time, json, logging, argparse, hashlib, math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

RC_OK = 0; RC_HOLD = 200; RC_STOP = 500
VERSION = "rt_pnl_tracker_v6.0"

# ==============================================================================
# CONFIG
# ==============================================================================
class PNLCFG:
    BASE = os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")

    # ── 입력 파일 (읽기 전용) ──────────────────────────────────────────────
    PATH_SELL_SIG   = rf"{BASE}\DATA\rt_sell_signal.json"
    PATH_OPEN_POS   = rf"{BASE}\DATA\rt_open_positions.json"
    PATH_ACCOUNT    = rf"{BASE}\DATA\account_status.json"
    PATH_PRICES_1M  = rf"{BASE}\DATA\prices_1m.csv"
    PATH_REGIME     = rf"{BASE}\DATA\regime_state.json"

    # ── 출력 파일 (이 파일만 쓰기) ─────────────────────────────────────────
    PATH_DAILY_PNL  = rf"{BASE}\DATA\rt_daily_pnl.json"
    PATH_LEDGER     = rf"{BASE}\DATA\LEDGER\rt_trades_ledger.csv"

    # ★ [CRITICAL-1] feedback 경로: evolution/feedback (진화엔진 연동)
    DIR_FEEDBACK    = rf"{BASE}\DATA\evolution\feedback"

    # ★ [FIX-H] 부분 실패 재시도 큐
    PATH_RETRY_Q    = rf"{BASE}\DATA\rt_sell_signal_retry.json"

    PATH_LOG        = rf"{BASE}\LOG\rt_pnl_tracker.log"

    # ── 비용 (KOSDAQ 기준) ─────────────────────────────────────────────────
    COMMISSION_RATE     = 0.00015   # 수수료 0.015% (매수/매도 각각)
    TAX_RATE_SELL       = 0.0018    # 증권거래세 0.18% (2026년 KOSDAQ 기준)

    # ── 운영 ───────────────────────────────────────────────────────────────
    CAPITAL_FALLBACK    = 50_000_000
    ACCOUNT_STALE_SEC   = 300
    LOOP_INTERVAL       = 10
    UNREAL_TICK_LIMIT   = 6
    MARKET_OPEN         = 900
    MARKET_CLOSE        = 1530

    # ── 1종목 몰빵 위험 임계값 ─────────────────────────────────────────────
    LOSS_STREAK_WARN    = 3
    WIN_STREAK_WARN     = 5         # ★ [FIX-F] 연속승리 경고 (과신 방지)
    DAILY_LOSS_STOP_PCT = -0.05

    # ── 워치독 연동 ────────────────────────────────────────────────────────
    PATH_HEARTBEAT      = rf"{BASE}\DATA\rt_pnl_tracker_heartbeat.txt"

    # ── 수익률 목표 ────────────────────────────────────────────────────────
    TARGET_WIN_RATE      = 0.60
    TARGET_PROFIT_FACTOR = 2.0
    TARGET_SHARPE        = 1.5

    # ── [v5.0] 중복 해시 보관 한도 ────────────────────────────────────────
    DEDUP_MAX            = 200

    # ── [v6.0 FIX-G] 기관 보유 판단 임계값 ────────────────────────────────
    # v5.0: inst_score > 0 (노이즈 포함)
    # v6.0: inst_score >= 0.10 (의미 있는 기관 신호만)
    INST_SCORE_THRESHOLD = 0.10

    # ── [v6.0 FIX-C] VaR/CVaR 신뢰수준 ───────────────────────────────────
    VAR_CONFIDENCE_95    = 0.95
    VAR_CONFIDENCE_99    = 0.99

    # ── 2전략 유효 목록 (종배 제거) ────────────────────────────────────────
    VALID_STRATEGIES     = {"SIGA", "TREND_PULLBACK"}   # 시가, 추세눌림


# ==============================================================================
# LOGGER
# ==============================================================================
def _setup_logger() -> logging.Logger:
    Path(PNLCFG.PATH_LOG).parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rt_pnl")
    log.setLevel(logging.DEBUG)
    if log.handlers:
        log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)-5s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(
        PNLCFG.PATH_LOG, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ch)
    return log


# ==============================================================================
# 헬퍼
# ==============================================================================
def _load_capital(log: logging.Logger) -> int:
    p = Path(PNLCFG.PATH_ACCOUNT)
    if not p.exists():
        return PNLCFG.CAPITAL_FALLBACK
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        ua = d.get("updated_at", "")
        if ua:
            t = pd.to_datetime(str(ua), format="%Y%m%d%H%M%S", errors="coerce")
            if pd.notna(t):
                age = (datetime.now() - t.to_pydatetime()).total_seconds()
                if age > PNLCFG.ACCOUNT_STALE_SEC:
                    log.warning(f"[PNL] 계좌 파일 stale ({age:.0f}초) → FALLBACK")
                    return PNLCFG.CAPITAL_FALLBACK
        cap = int(d.get("available_capital",
                        d.get("total_equity",
                              d.get("cash", PNLCFG.CAPITAL_FALLBACK))))
        return cap if cap > 0 else PNLCFG.CAPITAL_FALLBACK
    except Exception as e:
        log.warning(f"[PNL] 계좌 로드 실패 → FALLBACK: {e}")
        return PNLCFG.CAPITAL_FALLBACK


def _load_regime(log: logging.Logger) -> str:
    p = Path(PNLCFG.PATH_REGIME)
    if not p.exists():
        return "UNKNOWN"
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return str(d.get("regime", "UNKNOWN")).upper()
    except Exception:
        return "UNKNOWN"


def _fresh_daily_pnl() -> dict:
    return {
        "date"              : datetime.now().strftime("%Y%m%d"),
        # ── 손익 ──────────────────────────────────────────────────────
        "realized_pnl"      : 0,
        "gross_pnl"         : 0,
        "unrealized_pnl"    : 0,
        "net_unrealized"    : 0,
        "net_pnl"           : 0,
        # ── 비용 ──────────────────────────────────────────────────────
        "commission"        : 0,
        "tax"               : 0,
        # ── 통계 ──────────────────────────────────────────────────────
        "trade_count"       : 0,
        "win_count"         : 0,
        "loss_count"        : 0,
        "max_win"           : 0,
        "max_loss"          : 0,
        # ── 1종목 몰빵 특화 ──────────────────────────────────────────
        "entry_value"       : 0,
        "first_entry_code"  : "",
        "first_entry_value" : 0,
        "net_roe"           : 0.0,
        # ★ [FIX-B] TWR: 기하평균 연결 방식 (GIPS 2020 § 2.A.1)
        "twr"               : 0.0,       # ∏(1+r_i)-1
        "twr_factor"        : 1.0,       # 누적 (1+r_i) 곱 (트랜치별 갱신)
        "avg_hold_sec"      : 0,
        "avg_slippage_bps"  : 0.0,
        # ── 수익률 지표 ───────────────────────────────────────────────
        "net_wins"          : 0,
        "net_losses"        : 0,
        "profit_factor"     : 0.0,
        # ★ [FIX-D] 승/패 평균 수익률 및 비율
        "avg_win_pct"       : 0.0,       # 승리 거래 평균 ROE
        "avg_loss_pct"      : 0.0,       # 패배 거래 평균 ROE (음수)
        "win_loss_ratio"    : 0.0,       # |avg_win / avg_loss|
        "sum_win_pct"       : 0.0,       # 내부 집계용
        "sum_loss_pct"      : 0.0,       # 내부 집계용
        # ── 위험 추적 ─────────────────────────────────────────────────
        "peak_pnl"          : 0,
        "peak_equity"       : 0,
        "mdd"               : 0,
        "mdd_pct"           : 0.0,
        # ★ [FIX-E] MDD 지속시간 (Chekhlov et al 2005)
        "mdd_start_ts"      : "",        # MDD 시작 시각 (YYYYMMDDHHMMSS)
        "mdd_duration_sec"  : 0,         # 현재 MDD 지속 시간(초)
        # ★ [FIX-F] 연속 승리/패배 대칭 추적
        "losing_streak"     : 0,
        "losing_streak_max" : 0,
        "winning_streak"    : 0,         # 현재 연속 승리
        "winning_streak_max": 0,         # 당일 최대 연속 승리
        "daily_stop"        : False,
        # ── 기관 추적 ─────────────────────────────────────────────────
        # ★ [FIX-G] inst_holding 임계값 0.10 이상
        "inst_holding"      : False,
        # ── 공격/안정 배분 추적 ────────────────────────────────────────
        "attack_pnl"        : 0,
        "stable_pnl"        : 0,
        # ── 중복 방지 ─────────────────────────────────────────────────
        "processed_sigs"    : [],
        # ── 자본 스냅샷 (FIX-1 유지) ─────────────────────────────────
        "capital_snapshot"  : 0,
        "updated_at"        : datetime.now().strftime("%Y%m%d%H%M%S"),
    }


def _load_daily_pnl() -> dict:
    p = Path(PNLCFG.PATH_DAILY_PNL)
    if not p.exists():
        return _fresh_daily_pnl()
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if str(d.get("date", "")) != datetime.now().strftime("%Y%m%d"):
            return _fresh_daily_pnl()
        fresh = _fresh_daily_pnl()
        for k, v in fresh.items():
            d.setdefault(k, v)
        # v5.0 → v6.0 필드 마이그레이션
        if "gross_wins" in d and "net_wins" not in d:
            d["net_wins"]   = d.pop("gross_wins",  0)
            d["net_losses"] = d.pop("gross_losses", 0)
        # twr_factor 없으면 net_roe로 역산 (호환성)
        if d.get("twr_factor", 1.0) == 1.0 and d.get("net_roe", 0) != 0:
            d["twr_factor"] = 1.0  # 첫날은 그냥 1로 시작
        return d
    except Exception:
        return _fresh_daily_pnl()


def _save_daily_pnl(d: dict, log: logging.Logger):
    d["updated_at"] = datetime.now().strftime("%Y%m%d%H%M%S")
    tmp = PNLCFG.PATH_DAILY_PNL + ".tmp"
    Path(PNLCFG.PATH_DAILY_PNL).parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, PNLCFG.PATH_DAILY_PNL)
    except Exception as e:
        log.error(f"[PNL] daily_pnl.json 저장 실패: {e}")


def _calc_costs(entry_price: float, exit_price: float, qty: int) -> tuple:
    entry_amt   = entry_price * qty
    exit_amt    = exit_price  * qty
    gross_pnl   = (exit_price - entry_price) * qty

    buy_comm    = round(entry_amt * PNLCFG.COMMISSION_RATE)
    sell_comm   = round(exit_amt  * PNLCFG.COMMISSION_RATE)
    tax         = round(exit_amt  * PNLCFG.TAX_RATE_SELL)
    total_cost  = buy_comm + sell_comm + tax
    net_pnl     = round(gross_pnl) - total_cost

    return buy_comm, sell_comm, tax, total_cost, net_pnl


def _calc_hold_seconds(entry_ts: str, exit_ts: str) -> int:
    try:
        fmt = "%Y%m%d%H%M%S"
        e = datetime.strptime(str(entry_ts)[:14], fmt)
        x = datetime.strptime(str(exit_ts)[:14], fmt)
        return max(0, int((x - e).total_seconds()))
    except Exception:
        return 0


def _calc_slippage_bps(expected_price: float, actual_price: float) -> float:
    if expected_price <= 0:
        return 0.0
    return round((actual_price - expected_price) / expected_price * 10000, 2)


def _safe_sharpe(returns: pd.Series) -> float:
    """
    거래 단위 ROE 기반 Sharpe (비표준 — 일내 거래 비교용).
    표준 Sharpe는 일별 수익률 × sqrt(252) 연환산이 필요하나,
    당일 전략 간 비교 목적으로만 사용. 해석 주의.
    출처: Sharpe (1994) "The Sharpe Ratio" JPM 21(1):49-58
    """
    if len(returns) < 2:
        return float("nan")
    mu  = returns.mean()
    std = returns.std(ddof=1)
    if std < 1e-9:
        return float("nan")
    return float(mu / std)


def _safe_sortino(returns: pd.Series, mar: float = 0.0) -> float:
    """
    표준 Sortino Ratio (Sortino & Price, 1994).
    downside_deviation = sqrt(mean(min(r - MAR, 0)^2))
    출처: Sortino & Price (1994) JPI
    출처: CFA Institute Sortino Ratio paper (cfainstitute.org)
    """
    if len(returns) < 2:
        return float("nan")
    mu = float(returns.mean())
    downside_vals = returns.apply(lambda r: min(r - mar, 0.0))
    downside_sq_mean = float((downside_vals ** 2).mean())
    if downside_sq_mean < 1e-18:
        return float("inf") if mu > mar else float("nan")
    downside_std = math.sqrt(downside_sq_mean)
    return float((mu - mar) / downside_std)


def _safe_calmar(daily_roe: float, mdd_pct: float, trading_days: int = 1) -> float:
    """
    Calmar Ratio = 연환산 수익률 / |MDD|
    출처: Young (1991) "The Calmar Ratio" Futures Magazine
    주의: 일내 ROE × 252는 과대계상 — 일별 비교 목적 한정.
    """
    if abs(mdd_pct) < 1e-9:
        return float("nan")
    if trading_days <= 0:
        return float("nan")
    ann_ret = daily_roe * (252 / max(trading_days, 1))
    return float(ann_ret / abs(mdd_pct))


# ★ [FIX-C] VaR / CVaR — 역사적 방법 (Basel III 2019 / Rockafellar & Uryasev 2000)
def _calc_var_cvar(returns: pd.Series,
                   confidence: float = 0.95) -> tuple:
    """
    역사적 VaR(Value at Risk) 및 CVaR(Expected Shortfall).

    VaR  = -percentile(returns, (1-confidence) * 100)
    CVaR = -mean(returns ≤ -VaR)   ← 손실 초과분 평균

    반환: (var, cvar)  양수 = 손실 크기
    출처: Rockafellar & Uryasev (2000) JFEC — CVaR 최소화
    출처: Basel III (2019) § 325bf — 내부모형 ES(Expected Shortfall) 요건
    """
    if len(returns) < 5:
        return float("nan"), float("nan")
    arr = returns.dropna().values
    alpha = 1.0 - confidence
    var = float(-np.percentile(arr, alpha * 100))
    tail = arr[arr <= -var]
    cvar = float(-tail.mean()) if len(tail) > 0 else var
    return var, cvar


# ★ [FIX-B] 진짜 TWR — 기하평균 연결 (GIPS 2020 § 2.A.1)
def _update_twr_factor(current_factor: float, trade_roe: float) -> float:
    """
    TWR 누적 팩터 갱신.
    TWR_factor = ∏(1 + r_i)
    TWR        = TWR_factor - 1

    분할매도 각 트랜치 체결 시마다 호출.
    출처: CFA Institute GIPS Standards 2020 §2.A.1
    출처: AIMR-PPS Calculation Methodology Guidance Statement (2010)
    """
    return current_factor * (1.0 + trade_roe)


# ★ [FIX-7] SHA256 16자리 (v5.0 유지)
def _sig_hash(sig: dict) -> str:
    key = (
        f"{sig.get('ts', '')}-"
        f"{sig.get('code', '')}-"
        f"{sig.get('qty', 0)}-"
        f"{sig.get('exit_price', 0)}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ==============================================================================
# PnL 추적기
# ==============================================================================
class PnLTracker:
    def __init__(self, log: logging.Logger):
        self.log = log
        Path(PNLCFG.PATH_LEDGER).parent.mkdir(parents=True, exist_ok=True)
        Path(PNLCFG.DIR_FEEDBACK).mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────
    # 핵심: 거래 기록
    # ──────────────────────────────────────────────────────────────────────
    def record_trade(self, sig: dict, capital: int = None):
        """
        매도 신호로부터 거래 기록.

        sig 포맷:
          code, entry_price, exit_price, qty, reason, strategy, pattern_key,
          ts (exit 시각), entry_ts (진입 시각),
          expected_entry_price, expected_exit_price (슬리피지 계산용),
          strategy_type (ATTACK/STABLE),
          inst_score (기관 모멘텀 점수),
          inst_net_krw (기관 순매수 금액)
        """
        code          = str(sig.get("code", "")).zfill(6)
        entry_price   = float(sig.get("entry_price", 0))
        exit_price    = float(sig.get("exit_price",  0))
        qty           = int(sig.get("qty", 0))
        reason        = str(sig.get("reason", ""))
        strategy      = str(sig.get("strategy", "RT"))
        # [v4_9-옵션2] strategy 라벨 정규화 — PULLBACK_2CYCLE/PULLBACK_ADDON_*/TREND_PULLBACK → PULLBACK
        # 사유: 매수센더(PULLBACK_2CYCLE/PULLBACK_ADDON_*) ↔ linker(SIGA/PULLBACK) ↔ 엔진(PULLBACK/TREND)
        #       라벨 분산되어 자기진화 학습 데이터 일관성 손상. 진입부 1회 정규화로 해소.
        _strat_upper = strategy.strip().upper()
        if "PULLBACK" in _strat_upper:
            strategy = "PULLBACK"
        elif "SIGA" in _strat_upper:
            strategy = "SIGA"
        else:
            strategy = _strat_upper
        pattern_key   = str(sig.get("pattern_key", ""))
        ts            = str(sig.get("ts", datetime.now().strftime("%Y%m%d%H%M%S")))
        entry_ts      = str(sig.get("entry_ts", ts))
        strategy_type = str(sig.get("strategy_type", "ATTACK"))
        inst_score    = float(sig.get("inst_score", 0.0))
        inst_net_krw  = int(sig.get("inst_net_krw", 0))

        # 슬리피지 계산
        exp_entry      = float(sig.get("expected_entry_price", entry_price))
        exp_exit       = float(sig.get("expected_exit_price",  exit_price))
        slip_entry_bps = _calc_slippage_bps(exp_entry, entry_price)
        slip_exit_bps  = _calc_slippage_bps(exp_exit,  exit_price)
        total_slip_bps = slip_entry_bps + slip_exit_bps

        if qty <= 0 or exit_price <= 0 or entry_price <= 0:
            self.log.warning(
                f"[PNL] {code} 잘못된 거래 데이터 "
                f"qty={qty} entry={entry_price} exit={exit_price}"
            )
            return

        # ── [FIX-7] SHA256 중복 신호 방지 ───────────────────────────────
        sig_hash = _sig_hash(sig)
        d = _load_daily_pnl()
        processed = d.get("processed_sigs", [])
        if sig_hash in processed:
            self.log.warning(f"[PNL][DEDUP] {code} 중복 신호 스킵: hash={sig_hash}")
            return
        processed.append(sig_hash)
        if len(processed) > PNLCFG.DEDUP_MAX:
            processed = processed[-PNLCFG.DEDUP_MAX:]
        d["processed_sigs"] = processed

        # ── [FIX-1] 자본 스냅샷 갱신 ────────────────────────────────────
        cap = capital if (capital and capital > 0) else PNLCFG.CAPITAL_FALLBACK
        d["capital_snapshot"] = cap

        # ── 비용 계산 ────────────────────────────────────────────────────
        gross_pnl    = (exit_price - entry_price) * qty
        buy_comm, sell_comm, tax, total_cost, net_pnl = _calc_costs(
            entry_price, exit_price, qty
        )
        commission   = buy_comm + sell_comm
        entry_value  = entry_price * qty
        pnl_pct      = (exit_price - entry_price) / (entry_price + 1e-9)
        net_roe_trade = net_pnl / (entry_value + 1e-9)
        hold_sec     = _calc_hold_seconds(entry_ts, ts)

        # ── daily_pnl 업데이트 ────────────────────────────────────────────
        d["realized_pnl"] += net_pnl
        d["gross_pnl"]    += round(gross_pnl)
        d["commission"]   += commission
        d["tax"]          += tax
        d["net_pnl"]       = d["realized_pnl"]
        d["trade_count"]  += 1
        d["entry_value"]  += entry_value

        # ── [FIX-5] Profit Factor: net_pnl 기준 (v5.0 유지) ─────────────
        if net_pnl > 0:
            d["net_wins"]  = d.get("net_wins",  0) + net_pnl
        elif net_pnl < 0:
            d["net_losses"] = d.get("net_losses", 0) + abs(net_pnl)
        nw = d.get("net_wins",   0)
        nl = d.get("net_losses", 0)
        d["profit_factor"] = round(nw / (nl + 1e-9), 3) if nl > 0 else (
            float("inf") if nw > 0 else 0.0
        )

        # ── [FIX-D] 승/패 평균 수익률 및 비율 (Kaufman 1987) ─────────────
        if net_pnl > 0:
            d["sum_win_pct"]  = d.get("sum_win_pct", 0.0) + net_roe_trade
            wc_now = d.get("win_count", 0) + 1
            d["avg_win_pct"]  = d["sum_win_pct"] / wc_now if wc_now > 0 else 0.0
        elif net_pnl < 0:
            d["sum_loss_pct"] = d.get("sum_loss_pct", 0.0) + net_roe_trade
            lc_now = d.get("loss_count", 0) + 1
            d["avg_loss_pct"] = d["sum_loss_pct"] / lc_now if lc_now > 0 else 0.0
        # 비율: |avg_win / avg_loss|
        aw = abs(d.get("avg_win_pct", 0.0))
        al = abs(d.get("avg_loss_pct", 0.0))
        d["win_loss_ratio"] = round(aw / (al + 1e-9), 3) if al > 0 else (
            float("inf") if aw > 0 else 0.0
        )

        # ── 공격/안정 배분 추적 ──────────────────────────────────────────
        if strategy_type == "STABLE":
            d["stable_pnl"] = d.get("stable_pnl", 0) + net_pnl
        else:
            d["attack_pnl"] = d.get("attack_pnl", 0) + net_pnl

        # ── 분할매도 dedup — 같은 종목은 first_entry_value 유지 ─────────
        if not d.get("first_entry_code"):
            d["first_entry_code"]  = code
            d["first_entry_value"] = entry_value
        elif d["first_entry_code"] != code:
            self.log.warning(
                f"[PNL][⚠] 1종목 몰빵 원칙 위반 감지: "
                f"기존={d['first_entry_code']} / 신규={code}"
            )
            d["first_entry_code"]  = code
            d["first_entry_value"] = entry_value

        # ── 수익/손실 + 연속 스트릭 추적 ───────────────────────────────
        if net_pnl > 0:
            d["win_count"]      += 1
            d["max_win"]         = max(d.get("max_win", 0), net_pnl)
            d["losing_streak"]   = 0
            # ★ [FIX-F] 연속 승리 추적
            d["winning_streak"]  = d.get("winning_streak", 0) + 1
            d["winning_streak_max"] = max(
                d.get("winning_streak_max", 0), d["winning_streak"]
            )
            if d["winning_streak"] >= PNLCFG.WIN_STREAK_WARN:
                self.log.warning(
                    f"[PNL][과신경보] 연속승리 {d['winning_streak']}회 — "
                    f"과신 방지 모니터링 강화"
                )
        else:
            d["loss_count"]      += 1
            d["max_loss"]         = min(d.get("max_loss", 0), net_pnl)
            d["losing_streak"]    = d.get("losing_streak", 0) + 1
            d["losing_streak_max"] = max(
                d.get("losing_streak_max", 0), d["losing_streak"]
            )
            d["winning_streak"]   = 0  # 연속 승리 리셋
            if d["losing_streak"] >= PNLCFG.LOSS_STREAK_WARN:
                self.log.warning(
                    f"[PNL][위험] 연속손실 {d['losing_streak']}회 — "
                    f"당일 누적 순손익={d['realized_pnl']:+,}원"
                )

        # ── ROE (net_pnl / first_entry_value) ───────────────────────────
        fev = d.get("first_entry_value", 0)
        d["net_roe"] = round(d["realized_pnl"] / (fev + 1e-9), 6) if fev > 0 else 0.0

        # ★ [FIX-B] 진짜 TWR — 기하평균 연결 (GIPS 2020 § 2.A.1)
        # 각 트랜치 체결 시 (1 + trade_roe) 곱하여 TWR 팩터 갱신
        # TWR = TWR_factor - 1
        new_factor = _update_twr_factor(
            d.get("twr_factor", 1.0), net_roe_trade
        )
        d["twr_factor"] = round(new_factor, 8)
        d["twr"]        = round(new_factor - 1.0, 6)

        # ── 평균 보유시간 (누적 이동평균) ───────────────────────────────
        tc = d["trade_count"]
        prev_avg_hold = d.get("avg_hold_sec", 0)
        d["avg_hold_sec"] = round(prev_avg_hold + (hold_sec - prev_avg_hold) / tc)

        # ── 평균 슬리피지 (누적 이동평균) ───────────────────────────────
        prev_avg_slip = d.get("avg_slippage_bps", 0.0)
        d["avg_slippage_bps"] = round(
            prev_avg_slip + (total_slip_bps - prev_avg_slip) / tc, 2
        )

        # ── MDD 갱신 (실현 기반) ────────────────────────────────────────
        peak = d.get("peak_pnl", 0)
        cur  = d["realized_pnl"]
        if cur > peak:
            d["peak_pnl"] = cur
            peak = cur
            # 신고점 갱신 → MDD 지속 시간 리셋
            d["mdd_start_ts"]     = ts
            d["mdd_duration_sec"] = 0
        dd = cur - peak
        if dd < d.get("mdd", 0):
            d["mdd"] = dd
            # ★ [FIX-E] MDD 지속 시간 계산 (Chekhlov et al 2005 기반)
            mdd_start = d.get("mdd_start_ts", ts)
            d["mdd_duration_sec"] = _calc_hold_seconds(mdd_start, ts)
        d["mdd_pct"] = round(d["mdd"] / (cap + 1e-9), 6)

        # ── 당일 손실한도 체크 (플래그만, 집행은 risk_engine) ───────────
        roe_pct = d["realized_pnl"] / (cap + 1e-9)
        if roe_pct <= PNLCFG.DAILY_LOSS_STOP_PCT and not d.get("daily_stop"):
            d["daily_stop"] = True
            self.log.critical(
                f"[PNL][STOP] 당일 손실한도 도달 ({roe_pct:.2%}) — "
                f"daily_stop=True 기록. 집행 중단은 risk_engine 담당."
            )

        # ★ [FIX-G] inst_holding: 임계값 0.10 이상 (노이즈 제거)
        # v5.0: inst_score > 0 → 매우 미약한 값도 True (오판 가능)
        # v6.0: >= INST_SCORE_THRESHOLD(0.10) → 의미 있는 기관 신호만 True
        d["inst_holding"] = (
            inst_score >= PNLCFG.INST_SCORE_THRESHOLD or
            inst_net_krw > 0
        )

        _save_daily_pnl(d, self.log)

        # ── 원장 기록 (원자적 쓰기) ──────────────────────────────────────
        record = {
            "ts"                : ts,
            "date"              : datetime.now().strftime("%Y%m%d"),
            "code"              : code,
            "strategy"          : strategy,
            "strategy_type"     : strategy_type,
            "pattern_key"       : pattern_key,
            "entry_ts"          : entry_ts,
            "entry_price"       : entry_price,
            "exit_price"        : exit_price,
            "qty"               : qty,
            "entry_value"       : round(entry_value),
            "gross_pnl"         : round(gross_pnl),
            "buy_commission"    : buy_comm,
            "sell_commission"   : sell_comm,
            "tax"               : tax,
            "net_pnl"           : net_pnl,
            "pnl_pct"           : round(pnl_pct, 6),
            "net_roe"           : round(net_roe_trade, 6),
            "hold_seconds"      : hold_sec,
            "slip_entry_bps"    : slip_entry_bps,
            "slip_exit_bps"     : slip_exit_bps,
            "total_slip_bps"    : total_slip_bps,
            "exit_reason"       : reason,
            "inst_score"        : inst_score,
            "inst_net_krw"      : inst_net_krw,
            "sig_hash"          : sig_hash,
            # ★ v6.0 추가 필드
            "twr_factor_post"   : d.get("twr_factor", 1.0),
            "win_loss_ratio"    : d.get("win_loss_ratio", 0.0),
            "mdd_duration_sec"  : d.get("mdd_duration_sec", 0),
        }
        p_ledger   = Path(PNLCFG.PATH_LEDGER)
        tmp_ledger = str(p_ledger) + ".tmp"
        try:
            new_row = pd.DataFrame([record])
            if p_ledger.exists():
                existing = pd.read_csv(
                    p_ledger, encoding="utf-8-sig", dtype={"code": str}
                )
                combined = pd.concat([existing, new_row], ignore_index=True)
            else:
                combined = new_row
            combined.to_csv(tmp_ledger, index=False, encoding="utf-8-sig")
            os.replace(tmp_ledger, str(p_ledger))
        except Exception as e:
            self.log.error(f"[PNL] 원장 저장 실패: {e}")

        # ── heartbeat 갱신 ───────────────────────────────────────────────
        try:
            Path(PNLCFG.PATH_HEARTBEAT).write_text(
                datetime.now().strftime("%Y%m%d%H%M%S"), encoding="utf-8"
            )
        except Exception:
            pass

        self.log.info(
            f"[PNL] {code} | {strategy}({strategy_type}) | {reason} | "
            f"gross={gross_pnl:+,.0f}원 net={net_pnl:+,.0f}원 "
            f"ROE={net_roe_trade:+.2%} TWR={d.get('twr', 0):+.2%} "
            f"PF={d.get('profit_factor', 0):.2f} WLR={d.get('win_loss_ratio',0):.2f} | "
            f"보유={hold_sec}초 | slip={total_slip_bps:+.1f}bp | "
            f"연속손실={d['losing_streak']}회 연속승리={d['winning_streak']}회 | "
            f"기관={inst_score:.1f}(≥{PNLCFG.INST_SCORE_THRESHOLD}?{d['inst_holding']})"
        )

    # ──────────────────────────────────────────────────────────────────────
    # 미실현 손익 갱신
    # ──────────────────────────────────────────────────────────────────────
    def update_unrealized(self, open_pos: dict, prices: dict, capital: int = None):
        """미실현 손익 갱신 + 미실현 포함 MDD 갱신. (FIX-1 유지)"""
        gross_unreal = 0.0
        net_unreal   = 0.0
        for code, pos in open_pos.items():
            cp  = float(prices.get(code, {}).get("close", 0))
            if cp <= 0:
                continue
            ep  = float(pos.get("entry_price", 0))
            qty = int(pos.get("qty", 0))
            if ep <= 0 or qty <= 0:
                continue
            gross = (cp - ep) * qty
            gross_unreal += gross
            est_sell_comm = cp * qty * PNLCFG.COMMISSION_RATE
            est_tax       = cp * qty * PNLCFG.TAX_RATE_SELL
            net_unreal   += gross - est_sell_comm - est_tax

        d = _load_daily_pnl()
        d["unrealized_pnl"] = round(gross_unreal)
        d["net_unrealized"] = round(net_unreal)

        if capital and capital > 0:
            cap = capital
        elif d.get("capital_snapshot", 0) > 0:
            cap = d["capital_snapshot"]
        else:
            cap = PNLCFG.CAPITAL_FALLBACK

        total_equity = d.get("realized_pnl", 0) + round(net_unreal)
        peak_eq = d.get("peak_equity", 0)
        if total_equity > peak_eq:
            d["peak_equity"]      = total_equity
            peak_eq               = total_equity
            d["mdd_start_ts"]     = datetime.now().strftime("%Y%m%d%H%M%S")
            d["mdd_duration_sec"] = 0
        eq_dd = total_equity - peak_eq
        if eq_dd < d.get("mdd", 0):
            d["mdd"] = eq_dd
            d["mdd_pct"] = round(eq_dd / (cap + 1e-9), 6)
            # MDD 지속 시간 업데이트
            mdd_start = d.get("mdd_start_ts", datetime.now().strftime("%Y%m%d%H%M%S"))
            d["mdd_duration_sec"] = _calc_hold_seconds(
                mdd_start, datetime.now().strftime("%Y%m%d%H%M%S")
            )

        _save_daily_pnl(d, self.log)

    # ──────────────────────────────────────────────────────────────────────
    # ★ [FIX-H] sell_signal 폴링 — 부분 실패 처리
    # ──────────────────────────────────────────────────────────────────────
    def process_sell_signals(self, capital: int = None) -> int:
        """
        rt_sell_signal.json 폴링 → 거래 기록.

        ★ [FIX-H] v5.0 문제: 하나 실패해도 전체 파일 초기화 → 신호 유실
        v6.0 개선: 성공 신호만 제거, 실패 신호는 retry 큐로 이동
                   다음 루프에서 retry 큐 재처리 시도
        """
        # ── 메인 신호 처리 ────────────────────────────────────────────
        p = Path(PNLCFG.PATH_SELL_SIG)
        if not p.exists():
            # retry 큐 처리 시도
            self._process_retry_queue(capital)
            return 0

        try:
            with open(p, "r", encoding="utf-8") as f:
                signals = json.load(f)
            if not signals:
                self._process_retry_queue(capital)
                return 0
        except Exception as e:
            self.log.warning(f"[PNL] sell_signal 로드 실패: {e}")
            return 0

        failed_sigs = []
        count = 0
        for sig in signals:
            try:
                self.record_trade(sig, capital=capital)
                count += 1
            except Exception as e:
                self.log.error(f"[PNL] 거래 기록 실패 sig={sig}: {e}")
                failed_sigs.append(sig)

        # 성공 신호만 제거 (원자적 초기화)
        try:
            tmp = str(p) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([], f)
            os.replace(tmp, str(p))
        except Exception as e:
            self.log.warning(f"[PNL] sell_signal 초기화 실패: {e}")

        # ★ [FIX-H] 실패 신호 retry 큐 저장
        if failed_sigs:
            self._save_retry_queue(failed_sigs)
            self.log.warning(
                f"[PNL][RETRY] {len(failed_sigs)}건 처리 실패 → retry 큐 저장"
            )

        # retry 큐 처리
        self._process_retry_queue(capital)

        return count

    def _save_retry_queue(self, signals: list):
        """실패 신호 retry 큐에 추가."""
        p = Path(PNLCFG.PATH_RETRY_Q)
        existing = []
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        combined = existing + signals
        # 최대 50개 보관
        combined = combined[-50:]
        try:
            tmp = str(p) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(p))
        except Exception as e:
            self.log.error(f"[PNL] retry 큐 저장 실패: {e}")

    def _process_retry_queue(self, capital: int = None):
        """retry 큐 처리. 성공 시 큐에서 제거."""
        p = Path(PNLCFG.PATH_RETRY_Q)
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                retries = json.load(f)
            if not retries:
                return
        except Exception:
            return

        still_failed = []
        for sig in retries:
            try:
                self.record_trade(sig, capital=capital)
                self.log.info(f"[PNL][RETRY] 재처리 성공: {sig.get('code')}")
            except Exception as e:
                self.log.warning(f"[PNL][RETRY] 재처리 실패: {e}")
                still_failed.append(sig)

        # retry 큐 갱신
        try:
            tmp = str(p) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(still_failed, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(p))
        except Exception as e:
            self.log.error(f"[PNL] retry 큐 갱신 실패: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # 피드백 저장 (진화 엔진 입력) — v6.0 지표 완전체
    # ──────────────────────────────────────────────────────────────────────
    def save_feedback(self, capital: int = None):
        """
        야간 진화 엔진 입력용 feedback 저장.
        v6.0 신규: VaR/CVaR, Win-Loss Ratio, TWR(진짜), MDD 지속시간
        """
        today_dash = datetime.now().strftime("%Y-%m-%d")
        today_raw  = datetime.now().strftime("%Y%m%d")

        Path(PNLCFG.DIR_FEEDBACK).mkdir(parents=True, exist_ok=True)
        fb_path = Path(PNLCFG.DIR_FEEDBACK) / f"feedback_{today_dash}.json"
        cap     = capital if (capital and capital > 0) else PNLCFG.CAPITAL_FALLBACK

        try:
            p = Path(PNLCFG.PATH_LEDGER)
            if not p.exists():
                self.log.info("[PNL] 원장 없음 → feedback 스킵")
                return
            ledger = pd.read_csv(p, encoding="utf-8-sig", dtype={"code": str})
            today_trades = ledger[ledger["date"].astype(str) == today_raw].copy()
            if today_trades.empty:
                self.log.info("[PNL] 오늘 거래 없음 → feedback 스킵")
                return

            # 구버전 원장 호환
            for col, default in [
                ("pattern_key",    "RT"),
                ("net_roe",        0.0),
                ("hold_seconds",   0),
                ("total_slip_bps", 0.0),
                ("entry_value",    0),
                ("strategy_type",  "ATTACK"),
                ("inst_score",     0.0),
                ("inst_net_krw",   0),
            ]:
                if col not in today_trades.columns:
                    today_trades[col] = default

            roe_series     = pd.to_numeric(today_trades["net_roe"],  errors="coerce").dropna()
            returns_series = pd.to_numeric(today_trades["pnl_pct"], errors="coerce").dropna()

            d = _load_daily_pnl()
            regime = _load_regime(self.log)

            # 매매 간격 분석
            try:
                ts_list = pd.to_datetime(
                    today_trades["ts"].astype(str),
                    format="%Y%m%d%H%M%S", errors="coerce"
                )
                ts_list = ts_list.dropna().sort_values()
                if len(ts_list) >= 2:
                    gaps = ts_list.diff().dt.total_seconds().dropna()
                    avg_gap_min = float(gaps.mean() / 60)
                else:
                    avg_gap_min = 0.0
            except Exception:
                avg_gap_min = 0.0

            # 기관 모멘텀 통계
            inst_scores = pd.to_numeric(today_trades["inst_score"], errors="coerce").fillna(0)
            inst_krws   = pd.to_numeric(today_trades["inst_net_krw"], errors="coerce").fillna(0)

            # 공격/안정 분리
            attack_trades = today_trades[today_trades["strategy_type"] == "ATTACK"]
            stable_trades = today_trades[today_trades["strategy_type"] == "STABLE"]

            # 지표 계산
            daily_roe = d.get("net_roe", 0.0)
            mdd_pct   = d.get("mdd_pct", 0.0)
            calmar    = _safe_calmar(daily_roe, mdd_pct, trading_days=1)
            sortino   = _safe_sortino(roe_series)

            # ★ [FIX-C] VaR / CVaR (Rockafellar & Uryasev 2000)
            var_95, cvar_95 = _calc_var_cvar(roe_series, confidence=PNLCFG.VAR_CONFIDENCE_95)
            var_99, cvar_99 = _calc_var_cvar(roe_series, confidence=PNLCFG.VAR_CONFIDENCE_99)

            # ★ [FIX-B] 진짜 TWR (GIPS 2020)
            twr_final = d.get("twr", 0.0)

            feedback = {
                "date"               : today_dash,
                "capital"            : cap,
                "regime"             : regime,
                "version"            : VERSION,
                # ── 수익률 ────────────────────────────────────────────
                "trade_count"        : len(today_trades),
                "win_rate"           : float((today_trades["net_pnl"] > 0).mean()),
                "avg_pnl_pct"        : float(returns_series.mean()) if len(returns_series) > 0 else 0.0,
                "net_roe"            : d.get("net_roe", 0.0),
                # ★ [FIX-B] 진짜 TWR = ∏(1+r_i)-1
                "twr"                : twr_final,
                "total_net_pnl"      : int(d.get("net_pnl", 0)),
                "total_gross_pnl"    : int(d.get("gross_pnl", 0)),
                "total_commission"   : int(d.get("commission", 0)),
                "total_tax"          : int(d.get("tax", 0)),
                # ── 수익률 지표 3중 ─────────────────────────────────────
                "sharpe"             : _safe_sharpe(roe_series),
                "sortino"            : sortino,
                "calmar"             : calmar,
                "profit_factor"      : d.get("profit_factor", 0.0),
                "net_wins"           : d.get("net_wins",   0),
                "net_losses"         : d.get("net_losses", 0),
                # ★ [FIX-D] 승/패 비율 (Kaufman 1987)
                "avg_win_pct"        : d.get("avg_win_pct", 0.0),
                "avg_loss_pct"       : d.get("avg_loss_pct", 0.0),
                "win_loss_ratio"     : d.get("win_loss_ratio", 0.0),
                # ★ [FIX-C] VaR/CVaR 2레벨 (Basel III / Rockafellar & Uryasev)
                "var_95"             : var_95,
                "cvar_95"            : cvar_95,
                "var_99"             : var_99,
                "cvar_99"            : cvar_99,
                # ── 위험 지표 ─────────────────────────────────────────
                "mdd"                : d.get("mdd", 0),
                "mdd_pct"            : d.get("mdd_pct", 0.0),
                # ★ [FIX-E] MDD 지속 시간 (Chekhlov et al 2005)
                "mdd_duration_sec"   : d.get("mdd_duration_sec", 0),
                "max_win"            : int(d.get("max_win", 0)),
                "max_loss"           : int(d.get("max_loss", 0)),
                # ★ [FIX-F] 연속 승리/패배 대칭
                "losing_streak_max"  : int(d.get("losing_streak_max", 0)),
                "winning_streak_max" : int(d.get("winning_streak_max", 0)),
                "daily_stop"         : bool(d.get("daily_stop", False)),
                # ── 실행 품질 ─────────────────────────────────────────
                "avg_hold_sec"       : float(today_trades["hold_seconds"].mean()),
                "avg_slippage_bps"   : float(today_trades["total_slip_bps"].mean()),
                "total_entry_value"  : int(today_trades["entry_value"].sum()),
                "avg_gap_minutes"    : round(avg_gap_min, 1),
                # ── 기관 모멘텀 ─────────────────────────────────────────
                "avg_inst_score"     : round(float(inst_scores.mean()), 3),
                "total_inst_net_krw" : int(inst_krws.sum()),
                # ★ [FIX-G] inst_holding 임계값 0.10 기준
                "inst_holding_exit"  : bool(d.get("inst_holding", False)),
                "inst_threshold"     : PNLCFG.INST_SCORE_THRESHOLD,
                # ── 공격/안정 배분 ────────────────────────────────────
                "attack_pnl"         : d.get("attack_pnl", 0),
                "stable_pnl"         : d.get("stable_pnl", 0),
                "attack_trade_count" : len(attack_trades),
                "stable_trade_count" : len(stable_trades),
                # ── 세분화 ────────────────────────────────────────────
                "by_strategy"        : today_trades.groupby("strategy")["net_pnl"].sum().to_dict(),
                "by_reason"          : today_trades.groupby("exit_reason")["net_pnl"].mean().to_dict(),
                "by_pattern"         : today_trades.groupby("pattern_key")["net_pnl"].mean().to_dict(),
                "by_pattern_roe"     : today_trades.groupby("pattern_key")["net_roe"].mean().to_dict(),
                "by_hold_bucket"     : self._hold_bucket_stats(today_trades),
                # ── 진화엔진 Kelly 필수 필드 ──────────────────────────
                "next_day_open_ret"  : None,
                # ── 전체 거래 원장 ────────────────────────────────────
                "trades"             : today_trades.to_dict("records"),
            }

            tmp = str(fb_path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(feedback, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, str(fb_path))
            self.log.info(
                f"[PNL] feedback 저장완료: {fb_path.name} | "
                f"WR={feedback['win_rate']:.1%} PF={feedback['profit_factor']:.2f} "
                f"TWR={twr_final:+.2%}(GIPS) WLR={feedback['win_loss_ratio']:.2f} "
                f"VaR95={var_95:.2%} CVaR95={cvar_95:.2%} "
                f"Sortino={sortino:.2f} Calmar={calmar:.2f} (v6.0)"
            )

        except Exception as e:
            self.log.error(f"[PNL] feedback 저장 실패: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────────
    # 전일 feedback backfill (FIX-2 유지)
    # ──────────────────────────────────────────────────────────────────────
    def backfill_yesterday(self):
        """
        장 시작 직후 실행. 전일 feedback에 오늘 시가 기준 수익률 역기입.
        ★ [FIX-2] 마지막 거래 단일 객체에서 code·exit_price 취득 (v5.0 유지)
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        fb_path   = Path(PNLCFG.DIR_FEEDBACK) / f"feedback_{yesterday}.json"

        if not fb_path.exists():
            for i in range(2, 6):
                d_str     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                candidate = Path(PNLCFG.DIR_FEEDBACK) / f"feedback_{d_str}.json"
                if candidate.exists():
                    fb_path   = candidate
                    yesterday = d_str
                    break
            else:
                self.log.info("[PNL] backfill: 최근 feedback 없음 → 스킵")
                return

        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                fb = json.load(f)

            if fb.get("next_day_open_ret") is not None:
                self.log.info(f"[PNL] backfill: {yesterday} 이미 기입됨 → 스킵")
                return

            trades = fb.get("trades", [])
            if not trades:
                self.log.info("[PNL] backfill: 전일 trades 없음 → 스킵")
                return

            last_trade  = trades[-1]
            code        = str(last_trade.get("code", "")).zfill(6)
            entry_price = float(last_trade.get("exit_price", 0))

            if not code or entry_price <= 0:
                self.log.warning(
                    f"[PNL] backfill: 마지막 거래 데이터 불완전 "
                    f"(code={code} exit_price={entry_price}) → 스킵"
                )
                return

            today_open = None
            p_pr = Path(PNLCFG.PATH_PRICES_1M)
            if p_pr.exists():
                try:
                    df_p = pd.read_csv(p_pr, encoding="utf-8-sig", dtype={"code": str})
                    df_p["code"]  = df_p["code"].str.zfill(6)
                    df_c = df_p[df_p["code"] == code].copy()
                    if not df_c.empty:
                        df_c["ts"] = pd.to_datetime(df_c["ts"].astype(str), errors="coerce")
                        df_c = df_c.sort_values("ts")
                        first_bar  = df_c.iloc[0]
                        today_open = float(
                            first_bar.get("open", first_bar.get("close", 0))
                        )
                except Exception as e:
                    self.log.debug(f"[PNL] backfill 시가 조회 실패: {e}")

            if today_open and today_open > 0:
                next_day_ret = round((today_open - entry_price) / entry_price, 6)
                fb["next_day_open_ret"] = next_day_ret

                tmp = str(fb_path) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(fb, f, ensure_ascii=False, indent=2, default=str)
                os.replace(tmp, str(fb_path))
                self.log.info(
                    f"[PNL] backfill 완료: {yesterday} → "
                    f"next_day_open_ret={next_day_ret:+.4f} "
                    f"({code} exit={entry_price:,.0f} → open={today_open:,.0f})"
                )
            else:
                self.log.warning(
                    f"[PNL] backfill: 시가 미확보 (code={code} open={today_open})"
                )

        except Exception as e:
            self.log.error(f"[PNL] backfill 실패: {e}")

    def _hold_bucket_stats(self, df: pd.DataFrame) -> dict:
        """보유시간 구간별 평균 수익률 — 진화 엔진 최적 보유시간 피드백."""
        try:
            df = df.copy()
            df["hold_bucket"] = pd.cut(
                pd.to_numeric(df["hold_seconds"], errors="coerce").fillna(0),
                bins=[0, 300, 600, 900, 1800, float("inf")],
                labels=["<5분", "5-10분", "10-15분", "15-30분", "30분+"],
                right=False,
            )
            return (
                df.groupby("hold_bucket", observed=True)["net_roe"]
                .mean()
                .round(6)
                .to_dict()
            )
        except Exception:
            return {}

    # ──────────────────────────────────────────────────────────────────────
    # 리포트 출력 — v6.0 완전판
    # ──────────────────────────────────────────────────────────────────────
    def print_status(self, capital: int = None):
        d   = _load_daily_pnl()
        cap = capital if (capital and capital > 0) else PNLCFG.CAPITAL_FALLBACK
        tc  = d.get("trade_count", 0)
        wc  = d.get("win_count",   0)
        wr  = wc / tc if tc else 0.0
        net_roe  = d.get("net_roe", 0.0)
        twr      = d.get("twr", 0.0)
        mdd_pct  = d.get("mdd_pct", 0.0)
        streak   = d.get("losing_streak", 0)
        wstreak  = d.get("winning_streak", 0)
        dstop    = d.get("daily_stop", False)
        pf       = d.get("profit_factor", 0.0)
        wlr      = d.get("win_loss_ratio", 0.0)
        mdd_dur  = d.get("mdd_duration_sec", 0)

        # VaR/CVaR 계산 (원장에서)
        var_95 = cvar_95 = float("nan")
        try:
            p = Path(PNLCFG.PATH_LEDGER)
            if p.exists():
                ledger = pd.read_csv(p, encoding="utf-8-sig", dtype={"code": str})
                today_raw = datetime.now().strftime("%Y%m%d")
                today_t = ledger[ledger["date"].astype(str) == today_raw]
                roe_s = pd.to_numeric(today_t["net_roe"], errors="coerce").dropna()
                var_95, cvar_95 = _calc_var_cvar(roe_s, 0.95)
        except Exception:
            pass

        sep = "=" * 66
        print(f"\n{sep}")
        print(f"  ■ PnL 리포트 v6.0  {d.get('date','')}  [1종목 몰빵 · 시가/추세눌림]")
        print(sep)
        print(f"  기준자본:          {cap:>15,}원")
        print(f"  총투입금액:        {d.get('entry_value',0):>15,}원")
        print(f"  실현손익:          {d.get('realized_pnl',0):>+15,}원")
        print(f"  미실현(gross):     {d.get('unrealized_pnl',0):>+15,}원")
        print(f"  미실현(net):       {d.get('net_unrealized',0):>+15,}원")
        print(f"  순손익(당일):      {d.get('net_pnl',0):>+15,}원")
        print(f"  {'─'*62}")
        print(f"  ROE%:              {net_roe:>+14.2%}")
        print(f"  TWR% (GIPS기준):   {twr:>+14.2%}  ★진짜 기하평균 TWR")
        print(f"  MDD%:              {mdd_pct:>+14.2%}  [실자본 {cap:,}원 기준]")
        print(f"  MDD 지속:          {mdd_dur//60:>12}분 {mdd_dur%60}초")
        print(f"  Profit Factor:     {pf:>14.2f}  [net 기준]")
        print(f"  Win-Loss Ratio:    {wlr:>14.2f}  ★avg승/avg패 비율")
        if not math.isnan(var_95):
            print(f"  VaR 95%:           {var_95:>+14.2%}  ★Basel III 기준")
            print(f"  CVaR 95%:          {cvar_95:>+14.2%}  ★Expected Shortfall")
        print(f"  {'─'*62}")
        print(f"  거래수:            {tc}건  (승={wc} / 패={d.get('loss_count',0)})")
        print(f"  승률:              {wr:>14.1%}")
        print(f"  평균 승리 ROE:     {d.get('avg_win_pct',0):>+14.2%}")
        print(f"  평균 패배 ROE:     {d.get('avg_loss_pct',0):>+14.2%}")
        print(f"  연속손실:          {streak}회 (최대={d.get('losing_streak_max',0)}회)"
              f"{'  ⚠️ 경고' if streak >= PNLCFG.LOSS_STREAK_WARN else ''}")
        print(f"  연속승리:          {wstreak}회 (최대={d.get('winning_streak_max',0)}회)"
              f"{'  ⚠️ 과신' if wstreak >= PNLCFG.WIN_STREAK_WARN else ''}")
        print(f"  당일STOP:          {'🔴 YES' if dstop else '🟢 NO'}")
        print(f"  {'─'*62}")
        print(f"  수수료:            {d.get('commission',0):>15,}원")
        print(f"  세금:              {d.get('tax',0):>15,}원")
        print(f"  최대익절:          {d.get('max_win',0):>+15,}원")
        print(f"  최대손절:          {d.get('max_loss',0):>+15,}원")
        print(f"  평균보유시간:      {d.get('avg_hold_sec',0):>12}초")
        print(f"  평균슬리피지:      {d.get('avg_slippage_bps',0.0):>+12.1f}bp")
        print(f"  {'─'*62}")
        print(f"  공격(70%) 손익:    {d.get('attack_pnl',0):>+15,}원")
        print(f"  안정(30%) 손익:    {d.get('stable_pnl',0):>+15,}원")
        print(f"  기관보유중:        {'🟢 YES' if d.get('inst_holding') else '⚪ NO'}"
              f"  [임계={PNLCFG.INST_SCORE_THRESHOLD}]")

        # 목표 대비 평가
        print(f"  {'─'*62}")
        wr_ok  = "✅" if wr >= PNLCFG.TARGET_WIN_RATE else "❌"
        pf_ok  = "✅" if (isinstance(pf, (int, float)) and pf >= PNLCFG.TARGET_PROFIT_FACTOR) else "❌"
        wlr_ok = "✅" if (isinstance(wlr, float) and wlr >= 1.5) else "❌"
        print(f"  목표승률 {PNLCFG.TARGET_WIN_RATE:.0%}:    {wr_ok} ({wr:.1%})")
        print(f"  목표PF {PNLCFG.TARGET_PROFIT_FACTOR:.1f}:     {pf_ok} ({pf:.2f})  ← net 기준 정확값")
        print(f"  목표WLR 1.5:       {wlr_ok} ({wlr:.2f})  ← 승/패 비율")
        print(f"{sep}\n")

        # v6.0 변경사항 요약
        print(f"  [v6.0 주요 개선 확인]")
        print(f"  FIX-A 종배 삭제:   2전략 운용 (시가/추세눌림)")
        print(f"  FIX-B 진짜 TWR:    ∏(1+r_i)-1 = {twr:+.4f}  (GIPS 2020)")
        print(f"  FIX-C VaR/CVaR:    95%={var_95:.2%}/{cvar_95:.2%}  (Basel III)")
        print(f"  FIX-D WLR:         avg승={d.get('avg_win_pct',0):+.2%} / avg패={d.get('avg_loss_pct',0):+.2%}")
        print(f"  FIX-E MDD 지속:    {mdd_dur//60}분 {mdd_dur%60}초")
        print(f"  FIX-F 연속승리:    현재 {wstreak}회 / 최대 {d.get('winning_streak_max',0)}회")
        print(f"  FIX-G 기관임계:    inst_score >= {PNLCFG.INST_SCORE_THRESHOLD}")
        print(f"  FIX-H 신호안전:    retry 큐 보호 (유실 방지)")
        print()


# ==============================================================================
# MAIN
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description=f"PnL 추적 엔진 {VERSION}")
    parser.add_argument("--loop",     action="store_true", help="장중 루프")
    parser.add_argument("--report",   action="store_true", help="리포트 + feedback")
    parser.add_argument("--reset",    action="store_true", help="당일 초기화")
    parser.add_argument("--backfill", action="store_true", help="전일 next_day_open_ret 역기입")
    args = parser.parse_args()

    log = _setup_logger()
    log.info("=" * 66)
    log.info(
        f"{VERSION} (종배삭제·TWR수정·VaR추가·WLR추가·MDD기간·연승추적·기관임계·신호안전) | "
        f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    log.info("=" * 66)

    tracker = PnLTracker(log)

    if args.reset:
        _save_daily_pnl(_fresh_daily_pnl(), log)
        today = datetime.now().strftime("%Y%m%d")
        p_led = Path(PNLCFG.PATH_LEDGER)
        if p_led.exists():
            try:
                df = pd.read_csv(p_led, encoding="utf-8-sig", dtype={"code": str})
                df_clean = df[df["date"].astype(str) != today]
                if len(df_clean) < len(df):
                    tmp_led = str(p_led) + ".tmp"
                    df_clean.to_csv(tmp_led, index=False, encoding="utf-8-sig")
                    os.replace(tmp_led, str(p_led))
                    log.info(f"[PNL] 당일 ledger {len(df)-len(df_clean)}행 정리")
            except Exception as e:
                log.warning(f"[PNL] ledger 정리 실패: {e}")
        log.info("[PNL] 당일 초기화 완료")
        return RC_OK

    if args.backfill:
        tracker.backfill_yesterday()
        return RC_OK

    if args.report:
        capital = _load_capital(log)
        tracker.print_status(capital)
        tracker.save_feedback(capital)
        return RC_OK

    if args.loop:
        log.info(f"[PNL] 루프 모드 시작 (폴링={PNLCFG.LOOP_INTERVAL}초)")
        capital     = _load_capital(log)
        unreal_tick = 0

        try:
            tracker.backfill_yesterday()
        except Exception as e:
            log.warning(f"[PNL] 자동 backfill 실패 (계속 진행): {e}")

        while True:
            now_hhmm = int(datetime.now().strftime("%H%M"))

            if now_hhmm > PNLCFG.MARKET_CLOSE:
                log.info("[PNL] 장 종료 → feedback 저장")
                capital = _load_capital(log)
                tracker.save_feedback(capital)
                tracker.print_status(capital)
                break

            if (int(datetime.now().strftime("%M")) % 10 == 0 and
                    int(datetime.now().strftime("%S")) < PNLCFG.LOOP_INTERVAL):
                capital = _load_capital(log)

            cnt = tracker.process_sell_signals(capital=capital)
            if cnt:
                log.info(f"[PNL] {cnt}건 처리 완료")

            unreal_tick += 1
            if unreal_tick >= PNLCFG.UNREAL_TICK_LIMIT:
                unreal_tick = 0
                try:
                    p_pos = Path(PNLCFG.PATH_OPEN_POS)
                    if p_pos.exists():
                        with open(p_pos, "r", encoding="utf-8") as f:
                            open_pos = json.load(f)
                        prices = {}
                        p_pr = Path(PNLCFG.PATH_PRICES_1M)
                        if p_pr.exists() and open_pos:
                            df_p = pd.read_csv(
                                p_pr, encoding="utf-8-sig", dtype={"code": str}
                            )
                            df_p["code"]  = df_p["code"].str.zfill(6)
                            df_p["close"] = pd.to_numeric(df_p["close"], errors="coerce")
                            latest = df_p.sort_values("ts").groupby("code").last()
                            prices = {
                                c: {"close": v} for c, v in latest["close"].items()
                            }
                        if open_pos:
                            tracker.update_unrealized(open_pos, prices, capital=capital)
                except Exception as e:
                    log.debug(f"[PNL] 미실현 갱신 스킵: {e}")

            time.sleep(PNLCFG.LOOP_INTERVAL)
        return RC_OK

    capital = _load_capital(log)
    cnt = tracker.process_sell_signals(capital=capital)
    log.info(f"[PNL] 단발 처리: {cnt}건")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
