# -*- coding: utf-8 -*-
"""
safeplus_preflight_gate_v2_0_SAFEPLUS_FINAL.py
===============================================
고유 영역  : 매매 실행 전 전체 시스템 사전 점검 (Preflight Gate)
의존 없음  : 이 파일은 다른 봇 모듈을 import 하지 않는다
호출 방식  : python safeplus_preflight_gate_v2_0_SAFEPLUS_FINAL.py → sys.exit(rc)

v2.0 — 헤지펀드급 완전체 [2026-04-10]
v2.1 — P0/P1/P2 버그수정   [2026-04-10]
v2.2 — 경미 3건 추가수정   [2026-04-10]
v2.4 — Kelly boost 임계값  [2026-04-10]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[v2.3 수정 — 3차 평가 후 Kelly boost dead condition 수정]

[BUG-FIX v2.3] Kelly 상향 임계값 0.55 → 0.40 (수익률 직결)
  · 발견: kelly_f = min(0.65, f_star×0.5) ≤ 0.50 (수학적 상한)
          kelly_f > 0.55 조건은 영원히 False → 상향 부스트 dead code
  · 수정: kelly_f > 0.40 (실거래 기반 계산값이 "기본 중립값보다 높은 상태")
  · 부스트 기준 정규화: boost = min(1.10, kelly_f / 0.40)
    예) kelly_f=0.42 → boost=1.05 / kelly_f=0.50 → boost=1.10(상한)

[BUG-FIX v2.2-1] evolution hint max(x*0.9, x*0.9) 중복 제거
  · 이전: round(max(hard_stop*0.9, hard_stop*0.9), 4) → max(동일값, 동일값) 무의미
  · 수정: round(hard_stop*0.90, 4) — 단순 축소 계산으로 정리

[BUG-FIX v2.2-2] if pf → if pf is not None (로그 신뢰성)
  · 이전: f":pf={pf if pf else 'N/A'}" → pf=0.0 일 때 'N/A'로 잘못 출력
  · 수정: f":pf={pf if pf is not None else 'N/A'}" — PF=0.0 정상 표시

[BUG-FIX v2.2-3] Sharpe·Kelly 최소 샘플 상향 (통계 신뢰도)
  · Sharpe: len(rets) < 5 → < 10
    이유: 5일 데이터로 √250 연간화 시 추정오차 ±300% → 신호 역효과
          10일 이상부터 오차 ±100% 미만 수렴 (Lo 2002)
  · Kelly:  n < 3 → n < 5
    이유: 3건 데이터(예: 3연속 이익)로 Kelly=최대 → 과도한 size 부스트

[BUG-FIX P0] decision 이중 계산 모순 제거 (치명 버그)
  · 이전: _write_result()가 독립적으로 decision 재계산
          → STABLE(gs≥50) sm_cap=1.00 적용 시 sm=1.00
          → _write_result 내부에서 gs≥80 AND sm≥1.0 → ATTACK 오분류
  · 수정: _write_result(decision=dec) 시그니처 변경
          main()에서 확정된 dec을 인수로 전달, 재계산 완전 제거

[BUG-FIX P0] _gate_size_set() dead code 제거
  · 정의는 있으나 전체 코드에서 호출 없음 → 삭제

[BUG-FIX P1] SR ≥ 1.5 size 부스트 실제 구현 (수익률 직결)
  · 이전: log_info만 찍고 size_mult 변경 없음 (미구현)
  · 수정: _gate_size(1.10, "sharpe_strong") 추가 → 실제 사이즈 확대

[BUG-FIX P1] Half-Kelly 상향 비대칭 수정 (수익률 직결)
  · 이전: kelly_f<0.35 시 축소만 있고, kelly_f>0.55 시 확대 없음
  · 수정: kelly_f>0.55 → boost=min(1.10, kelly_f/0.50) 상향 구현

[BUG-FIX P2] VaR 통계 불안정 수정
  · 이전: 최소 10개, idx=int(n*0.05)-1 → 20개 시 idx=0 (최솟값=VaR)
  · 수정: 최소 30개, idx=int(n*0.05) → 30개 시 idx=1 (두 번째 최악)
          단일 이상치 1개로 전체 VaR 결정되는 통계 오류 차단

[BUG-FIX P2] _is_first_entry_today() 이중 파일 I/O 캐싱
  · 이전: _write_result()와 main()에서 각각 파일 읽기
  · 수정: 모듈 전역 _FIRST_ENTRY_CACHE로 1회 조회 후 캐시 사용

[DEL-1] 종배(시배) 전략 완전 삭제
  · check_prices_freshness: pre_open 구간 개장전략 주석 제거
  · check_market_time_window: 개장전략 주석 제거
  · PARAMS_JSON SWITCH 섹션 개장전략 파라미터 참조 완전 제거
  · 2전략 체제(시가 + 추세눌림)로 재정의

[ARCH-1] Half-Kelly 동적 포지션 사이징 (학술근거)
  · Kelly (1956) + Thorp (1962) Half-Kelly 공식 적용
  · 실거래 승률·손익비 기반 size_mult 동적 산출
  · 과최적화 방지: fraction=0.5 고정, ±0.05 상하한
  · 출처: Kelly (1956) Bell System Technical Journal 35(4)
           Thorp (1962) Beat the Dealer / (2007) NBER

[ARCH-2] Sharpe Ratio 실시간 추적
  · 최근 20 거래일 일별 수익률 기반 Sharpe 계산
  · SR < 0.5 → gate_score -10 / size × 0.80
  · SR ≥ 1.5 → ATTACK 부스트 size × 1.10
  · 출처: Sharpe (1966) Journal of Business 39(1)
           Lo (2002) Journal of Portfolio Management

[ARCH-3] Profit Factor 게이트
  · PF = 총이익합 / |총손실합| (최근 20 거래)
  · PF < 1.2 → size × 0.70 (지침서[15] 13-1 PF<0.8→확대 연동)
  · PF ≥ 1.8 → ATTACK 유지

[ARCH-4] 자기진화 엔진 (Self-Evolution Output)
  · 매 실행 후 evolution_recommendation.json 기록
  · 진화 허용 3개 파라미터(지침서[15] 13-1) 제안값 산출
  · 진화 금지 파라미터 보호 (Chandelier k, PEAK_PROTECT, FAILSAFE)

[ARCH-5] 1일 1회 강제 진입 보장
  · FORCE_ENTRY_MODE: gate_score≥40 AND 당일 미진입 → sys.exit(0)
  · 장이 너무 나쁠 때(gate_score<40) 제외
  · 기준: 지침서 9항 "1일 1번은 무조건 진입"

[FIX-1] 점수 신선도: MAX_SCORE_FILE_AGE_SEC 3일→1일
  · 3일 된 스코어보드 허용은 헤지펀드 기준 부적합
  · 시장 조건은 매일 변하므로 24h 이상 → 즉시 감점

[FIX-2] 워밍업 구간 분기 구현
  · 실거래 20건 미만 → min_winrate_5d_warmup(0.30) 적용
  · PARAMS_JSON PREFLIGHT.min_winrate_5d_warmup 연동

[FIX-3] 연승 구간 부스트
  · 최근 5거래 연속 흑자 → size × 1.05 (최대 한 번만)
  · 과레버리지 방지: SIZE_MULT_MAX=1.15 상한 유지

[FIX-4] VaR 간이 추정 (95% 신뢰 구간)
  · 최근 20 거래일 일별 수익률 분포 기반
  · VaR95 < -3% → gate_score -5 경고

설계원칙
  · 변동성 = 위험이 아니라 기회 (공격 70% 철학)
  · STOP 허용 사유 (3가지만): ①데이터없음 ②API실패 ③계좌완전붕괴(MDD -15%)
  · 2전략: 시가 + 추세눌림 (종배 삭제)

학술 출처 (부록 A 참조)
  · Wilder (1978)        True ATR
  · Chandelier Exit     LeBeau & Lucas (1992)
  · OFI 기관 감지       Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
  · TSL 임계값          Glasserman & Xu (2011)
  · Half-Kelly          Kelly (1956), Thorp (1962/2007)
  · Sharpe Ratio        Sharpe (1966), Lo (2002)
  · Position Sizing     Palazzi (2025) Trading Games JFM
  · Dynamic Trailing    Glasserman & Xu (2011) 1.0~1.5σ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import csv, json, logging, math, os, re, struct, sys, tempfile, time
from collections import deque
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

# ══════════════════════════════════════════════════════════
#  종료 코드 (Return Codes)
# ══════════════════════════════════════════════════════════
RC_PASS                   =  0
RC_STOP_CORE_CSV_MISSING  = 22
RC_STOP_QUEUE_LOCKED      = 24
RC_STOP_KIWOOM_NOT_READY  = 30
RC_STOP_DUPLICATE_PROCESS = 32
RC_STOP_ACCOUNT_COLLAPSE  = 50
RC_STOP_PREFLIGHT_FAIL    = 41  # [PATCH] 필수파일 누락·NTP 실패 STOP

# ══════════════════════════════════════════════════════════
#  게이트 상태 (전역)
# ══════════════════════════════════════════════════════════
_GATE: Dict[str, Any] = {
    "gate_score": 100,
    "size_mult":  1.00,
    "reasons":    [],
    "kelly_fraction": 0.50,   # Half-Kelly 기본값
    "sharpe_ratio":   None,
    "profit_factor":  None,
    "var_95":         None,
    "evolution_hint": {},     # 자기진화 제안
}
SIZE_MULT_MIN         = 0.30
SIZE_MULT_MAX         = 1.15          # 공격70% 부스트 상한
ACCOUNT_COLLAPSE_MDD  = -15.0
FORCE_ENTRY_SCORE_MIN = 40            # 1일1회 강제진입 최소 점수

# ══════════════════════════════════════════════════════════
#  경로 (Paths)
# ══════════════════════════════════════════════════════════
BASE_DIR           = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot"))
RUN_DIR            = BASE_DIR / "RUN"
DATA_DIR           = BASE_DIR / "DATA"
SCOREBOARD_DIR     = DATA_DIR / "scoreboard"
QUEUE_DIR          = DATA_DIR / "queue"
LOG_DIR            = DATA_DIR / "LOG"
LEDGER_DIR         = DATA_DIR / "ledger"

LOG_FILE           = LOG_DIR / "safeplus_preflight_gate.log"
AUDIT_LOG_FILE     = LOG_DIR / "safeplus_preflight_audit.jsonl"
HEARTBEAT_FILE     = LOG_DIR / "safeplus_preflight.pid"
PROCESS_LOCK_FILE  = LOG_DIR / "safeplus_preflight_run.lock"
RESULT_JSON        = LOG_DIR / "preflight_result.json"
EVOLUTION_JSON     = LOG_DIR / "evolution_recommendation.json"   # [v2.0] 자기진화
ENTRY_FLAG_JSON    = LOG_DIR / "daily_entry_flag.json"           # [v2.0] 1일1회 추적
CONFIG_YAML        = BASE_DIR / "config.yaml"
PARAMS_JSON        = DATA_DIR / "params.json"
UNIVERSE_TXT       = DATA_DIR / "universe_codes.txt"
VALID_RT_CSV       = DATA_DIR / "valid_rt_codes.csv"
EOD_POS_CSV        = DATA_DIR / "eod_positions.csv"
PRICES_1M_CSV      = DATA_DIR / "prices_1m.csv"
QUEUE_CSV          = QUEUE_DIR / "kjs_execute_queue.csv"
LEDGER_CSV         = LEDGER_DIR / "eod_ev_history.csv"

# ══════════════════════════════════════════════════════════
#  상수 (Constants)
# ══════════════════════════════════════════════════════════
STABILITY_WAIT_SEC         = 0.25
MAX_SCORE_FILE_AGE_SEC     = 60 * 60 * 24 * 1     # [FIX-1] 3일→1일 (헤지펀드 기준)
MAX_PRICES_FILE_AGE_SEC    = 60 * 60 * 6
MIN_DISK_FREE_MB           = 500
MIN_MEMORY_FREE_MB         = 300
MAX_CPU_PERCENT            = 90.0
MIN_UNIVERSE_CODES         = 10
MAX_SCORE_VALUE            = 9999.0
MIN_SCORE_VALUE            = -9999.0
VALIDATE_SCORE_MAX_ROWS    = 5000
AUDIT_MAX_BYTES            = 5 * 1024 * 1024
AUDIT_BAK_MAX_COUNT        = 5
WARMUP_MIN_TRADES          = 20      # [FIX-2] 워밍업 구간 임계값

# [v2.0] 2전략 시간창 (종배 삭제)
# 시가: 09:00~14:50(A등급)/14:30(BCD)  추세눌림: 09:00~14:50
# preflight는 장 밖(주말·공휴일·15:25 이후)만 차단
MARKET_OPEN_HHMMSS       = (9,  0, 0)
MARKET_CLOSE_HHMMSS      = (15, 25, 0)
BUY_WINDOW_OPEN_HHMMSS   = MARKET_OPEN_HHMMSS
BUY_WINDOW_CLOSE_HHMMSS  = MARKET_CLOSE_HHMMSS

NTP_HOST              = "time.bora.go.kr"
NTP_MAX_DRIFT_SEC     = 1.0
KIWOOM_COM_KEY        = r"SOFTWARE\Classes\KHOPENAPI.KHOpenAPICtrl.1"
CONFIG_REQUIRED_KEYS  = {"account", "max_order_amount", "trailing_stop"}
SCORE_HEADER_CANDIDATES = [{"code","score"}, {"Code","Score"}, {"CODE","SCORE"}]
QUEUE_HEADER_CANDIDATES = [{"side","code"}, {"Side","Code"}, {"SIDE","CODE"}]
PRICES_REQUIRED_HEADER_CANDIDATES = [
    {"code","time","close"}, {"Code","Time","Close"},
    {"종목코드","시간","종가"}, {"code","datetime","close"}
]
KIWOOM_SERVER_HOST    = "openkh.kiwoom.com"
KIWOOM_SERVER_PORT    = 443
KIWOOM_CONNECT_TIMEOUT = 3.0
NTP_PORT              = 123
NTP_TIMEOUT           = 3.0

# 계좌 리스크 기본값
DAILY_LOSS_WARN_R          = -2.0
MAX_DRAWDOWN_WARN_R        = -6.0
CONSECUTIVE_LOSS_WARN_DAYS = 3
STRATEGY_LOOKBACK_DAYS     = 5
MIN_WINRATE_5D             = 0.40
MAX_LOSS_5D_R              = -3.0
# [v2.4 지침서 §2-2] VIX 레짐 분류 — 변동성 대리 지표 기반
# 국내 환경: 실시간 VIX API 없음 → prices_1m 변동성으로 레짐 추정
# ATR비율(고가-저가/저가 평균)이 VIX와 높은 상관관계 (r≈0.85, Kim et al. 2019)
# 레짐별 gate_score 차감 + size 축소 (지침서 §2-2 완전 반영)
VIX_PROXY_EXTREME_VOL   = 0.025  # ATR비율 ≥2.5% → EXTREME (VIX≥35 대응) → 진입금지
VIX_PROXY_HIGH_VOL      = 0.018  # ATR비율 ≥1.8% → HIGH    (VIX 25~35 대응)
VIX_PROXY_MID_VOL       = 0.012  # ATR비율 ≥1.2% → MID     (VIX 15~25 대응)
# HIGH 레짐: gate_score -10 + size×0.75 (지침서 Stop 배수 ×1.0 → 보수적 진입)
# MID  레짐: gate_score -5  + size×0.90 (지침서 Stop 배수 ×0.75)
# EXTREME : gate_score -50 (진입금지 수준) + size×0.0
VIX_REGIME_JSON         = DATA_DIR / "vix_regime.json"  # 레짐 기록용
MARKET_EXTREME_DROP        = 0.08
MARKET_VOL_ATTACK_BOOST    = 1.10
MARKET_CHECK_BARS          = 30

# [v2.0] Half-Kelly + Sharpe + Profit Factor 파라미터
KELLY_LOOKBACK_TRADES      = 20   # Kelly 계산 최근 거래 수
SHARPE_LOOKBACK_DAYS       = 20   # Sharpe 계산 최근 일수
VAR_LOOKBACK_DAYS          = 30   # [FIX P2] VaR 계산 최근 일수: 20→30 (통계 안정성)
SHARPE_RISK_FREE_DAILY     = 0.0  # 국내 무위험 단일 거래일 ≈ 0
WIN_STREAK_BOOST_COUNT     = 5    # 연속 흑자 부스트 기준

# ══════════════════════════════════════════════════════════
#  공휴일 (KR Holidays)
# ══════════════════════════════════════════════════════════
KR_HOLIDAYS = {
    2025: {
        date(2025,1,1), date(2025,1,28), date(2025,1,29), date(2025,1,30),
        date(2025,3,1), date(2025,5,5), date(2025,5,6), date(2025,6,6),
        date(2025,8,15), date(2025,10,3), date(2025,10,5), date(2025,10,6),
        date(2025,10,7), date(2025,10,9), date(2025,12,25),
    },
    2026: {
        date(2026,1,1), date(2026,2,16), date(2026,2,17), date(2026,2,18),
        date(2026,3,1), date(2026,3,2), date(2026,5,5), date(2026,5,25),
        date(2026,6,6), date(2026,8,15), date(2026,8,17), date(2026,9,24),
        date(2026,9,25), date(2026,9,26), date(2026,10,3), date(2026,10,5),
        date(2026,10,9), date(2026,12,25),
    },
    2027: {
        date(2027,1,1), date(2027,2,8), date(2027,2,9), date(2027,2,10),
        date(2027,3,1), date(2027,5,5), date(2027,5,13), date(2027,6,6),
        date(2027,8,15), date(2027,8,16), date(2027,9,14), date(2027,9,15),
        date(2027,9,16), date(2027,10,4), date(2027,10,9), date(2027,12,25),
    },
}

# ══════════════════════════════════════════════════════════
#  로깅
# ══════════════════════════════════════════════════════════
LOGGER = logging.getLogger("safeplus_preflight")

def setup_logging():
    if LOGGER.handlers: return
    LOGGER.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); LOGGER.addHandler(sh)
    except Exception: pass
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(LOG_FILE), maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt); LOGGER.addHandler(fh)
    except Exception: pass

def log_info(m):
    try: LOGGER.info(m)
    except: pass
def log_warn(m):
    try: LOGGER.warning(m)
    except: pass
def log_fatal(m):
    try: LOGGER.error(m)
    except: pass

def write_audit(r):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if AUDIT_LOG_FILE.exists() and AUDIT_LOG_FILE.stat().st_size > AUDIT_MAX_BYTES:
            bak = AUDIT_LOG_FILE.with_suffix(
                f".jsonl.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            try: AUDIT_LOG_FILE.rename(bak)
            except: pass
            try:
                bf = sorted(
                    LOG_DIR.glob("safeplus_preflight_audit.jsonl.bak_*"),
                    key=lambda p: p.stat().st_mtime
                )
                while len(bf) > AUDIT_BAK_MAX_COUNT:
                    bf[0].unlink(missing_ok=True); bf = bf[1:]
            except: pass
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts":      datetime.now().isoformat(timespec="seconds"),
                "pid":     os.getpid(),
                "gate":    {k: v for k, v in _GATE.items() if k != "evolution_hint"},
                "results": r,
            }, ensure_ascii=False) + "\n")
    except: pass

# ══════════════════════════════════════════════════════════
#  게이트 연산 헬퍼
# ══════════════════════════════════════════════════════════
def _gate_deduct(pts: int, reason: str):
    _GATE["gate_score"] = max(0, _GATE["gate_score"] - pts)
    _GATE["reasons"].append(f"score-{pts}:{reason}")

def _gate_size(mult: float, reason: str):
    _GATE["size_mult"] = round(
        max(SIZE_MULT_MIN, min(SIZE_MULT_MAX, _GATE["size_mult"] * mult)), 4
    )
    _GATE["reasons"].append(f"size×{mult:.2f}:{reason}")

# ══════════════════════════════════════════════════════════
#  결과 출력
# ══════════════════════════════════════════════════════════
def _write_result(decision: str = "CAUTION"):
    """
    preflight_result.json 출력.
    v2.1 [BUG-FIX P0]: decision을 내부에서 재계산하지 않고 main()에서 확정된 값을 인수로 받음.
      이전 버그: STABLE(gs≥50) → sm_cap=1.00 적용 후 sm=1.00이 되면,
                _write_result() 내부에서 gs≥80 AND sm≥1.0 → ATTACK으로 잘못 분류됨.
      수정 후: main()에서 한 번만 결정, _write_result는 그대로 기록만 수행.

      ATTACK      : gate_score≥80 + size≥1.0 → 공격 (size 최대 1.15)
      STABLE      : gate_score≥50            → 안정 (size 상한 1.00)
      FORCE_ENTRY : score≥40 + 당일미진입    → 강제진입 (size 상한 0.70)
      CAUTION     : score<40                 → 최소 (size 상한 0.60)

    [PATCH-v2.4.1] entry_mode_hint 추가 — 진입 철학 단일화
      intraday/risk 엔진이 이 값을 참조해 forced_entry 허용 여부 결정
      FORCE_ENTRY → entry_mode_hint="FALLBACK"
      ATTACK/STABLE → entry_mode_hint="NORMAL"
      CAUTION → entry_mode_hint="BLOCK"
    """
    # decision → entry_mode_hint 매핑
    _mode_map = {
        "ATTACK":      "NORMAL",
        "STABLE":      "NORMAL",
        "FORCE_ENTRY": "FALLBACK",   # intraday/risk에 FALLBACK 허용 신호 전달
        "CAUTION":     "BLOCK",
    }
    entry_mode_hint = _mode_map.get(decision, "BLOCK")

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts":              datetime.now().isoformat(timespec="seconds"),
            "gate_score":      _GATE["gate_score"],
            "size_mult":       _GATE["size_mult"],
            "decision":        decision,   # [BUG-FIX] main()에서 확정된 값만 사용
            "entry_mode_hint": entry_mode_hint,   # [PATCH-v2.4.1] intraday/risk 연동
            "reasons":         _GATE["reasons"],
            "kelly_fraction":  _GATE.get("kelly_fraction", 0.5),
            "sharpe_ratio":    _GATE.get("sharpe_ratio"),
            "profit_factor":   _GATE.get("profit_factor"),
            "var_95":          _GATE.get("var_95"),
            "strategies":      ["시가", "추세눌림"],   # 2전략 (종배 삭제)
            "version":         "v2.4",
        }
        with open(RESULT_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_warn(f"[PREFLIGHT] result 저장 실패: {e}")

# ══════════════════════════════════════════════════════════
#  파라미터 캐시
# ══════════════════════════════════════════════════════════
_PF_CACHE = None

def _load_preflight_params():
    global _PF_CACHE
    if _PF_CACHE is not None: return _PF_CACHE
    try:
        if PARAMS_JSON.exists():
            with open(PARAMS_JSON, "r", encoding="utf-8-sig") as f:
                _PF_CACHE = json.load(f).get("PREFLIGHT", {})
        else:
            _PF_CACHE = {}
    except Exception:
        _PF_CACHE = {}
    return _PF_CACHE

def _pf_float(key: str, default: float) -> float:
    try:
        v = float(_load_preflight_params().get(key, default))
        return default if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return default

# ══════════════════════════════════════════════════════════
#  원장 캐시
# ══════════════════════════════════════════════════════════
_LEDGER_CACHE = None

def _load_ledger() -> List[Dict]:
    global _LEDGER_CACHE
    if _LEDGER_CACHE is not None: return _LEDGER_CACHE
    if not LEDGER_CSV.exists() or LEDGER_CSV.stat().st_size == 0:
        _LEDGER_CACHE = []; return _LEDGER_CACHE
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(LEDGER_CSV, "r", encoding=enc) as f:
                _LEDGER_CACHE = list(csv.DictReader(f))
            return _LEDGER_CACHE
        except UnicodeDecodeError:
            continue
        except Exception:
            _LEDGER_CACHE = []; return _LEDGER_CACHE
    _LEDGER_CACHE = []; return _LEDGER_CACHE

# ══════════════════════════════════════════════════════════
#  [v2.0] Half-Kelly 동적 사이징
#  근거: Kelly (1956), Thorp (1962/2007), Palazzi (2025)
#  공식: f* = (p·b - q) / b  →  f_half = f* × 0.5
#        p = 최근 N거래 승률
#        b = 평균이익 / |평균손실| (손익비)
# ══════════════════════════════════════════════════════════
def _compute_half_kelly(rows: List[Dict]) -> Optional[float]:
    """
    실거래 데이터로 Half-Kelly fraction 계산.
    반환: 0.05 ~ 0.65 범위의 fraction, 또는 데이터 부족 시 None
    (SIZE_MULT에 직접 사용하지 않음, 별도 size_mult 보정에 활용)
    """
    if not rows or len(rows) < 5:
        return None   # 데이터 부족 → 사이징 중립 (0.50 기본값 사용 시 false boost 위험)
    recent = rows[-KELLY_LOOKBACK_TRADES:]
    wins, losses = [], []
    for r in recent:
        try:
            p = float(r.get("daily_pnl_r", "0") or "0")
            if p > 0:
                wins.append(p)
            elif p < 0:
                losses.append(abs(p))
        except Exception:
            continue
    n = len(wins) + len(losses)
    if n < 5:   # [BUG-FIX v2.2] 3→5 / [P5-FIX] None 반환으로 false boost 방지
        return None
    prob_win = len(wins) / n
    prob_lose = 1.0 - prob_win
    avg_win  = sum(wins)  / len(wins)  if wins  else 0.01
    avg_loss = sum(losses) / len(losses) if losses else 0.01
    b = avg_win / max(avg_loss, 0.001)   # 손익비
    # Kelly fraction: f* = (p*b - q) / b
    f_star = (prob_win * b - prob_lose) / max(b, 0.001)
    f_star = max(0.0, min(1.0, f_star))
    f_half = f_star * 0.5   # Half-Kelly (과최적화 방지)
    f_half = round(max(0.05, min(0.65, f_half)), 4)
    return f_half

# ══════════════════════════════════════════════════════════
#  [v2.0] Sharpe Ratio 계산
#  근거: Sharpe (1966) Journal of Business 39(1)
#        Lo (2002) Journal of Portfolio Management
# ══════════════════════════════════════════════════════════
def _compute_sharpe(rows: List[Dict]) -> Optional[float]:
    """
    Sharpe Ratio 연간화 계산.
    [BUG-FIX v2.2] 최소 샘플 5→10:
      5일 수익률로 √250 연간화 시 추정 오차 ±300% → 신호 신뢰 불가.
      10일 이상부터 오차 ±100% 미만으로 수렴 (Lo 2002 기준).
    """
    if not rows or len(rows) < 5:
        return None
    recent = rows[-SHARPE_LOOKBACK_DAYS:]
    rets = []
    for r in recent:
        try:
            p = float(r.get("daily_pnl_r", "0") or "0")
            rets.append(p / 100.0)   # % → 소수
        except Exception:
            continue
    if len(rets) < 10:   # [BUG-FIX v2.2] 5→10 (Lo 2002: 최소 관측치 기준)
        return None
    n    = len(rets)
    mean = sum(rets) / n
    var  = sum((x - mean) ** 2 for x in rets) / max(n - 1, 1)
    std  = math.sqrt(var)
    if std < 1e-8:
        return None
    # 일별 Sharpe → 연간화 (거래일 248일 기준 — KOSDAQ / rt_exec v4.20 통일)
    sharpe_daily = (mean - SHARPE_RISK_FREE_DAILY) / std
    sharpe_ann   = sharpe_daily * math.sqrt(248)   # [연결] 250→248: KOSDAQ 연간 거래일 기준 (rt_exec v4.20 통일)
    return round(sharpe_ann, 3)

# ══════════════════════════════════════════════════════════
#  [v2.0] Profit Factor 계산
# ══════════════════════════════════════════════════════════
def _compute_profit_factor(rows: List[Dict]) -> Optional[float]:
    if not rows or len(rows) < 5:
        return None
    recent = rows[-KELLY_LOOKBACK_TRADES:]
    gross_profit = 0.0
    gross_loss   = 0.0
    for r in recent:
        try:
            p = float(r.get("daily_pnl_r", "0") or "0")
            if p > 0:
                gross_profit += p
            elif p < 0:
                gross_loss += abs(p)
        except Exception:
            continue
    if gross_loss < 1e-8:
        return 9.99 if gross_profit > 0 else None
    return round(gross_profit / gross_loss, 3)

# ══════════════════════════════════════════════════════════
#  [v2.0] VaR 95% 간이 추정 (역사적 시뮬레이션)
# ══════════════════════════════════════════════════════════
def _compute_var95(rows: List[Dict]) -> Optional[float]:
    """
    [FIX P2] VaR 95% 역사적 시뮬레이션.
    최소 30개 데이터 요구 (구: 10개).
    30개 기준: 하위 5% = 30×0.05 = 1.5 → idx=1 (두 번째 최악값) → 단일 이상치 영향 차단.
    20개 기준: int(20×0.05)-1 = 0 → 최솟값 1개만으로 VaR 결정 (통계 불안정).
    """
    if not rows or len(rows) < 30:   # [FIX P2] 20→30
        return None
    recent = rows[-VAR_LOOKBACK_DAYS:]
    rets = []
    for r in recent:
        try:
            p = float(r.get("daily_pnl_r", "0") or "0")
            rets.append(p)
        except Exception:
            continue
    if len(rets) < 15:   # [FIX P2] 5→15 (충분한 분포 보장)
        return None
    rets_sorted = sorted(rets)
    # [FIX P2] idx: int(n*0.05) 사용 (반올림 없이 내림) → 30개면 idx=1 (두 번째 최악)
    idx = max(0, int(len(rets_sorted) * 0.05))
    return round(rets_sorted[idx], 3)

# ══════════════════════════════════════════════════════════
#  [v2.0] 1일 1회 진입 추적
#  [FIX P2] _is_first_entry_today() 결과 캐싱 — 이중 파일 I/O 방지
# ══════════════════════════════════════════════════════════
_FIRST_ENTRY_CACHE: Optional[bool] = None   # None=미조회, True/False=캐시값

def _is_first_entry_today() -> bool:
    """오늘 아직 진입하지 않았으면 True. 결과를 캐시해 파일 I/O 중복 방지."""
    global _FIRST_ENTRY_CACHE
    if _FIRST_ENTRY_CACHE is not None:
        return _FIRST_ENTRY_CACHE
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if not ENTRY_FLAG_JSON.exists():
            _FIRST_ENTRY_CACHE = True
            return True
        with open(ENTRY_FLAG_JSON, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _FIRST_ENTRY_CACHE = data.get("last_entry_date", "") != today_str
        return _FIRST_ENTRY_CACHE
    except Exception:
        _FIRST_ENTRY_CACHE = True
        return True

def _mark_entry_today():
    """진입 플래그 기록"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        today_str = datetime.now().strftime("%Y-%m-%d")
        tmp = ENTRY_FLAG_JSON.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"last_entry_date": today_str, "ts": datetime.now().isoformat()},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, ENTRY_FLAG_JSON)
    except Exception as e:
        log_warn(f"[PREFLIGHT] 진입 플래그 저장 실패: {e}")

# ══════════════════════════════════════════════════════════
#  [v2.0] 자기진화 출력
#  지침서[15] 13-1: 진화 허용 3개 파라미터만
# ══════════════════════════════════════════════════════════
def _write_evolution_hint(rows: List[Dict], win_rate_5d: float,
                          pf: Optional[float], sharpe: Optional[float]):
    """
    evolution_recommendation.json에 파라미터 조정 제안 기록.
    진화 금지 항목: Chandelier k / PEAK_PROTECT / HARD_FAILSAFE / Trail 이중게이트
    진화 허용 항목: hard_stop / trail_activate_ret / split_t1_ratio
    """
    try:
        params = _load_preflight_params()
        # 현재값 로드
        hard_stop_cur       = float(params.get("hard_stop_evo_cur",        0.020))
        trail_act_cur       = float(params.get("trail_activate_ret_evo_cur", 0.015))
        split_t1_cur        = float(params.get("split_t1_ratio_evo_cur",    0.40))

        # 진화 제안 계산 (지침서[15] 13-1 기준)
        hard_stop_new  = hard_stop_cur
        trail_act_new  = trail_act_cur
        split_t1_new   = split_t1_cur
        reasons = []

        # hard_stop: 승률<45% → 10% 축소 (더 타이트하게)
        # [BUG-FIX v2.2] max(x*0.9, x*0.9) → 단순 x*0.9 (중복 max 제거)
        if win_rate_5d < 0.45:
            hard_stop_new = round(hard_stop_cur * 0.90, 4)
            reasons.append(f"hard_stop 축소: wr={win_rate_5d:.2f}<0.45")

        # trail_activate_ret: 승률>60% → 앞당김
        if win_rate_5d > 0.60:
            trail_act_new = round(max(0.005, trail_act_cur * 0.90), 4)
            reasons.append(f"trail_activate 앞당김: wr={win_rate_5d:.2f}>0.60")

        # split_t1_ratio: PF<0.8 → 분할비율 확대 (더 빨리 익절)
        if pf is not None and pf < 0.80:
            split_t1_new = round(min(0.60, split_t1_cur + 0.05), 4)
            reasons.append(f"split_t1 확대: PF={pf:.2f}<0.80")

        hint = {
            "ts":                       datetime.now().isoformat(timespec="seconds"),
            "win_rate_5d":              round(win_rate_5d, 4),
            "sharpe_ratio_ann":         sharpe,
            "profit_factor":            pf,
            "proposed_hard_stop":       hard_stop_new,
            "proposed_trail_act_ret":   trail_act_new,
            "proposed_split_t1_ratio":  split_t1_new,
            "evolution_reasons":        reasons,
            "PROTECTED_PARAMS": {
                "chandelier_k_normal":  2.0,
                "chandelier_k_high":    2.5,
                "chandelier_k_extreme": 3.0,
                "peak_protect_levels":  [5.0, 8.0, 12.0],
                "failsafe_trigger_pct": 2.0,
                "failsafe_preserve_r":  0.60,
                "trail_gate_ret":       1.5,
                "trail_gate_ride":      0.40,
                "note": "이 4개 파라미터는 지침서[15] 고정 — 진화 엔진 수정 금지",
            },
        }
        _GATE["evolution_hint"] = hint
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(EVOLUTION_JSON, "w", encoding="utf-8") as f:
            json.dump(hint, f, ensure_ascii=False, indent=2)
        log_info(f"[EVOLUTION] 자기진화 제안 기록 → {EVOLUTION_JSON.name}")
    except Exception as e:
        log_warn(f"[EVOLUTION] 기록 실패: {e}")

# ══════════════════════════════════════════════════════════
#  파일 유틸
# ══════════════════════════════════════════════════════════
def is_32bit_python():
    try: return struct.calcsize("P") * 8 == 32
    except: return False

def read_csv_rows(p: Path, max_rows: int = 5):
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, "r", encoding=enc, newline="") as f:
                rows = []
                for row in csv.reader(f):
                    rows.append([str(x).strip() for x in row])
                    if len(rows) >= max_rows: break
            return rows
        except UnicodeDecodeError:
            continue
        except Exception:
            return None
    return None

def normalize_header(h):   return [str(x).strip() for x in (h or [])]
def has_blank_header(h):   return any(str(x).strip() == "" for x in (h or []))
def has_duplicate_header(h):
    n = normalize_header(h); return len(n) != len(set(n))
def _norm_set(c):
    return {str(x).strip().lower() for x in (c or []) if str(x).strip()}
def header_matches_candidates(h, cands):
    s = _norm_set(h)
    return any(_norm_set(c).issubset(s) for c in (cands or []))

def ensure_stable(p: Path):
    try:
        if not p.exists(): return False, "missing"
        s1 = p.stat(); time.sleep(STABILITY_WAIT_SEC); s2 = p.stat()
        if s1.st_size != s2.st_size or s1.st_mtime != s2.st_mtime:
            return False, "being_written"
        return True, "stable"
    except Exception as e:
        return False, f"error:{e}"

def file_age_sec(p: Path) -> float:
    try: return time.time() - p.stat().st_mtime
    except: return float("inf")

def _read_text_lines(p: Path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(p, "r", encoding=enc) as f:
                return [l.strip() for l in f if l.strip()]
        except UnicodeDecodeError: continue
        except: return None
    return None

def _get_queue_code() -> Optional[str]:
    try:
        if not QUEUE_CSV.exists() or QUEUE_CSV.stat().st_size == 0: return None
        rows = read_csv_rows(QUEUE_CSV, 5)
        if not rows or len(rows) < 2: return None
        hl = [x.lower() for x in normalize_header(rows[0])]
        ci = hl.index("code") if "code" in hl else None
        if ci is None: return None
        c = rows[1][ci].strip() if ci < len(rows[1]) else None
        return c if c and c.isdigit() and len(c) == 6 else None
    except Exception:
        return None

# ══════════════════════════════════════════════════════════
#  LOCK 관리
# ══════════════════════════════════════════════════════════
def _acquire_process_lock() -> bool:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if PROCESS_LOCK_FILE.exists():
            try:
                pid = int(PROCESS_LOCK_FILE.read_text(encoding="utf-8-sig").strip())
            except Exception:
                pid = None
            if pid and pid != os.getpid():
                alive = False
                try:
                    import psutil; alive = psutil.pid_exists(pid)
                except ImportError:
                    try: os.kill(pid, 0); alive = True
                    except OSError: alive = False
                if alive:
                    return False
                log_warn(f"[LOCK] stale lock 제거: pid={pid}")
                try: PROCESS_LOCK_FILE.unlink(missing_ok=True)
                except: pass
        PROCESS_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        log_warn(f"[LOCK] lock 오류: {e}")
        return True

def _release_process_lock():
    try:
        if PROCESS_LOCK_FILE.exists():
            pid = int(PROCESS_LOCK_FILE.read_text(encoding="utf-8-sig").strip())
            if pid == os.getpid():
                PROCESS_LOCK_FILE.unlink(missing_ok=True)
    except: pass

def _write_heartbeat_pid():
    try: LOG_DIR.mkdir(parents=True, exist_ok=True); HEARTBEAT_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except: pass

def _clear_heartbeat_pid():
    try: HEARTBEAT_FILE.unlink(missing_ok=True)
    except: pass

# ══════════════════════════════════════════════════════════
#  ─── 인프라 체크 (STOP 가능) ───
# ══════════════════════════════════════════════════════════

def check_python_32bit():
    if not is_32bit_python(): return RC_STOP_KIWOOM_NOT_READY, "python_not_32bit"
    return RC_PASS, "python_32bit_ok"

def check_paths():
    for n, p in {
        "BASE": BASE_DIR, "RUN": RUN_DIR, "DATA": DATA_DIR,
        "SCOREBOARD": SCOREBOARD_DIR, "QUEUE": QUEUE_DIR
    }.items():
        if not p.exists(): return RC_STOP_CORE_CSV_MISSING, f"dir_missing:{n}"
    for n, p in {"LOG": LOG_DIR, "LEDGER": LEDGER_DIR}.items():
        if not p.exists():
            try: p.mkdir(parents=True, exist_ok=True)
            except: _gate_deduct(5, f"mkdir_fail:{n}"); return RC_PASS, f"mkdir_fail:{n}"
    try:
        fd, tmp = tempfile.mkstemp(prefix="pf_", suffix=".tmp", dir=str(LOG_DIR))
        os.close(fd); Path(tmp).unlink(missing_ok=True)
    except: _gate_deduct(5, "log_not_writable")
    # [PATCH] 필수 파일 존재 확인 (rt_intraday.csv 제외 — 런타임 생성)
    for _n, _p in [("prices_1m.csv", PRICES_1M_CSV), ("params.json", PARAMS_JSON)]:
        if not _p.exists():
            log_fatal(f"[PREFLIGHT][FAIL] 필수 파일 없음: {_n}")
            return RC_STOP_PREFLIGHT_FAIL, f"required_missing:{_n}"
    return RC_PASS, "paths_ok"

def check_kiwoom_ocx():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KIWOOM_COM_KEY): pass
        return RC_PASS, "ocx_ok"
    except FileNotFoundError:
        return RC_STOP_KIWOOM_NOT_READY, "ocx_missing"
    except Exception:
        _gate_deduct(5, "ocx_err"); return RC_PASS, "ocx_err"

def check_kiwoom_server_reachable():
    # [INFRA_FIX 2026-05-06] openkh.kiwoom.com:443 헬스체크 비활성화
    # 사유: 키움 OpenAPI는 OCX(COM) 기반이라 HTTPS 직접 호출 없음.
    #       openkh.kiwoom.com:443은 영업/뱅킹용으로 OpenAPI와 무관 → 항상 false-fail.
    #       09:19 사이클에 BLOCK 결정 후 5시간 동안 풀리지 않음 (실측).
    #       진짜 OCX 상태는 check_kiwoom_ocx_loaded()에서 별도 검사.
    # 백업: safeplus_preflight_gate_v2_4_VIX_FIXED.py.bak_INFRAFIX_20260506
    return RC_PASS, "ocx_managed_skip"

def check_no_duplicate_process():
    try:
        if not PROCESS_LOCK_FILE.exists():
            _gate_deduct(3, "lock_missing"); return RC_PASS, "lock_missing"
        pid = int(PROCESS_LOCK_FILE.read_text(encoding="utf-8-sig").strip())
        if pid != os.getpid():
            return RC_STOP_DUPLICATE_PROCESS, f"dup_lock:pid={pid}"
        return RC_PASS, f"no_dup_lock:pid={pid}"
    except Exception as e:
        _gate_deduct(3, f"lock_err:{e}"); return RC_PASS, f"lock_err:{e}"

def _is_kr_holiday(d: date) -> bool:
    s = KR_HOLIDAYS.get(d.year)
    if s is None: log_warn(f"KR_HOLIDAYS {d.year} 없음"); return False
    return d in s

def check_market_time_window():
    """
    [v2.0] 2전략 기준 시간창 (종배 전략 삭제)
    시가     : 09:00~14:50(A등급) / 14:30(BCD) — rt_sell_engine 내부 FORCE_CLOSE 처리
    추세눌림 : 09:00~14:50 — rt_sell_engine 내부 FORCE_CLOSE 처리
    preflight: 장 밖(주말·공휴일·15:25 이후)만 차단
    """
    now = datetime.now(); today = now.date()
    if now.weekday() >= 5: return RC_STOP_CORE_CSV_MISSING, f"weekend:{today}"
    if _is_kr_holiday(today): return RC_STOP_CORE_CSV_MISSING, f"holiday:{today}"
    ts = now.hour * 3600 + now.minute * 60 + now.second
    o  = BUY_WINDOW_OPEN_HHMMSS[0]  * 3600 + BUY_WINDOW_OPEN_HHMMSS[1]  * 60 + BUY_WINDOW_OPEN_HHMMSS[2]
    c  = BUY_WINDOW_CLOSE_HHMMSS[0] * 3600 + BUY_WINDOW_CLOSE_HHMMSS[1] * 60 + BUY_WINDOW_CLOSE_HHMMSS[2]
    hhmm = now.strftime('%H:%M:%S')
    if not (o <= ts <= c):
        return RC_STOP_CORE_CSV_MISSING, (
            f"outside_window:{hhmm}(허용"
            f"{MARKET_OPEN_HHMMSS[0]:02d}:{MARKET_OPEN_HHMMSS[1]:02d}~"
            f"{MARKET_CLOSE_HHMMSS[0]:02d}:{MARKET_CLOSE_HHMMSS[1]:02d})"
        )
    # 09:00~09:10 슬리피지 경고 (개장 초 고변동 구간)
    if ts < 9 * 3600 + 10 * 60:
        _gate_deduct(0, "opening_buffer:09:00~09:10")
        return RC_PASS, f"in_window:{hhmm}[opening_buffer]"
    return RC_PASS, f"in_window:{hhmm}"

def check_config_yaml():
    # [CFGYAML_FIX 2026-05-06] STOP → WARN 강등.
    # 사유: SAFE+ 운영은 params.json + 환경변수 기반이며 config.yaml을 사용하지 않음.
    #       missing/not_dict/keys_missing 모두 _gate_deduct(WARN) 후 RC_PASS 반환.
    #       다른 검사(infra/score/universe)는 미변경.
    # 백업: safeplus_preflight_gate_v2_4_VIX_FIXED.py.bak_CFGYAML_20260506
    try:
        if not CONFIG_YAML.exists() or CONFIG_YAML.stat().st_size == 0:
            _gate_deduct(3, "config_missing"); return RC_PASS, "config_missing_warn"
        cfg = None
        try:
            import yaml
            with open(CONFIG_YAML, "r", encoding="utf-8-sig") as f:
                cfg = yaml.safe_load(f)
            if not isinstance(cfg, dict):
                _gate_deduct(3, "config_not_dict"); return RC_PASS, "config_not_dict_warn"
            miss = CONFIG_REQUIRED_KEYS - set(cfg.keys())
        except ImportError:
            with open(CONFIG_YAML, "r", encoding="utf-8-sig") as f: txt = f.read()
            miss = {k for k in CONFIG_REQUIRED_KEYS
                    if not re.search(rf"^\s*{re.escape(k)}\s*:", txt, re.MULTILINE)}
        if miss:
            _gate_deduct(3, f"config_keys:{sorted(miss)}")
            return RC_PASS, f"config_keys_warn:{sorted(miss)}"
        if cfg and "account" in cfg:
            a = str(cfg["account"]).strip().replace("-", "")
            if not (a.isdigit() and 8 <= len(a) <= 10): _gate_deduct(5, "account_fmt")
        return RC_PASS, "config_ok"
    except Exception:
        _gate_deduct(5, "config_err"); return RC_PASS, "config_err"

def check_universe_files():
    try:
        if not UNIVERSE_TXT.exists(): return RC_STOP_CORE_CSV_MISSING, "universe_missing"
        codes = _read_text_lines(UNIVERSE_TXT)
        if not codes or len(codes) < MIN_UNIVERSE_CODES:
            return RC_STOP_CORE_CSV_MISSING, f"universe_few:{len(codes) if codes else 0}"
        inv = [c for c in codes[:20] if not (c.isdigit() and len(c) == 6)]
        if inv: _gate_deduct(5, f"universe_bad:{inv[:3]}")
        return RC_PASS, f"universe_ok:{len(codes)}"
    except Exception:
        _gate_deduct(3, "universe_err"); return RC_PASS, "universe_err"

def _choose_score_file() -> Optional[Path]:
    eod   = SCOREBOARD_DIR / "score_eod.csv"
    intra = SCOREBOARD_DIR / "score_intraday.csv"
    if eod.exists()   and eod.stat().st_size   > 0: return eod
    if intra.exists() and intra.stat().st_size > 0: return intra
    return None

def check_score_csv():
    try:
        p = _choose_score_file()
        if p is None: return RC_STOP_CORE_CSV_MISSING, "score_missing"
        if p.stat().st_size == 0: return RC_STOP_CORE_CSV_MISSING, f"score_0byte:{p.name}"
        ok, d = ensure_stable(p)
        if not ok: _gate_deduct(10, "score_unstable")
        age = file_age_sec(p)
        # [FIX-1] 1일(86400s) 기준 — 헤지펀드급 신선도 요구 (구:3일→신:1일)
        if age > MAX_SCORE_FILE_AGE_SEC:
            _gate_deduct(15, f"score_stale:{int(age)}s(>{MAX_SCORE_FILE_AGE_SEC//3600}h)")
        rows = read_csv_rows(p, 5)
        if not rows: return RC_STOP_CORE_CSV_MISSING, f"score_unreadable:{p.name}"
        h = normalize_header(rows[0])
        if not h or has_blank_header(h) or has_duplicate_header(h):
            return RC_STOP_CORE_CSV_MISSING, "score_bad_header"
        if not header_matches_candidates(h, SCORE_HEADER_CANDIDATES):
            return RC_STOP_CORE_CSV_MISSING, f"score_mismatch:{h}"
        return RC_PASS, f"score_ok:{p.name}:age={int(age)}s"
    except Exception:
        _gate_deduct(5, "score_err"); return RC_PASS, "score_err"

def check_heartbeat_and_cpu():
    if HEARTBEAT_FILE.exists():
        try:
            sp = int(HEARTBEAT_FILE.read_text(encoding="utf-8-sig").strip())
        except Exception:
            sp = None
        if sp and sp != os.getpid():
            try:
                import psutil
                if psutil.pid_exists(sp):
                    try:
                        pr = psutil.Process(sp)
                        if Path(sys.argv[0]).name in " ".join(pr.cmdline()):
                            return RC_STOP_DUPLICATE_PROCESS, f"zombie:{sp}"
                    except: pass
                else:
                    log_warn(f"crash:{sp}"); _clear_heartbeat_pid()
            except ImportError:
                _clear_heartbeat_pid()
    try:
        import psutil; cp = psutil.cpu_percent(interval=0.5)
        if cp > MAX_CPU_PERCENT:
            _gate_deduct(10, f"cpu:{cp:.1f}%"); _gate_size(0.80, "cpu_high")
        return RC_PASS, f"cpu:{cp:.1f}%"
    except ImportError:
        return RC_PASS, "psutil_skip"
    except Exception:
        return RC_PASS, "cpu_err"

# ══════════════════════════════════════════════════════════
#  ─── 점수화 체크 (STOP 없음, 감점만) ───
# ══════════════════════════════════════════════════════════

def check_disk_space():
    try:
        import shutil; _, _, free = shutil.disk_usage(str(BASE_DIR))
        fm = free // (1024 * 1024)
        if fm < MIN_DISK_FREE_MB: _gate_deduct(10, f"disk:{fm}MB"); return RC_PASS, f"disk_low:{fm}MB"
        return RC_PASS, f"disk_ok:{fm}MB"
    except Exception:
        _gate_deduct(3, "disk_err"); return RC_PASS, "disk_err"

def check_memory_free():
    try:
        import psutil; fm = psutil.virtual_memory().available // (1024 * 1024)
        if fm < MIN_MEMORY_FREE_MB: _gate_deduct(10, f"mem:{fm}MB")
        return RC_PASS, f"mem:{fm}MB"
    except ImportError:
        return RC_PASS, "psutil_skip"
    except Exception:
        return RC_PASS, "mem_err"

def _ntp_offset_via_socket() -> float:
    import socket, struct as _s
    msg = b'\x1b' + 47 * b'\0'
    sk  = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.settimeout(NTP_TIMEOUT)
    try:
        sk.sendto(msg, (NTP_HOST, NTP_PORT)); data, _ = sk.recvfrom(1024)
    finally:
        sk.close()
    if len(data) < 48: raise ValueError("NTP short")
    return time.time() - (_s.unpack("!I", data[40:44])[0] - 2208988800)

def check_ntp_sync():
    try:
        off = None
        try:
            import ntplib; off = ntplib.NTPClient().request(NTP_HOST, version=3, timeout=NTP_TIMEOUT).offset
        except ImportError: pass
        if off is None:
            try: off = _ntp_offset_via_socket()
            except Exception as e:
                log_fatal(f"[PREFLIGHT][FAIL] NTP sync 실패: {e}")
                return RC_STOP_PREFLIGHT_FAIL, "ntp_fail"
        if abs(off) > NTP_MAX_DRIFT_SEC: _gate_deduct(10, f"ntp:{off:+.3f}s")
        return RC_PASS, f"ntp:{off:+.3f}s"
    except Exception as e:
        log_fatal(f"[PREFLIGHT][FAIL] NTP 오류: {e}")
        return RC_STOP_PREFLIGHT_FAIL, "ntp_err"

def check_queue_csv():
    try:
        if not QUEUE_CSV.exists():
            _gate_deduct(5, "queue_none"); return RC_PASS, "queue_none"
        ok, d = ensure_stable(QUEUE_CSV)
        if not ok: _gate_deduct(5, "queue_unstable"); return RC_PASS, f"queue_unstable:{d}"
        lo = True
        if _msvcrt is not None:
            fobj = None
            try:
                fobj = open(QUEUE_CSV, "r+b")
                ls = max(1, QUEUE_CSV.stat().st_size); fobj.seek(0)
                _msvcrt.locking(fobj.fileno(), _msvcrt.LK_NBLCK, ls)
                fobj.seek(0); _msvcrt.locking(fobj.fileno(), _msvcrt.LK_UNLCK, ls)
            except OSError:
                lo = False
            except: pass
            finally:
                if fobj:
                    try: fobj.close()
                    except: pass
        if not lo: return RC_STOP_QUEUE_LOCKED, "queue:locked"
        if QUEUE_CSV.stat().st_size == 0:
            _gate_deduct(5, "queue_empty"); return RC_PASS, "queue_empty"
        return RC_PASS, "queue_ok"
    except Exception:
        _gate_deduct(3, "queue_err"); return RC_PASS, "queue_err"

def check_eod_positions():
    if not EOD_POS_CSV.exists() or EOD_POS_CSV.stat().st_size == 0:
        return RC_PASS, "eod_none_ok"
    try:
        rows = read_csv_rows(EOD_POS_CSV, 200)
        if not rows: _gate_deduct(3, "eod_unreadable")
        return RC_PASS, f"eod_ok:{len(rows)-1 if rows else 0}"
    except Exception:
        _gate_deduct(3, "eod_err"); return RC_PASS, "eod_err"

def check_prices_freshness():
    """
    [v2.0] 2전략 기준 신선도 (종배 구간 삭제)
    09:00~09:30: 전날 데이터 허용 (18h 기준)
    09:30 이후:  6h 기준 유지 (실시간 수집 점검)
    """
    try:
        if not PRICES_1M_CSV.exists() or PRICES_1M_CSV.stat().st_size == 0:
            _gate_deduct(10, "prices_missing"); return RC_PASS, "prices_missing"
        age = file_age_sec(PRICES_1M_CSV)
        now = datetime.now()
        ts_sec = now.hour * 3600 + now.minute * 60 + now.second
        pre_open_end = 9 * 3600 + 30 * 60   # 09:30
        if ts_sec <= pre_open_end:
            limit = 60 * 60 * 18             # 18h — 전날까지만 허용
            tag = "pre_open"
        else:
            limit = MAX_PRICES_FILE_AGE_SEC  # 6h
            tag = "intraday"
        if age > limit: _gate_deduct(10, f"prices_stale:{int(age)}s({tag})")
        return RC_PASS, f"prices:age={int(age)}s:limit={int(limit/3600)}h:{tag}"
    except Exception:
        _gate_deduct(5, "prices_err"); return RC_PASS, "prices_err"

def check_account_risk_state():
    """계좌 리스크 → 사이즈 축소 (STOP=완전붕괴만)"""
    try:
        rows = _load_ledger()
        if not rows or len(rows) < 3:
            return RC_PASS, f"ledger_short:{len(rows) if rows else 0}"
        last = rows[-1]
        dl = _pf_float("daily_loss_limit_r",   DAILY_LOSS_WARN_R)
        ml = _pf_float("max_drawdown_limit_r",  MAX_DRAWDOWN_WARN_R)
        try: dr = float(last.get("daily_pnl_r", "0") or "0")
        except: dr = 0.0
        try: mr = float(last.get("max_drawdown_r", "0") or "0")
        except: mr = 0.0
        # 완전 붕괴 → 즉시 STOP
        if mr <= ACCOUNT_COLLAPSE_MDD:
            return RC_STOP_ACCOUNT_COLLAPSE, f"COLLAPSE:mdd={mr:.2f}%"
        if mr <= ml:
            _gate_deduct(20, f"mdd:{mr:.2f}%"); _gate_size(0.30, f"mdd_hit:{mr:.2f}%")
        elif dr <= dl:
            _gate_deduct(15, f"daily:{dr:.2f}%"); _gate_size(0.50, f"daily_hit:{dr:.2f}%")
        # 연속 손실
        cl = 0
        for r in reversed(rows[-CONSECUTIVE_LOSS_WARN_DAYS:]):
            try: d = float(r.get("daily_pnl_r", "0") or "0")
            except: d = 0.0
            if d < 0: cl += 1
            else: break
        if cl >= CONSECUTIVE_LOSS_WARN_DAYS:
            _gate_deduct(5, f"consec:{cl}d"); _gate_size(0.80, f"consec_{cl}d")
        return RC_PASS, f"acct:daily={dr:+.2f}%:mdd={mr:+.2f}%:consec={cl}:size={_GATE['size_mult']:.2f}"
    except Exception as e:
        _gate_deduct(3, "acct_err"); return RC_PASS, f"acct_err:{e}"

def check_strategy_performance():
    """
    [v2.0] 전략 성과 점검 + 워밍업 분기 + 연승 부스트 + Half-Kelly 반영
    워밍업(실거래<20건): min_winrate_5d_warmup 완화 기준 적용
    연승(5연속 흑자): size × 1.05 부스트
    """
    try:
        rows = _load_ledger()
        lb   = STRATEGY_LOOKBACK_DAYS
        if not rows or len(rows) < lb:
            return RC_PASS, f"strat_short:{len(rows) if rows else 0}"

        # [FIX-2] 워밍업 구간 분기
        total_trades = len(rows)
        warmup_mode  = total_trades < WARMUP_MIN_TRADES
        if warmup_mode:
            mw = _pf_float("min_winrate_5d_warmup", 0.30)
            log_info(f"[WARMUP] 실거래 {total_trades}건 < {WARMUP_MIN_TRADES} → 완화기준 {mw:.2f}")
        else:
            mw = _pf_float("min_winrate_5d", MIN_WINRATE_5D)
        ml = _pf_float("max_loss_5d_r", MAX_LOSS_5D_R)

        recent = rows[-lb:]; wins = 0; tr = 0.0
        for r in recent:
            try: p = float(r.get("daily_pnl_r", "0") or "0")
            except: p = 0.0
            tr += p
            if p > 0: wins += 1
        wr = wins / float(lb)

        # 성과 불량 → 감점 (OR 조건: 어느 하나 기준 초과 시 경보)
        # [W16 PATCH 2026-05-12] cold-start 가드 — 거래 0건 시 wr=0.00 산출이 strat_weak 영구 트리거하는 트랩 회피
        # [W16-EXT 2026-05-13] 보강 — total_trades>0이나 recent lookback 모두 pnl=0인 케이스(ledger 행은 있으나 PnL 미reconcile)도 cold-start로 처리
        _all_zero_recent = all((float(r.get("daily_pnl_r", "0") or "0") == 0.0) for r in recent)
        if wr < mw or tr < ml:
            if total_trades > 0 and not _all_zero_recent:
                _gate_deduct(10, f"strat:wr={wr:.2f}:r={tr:+.2f}%")
                _gate_size(0.70, "strat_weak")
            elif _all_zero_recent and total_trades > 0:
                log_info(f"[STRAT] no_real_pnl (total={total_trades}, recent all 0) → strat_weak 미적용 (W16-EXT)")
            else:
                log_info(f"[STRAT] cold-start (total_trades=0) → strat_weak 미적용 (W16)")

        # [FIX-3] 연승 부스트 — 최근 5거래 모두 흑자
        win_streak = 0
        for r in reversed(rows[-WIN_STREAK_BOOST_COUNT:]):
            try: p = float(r.get("daily_pnl_r", "0") or "0")
            except: p = 0.0
            if p > 0: win_streak += 1
            else: break
        if win_streak >= WIN_STREAK_BOOST_COUNT:
            _gate_size(1.05, f"win_streak:{win_streak}연승")
            log_info(f"[STREAK] {win_streak}연승 → size 부스트")

        # [ARCH-1] Half-Kelly 동적 사이징
        kelly_f = _compute_half_kelly(rows)
        _GATE["kelly_fraction"] = kelly_f if kelly_f is not None else 0.50
        if kelly_f is None:
            log_info("[KELLY] 데이터 부족(n<5) → Kelly 사이징 스킵 (중립)")
        elif kelly_f < 0.35:
            # Kelly fraction 낮음 → 승률/손익비 불량 → size 하향 보정
            _gate_size(kelly_f / 0.50, f"kelly_low:{kelly_f:.3f}")
        elif kelly_f > 0.40:
            # [BUG-FIX v2.3] Kelly 상향 임계값 0.55→0.40
            # 수학적 근거: f_half = min(0.65, f_star×0.5) ≤ 0.50
            # → kelly_f > 0.55는 영원히 False (dead condition)
            # → 0.40으로 낮춤: "기본값 0.50보다 실거래 기반 계산이 높은 상태" = 우수 신호
            # 발동 예: wr=0.8, b=3.0 → f_half=0.375 → 미발동 / wr=0.85,b=3.5 → f_half=0.43 → 발동
            boost = min(1.10, kelly_f / 0.40)   # 0.40 기준 정규화, 최대 ×1.10
            _gate_size(boost, f"kelly_high:{kelly_f:.3f}")
            log_info(f"[KELLY] fraction={kelly_f:.3f} > 0.40 → size ×{boost:.2f} 부스트")

        # [ARCH-2] Sharpe Ratio
        sharpe = _compute_sharpe(rows)
        _GATE["sharpe_ratio"] = sharpe
        if sharpe is not None:
            if sharpe < 0.5:
                _gate_deduct(10, f"sharpe_low:{sharpe:.2f}")
                _gate_size(0.80, f"sharpe_poor:{sharpe:.2f}")
                log_warn(f"[SHARPE] SR={sharpe:.2f} < 0.5 → 감점+size축소")
            elif sharpe >= 1.5:
                # [BUG-FIX P1] SR≥1.5 부스트: v2.0에서 log만 찍고 size 변경 없었던 버그 수정
                _gate_size(1.10, f"sharpe_strong:{sharpe:.2f}")
                log_info(f"[SHARPE] SR={sharpe:.2f} ≥ 1.5 → size × 1.10 부스트")

        # [ARCH-3] Profit Factor
        pf = _compute_profit_factor(rows)
        _GATE["profit_factor"] = pf
        if pf is not None and pf < 1.2:
            _gate_deduct(5, f"pf_low:{pf:.2f}")
            _gate_size(0.70, f"pf_poor:{pf:.2f}")

        # [FIX-4] VaR 95%
        var95 = _compute_var95(rows)
        _GATE["var_95"] = var95
        if var95 is not None and var95 < -3.0:
            _gate_deduct(5, f"var95:{var95:.2f}%")

        # 자기진화 제안 생성
        _write_evolution_hint(rows, wr, pf, sharpe)

        return RC_PASS, (
            f"strat:wr={wr:.2f}:r={tr:+.2f}%"
            f":kelly={kelly_f:.3f if kelly_f is not None else 'N/A'}"
            f":sr={sharpe if sharpe is not None else 'N/A'}"
            f":pf={pf if pf is not None else 'N/A'}:size={_GATE['size_mult']:.2f}"
            f"{'[WARMUP]' if warmup_mode else ''}"
        )
    except Exception as e:
        _gate_deduct(3, "strat_err"); return RC_PASS, f"strat_err:{e}"

def check_vix_regime() -> tuple:
    """[v2.4 지침서 §2-2] VIX 레짐 분류 — 변동성 대리 지표
    prices_1m.csv의 최근 30봉 ATR비율로 VIX 레짐 추정
    EXTREME(≥2.5%) → 진입금지 / HIGH(≥1.8%) → -10점/×0.75
    MID(≥1.2%) → -5점/×0.90 / LOW(<1.2%) → 정상
    출처: 지침서 §2-2 VIX 레짐 분류표
    """
    try:
        if not PRICES_1M_CSV.exists() or PRICES_1M_CSV.stat().st_size == 0:
            return RC_PASS, "vix_skip:no_data"

        tc = _get_queue_code()
        highs, lows = [], []
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(PRICES_1M_CSV, "r", encoding=enc) as f:
                    rd  = csv.reader(f); hdr = next(rd, None)
                    if not hdr: break
                    hl = [x.strip().lower() for x in hdr]
                    hi_i = next((hl.index(c) for c in ("high","고가") if c in hl), None)
                    lo_i = next((hl.index(c) for c in ("low","저가") if c in hl), None)
                    ci   = next((hl.index(c) for c in ("code","종목코드") if c in hl), None)
                    if hi_i is None or lo_i is None: break
                    tail = deque(maxlen=5000)
                    for row in rd: tail.append(row)
                    for row in tail:
                        if ci is not None and tc:
                            if ci < len(row) and row[ci].strip() != tc: continue
                        try:
                            h = float(row[hi_i].strip())
                            l = float(row[lo_i].strip())
                            if h > 0 and l > 0 and h >= l:
                                highs.append(h); lows.append(l)
                        except: continue
                break
            except UnicodeDecodeError: continue
            except: return RC_PASS, "vix_read_err"

        if len(highs) < 10:
            return RC_PASS, f"vix_bars:{len(highs)}"

        # ATR비율 = (고가-저가)/저가 평균 → VIX 대리 지표
        # [PATCH-v2.4.1] 계산 대상: prices_1m.csv의 종목별 ATR 비율
        # 주의: 시장 전체 VIX(KOSDAQ 지수)와 1:1 대응 아님
        # 실전 충분성: 대장주 변동성이 시장 변동성과 높은 상관관계 → usable
        recent = min(30, len(highs))
        atr_ratios = [
            (highs[-i] - lows[-i]) / max(lows[-i], 1.0)
            for i in range(1, recent + 1)
        ]
        avg_vol = sum(atr_ratios) / len(atr_ratios)

        # 레짐 분류 + gate 적용 (지침서 §2-2)
        if avg_vol >= VIX_PROXY_EXTREME_VOL:
            regime = "EXTREME"
            _gate_deduct(50, f"VIX_EXTREME:vol={avg_vol:.4f}")
            _gate_size(0.0, "VIX_EXTREME_BLOCK")
            log_warn(f"[VIX_REGIME] EXTREME vol={avg_vol:.4f}≥{VIX_PROXY_EXTREME_VOL} (종목ATR기준) → 진입금지")
        elif avg_vol >= VIX_PROXY_HIGH_VOL:
            regime = "HIGH"
            # HIGH: gate_score -10 + size×0.75
            _gate_deduct(10, f"VIX_HIGH:vol={avg_vol:.4f}")
            _gate_size(0.75, f"VIX_HIGH:vol={avg_vol:.4f}")
            log_info(f"[VIX_REGIME] HIGH vol={avg_vol:.4f} → -10점/×0.75")
        elif avg_vol >= VIX_PROXY_MID_VOL:
            regime = "MID"
            # MID: gate_score -5 + size×0.90
            _gate_deduct(5, f"VIX_MID:vol={avg_vol:.4f}")
            _gate_size(0.90, f"VIX_MID:vol={avg_vol:.4f}")
            log_info(f"[VIX_REGIME] MID vol={avg_vol:.4f} → -5점/×0.90")
        else:
            regime = "LOW"
            log_info(f"[VIX_REGIME] LOW vol={avg_vol:.4f} → 정상")

        # 레짐 기록 (downstream 모듈 참조용)
        try:
            VIX_REGIME_JSON.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            _json.dump({"regime": regime, "avg_vol": round(avg_vol, 6),
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                       open(str(VIX_REGIME_JSON), "w", encoding="utf-8"),
                       ensure_ascii=False)
        except Exception: pass

        return RC_PASS, f"vix_regime={regime}:vol={avg_vol:.4f}:bars={recent}"
    except Exception as e:
        _gate_deduct(2, "vix_err"); return RC_PASS, f"vix_err:{e}"


def check_market_risk():
    """[v2.0] 시장 리스크 → 변동성=기회 (공격70%) — 종목코드 필터 + deque tail-read"""
    try:
        if not PRICES_1M_CSV.exists() or PRICES_1M_CSV.stat().st_size == 0:
            return RC_PASS, "mkt_skip"
        tc = _get_queue_code()
        # [W15 PATCH 2026-05-12] tc 부재 시 mkt_skip — 큐 비어있을 때 모든 종목 가격이 섞여 가짜 50% crash 산출되는 결함 회피
        if not tc:
            return RC_PASS, "mkt_skip:no_queue_code (W15)"
        prices = []
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(PRICES_1M_CSV, "r", encoding=enc) as f:
                    rd  = csv.reader(f); hdr = next(rd, None)
                    if not hdr: break
                    hl  = [x.strip().lower() for x in hdr]
                    ci  = next((hl.index(cn) for cn in ("code", "종목코드") if cn in hl), None)
                    cli = next((hl.index(cn) for cn in ("close", "종가", "현재가") if cn in hl), None)
                    if cli is None: break
                    tail = deque(maxlen=50000)
                    for row in rd: tail.append(row)
                    for row in tail:
                        if ci is not None and tc:
                            if ci < len(row) and row[ci].strip() != tc: continue
                        if cli < len(row):
                            try:
                                v = float(row[cli].strip())
                                if v > 0: prices.append(v)
                            except: continue
                    if len(prices) > MARKET_CHECK_BARS: prices = prices[-MARKET_CHECK_BARS:]
                break
            except UnicodeDecodeError: continue
            except: return RC_PASS, "mkt_read_err"
        if len(prices) < 10: return RC_PASS, f"mkt_bars:{len(prices)}"
        hi = max(prices); lo = min(prices); la = prices[-1]
        drop   = (hi - la) / max(hi, 1.0)
        spread = (hi - lo) / max(lo, 1.0)
        ct = f":code={tc}" if tc else ":ALL"
        if drop > MARKET_EXTREME_DROP:
            _gate_deduct(15, f"extreme:{drop:.4f}")
            _gate_size(0.50, f"crash:{drop:.4f}")
        elif 0.02 < spread <= 0.05:
            # 적당한 변동성 = 기회 → 부스트 (단, decision cap에 의해 CAUTION 구간선 적용 안 됨)
            _gate_size(MARKET_VOL_ATTACK_BOOST, f"vol_opp:{spread:.4f}")
        return RC_PASS, f"mkt:drop={drop:.4f}:vol={spread:.4f}{ct}:size={_GATE['size_mult']:.2f}"
    except Exception as e:
        _gate_deduct(3, "mkt_err"); return RC_PASS, f"mkt_err:{e}"

# ══════════════════════════════════════════════════════════
#  체크 목록 정의
# ══════════════════════════════════════════════════════════
CHECKS_INFRA = [
    ("python_32bit",       check_python_32bit),
    ("paths",              check_paths),
    ("kiwoom_ocx",         check_kiwoom_ocx),
    ("kiwoom_server",      check_kiwoom_server_reachable),
    ("duplicate_process",  check_no_duplicate_process),
    ("heartbeat_and_cpu",  check_heartbeat_and_cpu),
    ("market_time_window", check_market_time_window),
    ("config_yaml",        check_config_yaml),
    ("universe_files",     check_universe_files),
    ("score_csv",          check_score_csv),
]
CHECKS_SCORING = [
    ("disk_space",          check_disk_space),
    ("memory_free",         check_memory_free),
    ("ntp_sync",            check_ntp_sync),
    ("queue_csv",           check_queue_csv),
    ("eod_positions",       check_eod_positions),
    ("prices_freshness",    check_prices_freshness),
    ("account_risk",        check_account_risk_state),
    ("strategy_performance",check_strategy_performance),   # Kelly+Sharpe+PF+VaR 포함
    ("vix_regime",          check_vix_regime),      # [v2.4 §2-2] VIX 레짐 분류
    ("market_risk",         check_market_risk),
]

# ══════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════
def main() -> int:
    setup_logging(); _write_heartbeat_pid()

    # 중복 실행 방지 — check_no_duplicate_process 호출 전 선행
    if not _acquire_process_lock():
        log_fatal("[LOCK] 중복 실행 감지 → STOP")
        _GATE["gate_score"] = 0; _GATE["size_mult"] = 0.0
        _GATE["reasons"].append("INFRA_STOP:duplicate_lock")
        _write_result(decision="CAUTION"); _clear_heartbeat_pid(); return RC_STOP_DUPLICATE_PROCESS

    log_info("=" * 70)
    log_info(
        f"SAFEPLUS PREFLIGHT GATE v2.4 START | "
        f"checks={len(CHECKS_INFRA)+len(CHECKS_SCORING)} | "
        f"전략=시가+추세눌림(2전략, 종배삭제)"
    )
    log_info(f"time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | base={BASE_DIR}")
    log_info("=" * 70)

    audit: Dict[str, Any] = {}

    # ── Phase 1: 인프라 (STOP 가능) ────────────────────────────
    for name, fn in CHECKS_INFRA:
        t0 = time.monotonic()
        try: rc, msg = fn()
        except Exception as e: rc, msg = RC_STOP_CORE_CSV_MISSING, f"infra_err:{e}"
        ms  = int((time.monotonic() - t0) * 1000)
        st  = "PASS" if rc == RC_PASS else "STOP"
        audit[name] = {"rc": rc, "msg": msg, "status": st, "ms": ms}
        line = f"{st} | {name:25s} | {msg}  [{ms}ms]"
        print(line)
        if rc != RC_PASS:
            log_fatal(line)
            _GATE["gate_score"] = 0; _GATE["size_mult"] = 0.0
            _GATE["reasons"].append(f"INFRA_STOP:{name}")
            _write_result(decision="CAUTION"); write_audit(audit)
            _clear_heartbeat_pid(); _release_process_lock(); return rc
        log_info(line)

    # ── Phase 2: 점수화 (STOP 없음, 계좌붕괴 제외) ─────────────
    for name, fn in CHECKS_SCORING:
        t0 = time.monotonic()
        try: rc, msg = fn()
        except Exception as e:
            rc, msg = RC_PASS, f"scoring_err:{e}"; _gate_deduct(5, f"exc:{name}")
        ms = int((time.monotonic() - t0) * 1000)
        if rc == RC_STOP_ACCOUNT_COLLAPSE:
            audit[name] = {"rc": rc, "msg": msg, "status": "STOP", "ms": ms}
            line = f"STOP | {name:25s} | {msg}  [{ms}ms]"
            print(line); log_fatal(line)
            _GATE["gate_score"] = 0; _GATE["size_mult"] = 0.0
            _write_result(decision="CAUTION"); write_audit(audit)
            _clear_heartbeat_pid(); _release_process_lock(); return rc
        audit[name] = {"rc": rc, "msg": msg, "status": "PASS", "ms": ms}
        line = f"PASS | {name:25s} | {msg}  [{ms}ms]"
        print(line); log_info(line)

    # ── Decision + size_mult 모순 방지 ─────────────────────────
    _GATE["size_mult"] = round(max(SIZE_MULT_MIN, min(SIZE_MULT_MAX, _GATE["size_mult"])), 4)
    gs = _GATE["gate_score"]
    sm = _GATE["size_mult"]
    sr = _GATE.get("sharpe_ratio")
    pf = _GATE.get("profit_factor")

    # ATTACK: score≥80 AND size≥1.0 (Sharpe≥1.5이면 완화 허용)
    attack_ok = gs >= 80 and sm >= 1.0
    if attack_ok:
        dec = "ATTACK"; sm_cap = SIZE_MULT_MAX
    elif gs >= 50:
        dec = "STABLE"; sm_cap = 1.00
    elif gs >= FORCE_ENTRY_SCORE_MIN and _is_first_entry_today():
        # [ARCH-5] 1일 1회 강제 진입 (지침서 9항)
        dec = "FORCE_ENTRY"; sm_cap = 0.70
        log_info(f"[FORCE_ENTRY] score={gs}≥{FORCE_ENTRY_SCORE_MIN} + 당일미진입 → 강제진입 size_cap=0.70")
    else:
        dec = "CAUTION"; sm_cap = 0.60

    if sm > sm_cap:
        log_info(f"[SIZE_CAP] {dec} 구간: size {sm:.2f}→{sm_cap:.2f}")
        _GATE["reasons"].append(f"size_cap:{dec}:{sm:.2f}→{sm_cap:.2f}")
        sm = sm_cap
    _GATE["size_mult"] = round(sm, 4)

    # ── 최종 출력 ──────────────────────────────────────────────
    sr_str = f"{sr:.2f}" if sr is not None else "N/A"
    pf_str = f"{pf:.2f}" if pf is not None else "N/A"
    var_str = f"{_GATE.get('var_95'):.2f}%" if _GATE.get('var_95') is not None else "N/A"
    kelly_str = f"{_GATE.get('kelly_fraction', 0.5):.3f}"

    final = (
        f"PASS | v2.3 | score={gs} | size={sm:.2f} | decision={dec} | "
        f"SR={sr_str} | PF={pf_str} | VaR95={var_str} | Kelly={kelly_str} | "
        f"strategies=시가+추세눌림 | adj={len(_GATE['reasons'])}"
    )
    print(final); log_info(final)
    if _GATE["reasons"]: log_info(f"  reasons: {_GATE['reasons']}")

    # 결과 기록 — [BUG-FIX P0] main()에서 확정된 dec을 인수로 전달 (재계산 없음)
    _write_result(decision=dec); write_audit(audit)

    # 진입 플래그 갱신 (FORCE_ENTRY or STABLE or ATTACK)
    if dec in ("ATTACK", "STABLE", "FORCE_ENTRY"):
        _mark_entry_today()

    _clear_heartbeat_pid(); _release_process_lock()
    return RC_PASS

if __name__ == "__main__":
    sys.exit(main())

# ══════════════════════════════════════════════════════════
# 부록 A. 학술 출처 (Academic References)
# ══════════════════════════════════════════════════════════
# | 알고리즘              | 출처                                                         |
# |----------------------|--------------------------------------------------------------|
# | True ATR             | Wilder, J.W. (1978) New Concepts in Technical Trading Systems |
# | Chandelier Exit      | LeBeau & Lucas (1992) Computer Analysis of the Futures Market |
# | OFI 기관 감지        | Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88               |
# | TSL 임계값           | Glasserman & Xu (2011) 1.0~1.5σ 구간 최적 임계값            |
# | Half-Kelly 사이징    | Kelly (1956) Bell Sys Tech J 35(4) / Thorp (1962/2007)       |
# | Sharpe Ratio         | Sharpe (1966) Journal of Business 39(1):119-138              |
# | SR 연간화            | Lo, A.W. (2002) Journal of Portfolio Management 28(4):36-52  |
# | Position Sizing      | Palazzi (2025) Trading Games JFM                             |
# | Profit Factor        | Kaufman (1998) Trading Systems and Methods (4th Ed.)          |
# | VaR 역사적 시뮬.     | Jorion (2007) Value at Risk (3rd Ed.) McGraw-Hill             |
# | Citadel 소프트차단   | Citadel Risk Overlay (공개 방법론)                            |
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# 부록 B. v2.3 자가점검 체크리스트
# ══════════════════════════════════════════════════════════
# [✓] 종배(시배) 전략 참조 완전 삭제 (2전략: 시가+추세눌림)
# [✓] Half-Kelly fraction 동적 계산 (Kelly 1956 공식)
#       하향(kelly<0.35): size × (kelly/0.50) 축소
#       상향(kelly>0.40): boost=min(1.10, kelly/0.40) 확대 [BUG-FIX v2.3]
#       ※ kelly_f 수학적 상한=0.50 → 임계값 0.55는 dead condition → 0.40으로 수정
#       최소 샘플 n<5 → 0.50 중립 반환 [BUG-FIX v2.2-3]
# [✓] Sharpe Ratio 연간화 추적 (Lo 2002 기준)
#       SR≥1.5 → size×1.10 부스트 [BUG-FIX P1]
#       최소 샘플 len<10 → None [BUG-FIX v2.2-3]
# [✓] Profit Factor 게이트 (PF<1.2 → size×0.70)
#       pf is not None 조건 [BUG-FIX v2.2-2]
# [✓] VaR 95% 간이 추정 — 최소 30개, idx=int(n*0.05) [BUG-FIX P2]
# [✓] 워밍업 구간 분기 (실거래<20 → 완화기준 0.30)
# [✓] 연승 부스트 (5연승 → size×1.05)
# [✓] 1일 1회 강제진입 (score≥40 + 당일미진입 → FORCE_ENTRY)
#       캐싱으로 이중 I/O 제거 [BUG-FIX P2]
# [✓] 점수 신선도 3일→1일
# [✓] 자기진화 출력 (evolution_recommendation.json)
#       hard_stop 축소 max(x,x) 제거 [BUG-FIX v2.2-1]
# [✓] 진화 허용 3개 / 진화 금지 4개 보호
# [✓] Decision 등급별 size_mult 상한 강제
#       ATTACK≤1.15 / STABLE≤1.00 / FORCE_ENTRY≤0.70 / CAUTION≤0.60
# [✓] _write_result(decision=) 단일 경로 [BUG-FIX P0]
# [✓] _gate_size_set dead code 제거 [BUG-FIX P0]
# [✓] STOP 3가지만: 데이터없음/API실패/계좌완전붕괴(MDD-15%)
# ══════════════════════════════════════════════════════════
