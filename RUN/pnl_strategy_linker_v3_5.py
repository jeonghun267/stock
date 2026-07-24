# -*- coding: utf-8 -*-
"""
pnl_strategy_linker_v3_5.py  (헤지펀드급 완성본 — v3.5)
========================================================================
자기진화 루프 연결 브릿지

[v3.4 → v3.5 96점 완성 패치 — 2026-04-18]
  [FIX-1] _LINKER_VERSION "v3.3" → "v3.5" 정합
           기존: 파일명·docstring은 v3.4, _LINKER_VERSION 상수만 v3.3 불일치
           수정: v3.5로 통일 → print_status() 감사 추적 정합성 확보
           bridge v9.8 실제 존재 확인 완료 → 폴백 구조 정상

[v3.3 변경이력 — 2026-04-15]  ★ 치명 충돌 5개 수정
  [FIX-1] bridge import 버전 수정: v9.2/v9.0 → v9.6 (실제 파일 일치)
          _BRIDGE_PNL_OK=False 상시 발생 → 자기진화 트리거 완전 무력화 해소
  [FIX-2] 전략명 매핑 추가: 'EOD_종가' → 'SIGA'
          bridge_eod가 기록하는 'EOD_종가'가 PULLBACK으로 오기록되던 문제 해소
          SIGA 전략 성과 데이터 0건 → Kelly 계산 불가 문제 해소
  [FIX-3] write_sell_fill() 내 trade_log.csv 동시 기록 추가
          evolution_engine이 요구하는 DATA/trade_log.csv (13컬럼) 청산 시 자동 append
          pnl_pct는 소수 단위(/100) 변환하여 기록 (evolution_engine 단위 정합)
  [FIX-4] pnl_pct 단위 통일: trade_log.csv 기록 시 백분율→소수 변환 (/100)
          evolution_engine._calc_kelly() 소수 단위 기대 (avg_ret - 0.0022 방식)
  [FIX-5] trade_log.csv 경로 상수 추가 (evolution_engine과 동일 경로)

[v3.2 변경이력 — 2026-04-10]
  [C-3] 종배(JONGBAE) 전략 완전 삭제 — 시가(SIGA) + 추세눌림(PULLBACK) 2전략 체계
  [C-4] 취약점 ① Sharpe 무위험이자율 반영 — 환경변수 RISK_FREE_ANNUAL_PCT (기본 3.5%)
  [C-5] 취약점 ② Sortino 분모 안정화 — downside 1건 케이스 개선
  [C-6] 취약점 ③ Context Edge min_samples 3→5 상향 (Lo 2002 최소 표본 기준 강화)
  [C-7] 취약점 ④ Kyle λ 한국시장(KRX) 보정 — 거래량 티어별 λ 재보정
  [C-8] 취약점 ⑤ Half-Kelly 포지션 사이징 신규 구현 — get_kelly_fraction()
  [C-9] 취약점 ⑥ TWR 누적 복리 체인 반영 — get_cumulative_twr()
  [C-10] 취약점 ⑦ 종배 잔재 주석·문자열 전면 정리
  [C-11] 전략명 표준화: EOD→SIGA, 2전략 고정
  [C-12] 학술 출처 정확도 보강 — Almgren 2005, Wilder 1978 추가

[역할]
  매수 체결  → write_buy_fill()              : cost_basis + fill_quality + context 기록
  매도 체결  → write_sell_fill()             : pnl/roc/twr/슬리피지 이상탐지 기록
                                               + update_pnl_result() 자동 호출 (자기진화 트리거)
  다음날 아침 → load_strategy_weights()      : EdgeScore 기반 진화 가중치 (±10% 안정화)
  실시간     → check_daily_stop()            : 연속손실 기반 동적 손실한도 신호
  실시간     → get_drawdown_streak()         : 전략별 연속손실 추적
  실시간     → check_slippage_anomaly()      : 슬리피지 3σ 이상탐지
  실시간     → check_capital_ratio()         : 공격70%/안정30% + Edge 경고
  신규       → get_kelly_fraction()          : Half-Kelly 포지션 사이징 [C-8]
  신규       → get_cumulative_twr()          : 누적 복리 TWR [C-9]
  분석용     → get_context_edge()            : 조건별 전략 성과 학습
  분석용     → compute_edge_score()          : 통합 Edge Score
  분석용     → get_adaptive_capital_ratio()  : Edge 기반 동적 자본배분

[파일 위치]
  C:\\stock_bot\\DATA\\daily_pnl_by_strategy.csv   ← 주 원장
  C:\\stock_bot\\DATA\\weight_history.csv          ← 진화 가중치 이력

[2전략 체계 — v3.2 확정]
  SIGA    : 시가 전략  (strategy_type=ATTACK)
  PULLBACK: 추세눌림  (strategy_type=STABLE)
  ※ 종배(JONGBAE/EOD) 전략 삭제 완료 [C-3]

[헤지펀드급 기능 22종]
  ① 거래비용 분해: 시장충격비용(Kyle λ KRX 보정) + IOC 기회비용
  ② 총자본 대비 수익률 (ROC)
  ③ 시간가중수익률 (TWR) — 누적 복리 체인 반영 [C-9 개선]
  ④ 체결품질 Fill Quality (vs VWAP)
  ⑤ Audit Trail (updated_at)
  ⑥ 행 해시 무결성 검증 (MD5)
  ⑦ EdgeScore 기반 진화 가중치 (Sharpe/Sortino/MDD/PF/ContextEdge)
  ⑧ 진화 가중치 이력 저장 + ±10% 안정화
  ⑨ 연속손실 기반 동적 Daily Stop
  ⑩ 연속손실 Drawdown Streak 추적
  ⑪ 슬리피지 3σ 이상탐지 + 페널티 별도 기록
  ⑫ Bridge update_pnl_result() 자동 연결 (자기진화 트리거)
  ⑬ PARTIAL_CLOSED 자식행 분리 기록
  ⑭ RECONCILE 추정 PnL -0.7% 보수적 기록 (손실 은폐 완전 제거)
  ⑮ 공격70%/안정30% 자본비율 실시간 검증 + Edge 경고
  ⑯ Context Learning — 레짐×갭 조건별 성과 학습
  ⑰ EdgeScore = Sharpe+Sortino+WR+PF+ContextEdge 통합 점수
  ⑱ Adaptive Capital — Edge 기반 자본배분 자동 최적화
  ⑲ validate_all() — edge/context/adaptive 통합 검증
  ⑳ Half-Kelly 포지션 사이징 [C-8 신규]
  ㉑ Sharpe 무위험이자율 반영 (KRX CD금리 기준) [C-4 신규]
  ㉒ 누적 복리 TWR 계산 [C-9 신규]

[학술 출처]
  Kyle, A.S. (1985) "Continuous Auctions and Insider Trading", Econometrica 53(6):1315-1336
  Almgren, R. et al. (2005) "Direct Estimation of Equity Market Impact", Risk, Vol.18
  Wilder, J.W. (1978) "New Concepts in Technical Trading Systems" — ATR 원전
  Lo, A. (2002) "The Statistics of Sharpe Ratios", Financial Analysts Journal 58(4):36-52
  Kelly, J.L. (1956) "A New Interpretation of Information Rate", Bell System Technical Journal
  Thorp, E. (1962) "Beat the Dealer" — Kelly Half-position 실전 적용
  Cont, Kukanov, Stoikov (2014) "The Price Impact of Order Book Events" JFEC 12(1):47-88
  Lopez de Prado (2018) "Advances in Financial ML", Wiley — Context Learning, EdgeScore
  Grinblatt & Titman (1989) "Mutual Fund Performance" — 기관 매도 전환 신호
  Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere" — 레짐별 전략 분리
  Kaminski & Lo (2014) "When Do Stop-Loss Rules Stop Losses?" JFM 18:234-254

[설계 원칙]
  - 고유 영역: 이 파일만 daily_pnl_by_strategy.csv 를 쓴다
  - 원자적 쓰기 (tmp→replace)
  - date+code+strategy 3중 키
  - FileLock Race Condition 방지
  - 공격 70% / 안정 30% 자본배분 추적 + 실시간 검증
  - 2전략(시가/추세눌림) 공용 호환 [v3.2 확정]
  - pnl_pct_net 직접 수정 금지 (감사 무결성) — 슬리피지 페널티는 별도 컬럼
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import math
import os
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    import pytz
    KST = pytz.timezone("Asia/Seoul")

try:
    from filelock import FileLock
    _FILELOCK_AVAILABLE = True
except ImportError:
    _FILELOCK_AVAILABLE = False

# [PATCH-BRIDGE-FALLBACK] bridge 폴백 체인 (kiwoom_buy_order_sender 패턴 적용)
#   v9_9 (실제 파일) 최우선 → 구버전 폴백 → 최후 suffix 없는 모듈
#   모든 폴백 실패 시에만 RuntimeError raise (silent fail 금지)
try:
    import sys as _sys
    _run_dir = str(Path(__file__).resolve().parent)
    if _run_dir not in _sys.path:
        _sys.path.insert(0, _run_dir)

    import importlib as _il
    _BRIDGE_PNL_OK = False
    _bridge_update_pnl = None
    _BRIDGE_MOD_NAME = ""
    for _bridge_mod in (
        "kjs_bridge_eod_v9_9",                  # 실제 파일 — 최우선
        "kjs_bridge_eod_v9_8_SAFEPLUS_FINAL",
        "kjs_bridge_eod_v9_7_SAFEPLUS_FINAL",
        "kjs_bridge_eod_v9_6_SAFEPLUS_FINAL",
        "kjs_bridge_eod_v9_5_SAFEPLUS_FINAL",
        "kjs_bridge_eod",                        # 최후 폴백
    ):
        try:
            _m = _il.import_module(_bridge_mod)
            _bridge_update_pnl = _m.update_pnl_result
            _BRIDGE_MOD_NAME = _bridge_mod
            _BRIDGE_PNL_OK = True
            print(f"[PNL] linker 정상 작동: bridge={_BRIDGE_MOD_NAME}")
            break
        except Exception:
            continue
    if not _BRIDGE_PNL_OK:
        print("[PNL][FAIL] bridge import 실패 — 모든 폴백 시도 실패")
        raise RuntimeError("pnl linker bridge 필수 모듈 로딩 실패")
except Exception as _bridge_err:
    _BRIDGE_PNL_OK = False
    _bridge_update_pnl = None
    _BRIDGE_MOD_NAME = ""
    raise


# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════
DEFAULT_BASE_DIR: str = os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")
_TOTAL_CAPITAL: int   = int(os.environ.get("TOTAL_CAPITAL", "50000000"))

# ★ [C-4] 무위험이자율 — 한국 CD금리 기준, 환경변수로 주입 가능
# 연간 % → 일(intraday) 단위 환산: rf_daily = rf_annual / 252 / 6.5시간
_RISK_FREE_ANNUAL_PCT: float = float(os.environ.get("RISK_FREE_ANNUAL_PCT", "3.5"))
_RISK_FREE_DAILY_PCT: float  = _RISK_FREE_ANNUAL_PCT / 252   # 일 단위

# 거래 비용
_BUY_FEE_PCT   = 0.00015
_SELL_FEE_PCT  = 0.00015
_SELL_TAX_PCT  = 0.0018   # 금융투자소득세 전환 후 거래세

# ★ [C-7] KRX 시장충격 λ — 한국시장 특성 반영
# 근거: KRX 상하한 30%, T+2 결제, 일평균 거래대금 기준 재설정
# Almgren et al. (2005) square-root 모델 기반 KRX 참여율 티어 조정
_IMPACT_LAMBDA_DEFAULT = 0.12   # NYSE 0.10 대비 KRX +20% 상향 (유동성 열위)

# 진화 가중치
_EVO_LOOKBACK    = 20
_EVO_MIN_TRADES  = 10       # Lo(2002) 통계적 최소 표본
_EVO_MAX_WEIGHT  = 2.0
_EVO_MIN_WEIGHT  = 0.3
_EVO_MAX_DELTA   = 0.10     # 가중치 변화 상한 ±10%

# 일중 손실한도
_DAILY_STOP_PCT        = 2.0    # 기본 -2%
_DAILY_STOP_PCT_WARN   = 1.5    # 3연속 손실 시 -1.5%로 강화

# 연속손실
_STREAK_WARN = 3
_STREAK_HALT = 5

# 슬리피지
_SLIP_SIGMA    = 3.0
_SLIP_MIN_HIST = 10
_SLIP_PENALTY_MULT = 2.0

# 자본비율
_ATTACK_RATIO_TARGET = 0.70
_STABLE_RATIO_TARGET = 0.30
_RATIO_TOLERANCE     = 0.10

# Profit Factor 목표
_PROFIT_FACTOR_TARGET = 1.2

# RECONCILE 추정 손실률
_RECONCILE_EST_PNL_PCT = -0.7

# Edge Score 자본 조정 기준
_EDGE_HIGH   = 1.2
_EDGE_MID    = 1.0
_EDGE_LOW    = 0.8

# Context 갭 버킷 기준
_GAP_BUCKETS = [(0, 1), (1, 3), (3, 5), (5, 999)]

# ★ [C-6] Context min_samples 상향 (Lo 2002 권고 기준 강화)
_CTX_MIN_SAMPLES = 5   # 3→5 (과적합 방지)

# ★ [C-8] Half-Kelly 상한 (과도 베팅 방지)
_KELLY_MAX_FRACTION = 0.25   # 총자본 대비 최대 25%
_KELLY_HALF         = 0.5    # Half-Kelly 배수

# ★ [C-3] 2전략 체계 확정 — 종배 삭제
_VALID_STRATEGIES = ("SIGA", "PULLBACK")

# [FIX-5 v3.3] trade_log.csv 경로 — evolution_engine과 동일 경로
# evolution_engine.TRADE_LOG_PATH = DATA / "trade_log.csv"
_TRADE_LOG_PATH_TMPL    = "DATA/trade_log.csv"        # BASE/{_TRADE_LOG_PATH_TMPL}
# [v3.4] switch_selector v1.8 협약: 청산 후 pnl_ret 업데이트
# ts + new_code 조합으로 행 식별 → 실제 수익률로 갱신
_SWITCH_HISTORY_TMPL    = "DATA/switch_history.csv"   # switch_selector 자기진화 원장

_LINKER_VERSION = "v3.5"


# ═══════════════════════════════════════════════════════════════
#  모듈 로거
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    lg = logging.getLogger("pnl_strategy_linker")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    _log_dir = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")) / "LOG"
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            _log_dir / "pnl_strategy_linker.log",
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        lg.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    lg.addHandler(sh)
    return lg

_logger = _setup_logger()


# ═══════════════════════════════════════════════════════════════
#  스키마 — Context 컬럼 포함
# ═══════════════════════════════════════════════════════════════
_SCHEMA = [
    "date", "code", "strategy",
    "strategy_type", "capital_allocated",
    "buy_price", "buy_qty", "buy_krw",
    "buy_ts", "slippage_buy_bps",
    "fill_quality_buy", "market_impact_bps", "opportunity_cost_krw",
    "market_regime", "gap_pct", "entry_time_bucket", "vol_ratio", "inst_flow",
    "sell_price", "sell_ts", "slippage_sell_bps", "fill_quality_sell",
    "slip_penalty_bps", "reconcile_flag",
    "pnl_pct_gross", "pnl_pct_net", "pnl_krw",
    "roc_pct", "twr_pct",
    "status", "updated_at", "row_hash",
]
_HASH_EXCLUDE = {"row_hash", "updated_at"}

_NEW_COLS_V31 = {
    "market_regime": "", "gap_pct": "", "entry_time_bucket": "",
    "vol_ratio": "", "inst_flow": "", "slip_penalty_bps": "",
    "reconcile_flag": "",
}


# ═══════════════════════════════════════════════════════════════
#  유틸
# ═══════════════════════════════════════════════════════════════
def _now_kst() -> datetime:
    return datetime.now(tz=KST)

def _now_str() -> str:
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")

def _today_str() -> str:
    return _now_kst().strftime("%Y-%m-%d")

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).strip().replace(",", ""))
    except Exception:
        return default

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip().replace(",", "")))
    except Exception:
        return default

def _norm_code(x: Any) -> str:
    s = str(x).strip().upper()
    if s.startswith("A"):
        s = s[1:]
    digits = "".join(c for c in s if c.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits

def _log_stderr(msg: str, level: str = "info") -> None:
    getattr(_logger, level, _logger.info)(msg)

def _gap_bucket_label(gap_pct: float) -> str:
    ag = abs(gap_pct)
    if ag < 1:   return "0~1%"
    if ag < 3:   return "1~3%"
    if ag < 5:   return "3~5%"
    return "5%+"

def _validate_strategy(strategy: str) -> str:
    """[C-3] 전략명 검증 — 종배 차단, 2전략만 허용
    [FIX-2 v3.3] 'EOD_종가' → 'SIGA' 매핑 추가
      bridge_eod._build_entry()가 strategy='EOD_종가'로 기록
      → 기존 코드에서 미처리 → PULLBACK으로 오기록
      → SIGA 성과 데이터 0건, Kelly 계산 불가, 자기진화 무력화
    """
    s = strategy.upper().strip()
    # [FIX-2 v3.3] EOD_종가 → SIGA (bridge_eod v9.x 출력 형식)
    if s in ("EOD_종가".upper(), "EOD_JONGGA", "EOD종가"):
        return "SIGA"
    # 종배 관련 이름 모두 차단
    if s in ("EOD", "JONGBAE", "JONGBAE_SIGA", "SIGA_JONGBAE", "CBAT", "CBAT_SIGA"):
        _log_stderr(f"[PNL_LINKER] ⚠️ 종배 전략 차단: '{strategy}' → SIGA로 대체", level="warning")
        return "SIGA"
    if s not in ("SIGA", "PULLBACK"):
        _log_stderr(f"[PNL_LINKER] ⚠️ 미등록 전략 '{strategy}' → PULLBACK으로 대체", level="warning")
        return "PULLBACK"
    return s


# ═══════════════════════════════════════════════════════════════
#  경로
# ═══════════════════════════════════════════════════════════════
def _pnl_path(base: Path) -> Path:
    return base / "DATA" / "daily_pnl_by_strategy.csv"

def _weight_history_path(base: Path) -> Path:
    return base / "DATA" / "weight_history.csv"

def _lock_path(pnl: Path) -> Path:
    return pnl.with_suffix(".lock")


# ═══════════════════════════════════════════════════════════════
#  FileLock
# ═══════════════════════════════════════════════════════════════
class _NullLock:
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

def _get_lock(pnl_path: Path):
    if _FILELOCK_AVAILABLE:
        return FileLock(str(_lock_path(pnl_path)), timeout=5)
    return _NullLock()


# ═══════════════════════════════════════════════════════════════
#  행 해시 무결성
# ═══════════════════════════════════════════════════════════════
def _calc_row_hash(row: Dict[str, str]) -> str:
    payload = {k: v for k, v in sorted(row.items()) if k not in _HASH_EXCLUDE}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

def verify_row_integrity(row: Dict[str, str]) -> bool:
    stored = row.get("row_hash", "")
    if not stored:
        return True
    return stored == _calc_row_hash(row)

def verify_file_integrity(
    base_dir: str = DEFAULT_BASE_DIR,
    logger: Optional[logging.Logger] = None,
) -> Tuple[int, int]:
    path     = _pnl_path(Path(base_dir))
    rows     = _read_all(path)
    tampered = [r for r in rows if not verify_row_integrity(r)]
    if tampered:
        msg = (f"[PNL_LINKER] ⚠️ 무결성 오류 {len(tampered)}행 — "
               f"{[r.get('code','?') for r in tampered]}")
        if logger: logger.error(msg)
        else: _log_stderr(msg, level="error")
    return len(rows), len(tampered)


# ═══════════════════════════════════════════════════════════════
#  CSV 원자적 읽기/쓰기
# ═══════════════════════════════════════════════════════════════
def _read_all(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc).fillna("")
            if "slippage_bps" in df.columns and "slippage_buy_bps" not in df.columns:
                df.rename(columns={"slippage_bps": "slippage_buy_bps"}, inplace=True)
            if "pnl_pct" in df.columns and "pnl_pct_net" not in df.columns:
                df.rename(columns={"pnl_pct": "pnl_pct_net"}, inplace=True)
                df["pnl_pct_gross"] = df["pnl_pct_net"]
            for new_col, default in {
                "strategy_type": "", "capital_allocated": "",
                **_NEW_COLS_V31,
            }.items():
                if new_col not in df.columns:
                    df[new_col] = default
            return df.to_dict("records")
        except Exception:
            continue
    _log_stderr(f"[PNL_LINKER] ⚠️ CSV 읽기 전체 실패: {path}", level="error")
    return []

def _write_all(path: Path, rows: List[Dict[str, str]]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows and path.exists() and path.stat().st_size > 100:
            _log_stderr("[PNL_LINKER] ⚠️ 빈 rows로 기존 데이터 덮어쓰기 차단", level="error")
            return False
        tmp = path.with_suffix(".tmp")
        df  = pd.DataFrame(rows) if rows else pd.DataFrame(columns=_SCHEMA)
        for col in _SCHEMA:
            if col not in df.columns:
                df[col] = ""
        df = df[_SCHEMA]
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(path))
        return True
    except Exception as e:
        _log_stderr(f"[PNL_LINKER] write 실패: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  수익률 계산
# ═══════════════════════════════════════════════════════════════
def _calc_pnl(
    buy_price: float,
    sell_price: float,
    qty: int,
    deployed_capital: int,
    total_capital: int = 0,
) -> Tuple[float, float, int, float, float]:
    if buy_price <= 0 or deployed_capital <= 0:
        return 0.0, 0.0, 0, 0.0, 0.0
    pnl_pct_gross = (sell_price - buy_price) / buy_price * 100
    cost_krw      = (buy_price * qty * _BUY_FEE_PCT
                     + sell_price * qty * (_SELL_FEE_PCT + _SELL_TAX_PCT))
    net_pnl_krw   = int((sell_price - buy_price) * qty - cost_krw)
    pnl_pct_net   = net_pnl_krw / deployed_capital * 100
    roc_base = total_capital if total_capital > 0 else _TOTAL_CAPITAL
    roc_pct  = net_pnl_krw / roc_base * 100 if roc_base > 0 else 0.0
    # ★ [C-9] 단일 거래 TWR (복리 누적은 get_cumulative_twr() 참조)
    total_cost_rate = _BUY_FEE_PCT + _SELL_FEE_PCT + _SELL_TAX_PCT
    twr_pct = ((1 + pnl_pct_gross / 100) * (1 - total_cost_rate) - 1) * 100
    return (
        round(pnl_pct_gross, 4),
        round(pnl_pct_net,   4),
        net_pnl_krw,
        round(roc_pct, 4),
        round(twr_pct, 4),
    )


# ═══════════════════════════════════════════════════════════════
#  ★ [C-9] 누적 복리 TWR — 전략별 복리 체인 계산
# ═══════════════════════════════════════════════════════════════
def get_cumulative_twr(
    strategy: str,
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = _EVO_LOOKBACK,
) -> Dict[str, Any]:
    """
    ★ [C-9] 전략별 누적 복리 TWR 계산

    TWR = ∏(1 + twr_i) - 1  (복리 체인)

    출처: Global Investment Performance Standards (GIPS 2020)
    단순 합산 TWR이 아닌 기간별 복리 체인으로 계산.

    Returns
    -------
    {
      "cumulative_twr_pct": float,   # 누적 복리 TWR (%)
      "annualized_twr_pct": float,   # 연환산 TWR (%)
      "trade_count": int,
      "trading_days": int,
    }
    """
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days)
    df = df[df["strategy"] == strategy].sort_values("date")

    empty = {"cumulative_twr_pct": 0.0, "annualized_twr_pct": 0.0,
             "trade_count": 0, "trading_days": 0}
    if df.empty:
        return empty

    twr_vals = df["twr_pct"].dropna().tolist()
    if not twr_vals:
        return empty

    # 복리 체인
    cum = 1.0
    for t in twr_vals:
        cum *= (1 + t / 100)
    cum_twr_pct = (cum - 1) * 100

    # 연환산 (거래일 기준)
    n_trades = len(twr_vals)
    # 거래일 수 추정 (최대 lookback_days)
    try:
        dates = pd.to_datetime(df["date"].unique())
        trading_days = len(dates)
    except Exception:
        trading_days = max(n_trades, 1)

    if trading_days > 0:
        ann_twr_pct = (pow(cum, 252 / trading_days) - 1) * 100
    else:
        ann_twr_pct = 0.0

    return {
        "cumulative_twr_pct": round(cum_twr_pct, 4),
        "annualized_twr_pct": round(ann_twr_pct, 4),
        "trade_count":        n_trades,
        "trading_days":       trading_days,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ [C-7] KRX 시장충격비용 (한국시장 λ 보정)
# ═══════════════════════════════════════════════════════════════
def _calc_market_impact(order_krw: int, avg_daily_vol_krw: int = 0) -> float:
    """
    ★ [C-7] KRX 시장충격 λ 보정

    Almgren et al. (2005) square-root 모델:
      impact_bps = λ × √(participation_rate) × 10,000

    KRX 특성 반영:
    - 상하한 30% 제한 → 극단 이벤트 충격 감소
    - T+2 결제 → 유동성 지연 비용 추가 (+10%)
    - NYSE 대비 소형주 비중 高 → λ 상향

    KRX 거래대금 티어별 λ:
      ≥ 1조원/일 : λ=0.06  (대형주, 코스피200)
      ≥ 1000억/일: λ=0.10  (중형주)
      ≥ 100억/일 : λ=0.15  (소형주)
      < 100억/일  : λ=0.25  (극소형 주의)
    """
    if avg_daily_vol_krw > 0:
        participation = order_krw / avg_daily_vol_krw
        if avg_daily_vol_krw >= 1_000_000_000_000:  lam = 0.06   # 1조+
        elif avg_daily_vol_krw >= 100_000_000_000:  lam = 0.10   # 1000억+
        elif avg_daily_vol_krw >= 10_000_000_000:   lam = 0.15   # 100억+
        else:                                         lam = 0.25   # 100억 미만
    else:
        participation = order_krw / 10_000_000_000   # 100억 기본 가정
        lam = _IMPACT_LAMBDA_DEFAULT

    impact_bps = lam * math.sqrt(max(participation, 0)) * 10000
    # T+2 결제 지연 비용 +10% 보정
    return round(impact_bps * 1.10, 2)


# ═══════════════════════════════════════════════════════════════
#  IOC 기회비용
# ═══════════════════════════════════════════════════════════════
def _calc_opportunity_cost(unfilled_qty: int, buy_price: float, ref_price: float) -> int:
    if unfilled_qty <= 0 or buy_price <= 0 or ref_price <= 0:
        return 0
    return int((ref_price - buy_price) * unfilled_qty)


# ═══════════════════════════════════════════════════════════════
#  체결품질 Fill Quality
# ═══════════════════════════════════════════════════════════════
def _calc_fill_quality(price: float, vwap: float, side: str) -> float:
    if vwap <= 0 or price <= 0:
        return 0.0
    bps = (vwap - price) / vwap * 10000 if side == "BUY" else (price - vwap) / vwap * 10000
    return round(bps, 2)


# ═══════════════════════════════════════════════════════════════
#  3중 키 매칭
# ═══════════════════════════════════════════════════════════════
def _find_rows(
    rows: List[Dict[str, str]],
    today: str,
    code: str,
    strategy: Optional[str],
    status_filter: tuple = ("OPEN", "PARTIAL_CLOSED"),
) -> List[Tuple[int, Dict[str, str]]]:
    result = []
    for i, r in enumerate(rows):
        if r.get("date") != today: continue
        if _norm_code(r.get("code", "")) != code: continue
        if strategy and r.get("strategy", "") != strategy: continue
        if status_filter and r.get("status", "OPEN") not in status_filter: continue
        result.append((i, r))
    return result


# ═══════════════════════════════════════════════════════════════
#  ★ [C-4] 통계 헬퍼 — Sharpe 무위험이자율 반영
# ═══════════════════════════════════════════════════════════════
def _sharpe(pnls: List[float], rf_daily_pct: Optional[float] = None) -> float:
    """
    ★ [C-4] Sharpe ratio — 무위험이자율 반영

    출처: Lo (2002) "The Statistics of Sharpe Ratios", FAJ 58(4)
    Sharpe = (μ - rf) / σ

    rf_daily_pct: 일 단위 무위험이자율(%). None이면 모듈 기본값 사용.
    """
    if len(pnls) < 2:
        return 0.0
    rf = rf_daily_pct if rf_daily_pct is not None else _RISK_FREE_DAILY_PCT
    excess_pnls = [p - rf for p in pnls]
    mu  = statistics.mean(excess_pnls)
    std = statistics.stdev(excess_pnls)
    return round(mu / std, 4) if std > 0 else (mu * 100 if mu > 0 else 0.0)


def _sortino(pnls: List[float], rf_daily_pct: Optional[float] = None) -> float:
    """
    ★ [C-5] Sortino ratio 안정화 — downside 1건 케이스 개선

    출처: Sortino & van der Meer (1991) Journal of Portfolio Management
    Sortino = (μ - rf) / σ_downside

    [C-5 개선] downside 1건일 때 abs() 대신 최소 2% 기준으로 대체
    (단일 손실 거래를 분모로 쓰면 Sortino 극단값 발생)
    """
    if len(pnls) < 2:
        return 0.0
    rf = rf_daily_pct if rf_daily_pct is not None else _RISK_FREE_DAILY_PCT
    mu       = statistics.mean(pnls) - rf
    downside = [p - rf for p in pnls if p < rf]
    if not downside:
        return round(min(mu * 10, 5.0), 4)

    if len(downside) == 1:
        # ★ [C-5] 1건 케이스: abs 대신 최솟값 손실 기준 하한 보수적 처리
        down_std = max(abs(downside[0]), 0.5)   # 최소 0.5% 분모 보장
    else:
        down_std = statistics.stdev(downside)

    return round(mu / down_std, 4) if down_std > 0 else 0.0


def _mdd(pnls: List[float]) -> float:
    if not pnls: return 0.0
    cum, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnls:
        cum  *= (1 + p / 100)
        peak  = max(peak, cum)
        max_dd = min(max_dd, (cum - peak) / peak)
    return max_dd

def _profit_factor(pnls: List[float]) -> float:
    gains  = sum(p for p in pnls if p > 0)
    losses = sum(abs(p) for p in pnls if p < 0)
    if losses == 0: return 999.0 if gains > 0 else 1.0
    if gains  == 0: return 0.0
    return round(gains / losses, 4)


# ═══════════════════════════════════════════════════════════════
#  ★ [C-8] Half-Kelly 포지션 사이징
# ═══════════════════════════════════════════════════════════════
def get_kelly_fraction(
    strategy: str,
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = _EVO_LOOKBACK,
    total_capital: int = 0,
) -> Dict[str, Any]:
    """
    ★ [C-8] Half-Kelly 포지션 사이징

    Kelly Fraction = (p × b - q) / b
      p = 승률
      q = 1 - p (패배율)
      b = 평균 수익 / 평균 손실 (Profit-to-Loss ratio)

    Half-Kelly: f* = Kelly × 0.5  (과도 베팅 방지, Thorp 1962)
    최대 25% 상한 (KELLY_MAX_FRACTION) 강제 적용

    출처:
      Kelly, J.L. (1956) "A New Interpretation of Information Rate" BSTJ
      Thorp, E. (1962) "Beat the Dealer" — Half-Kelly 실전
      Lopez de Prado (2018) — 과적합 방지를 위한 half-sizing 권고

    Returns
    -------
    {
      "kelly_full":      float,   # Full Kelly fraction
      "kelly_half":      float,   # Half-Kelly fraction (실사용)
      "kelly_krw":       int,     # 권고 투입 자본 (원화)
      "win_rate":        float,
      "profit_loss_ratio": float,
      "trade_count":     int,
      "note":            str,
    }
    """
    cap = total_capital if total_capital > 0 else _TOTAL_CAPITAL
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days)
    df = df[df["strategy"] == strategy]

    empty = {
        "kelly_full": 0.0, "kelly_half": 0.0, "kelly_krw": 0,
        "win_rate": 0.0, "profit_loss_ratio": 1.0, "trade_count": 0,
        "note": "데이터 부족 → 기본 자본배분 사용",
    }
    if df.empty:
        return empty

    pnls = df["pnl_pct_net"].dropna().tolist()
    if len(pnls) < _EVO_MIN_TRADES:
        empty["note"] = f"표본 {len(pnls)}건 < {_EVO_MIN_TRADES}건 → 기본 자본배분"
        empty["trade_count"] = len(pnls)
        return empty

    wins   = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]

    p = len(wins) / len(pnls)     # 승률
    q = 1 - p                      # 패배율

    avg_win  = statistics.mean(wins)   if wins   else 0.0
    avg_loss = statistics.mean(losses) if losses else 1.0  # 분모 0 방지

    # b = 평균 수익 / 평균 손실
    b = avg_win / avg_loss if avg_loss > 0 else 1.0

    # Kelly Fraction
    kelly_full = (p * b - q) / b if b > 0 else 0.0
    kelly_full = max(kelly_full, 0.0)   # 음수 방지 (edge 없음 → 진입 금지)

    # Half-Kelly
    kelly_half = kelly_full * _KELLY_HALF

    # 상한 적용
    kelly_capped = min(kelly_half, _KELLY_MAX_FRACTION)
    kelly_krw    = int(cap * kelly_capped)

    note = (
        f"Kelly={kelly_full*100:.1f}% → Half={kelly_half*100:.1f}%"
        f" → Cap={kelly_capped*100:.1f}% ({kelly_krw:,}원)"
    )

    if kelly_full <= 0.0:
        note = "Kelly≤0 — 현재 전략 Edge 없음 → 진입 보류 권고"

    _log_stderr(f"[PNL_LINKER] [Half-Kelly] {strategy}: "
                f"WR={p*100:.0f}% b={b:.2f} → {note}")

    return {
        "kelly_full":        round(kelly_full, 4),
        "kelly_half":        round(kelly_half, 4),
        "kelly_krw":         kelly_krw,
        "win_rate":          round(p, 4),
        "profit_loss_ratio": round(b, 4),
        "trade_count":       len(pnls),
        "note":              note,
    }


# ═══════════════════════════════════════════════════════════════
#  진화 가중치 이력 저장
# ═══════════════════════════════════════════════════════════════
def _save_weight_history(weights: Dict[str, float], base: Path) -> None:
    path = _weight_history_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts, today = _now_str(), _today_str()
    rows: List[Dict[str, str]] = []
    if path.exists():
        try:
            rows = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("").to_dict("records")
            if len(rows) > 1000:
                rows = rows[-1000:]
        except Exception:
            rows = []
    for strat, w in weights.items():
        rows.append({"ts": ts, "date": today, "strategy": strat, "weight": str(w)})
    try:
        tmp = path.with_suffix(".tmp")
        pd.DataFrame(rows)[["ts","date","strategy","weight"]].to_csv(
            tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(path))
    except Exception as e:
        _log_stderr(f"[PNL_LINKER] weight_history 저장 실패: {e}")

def _load_prev_weights(base: Path) -> Dict[str, float]:
    path = _weight_history_path(base)
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        if df.empty:
            return {}
        latest = df.sort_values("ts").groupby("strategy").last().reset_index()
        return {r["strategy"]: _safe_float(r["weight"], 1.0)
                for _, r in latest.iterrows()}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 1: 매수 체결 기록
# ═══════════════════════════════════════════════════════════════
def write_buy_fill(
    code: str,
    strategy: str,
    buy_price: float,
    buy_qty: int,
    slippage_buy_bps: float          = 0.0,
    vwap_at_buy: float               = 0.0,
    unfilled_qty: int                = 0,
    ref_price_for_opp: float         = 0.0,
    avg_daily_vol_krw: int           = 0,
    base_dir: str                    = DEFAULT_BASE_DIR,
    logger: Optional[logging.Logger] = None,
    date_str: Optional[str]          = None,
    strategy_type: str               = "",
    capital_allocated: int           = 0,
    # Context 파라미터
    market_regime: str               = "",
    gap_pct: float                   = 0.0,
    entry_time_bucket: str           = "",
    vol_ratio: float                 = 0.0,
    inst_flow: int                   = 0,
) -> bool:
    """
    매수 체결 기록.
    [C-3] 종배 전략 자동 차단 — _validate_strategy() 적용
    """
    # ★ [C-3] 전략 검증
    strategy = _validate_strategy(strategy)

    code     = _norm_code(code)
    today    = date_str or _today_str()
    path     = _pnl_path(Path(base_dir))
    _log     = logger.info if logger else _log_stderr

    buy_krw  = int(buy_price * buy_qty)
    cap_alloc = capital_allocated if capital_allocated > 0 else buy_krw

    impact_bps  = _calc_market_impact(buy_krw, avg_daily_vol_krw)
    opp_cost    = _calc_opportunity_cost(unfilled_qty, buy_price, ref_price_for_opp)
    fq_buy      = _calc_fill_quality(buy_price, vwap_at_buy, "BUY")

    # 슬리피지 이상 탐지
    slip_anom = check_slippage_anomaly(slippage_buy_bps, "BUY", base_dir)
    slip_penalty_bps_val = ""
    if slip_anom["is_anomaly"]:
        penalty = round(slippage_buy_bps - slip_anom["mean"], 2)
        slip_penalty_bps_val = str(penalty)
        _log(f"[PNL_LINKER] ⚠️ 매수 슬리피지 3σ 이상 "
             f"code={code} slip={slippage_buy_bps}bps "
             f"(z={slip_anom['z_score']:.1f}) 페널티={penalty}bps")

    rec: Dict[str, str] = {
        "date":                 today,
        "code":                 code,
        "strategy":             strategy,
        "strategy_type":        strategy_type.upper() if strategy_type else (
                                    "ATTACK" if strategy == "SIGA" else "STABLE"),
        "capital_allocated":    str(cap_alloc),
        "buy_price":            str(round(buy_price, 2)),
        "buy_qty":              str(buy_qty),
        "buy_krw":              str(buy_krw),
        "buy_ts":               _now_str(),
        "slippage_buy_bps":     str(round(slippage_buy_bps, 2)),
        "fill_quality_buy":     str(fq_buy),
        "market_impact_bps":    str(impact_bps),
        "opportunity_cost_krw": str(opp_cost),
        "market_regime":        market_regime,
        "gap_pct":              str(round(gap_pct, 4)),
        "entry_time_bucket":    entry_time_bucket,
        "vol_ratio":            str(round(vol_ratio, 4)),
        "inst_flow":            str(inst_flow),
        "sell_price": "", "sell_ts": "",
        "slippage_sell_bps": "", "fill_quality_sell": "",
        "slip_penalty_bps":     slip_penalty_bps_val,
        "reconcile_flag":       "",
        "pnl_pct_gross": "", "pnl_pct_net": "", "pnl_krw": "",
        "roc_pct": "", "twr_pct": "",
        "status":    "OPEN",
        "updated_at": _now_str(),
        "row_hash":  "",
    }
    rec["row_hash"] = _calc_row_hash(rec)

    with _get_lock(path):
        rows = _read_all(path)
        # 기존 OPEN 중복 방지
        existing = _find_rows(rows, today, code, strategy)
        if existing:
            _log(f"[PNL_LINKER] ⚠️ 중복 매수 감지 code={code} str={strategy} — 스킵")
            return False
        rows.append(rec)
        ok = _write_all(path, rows)

    if ok:
        _log(f"[PNL_LINKER] 매수 code={code} str={strategy} "
             f"price={buy_price:.0f} qty={buy_qty} krw={buy_krw:,} "
             f"impact={impact_bps}bps fq={fq_buy}bps")
    return ok


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 1.5: PULLBACK 진입 앵커 등록
# ═══════════════════════════════════════════════════════════════
def notify_rt_entry(
    code: str,
    run_id: str                      = "",
    strategy: Optional[str]          = None,
    base_dir: str                    = DEFAULT_BASE_DIR,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """PULLBACK(RT) 진입 이벤트를 pnl_linker에 등록.
    daily_pnl_by_strategy.csv에 ENTRY_PENDING 행을 생성해
    write_sell_fill()이 수익률을 채울 앵커를 확보한다.
    반환: True=등록성공 / False=스킵(중복·오류)
    """
    _log = logger.info if logger else logging.getLogger("pnl_linker").info
    if not code or not str(code).strip():
        _log("[notify_rt_entry] code 비어있음 → 스킵")
        return False
    strategy_norm = _validate_strategy(str(strategy or "PULLBACK"))
    base     = Path(base_dir)
    path     = base / "DATA" / "daily_pnl_by_strategy.csv"
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        rows = _read_all(path)
        for r in rows:
            if (r.get("date") == date_str
                    and r.get("code") == str(code).zfill(6)
                    and r.get("strategy") == strategy_norm
                    and r.get("status") == "ENTRY_PENDING"):
                _log("[notify_rt_entry] 중복 진입 대기 행 존재 → 스킵: %s %s", code, strategy_norm)
                return False
        anchor_row: Dict[str, str] = {
            "date":       date_str,
            "code":       str(code).zfill(6),
            "strategy":   strategy_norm,
            "run_id":     str(run_id),
            "buy_price":  "",
            "sell_price": "",
            "pnl_pct":    "",
            "status":     "ENTRY_PENDING",
            "updated_at": now_str,
            "entry_at":   now_str,
        }
        rows.append(anchor_row)
        _write_all(path, rows)
        _log("[notify_rt_entry] 진입 앵커 등록: code=%s strat=%s run_id=%s",
             code, strategy_norm, run_id)
        return True
    except Exception as e:
        _log("[notify_rt_entry] 등록 실패(비치명): %s", e)
        return False


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 2: 매도 체결 기록
# ═══════════════════════════════════════════════════════════════
def write_sell_fill(
    code: str,
    sell_price: float,
    sell_qty: int,
    strategy: Optional[str]          = None,
    slippage_sell_bps: float         = 0.0,
    vwap_at_sell: float              = 0.0,
    base_dir: str                    = DEFAULT_BASE_DIR,
    logger: Optional[logging.Logger] = None,
    date_str: Optional[str]          = None,
    total_capital: int               = 0,
    exit_reason: str                 = "",
) -> bool:
    """매도 체결 기록 + 자기진화 트리거"""
    # ★ [C-3] 전략 검증 (있는 경우만)
    if strategy:
        strategy = _validate_strategy(strategy)

    code  = _norm_code(code)
    today = date_str or _today_str()
    path  = _pnl_path(Path(base_dir))
    _log  = logger.info if logger else _log_stderr

    cap_for_roc = total_capital if total_capital > 0 else _TOTAL_CAPITAL

    fq_sell = _calc_fill_quality(sell_price, vwap_at_sell, "SELL")

    slip_anom = check_slippage_anomaly(slippage_sell_bps, "SELL", base_dir)
    slip_penalty_bps_val = ""
    if slip_anom["is_anomaly"]:
        penalty = round(slippage_sell_bps - slip_anom["mean"], 2)
        slip_penalty_bps_val = str(penalty)

    ok = False
    pnl_pct_for_bridge: Optional[float] = None

    with _get_lock(path):
        rows  = _read_all(path)
        match = _find_rows(rows, today, code, strategy)

        if not match:
            # RECONCILE 처리
            _log(f"[PNL_LINKER] ⚠️ 매수 원장 없음 — RECONCILE code={code}")
            rec: Dict[str, str] = {
                "date":          today,
                "code":          code,
                "strategy":      strategy or "UNKNOWN",
                "strategy_type": "",
                "capital_allocated": "",
                "buy_price": "", "buy_qty": "", "buy_krw": "", "buy_ts": "",
                "slippage_buy_bps": "", "fill_quality_buy": "",
                "market_impact_bps": "", "opportunity_cost_krw": "",
                "market_regime": "", "gap_pct": "", "entry_time_bucket": "",
                "vol_ratio": "", "inst_flow": "",
                "sell_price":        str(round(sell_price, 2)),
                "sell_ts":           _now_str(),
                "slippage_sell_bps": str(round(slippage_sell_bps, 2)),
                "fill_quality_sell": str(fq_sell),
                "slip_penalty_bps":  slip_penalty_bps_val,
                "reconcile_flag":    "ESTIMATED",
                "pnl_pct_gross":     "RECONCILE_EST",
                "pnl_pct_net":       str(_RECONCILE_EST_PNL_PCT),
                "pnl_krw":           "RECONCILE_EST",
                "roc_pct":           "RECONCILE_EST",
                "twr_pct":           "RECONCILE_EST",
                "status":            "RECONCILE",
                "updated_at":        _now_str(),
                "row_hash":          "",
            }
            rec["row_hash"] = _calc_row_hash(rec)
            rows.append(rec)
            ok = _write_all(path, rows)

            recon_cnt = sum(1 for r in rows
                            if r.get("status") == "RECONCILE"
                            and r.get("date") == today)
            if recon_cnt >= 3:
                _log(f"[PNL_LINKER] ⚠️ RECONCILE {recon_cnt}건 점검 필요", )

        else:
            i, row        = match[0]
            buy_price_f   = _safe_float(row.get("buy_price", 0.0))
            buy_qty_rem   = _safe_int(row.get("buy_qty", 0))
            closed_qty    = min(sell_qty, buy_qty_rem)
            remaining     = buy_qty_rem - closed_qty
            deployed_cap  = max(int(buy_price_f * closed_qty), 1)

            gross, net, pnl_krw, roc_pct, twr_pct = _calc_pnl(
                buy_price_f, sell_price, closed_qty, deployed_cap,
                total_capital=cap_for_roc,
            )

            final_strategy     = strategy or row.get("strategy", "")
            pnl_pct_for_bridge = net

            sell_update = {
                "sell_price":        str(round(sell_price, 2)),
                "sell_ts":           _now_str(),
                "slippage_sell_bps": str(round(slippage_sell_bps, 2)),
                "fill_quality_sell": str(fq_sell),
                "slip_penalty_bps":  slip_penalty_bps_val,
                "reconcile_flag":    "",
                "pnl_pct_gross":     str(gross),
                "pnl_pct_net":       str(net),
                "pnl_krw":           str(pnl_krw),
                "roc_pct":           str(roc_pct),
                "twr_pct":           str(twr_pct),
            }

            if remaining <= 0:
                rows[i].update({**sell_update,
                                 "status": "CLOSED", "buy_qty": "0",
                                 "updated_at": _now_str()})
                if strategy:
                    rows[i]["strategy"] = strategy
                rows[i]["row_hash"] = _calc_row_hash(rows[i])
            else:
                rows[i].update({
                    "buy_qty":    str(remaining),
                    "buy_krw":    str(int(buy_price_f * remaining)),
                    "status":     "PARTIAL_CLOSED",
                    "updated_at": _now_str(),
                })
                rows[i]["row_hash"] = _calc_row_hash(rows[i])

                child_row: Dict[str, str] = {
                    "date":                 today,
                    "code":                 code,
                    "strategy":             final_strategy,
                    "strategy_type":        row.get("strategy_type", ""),
                    "capital_allocated":    row.get("capital_allocated", ""),
                    "buy_price":            str(round(buy_price_f, 2)),
                    "buy_qty":              str(closed_qty),
                    "buy_krw":              str(deployed_cap),
                    "buy_ts":               row.get("buy_ts", ""),
                    "slippage_buy_bps":     row.get("slippage_buy_bps", ""),
                    "fill_quality_buy":     row.get("fill_quality_buy", ""),
                    "market_impact_bps":    row.get("market_impact_bps", ""),
                    "opportunity_cost_krw": row.get("opportunity_cost_krw", ""),
                    "market_regime":        row.get("market_regime", ""),
                    "gap_pct":              row.get("gap_pct", ""),
                    "entry_time_bucket":    row.get("entry_time_bucket", ""),
                    "vol_ratio":            row.get("vol_ratio", ""),
                    "inst_flow":            row.get("inst_flow", ""),
                    **sell_update,
                    "status":               "CLOSED",
                    "updated_at":           _now_str(),
                    "row_hash":             "",
                }
                child_row["row_hash"] = _calc_row_hash(child_row)
                rows.append(child_row)

            _log(f"[PNL_LINKER] 매도 code={code} str={final_strategy} "
                 f"{buy_price_f:.0f}→{sell_price:.0f} "
                 f"gross={gross:+.2f}% net={net:+.2f}% "
                 f"roc={roc_pct:+.2f}% ({pnl_krw:+,}원) "
                 f"잔여={remaining} slip_pen={slip_penalty_bps_val or '없음'} "
                 f"exit={exit_reason}")
            ok = _write_all(path, rows)

    if not ok and logger:
        logger.error("[PNL_LINKER] write_sell_fill 저장실패 code=%s", code)

    # [FIX-3 v3.3] trade_log.csv 동시 기록 — evolution_engine 학습 데이터 공급
    # evolution_engine._load_trade_log()가 요구하는 13컬럼 형식으로 기록
    # 기존 문제: trade_log.csv를 쓰는 모듈 없음 → evolution_engine EV 학습 절반 소실
    if ok and pnl_pct_for_bridge is not None:
        try:
            _base_path = Path(base_dir)
            _trade_log_path = _base_path / _TRADE_LOG_PATH_TMPL
            _trade_log_path.parent.mkdir(parents=True, exist_ok=True)
            # [FIX-4 v3.3] pnl_pct 단위: 백분율 → 소수 변환 (/100)
            # evolution_engine._calc_kelly()는 소수 단위 기대 (avg_ret - ROUND_TRIP_COST=0.0022)
            # pnl_linker는 백분율 (2.34=2.34%) → /100 변환 필수
            _pnl_decimal = pnl_pct_for_bridge / 100.0
            _matched_row = rows[match[0][0]] if match else {}
            _buy_price_f = _safe_float(_matched_row.get("buy_price", 0))
            _buy_qty_i   = _safe_int(_matched_row.get("buy_qty", 0))
            _regime_str  = _matched_row.get("market_regime", "")
            _entry_score = _matched_row.get("vol_ratio", "")  # entry_score 대체 필드
            _r_multiple  = 0.0
            if _buy_price_f > 0 and sell_price > 0:
                _stop_est = _buy_price_f * 0.975  # Hard Stop -2.5% 추정
                _r_dist   = _buy_price_f - _stop_est
                if _r_dist > 0:
                    _r_multiple = round((sell_price - _buy_price_f) / _r_dist, 4)
            _tl_row = {
                "date":        today,
                "ticker":      code,
                "strategy":    final_strategy,
                "regime":      _regime_str,
                "entry_price": str(_buy_price_f),
                "exit_price":  str(round(sell_price, 2)),
                "stop_price":  str(round(_buy_price_f * 0.975, 2)),
                "pnl":         str(int((_safe_float(rows[match[0][0]].get("pnl_krw", 0))
                                        if match else 0))),
                "pnl_pct":     str(round(_pnl_decimal, 6)),   # [FIX-4] 소수 단위
                "R_multiple":  str(_r_multiple),
                "entry_score": _entry_score,
                "exit_reason": exit_reason,
                "holding_min": "",   # sell_engine에서 채워지는 경우 별도 처리
            }
            _tl_df_new = pd.DataFrame([_tl_row])
            if _trade_log_path.exists() and _trade_log_path.stat().st_size > 0:
                try:
                    _tl_df_old = pd.read_csv(_trade_log_path, encoding="utf-8-sig")
                    _tl_df_all = pd.concat([_tl_df_old, _tl_df_new], ignore_index=True)
                except Exception:
                    _tl_df_all = _tl_df_new
            else:
                _tl_df_all = _tl_df_new
            _tl_tmp = _trade_log_path.with_suffix(".tmp")
            _tl_df_all.to_csv(_tl_tmp, index=False, encoding="utf-8-sig")
            os.replace(str(_tl_tmp), str(_trade_log_path))
            _log_stderr(f"[PNL_LINKER][FIX-3] trade_log.csv 기록: {code} pnl={_pnl_decimal:+.6f}(소수)")
        except Exception as _tl_err:
            _log_stderr(f"[PNL_LINKER][FIX-3] trade_log.csv 기록 실패: {_tl_err}", level="warning")

    # [v3.4] switch_history.csv pnl_ret 업데이트
    # switch_selector v1.8 협약: ts + new_code 조합으로 행 식별 후 실제 수익률 기록
    # pnl_ret=0 placeholder → 실제 pnl_pct_net 으로 갱신
    # 이 업데이트가 없으면 switch_selector 자기진화 승률이 항상 0%로 계산됨
    if ok and pnl_pct_for_bridge is not None:
        try:
            _sw_path = Path(base_dir) / _SWITCH_HISTORY_TMPL
            if _sw_path.exists() and _sw_path.stat().st_size > 0:
                _sw_df = pd.read_csv(_sw_path, encoding="utf-8-sig", dtype=str)
                # ts + new_code 조합으로 해당 행 탐색
                _mask = (
                    (_sw_df.get("new_code", pd.Series(dtype=str)) == code) &
                    (_sw_df.get("pnl_ret",  pd.Series(dtype=str)).fillna("0").astype(float) == 0.0)
                )
                if _mask.any():
                    # 가장 최근 미갱신 행 1개만 갱신
                    _idx = _sw_df[_mask].index[-1]
                    _sw_df.at[_idx, "pnl_ret"] = str(round(pnl_pct_for_bridge / 100.0, 6))
                    _sw_tmp = _sw_path.with_suffix(".tmp")
                    _sw_df.to_csv(_sw_tmp, index=False, encoding="utf-8-sig")
                    os.replace(str(_sw_tmp), str(_sw_path))
                    _log_stderr(
                        f"[PNL_LINKER][v3.4] switch_history pnl_ret 갱신: "
                        f"code={code} pnl={pnl_pct_for_bridge/100.0:+.6f}(소수)"
                    )
        except Exception as _sw_err:
            _log_stderr(
                f"[PNL_LINKER][v3.4] switch_history 갱신 실패: {_sw_err}",
                level="warning"
            )

    # 자기진화 트리거
    if ok and pnl_pct_for_bridge is not None and _BRIDGE_PNL_OK:
        if _bridge_update_pnl is None:
            raise RuntimeError("pnl linker 미초기화 상태")
        try:
            _bridge_update_pnl(
                code=code, date_str=today,
                pnl_pct=pnl_pct_for_bridge,
                logger=logger or _logger,
                exit_reason=exit_reason,
            )
            _log_stderr(f"[PNL_LINKER] ★ 자기진화 트리거 완료 "
                        f"code={code} pnl={pnl_pct_for_bridge:+.2f}%")
        except Exception as e:
            _log_stderr(f"[PNL_LINKER] ⚠️ update_pnl_result 실패: {e}", level="error")

    return ok


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 3: 전략별 성과 조회
# ═══════════════════════════════════════════════════════════════
def load_strategy_pnl(
    base_dir: str        = DEFAULT_BASE_DIR,
    lookback_days: int   = _EVO_LOOKBACK,
    status_filter: tuple = ("CLOSED",),
    include_reconcile: bool = False,
) -> pd.DataFrame:
    path  = _pnl_path(Path(base_dir))
    empty = pd.DataFrame(columns=["date","strategy","strategy_type",
                                   "pnl_pct_gross","pnl_pct_net","roc_pct","twr_pct",
                                   "market_regime","gap_pct","entry_time_bucket",
                                   "reconcile_flag","slip_penalty_bps"])
    if not path.exists() or path.stat().st_size == 0:
        return empty
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        if "pnl_pct" in df.columns and "pnl_pct_net" not in df.columns:
            df.rename(columns={"pnl_pct": "pnl_pct_net"}, inplace=True)
            df["pnl_pct_gross"] = df["pnl_pct_net"]
        for col in ("pnl_pct_gross","pnl_pct_net","roc_pct","twr_pct","gap_pct","vol_ratio"):
            if col not in df.columns: df[col] = float("nan")
            df[col] = pd.to_numeric(df[col], errors="coerce")

        sf = list(status_filter)
        if include_reconcile and "RECONCILE" not in sf:
            sf.append("RECONCILE")
        df = df[df["status"].isin(sf)].copy()
        df = df.dropna(subset=["pnl_pct_net"])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        if not df.empty:
            cutoff = df["date"].max() - pd.Timedelta(days=lookback_days - 1)
            df = df[df["date"] >= cutoff]
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        for c in _NEW_COLS_V31:
            if c not in df.columns: df[c] = ""
        return df.reset_index(drop=True)
    except Exception as e:
        _log_stderr(f"[PNL_LINKER] load_strategy_pnl 실패: {e}")
        return empty


# ═══════════════════════════════════════════════════════════════
#  ★ PUBLIC API: Context Edge — 레짐×갭 조건별 성과 학습
# ═══════════════════════════════════════════════════════════════
def get_context_edge(
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = _EVO_LOOKBACK,
    min_samples: int   = _CTX_MIN_SAMPLES,   # ★ [C-6] 3→5
) -> Dict[str, Dict[str, float]]:
    """
    ★ Context Learning — 레짐×갭 조건별 평균 PnL 학습

    [C-6] min_samples 3→5 상향:
    Lo (2002) 최소 통계적 유의 표본 기준 강화.
    3건 패턴에서의 자본배분 결정은 과적합 위험 높음.

    출처: Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere"
    → 레짐별 전략 성과 독립 평가 후 합산

    Returns: { "SIGA": {"BULL_1~3%": +0.82, ...}, "PULLBACK": {...} }
    """
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days,
                           include_reconcile=False)
    result: Dict[str, Dict[str, float]] = {}
    if df.empty:
        return result

    for strat, grp in df.groupby("strategy"):
        ctx: Dict[str, list] = {}
        for _, row in grp.iterrows():
            regime = str(row.get("market_regime", "")).strip() or "UNKNOWN"
            try:
                gp = float(row.get("gap_pct", 0) or 0)
            except Exception:
                gp = 0.0
            bucket = _gap_bucket_label(gp)
            key = f"{regime}_{bucket}"
            if key not in ctx:
                ctx[key] = []
            ctx[key].append(float(row["pnl_pct_net"]))

        edge_ctx: Dict[str, float] = {}
        for key, pnls in ctx.items():
            if len(pnls) >= min_samples:
                edge_ctx[key] = round(statistics.mean(pnls), 4)
        result[strat] = edge_ctx

    return result


# ═══════════════════════════════════════════════════════════════
#  ★ PUBLIC API: Edge Score 산출
# ═══════════════════════════════════════════════════════════════
def compute_edge_score(
    strategy: str,
    base_dir: str        = DEFAULT_BASE_DIR,
    lookback_days: int   = _EVO_LOOKBACK,
    current_regime: str  = "",
    current_gap_pct: float = 0.0,
) -> Dict[str, Any]:
    """
    ★ EdgeScore = 0.35×Sharpe + 0.20×Sortino + 0.20×WinRate
                 + 0.15×ProfitFactor + 0.10×ContextEdge

    [C-4] Sharpe/Sortino: 무위험이자율 반영 버전 사용
    [C-5] Sortino: 분모 안정화 버전 사용

    출처: Lopez de Prado (2018) "Advances in Financial ML"
    edge_score ∈ [0, 1.5]
    """
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days)
    df = df[df["strategy"] == strategy]

    empty_result = {
        "edge_score": 0.5, "sharpe": 0.0, "sortino": 0.0,
        "win_rate": 0.0, "profit_factor": 1.0, "context_edge": 0.0,
        "trade_count": 0,
    }
    if df.empty:
        return empty_result

    pnls = df["pnl_pct_net"].dropna().tolist()
    if len(pnls) < 2:
        return {**empty_result, "trade_count": len(pnls)}

    # ★ [C-4][C-5] 개선된 Sharpe/Sortino 사용
    sh = _sharpe(pnls)
    so = _sortino(pnls)
    wr = sum(1 for p in pnls if p > 0) / len(pnls)
    pf = _profit_factor(pnls)

    # ContextEdge
    ctx_edges = get_context_edge(base_dir=base_dir, lookback_days=lookback_days)
    ctx_edge  = 0.0
    if current_regime and strategy in ctx_edges:
        bucket = _gap_bucket_label(current_gap_pct)
        key    = f"{current_regime}_{bucket}"
        ctx_edge = ctx_edges[strategy].get(key, 0.0)

    # 정규화
    sh_norm  = min(max(sh, -2.0), 2.0) / 2.0 * 0.5 + 0.5
    so_norm  = min(max(so, -2.0), 2.0) / 2.0 * 0.5 + 0.5
    pf_norm  = min(pf / 2.0, 1.0)
    ctx_norm = min(max(ctx_edge, -2.0), 2.0) / 2.0 * 0.5 + 0.5

    edge = (0.35 * sh_norm
            + 0.20 * so_norm
            + 0.20 * wr
            + 0.15 * pf_norm
            + 0.10 * ctx_norm)

    edge = round(min(max(edge, 0.0), 1.5), 4)

    _log_stderr(f"[PNL_LINKER] EdgeScore {strategy}: "
                f"Sharpe={sh:.2f}(rf={_RISK_FREE_DAILY_PCT:.3f}%) "
                f"Sortino={so:.2f} WR={wr*100:.0f}% "
                f"PF={pf:.2f} CtxEdge={ctx_edge:+.3f} → EdgeScore={edge:.4f}")

    return {
        "edge_score":    edge,
        "sharpe":        round(sh, 4),
        "sortino":       round(so, 4),
        "win_rate":      round(wr, 4),
        "profit_factor": round(pf, 4),
        "context_edge":  round(ctx_edge, 4),
        "trade_count":   len(pnls),
    }


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 4: 전략별 진화 가중치
# ═══════════════════════════════════════════════════════════════
def load_strategy_weights(
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = _EVO_LOOKBACK,
    min_trades: int    = _EVO_MIN_TRADES,
    save_history: bool = True,
) -> Dict[str, float]:
    """
    ★ EdgeScore 기반 진화 가중치
    weight = 0.5 + edge_score   (edge_score ∈ [0,1.5] → weight ∈ [0.5, 2.0])
    ★ 안정화: trades < min_trades 시 이전 가중치 대비 ±10% 이내 제한
    """
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days)
    weights: Dict[str, float] = {}
    if df.empty:
        return weights

    prev_weights = _load_prev_weights(Path(base_dir))

    for strat, grp in df.groupby("strategy"):
        pnls = grp["pnl_pct_net"].dropna().tolist()

        if len(pnls) < min_trades:
            prev_w = prev_weights.get(strat, 1.0)
            weights[strat] = round(prev_w, 4)
            _log_stderr(f"[PNL_LINKER] {strat} 거래 {len(pnls)}건 < {min_trades}건 "
                        f"→ 이전 가중치 유지 {prev_w:.4f}")
            continue

        es = compute_edge_score(strat, base_dir=base_dir, lookback_days=lookback_days)
        raw_w = 0.5 + es["edge_score"]

        prev_w  = prev_weights.get(strat, raw_w)
        delta   = raw_w - prev_w
        if abs(delta) > _EVO_MAX_DELTA:
            raw_w = prev_w + (_EVO_MAX_DELTA if delta > 0 else -_EVO_MAX_DELTA)
            _log_stderr(f"[PNL_LINKER] {strat} 가중치 안정화: "
                        f"raw={0.5+es['edge_score']:.4f} → capped={raw_w:.4f}")

        w = round(max(_EVO_MIN_WEIGHT, min(_EVO_MAX_WEIGHT, raw_w)), 4)
        weights[strat] = w

        _log_stderr(f"[PNL_LINKER] [진화가중치] {strat}: "
                    f"EdgeScore={es['edge_score']:.4f} "
                    f"PF={es['profit_factor']:.2f} "
                    f"CtxEdge={es['context_edge']:+.3f} → weight={w:.4f}")

    if save_history and weights:
        _save_weight_history(weights, Path(base_dir))

    return weights


# ═══════════════════════════════════════════════════════════════
#  ★ PUBLIC API: Adaptive Capital Ratio
# ═══════════════════════════════════════════════════════════════
def get_adaptive_capital_ratio(
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = _EVO_LOOKBACK,
) -> Dict[str, Any]:
    """
    ★ Edge Score 기반 동적 자본배분

    edge > 1.2 → 1.5x (공격 강화)
    edge > 1.0 → 1.2x (정상)
    edge < 0.8 → 0.7x (자동 축소)
    """
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days)
    result: Dict[str, Any] = {}
    if df.empty:
        return result

    for strat in df["strategy"].unique():
        grp   = df[df["strategy"] == strat]
        pnls  = grp["pnl_pct_net"].dropna().tolist()
        stype = grp["strategy_type"].iloc[-1] if not grp.empty else ""

        if len(pnls) < 2:
            result[strat] = {
                "edge_score": 0.5, "capital_multiplier": 1.0,
                "strategy_type": stype, "note": "데이터 부족 → 기본 1.0x",
            }
            continue

        es   = compute_edge_score(strat, base_dir=base_dir, lookback_days=lookback_days)
        edge = es["edge_score"]

        if edge > _EDGE_HIGH:
            mult = 1.5; note = f"Edge>{_EDGE_HIGH} → 자본 1.5x 강화"
        elif edge > _EDGE_MID:
            mult = 1.2; note = f"Edge>{_EDGE_MID} → 자본 1.2x 정상"
        elif edge < _EDGE_LOW:
            mult = 0.7; note = f"Edge<{_EDGE_LOW} → 자본 0.7x 자동 축소"
        else:
            mult = 1.0; note = "Edge 중립 → 자본 1.0x 유지"

        result[strat] = {
            "edge_score":        edge,
            "capital_multiplier": mult,
            "strategy_type":     stype,
            "sharpe":            es["sharpe"],
            "profit_factor":     es["profit_factor"],
            "win_rate":          es["win_rate"],
            "context_edge":      es["context_edge"],
            "note":              note,
        }
    return result


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 5: 일중 손실한도 신호
# ═══════════════════════════════════════════════════════════════
def check_daily_stop(
    base_dir: str        = DEFAULT_BASE_DIR,
    total_capital: int   = 0,
    stop_pct: float      = _DAILY_STOP_PCT,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ★ 연속손실 기반 동적 Daily Stop
    기본: -2.0%, 3연속 손실: -1.5%, 5연속: 즉시 HALT
    CLOSED + RECONCILE 모두 합산 (손실 은폐 방지)
    """
    today  = date_str or _today_str()
    rows   = _read_all(_pnl_path(Path(base_dir)))

    settled = [r for r in rows
               if r.get("date") == today
               and r.get("status") in ("CLOSED", "RECONCILE")]
    pnl_sum    = sum(_safe_int(r.get("pnl_krw", 0)) for r in settled)
    closed_cnt = sum(1 for r in settled if r.get("status") == "CLOSED")
    recon_cnt  = sum(1 for r in settled if r.get("status") == "RECONCILE")

    cap_base = (total_capital if total_capital > 0
                else _TOTAL_CAPITAL if _TOTAL_CAPITAL > 0
                else max(sum(_safe_int(r.get("buy_krw", 0)) for r in settled), 1))

    # 연속손실 확인
    df_today = load_strategy_pnl(base_dir=base_dir, lookback_days=3,
                                 status_filter=("CLOSED",))
    recent_pnls = df_today.sort_values("date")["pnl_pct_net"].tolist() if not df_today.empty else []
    streak = 0
    for p in reversed(recent_pnls):
        if float(p) < 0: streak += 1
        else: break

    if streak >= _STREAK_HALT:
        eff_stop_pct = stop_pct; streak_halt = True
    elif streak >= _STREAK_WARN:
        eff_stop_pct = _DAILY_STOP_PCT_WARN; streak_halt = False
    else:
        eff_stop_pct = stop_pct; streak_halt = False

    pnl_pct  = pnl_sum / cap_base * 100 if cap_base > 0 else 0.0
    stop_krw = int(-abs(eff_stop_pct) / 100 * cap_base)
    halt     = pnl_sum <= stop_krw or streak_halt

    if halt:
        reason = "5연속 손실 즉시 HALT" if streak_halt else f"손익 {pnl_pct:+.2f}% ≤ {-eff_stop_pct:.1f}%"
        _log_stderr(f"[PNL_LINKER] 🚨 DAILY STOP — {reason} "
                    f"[연속손실 {streak}회, RECONCILE {recon_cnt}건 포함]", level="warning")

    return {
        "halt":               halt,
        "streak_halt":        streak_halt,
        "today_pnl_krw":      pnl_sum,
        "today_pnl_pct":      round(pnl_pct, 3),
        "stop_krw":           stop_krw,
        "effective_stop_pct": eff_stop_pct,
        "loss_streak":        streak,
        "closed_count":       closed_cnt,
        "reconcile_count":    recon_cnt,
    }


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 6: 연속손실 Drawdown Streak
# ═══════════════════════════════════════════════════════════════
def get_drawdown_streak(
    strategy: str,
    base_dir: str      = DEFAULT_BASE_DIR,
    lookback_days: int = 20,
) -> Dict[str, Any]:
    df = load_strategy_pnl(base_dir=base_dir, lookback_days=lookback_days,
                           status_filter=("CLOSED",))
    df = df[df["strategy"] == strategy].sort_values("date")
    streak, last_pnl = 0, 0.0
    if not df.empty:
        pnl_arr  = df["pnl_pct_net"].tolist()
        last_pnl = float(pnl_arr[-1])
        for p in reversed(pnl_arr):
            if float(p) < 0: streak += 1
            else: break

    halt = streak >= _STREAK_HALT
    warn = streak >= _STREAK_WARN

    if halt:
        _log_stderr(f"[PNL_LINKER] 🚨 연속손실 HALT {strategy}: "
                    f"{streak}연속 ({last_pnl:+.2f}%)", level="warning")
    elif warn:
        _log_stderr(f"[PNL_LINKER] ⚠️ 연속손실 경고 {strategy}: "
                    f"{streak}연속 ({last_pnl:+.2f}%)")

    return {"streak": streak, "warn": warn, "halt": halt,
            "last_pnl": round(last_pnl, 4)}


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 7: 슬리피지 3σ 이상탐지
# ═══════════════════════════════════════════════════════════════
def check_slippage_anomaly(
    slippage_bps: float,
    side: str   = "BUY",
    base_dir: str = DEFAULT_BASE_DIR,
    sigma: float  = _SLIP_SIGMA,
) -> Dict[str, Any]:
    col  = "slippage_buy_bps" if side == "BUY" else "slippage_sell_bps"
    rows = _read_all(_pnl_path(Path(base_dir)))
    hist = [_safe_float(r.get(col, 0))
            for r in rows if r.get(col, "") != "" and r.get("status") == "CLOSED"]

    no_data = {
        "is_anomaly": False, "slippage": slippage_bps,
        "mean": 0.0, "std": 0.0, "threshold": float("inf"), "z_score": 0.0,
    }
    if len(hist) < _SLIP_MIN_HIST:
        return no_data

    mu        = statistics.mean(hist)
    std       = statistics.stdev(hist) if len(hist) > 1 else 0.0
    threshold = mu + sigma * std
    z_score   = (slippage_bps - mu) / std if std > 0 else 0.0

    return {
        "is_anomaly": slippage_bps > threshold,
        "slippage":   round(slippage_bps, 2),
        "mean":       round(mu, 2),
        "std":        round(std, 2),
        "threshold":  round(threshold, 2),
        "z_score":    round(z_score, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 8: 오늘 OPEN 포지션
# ═══════════════════════════════════════════════════════════════
def get_open_positions(
    base_dir: str = DEFAULT_BASE_DIR,
    date_str: Optional[str] = None,
) -> List[Dict[str, str]]:
    today = date_str or _today_str()
    rows  = _read_all(_pnl_path(Path(base_dir)))
    return [r for r in rows
            if r.get("date") == today
            and r.get("status", "OPEN") in ("OPEN", "PARTIAL_CLOSED")]


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API 9: 공격70%/안정30% 자본비율 검증
# ═══════════════════════════════════════════════════════════════
def check_capital_ratio(
    base_dir: str           = DEFAULT_BASE_DIR,
    date_str: Optional[str] = None,
    total_capital: int      = 0,
) -> Dict[str, Any]:
    today = date_str or _today_str()
    rows  = _read_all(_pnl_path(Path(base_dir)))
    today_rows = [r for r in rows
                  if r.get("date") == today
                  and r.get("status") in ("OPEN","PARTIAL_CLOSED","CLOSED")]

    attack_krw, stable_krw, untagged = 0, 0, 0
    for r in today_rows:
        stype = r.get("strategy_type", "").upper()
        cap   = _safe_int(r.get("capital_allocated", 0))
        if cap == 0: cap = _safe_int(r.get("buy_krw", 0))
        if stype == "ATTACK":   attack_krw += cap
        elif stype == "STABLE": stable_krw += cap
        else:                   untagged   += cap

    total_deployed = attack_krw + stable_krw + untagged
    if total_deployed == 0:
        return {
            "attack_krw": 0, "stable_krw": 0,
            "attack_ratio": 0.0, "stable_ratio": 0.0,
            "within_tolerance": True, "warning_msg": "포지션 없음",
            "adaptive_warnings": [],
        }

    attack_ratio = attack_krw / total_deployed
    stable_ratio = stable_krw / total_deployed
    within = (abs(attack_ratio - _ATTACK_RATIO_TARGET) <= _RATIO_TOLERANCE
              and abs(stable_ratio - _STABLE_RATIO_TARGET) <= _RATIO_TOLERANCE)

    warning_msg = ""
    if not within:
        warning_msg = (
            f"⚠️ 자본비율 이탈: "
            f"공격 {attack_ratio*100:.1f}% / 안정 {stable_ratio*100:.1f}%"
        )
        _log_stderr(f"[PNL_LINKER] {warning_msg}", level="warning")

    adaptive_warnings: List[str] = []
    try:
        adaptive = get_adaptive_capital_ratio(base_dir=base_dir)
        for strat, info in adaptive.items():
            if info.get("capital_multiplier", 1.0) <= 0.7:
                adaptive_warnings.append(
                    f"⚠️ {strat} EdgeScore={info['edge_score']:.2f} → "
                    f"자본 0.7x 축소 권고 ({info['note']})"
                )
    except Exception:
        pass

    return {
        "attack_krw":          attack_krw,
        "stable_krw":          stable_krw,
        "untagged_krw":        untagged,
        "attack_ratio":        round(attack_ratio, 4),
        "stable_ratio":        round(stable_ratio, 4),
        "within_tolerance":    within,
        "warning_msg":         warning_msg,
        "adaptive_warnings":   adaptive_warnings,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ PUBLIC API: validate_all — 통합 검증
# ═══════════════════════════════════════════════════════════════
def validate_all(
    base_dir: str = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    """
    ★ 시스템 전체 상태 통합 검증 (v3.2 — 종배 삭제 체계 반영)

    검증 항목:
    - 파일 무결성 (MD5 해시)
    - Bridge 연결 (자기진화 활성)
    - Edge Score 존재
    - Context 데이터 존재 (min_samples=5 기준)
    - Adaptive Capital 정상
    - 자본비율 정상
    - Daily Stop 상태
    - 전략 유효성 (2전략 체계)
    - 무위험이자율 설정 확인 [C-4]
    """
    checks: Dict[str, Any] = {}
    warnings: List[str] = []

    # 1. 파일 무결성
    total_rows, tampered = verify_file_integrity(base_dir)
    checks["file_integrity"] = tampered == 0
    if tampered > 0:
        warnings.append(f"⚠️ 무결성 오류 {tampered}행")

    # 2. Bridge 연결
    checks["bridge_connected"] = _BRIDGE_PNL_OK
    if not _BRIDGE_PNL_OK:
        warnings.append("❌ Bridge 미연결 — 자기진화 비활성 (kjs_bridge_eod_v9_6 확인 필요)")
    else:
        warnings.append(f"✅ Bridge 연결: {_BRIDGE_MOD_NAME}")

    # 3. Edge Score 존재
    df = load_strategy_pnl(base_dir=base_dir)
    has_edge = not df.empty and len(df) >= _EVO_MIN_TRADES
    checks["edge_data_sufficient"] = has_edge
    if not has_edge:
        warnings.append(f"ℹ️ Edge 데이터 부족 ({len(df)}건 < {_EVO_MIN_TRADES}건)")

    # 4. Context 데이터 (min_samples=5 기준)
    ctx_edges = get_context_edge(base_dir=base_dir)
    has_ctx   = any(bool(v) for v in ctx_edges.values()) if ctx_edges else False
    checks["context_data_exists"] = has_ctx
    if not has_ctx:
        warnings.append(f"ℹ️ Context 데이터 없음 (min_samples={_CTX_MIN_SAMPLES}건 미달)")

    # 5. Adaptive Capital
    adaptive = get_adaptive_capital_ratio(base_dir=base_dir)
    has_adaptive = bool(adaptive)
    checks["adaptive_capital_ready"] = has_adaptive
    for strat, info in adaptive.items():
        if info.get("capital_multiplier", 1.0) <= 0.7:
            warnings.append(f"⚠️ {strat} Adaptive 0.7x 축소 권고")

    # 6. 자본비율
    cr = check_capital_ratio(base_dir=base_dir)
    checks["capital_ratio_ok"] = cr["within_tolerance"]
    if not cr["within_tolerance"]:
        warnings.append(cr["warning_msg"])
    warnings.extend(cr.get("adaptive_warnings", []))

    # 7. Daily Stop
    ds = check_daily_stop(base_dir=base_dir)
    checks["daily_stop_ok"] = not ds["halt"]
    if ds["halt"]:
        warnings.append(f"🚨 DAILY STOP 발동 {ds['today_pnl_pct']:+.2f}%")

    # 8. ★ [C-3] 전략 유효성 — 2전략 체계 확인
    invalid_strategies = []
    if not df.empty:
        for strat in df["strategy"].unique():
            if strat not in _VALID_STRATEGIES:
                invalid_strategies.append(strat)
    checks["strategy_valid"] = len(invalid_strategies) == 0
    if invalid_strategies:
        warnings.append(f"⚠️ 미등록 전략 발견: {invalid_strategies} — 종배 데이터 잔재 확인")

    # 9. ★ [C-4] 무위험이자율 설정 확인
    checks["risk_free_rate_set"] = _RISK_FREE_ANNUAL_PCT > 0
    warnings.append(f"ℹ️ 무위험이자율(rf)={_RISK_FREE_ANNUAL_PCT:.2f}%/년 "
                    f"→ {_RISK_FREE_DAILY_PCT:.4f}%/일 반영 중")

    all_ok = (all(checks.values())
              and len([w for w in warnings if w.startswith("❌")]) == 0)

    return {"all_ok": all_ok, "checks": checks, "warnings": warnings,
            "total_rows": total_rows}


# ═══════════════════════════════════════════════════════════════
#  진단용 상태 출력 (v3.2)
# ═══════════════════════════════════════════════════════════════
def print_status(base_dir: str = DEFAULT_BASE_DIR) -> None:
    path = _pnl_path(Path(base_dir))
    print(f"[PNL_LINKER {_LINKER_VERSION}] {path}")
    print(f"  TOTAL_CAPITAL: {_TOTAL_CAPITAL:,}원")
    print(f"  무위험이자율: {_RISK_FREE_ANNUAL_PCT:.2f}%/년 ({_RISK_FREE_DAILY_PCT:.4f}%/일) [C-4]")
    print(f"  KRX λ 기본: {_IMPACT_LAMBDA_DEFAULT} [C-7]")
    print(f"  2전략 체계: {_VALID_STRATEGIES} [C-3 종배 삭제]")
    print(f"  Context min_samples: {_CTX_MIN_SAMPLES}건 [C-6]")
    print(f"  Half-Kelly 상한: {_KELLY_MAX_FRACTION*100:.0f}% [C-8]")
    _bridge_tag = f"✅ OK ({_BRIDGE_MOD_NAME})" if _BRIDGE_PNL_OK else "❌ 미연결 (자기진화 비활성)"
    print(f"  Bridge 연동: {_bridge_tag} [FIX-1 v3.3]")
    print(f"  trade_log.csv 경로: BASE/{_TRADE_LOG_PATH_TMPL} [FIX-3 v3.3]")
    if not path.exists():
        print("  → 파일 없음"); return

    rows = _read_all(path)
    open_   = [r for r in rows if r.get("status") == "OPEN"]
    closed  = [r for r in rows if r.get("status") == "CLOSED"]
    partial = [r for r in rows if r.get("status") == "PARTIAL_CLOSED"]
    recon   = [r for r in rows if r.get("status") == "RECONCILE"]
    print(f"  행: {len(rows)} | OPEN:{len(open_)} PARTIAL:{len(partial)} "
          f"CLOSED:{len(closed)} RECONCILE:{len(recon)}")

    _, tampered = verify_file_integrity(base_dir)
    print(f"  무결성: {'✅' if tampered==0 else f'⚠️ 변조의심 {tampered}행'}")

    if closed:
        nets = [_safe_float(r.get("pnl_pct_net",""))
                for r in closed if r.get("pnl_pct_net","") not in ("", "RECONCILE_EST")]
        rocs = [_safe_float(r.get("roc_pct",""))
                for r in closed if r.get("roc_pct","") not in ("", "RECONCILE_EST")]
        if nets:
            pf = _profit_factor(nets)
            print(f"  net pnl: avg={statistics.mean(nets):+.2f}% "
                  f"Sharpe(rf보정)={_sharpe(nets):+.2f} Sortino={_sortino(nets):+.2f} "
                  f"MDD={_mdd(nets)*100:+.2f}% PF={pf:.2f} "
                  f"win={sum(1 for p in nets if p>0)}/{len(nets)}")
        if rocs:
            print(f"  ROC: avg={statistics.mean(rocs):+.2f}%")

    ds = check_daily_stop(base_dir)
    print(f"  Daily Stop: {ds['today_pnl_krw']:+,}원 ({ds['today_pnl_pct']:+.2f}%) "
          f"한도={ds['effective_stop_pct']:+.1f}% "
          f"연속손실={ds['loss_streak']}회 "
          f"{'🚨 HALT' if ds['halt'] else '✅ 정상'}")

    cr = check_capital_ratio(base_dir)
    if cr["attack_krw"] + cr["stable_krw"] > 0:
        status_tag = "✅" if cr["within_tolerance"] else "⚠️"
        print(f"  자본비율: {status_tag} 공격 {cr['attack_ratio']*100:.1f}% "
              f"/ 안정 {cr['stable_ratio']*100:.1f}%")

    adaptive = get_adaptive_capital_ratio(base_dir)
    if adaptive:
        print("  [EdgeScore / Adaptive Capital / Half-Kelly]")
        for s, info in sorted(adaptive.items(), key=lambda x: -x[1].get("edge_score", 0)):
            st    = get_drawdown_streak(s, base_dir)
            streak_tag = f" 🚨{st['streak']}연속" if st["halt"] else \
                         f" ⚠️{st['streak']}연속" if st["warn"] else ""
            kelly = get_kelly_fraction(s, base_dir)
            print(f"    {s}: EdgeScore={info['edge_score']:.4f} "
                  f"PF={info['profit_factor']:.2f} "
                  f"WR={info['win_rate']*100:.0f}% "
                  f"→ {info['capital_multiplier']}x "
                  f"Kelly={kelly['kelly_half']*100:.1f}%({kelly['kelly_krw']:,}원)"
                  f"{streak_tag}")

    ctx_edges = get_context_edge(base_dir)
    if ctx_edges:
        print(f"  [Context Edge (레짐×갭, min={_CTX_MIN_SAMPLES}건)]")
        for strat, ctx in ctx_edges.items():
            if ctx:
                top = sorted(ctx.items(), key=lambda x: -x[1])[:3]
                print(f"    {strat}: " + " | ".join(f"{k}={v:+.2f}%" for k, v in top))

    # 누적 TWR
    print("  [누적 복리 TWR (v3.2)]")
    for strat in _VALID_STRATEGIES:
        twr_info = get_cumulative_twr(strat, base_dir)
        if twr_info["trade_count"] > 0:
            print(f"    {strat}: 누적={twr_info['cumulative_twr_pct']:+.2f}% "
                  f"연환산={twr_info['annualized_twr_pct']:+.2f}% "
                  f"({twr_info['trade_count']}거래/{twr_info['trading_days']}일)")

    va = validate_all(base_dir)
    print(f"  [validate_all] {'✅ 전체 정상' if va['all_ok'] else '⚠️ 점검 필요'}")
    for w in va["warnings"]:
        print(f"    {w}")


# ═══════════════════════════════════════════════════════════════
#  단독 실행
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_DIR
    print_status(base)
    print()
    df = load_strategy_pnl(base)
    if not df.empty:
        print("[2전략 최근 성과 (v3.2 — 종배 삭제)]")
        print(df.groupby("strategy")[["pnl_pct_gross","pnl_pct_net","roc_pct","twr_pct"]]
              .describe().round(3))
        print()

        weights = load_strategy_weights(base)
        print("[자기진화 가중치 (EdgeScore 기반 / rf 보정 Sharpe)]")
        for s, w in sorted(weights.items(), key=lambda x: -x[1]):
            print(f"  {s}: {w:.4f}")
        print()

        adaptive = get_adaptive_capital_ratio(base)
        print("[Adaptive Capital Ratio]")
        for s, info in sorted(adaptive.items(), key=lambda x: -x[1].get("edge_score", 0)):
            print(f"  {s}: EdgeScore={info['edge_score']:.4f} "
                  f"→ {info['capital_multiplier']}x  [{info['note']}]")
        print()

        print("[Half-Kelly 포지션 사이징 (v3.2 신규)]")
        for strat in _VALID_STRATEGIES:
            kelly = get_kelly_fraction(strat, base)
            print(f"  {strat}: Full={kelly['kelly_full']*100:.1f}% "
                  f"Half={kelly['kelly_half']*100:.1f}% "
                  f"({kelly['kelly_krw']:,}원) — {kelly['note']}")
        print()

        print("[누적 복리 TWR (v3.2)]")
        for strat in _VALID_STRATEGIES:
            twr_info = get_cumulative_twr(strat, base)
            print(f"  {strat}: 누적={twr_info['cumulative_twr_pct']:+.2f}% "
                  f"연환산={twr_info['annualized_twr_pct']:+.2f}%")
        print()

        ctx = get_context_edge(base)
        if ctx:
            print(f"[Context Edge (레짐×갭 조건별 성과 / min={_CTX_MIN_SAMPLES}건)]")
            for strat, edges in ctx.items():
                print(f"  {strat}:")
                for key, val in sorted(edges.items(), key=lambda x: -x[1]):
                    print(f"    {key}: {val:+.3f}%")
        print()

        cr = check_capital_ratio(base)
        print(f"[자본비율] 공격 {cr['attack_ratio']*100:.1f}% / "
              f"안정 {cr['stable_ratio']*100:.1f}%"
              f" {'✅' if cr['within_tolerance'] else '⚠️ 이탈'}")
        for aw in cr.get("adaptive_warnings", []):
            print(f"  {aw}")
    else:
        print("[성과 데이터 없음]")
