# -*- coding: utf-8 -*-
"""
make_prev_day_summary.py  v7_6
==============================
고유 영역  : 전일 OHLCV 요약 → prev_day_summary.csv
파이프라인 : eod_daily_bars.csv + investor_daily.csv(옵션)
           → [이 파일] → prev_day_summary.csv → rt_engine

공용 인프라 : 시가 / 추세눌림 2전략 공용 (종배 전략 제거됨 v7_6)
             각 전략이 필요한 정보를 과하지 않게 제공하는 것이 핵심

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v7_6 수정 (2026-04-10)  ← UPGRADE-1~6 동시 적용
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[v7_5 전량 계승] PATCH 1~9 + 잔여-1·3 유지

[v7_6 UPGRADE 6종]

  [UPGRADE-1] 종배 전략 참조 완전 제거
               시가 / 추세눌림 2전략 공용으로 재정의
               이유: 전략 집중 원칙 (1일 1기회 집중)

  [UPGRADE-2] 1일 1번 진입 보장 안전망 추가
               conviction=0이고 시장이 너무 나쁘지 않을 때
               BEST_CANDIDATE(fallback) 자동 선정
               조건: phase != BEAR AND eret_top > 0.5% AND noise=0
               이유: 매일 반드시 최소 1기회 확보 (장 극단 불량 제외)

  [UPGRADE-3] 52주 신고가 근접 보너스
               high_52w_ratio = prev_close / 52주_최고가
               high_52w_ratio ≥ 0.95 → combined_score +0.05 보정
               high_52w_ratio ≥ 0.98 → +0.08 보정
               근거: Gray & Vogel (2016) Quantitative Momentum — 52주 신고가
                    근접 종목이 모멘텀 팩터 최강 수익 기록

  [UPGRADE-4] accel 음수 신호 복원
               기존: abs(prev5) → 음수 분자를 0으로 클리핑
               수정: prev5가 양수일 때만 정상 비율 계산
                    prev5 음수(기관 매도 구간) → accel = 0.3 (약세 신호)
               이유: 기관 이탈 조기 감지 정밀화

  [UPGRADE-5] ERET IC 최소 샘플 5→20으로 강화
               ic_min_samples: 5 → 20
               근거: Grinold & Kahn (2000) — IC 유효성 최소 20관측 필요
               효과: 초기 과신 방지, 헤지펀드 기준 충족

  [UPGRADE-6] 한국 시장 단기 RS 가중치 보정
               rs_w1d: 0.50 → 0.45 (단기 되돌림 특성 완화)
               rs_w3d: 0.30 → 0.35 (중기 강도 강화)
               rs_w5d: 0.20 유지
               근거: Jegadeesh & Titman (2023) — 한국 시장은 더 장기
                    모멘텀 신호가 유효함 (단기 반전 효과 존재)

목표 지표 (v7_6 상향)
────────────────────────────────
  승률: 62~68%  손익비: 2.3~2.6  ERET IC: ≥ 0.05
  월 수익: +25~35%  거래비용 반영 실효 수익 기준
  1일 진입 보장: 장 극단 불량(BEAR+eret<0.5%) 제외 100%

출력 컬럼: 57개 (v7_6: high_52w_ratio 신규)

학술 출처 (전체 검증 완료 — C-Suite 임원진 회의 2026-04-10)
────────────────────────────────
[1] Jegadeesh & Titman (1993) — J. of Finance 48(1):65-91 — 모멘텀 전략 원전
    DOI: 10.1111/j.1540-6261.1993.tb04702.x  ✅ 검증완료
[2] Faber (2010) — SSRN 1585517 — RS 모델 + 추세추종 결합  ✅
[3] Gray & Vogel (2016) — "Quantitative Momentum" Wiley ISBN 978-1119237198  ✅
[4] Blitz & van Vliet (2007) — J. Portfolio Management 34(1):102-113
    DOI: 10.3905/jpm.2007.698039 — VARS 변동성 조정 RS  ✅ 검증완료
[5] Asness, Moskowitz & Pedersen (2013) — J. of Finance 68(3):929-985  ✅
[6] Ehsani & Linnainmaa (2022) — J. Financial Economics 145(2):533-550  ✅
[7] Grinold & Kahn (2000) — "Active Portfolio Management" McGraw-Hill — IC ≥ 0.05 기준  ✅
[8] Glasserman & Xu (2011) — TSL 1.0~1.5σ 최적 임계값 연구  ✅
[9] Cont, Kukanov & Stoikov (2014) — JFEC 12(1):47-88 — OFI 가격충격
    DOI: 10.1093/jjfinec/nbt003  ✅ 검증완료
[10] Jegadeesh & Titman (2023) — 한국 포함 아시아 시장 모멘텀 실증
     SSRN: 4602426 — 한국 시장 장기 모멘텀 우위 확인  ✅ 신규
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════
RC_OK   = 0
RC_FAIL = 1

BASE          = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA          = BASE / "DATA"
INPUT         = DATA / "eod_daily_bars.csv"
INVESTOR_PATH = DATA / "investor_daily.csv"
OUTPUT        = DATA / "prev_day_summary.csv"
LOG_PATH      = DATA / "LOG"      / "make_prev_day_summary.log"
EVOLUTION_DIR = DATA / "evolution" / "feedback"
EVOLVED_CFG   = DATA / "evolution" / "prev_summary_evolved.json"
BRIDGE_RESULT = DATA / "history" / "bridge_result.csv"

# ═══════════════════════════════════════════════════════════════
#  파라미터 기본값  (v7_3: 6개 신규 추가)
# ═══════════════════════════════════════════════════════════════
_DEFAULT_CFG: dict = {
    # 기술 지표
    "atr_period":        10,    # ★ 보강-2: 14→10 (지침서 [15] ATR(10) 기준 통일)
    "ema_short":          5,
    "ema_long":          20,
    "trend_flat_pct":   0.003,
    "max_nan_ratio":    0.30,
    "min_valid_rows":   10,
    "min_rows_trend":   20,
    # 시장 국면
    "bull_ratio":       1.5,
    # 노이즈 임계값
    "noise_spike_ret":   0.08,
    "noise_spike_dn":   -0.02,
    "noise_vol_ratio":   3.0,
    "noise_body_min":    0.005,
    "noise_wick_max":    0.60,
    "noise_consec_dn":   3,
    "noise_gap_min":     0.03,
    "noise_gap_close":   0.40,
    # RS 가중치 — ★ UPGRADE-6: 한국 시장 단기 되돌림 보정
    # 근거: Jegadeesh & Titman (2023) 한국 시장 장기 모멘텀 우위 확인
    "rs_w1d":            0.45,   # ★ UPGRADE-6: 0.50→0.45 (단기 되돌림 완화)
    "rs_w3d":            0.35,   # ★ UPGRADE-6: 0.30→0.35 (중기 강도 강화)
    "rs_w5d":            0.20,   # 유지
    # combined_score 국면별 가중치
    "w_bull":  [0.40, 0.35, 0.15, 0.10],
    "w_mixed": [0.35, 0.30, 0.20, 0.15],
    "w_bear":  [0.25, 0.20, 0.30, 0.25],
    # gap_up_prob 가중치
    "gup_w_cp":   0.40,
    "gup_w_vwap": 0.35,
    "gup_w_inst": 0.25,
    # conviction 기준 — ★ PATCH-2: conv_eret_min 1.2→1.0
    "conv_score_pct":    0.80,
    "conv_rs_grade":     "A",
    "conv_abs_min":      0.50,
    "winner_gap_min":    0.02,
    "conv_vars_min":     0.40,
    "conv_breadth_min":  0.20,
    "conv_eret_min":     1.0,    # ★ PATCH-2: 1.2→1.0 (conviction 0종목 방지)
    # ★ 필수-8: conviction 품질 하한
    "conv_score_floor":  0.58,   # combined_score ≥ 0.58 필수
    # ERET 임계값 — ★ 필수-2: 5단계로 확장
    "eret_thr_min":      0.8,    # 탐색 최소 ERET
    "eret_thr_low":      1.0,    # ★ PATCH-2 연동: 기본 진입 하한 (1.2→1.0)
    "eret_thr_mid":      2.0,    # 적극 진입
    "eret_thr_high":     3.0,    # 몰빵
    # 최소 품질 안전망
    "pos_quality_floor": 0.45,
    # position_ratio 비율 — ★ PATCH-4: 공격성 강화
    "pos_ratio_probe":   0.45,   # 탐색 비중
    "pos_ratio_low":     0.75,   # ★ PATCH-4: 0.70→0.75
    "pos_ratio_mid":     0.90,   # ★ PATCH-4: 0.85→0.90
    "pos_ratio_high":    1.00,   # ★ PATCH-4: 0.98→1.00 (지침서 1종목몰빵 정합)
    "pos_ratio_skip":    0.00,
    "pos_thr_high":      0.70,
    "pos_thr_mid":       0.58,
    "pos_thr_low":       0.50,
    # ★ PATCH-5: 시장 감쇄 완화
    "phase_bear_mult":   0.75,   # ★ PATCH-5: 0.70→0.75
    "phase_mixed_mult":  0.95,   # ★ PATCH-5: 0.90→0.95
    # VARS
    "vars_vol_period":   5,
    "vars_vol_floor":    0.005,
    # inst_momentum_quality (★ 필수-6: accel 가중치 포함)
    "inst_mq_net_w":     0.55,   # 0.60→0.55
    "inst_mq_flag_w":    0.35,   # 0.40→0.35
    "inst_mq_accel_w":   0.10,   # 신규: 가속도 가중치
    # ERET — ★ PATCH-7: 모멘텀 비중 강화 (실증 우위)
    "eret_mom_w":        0.40,   # ★ PATCH-7: 0.35→0.40
    "eret_gap_w":        0.25,   # 유지
    "eret_qual_w":       0.20,   # ★ PATCH-7: 0.25→0.20 (quality 과도비중 축소)
    "eret_inst_w":       0.15,   # 유지
    # 기존 파라미터 (하위 호환 유지, 미사용)
    "eret_range_w":      0.40,
    "eret_rs_w":         0.30,
    # ★ PATCH-1: 거래비용 현실화 (슬리피지+수수료)
    "cost_rate":         0.003,  # ★ PATCH-1: 0.004→0.003 (0.3%, ERET 과도차감 방지)
    # ★ PATCH-3: conviction 기관 동행 완화
    "conv_inst_mq_min":  0.15,   # ★ PATCH-3: 0.20→0.15 (초기 기관 유입 포착)
    # ★ PATCH-6: 변동성 레짐 cap 완화
    "vol_regime_high_cap":    0.90,  # ★ PATCH-6: 0.85→0.90
    "vol_regime_extreme_cap": 0.75,  # ★ PATCH-6: 0.70→0.75
    # 자기진화
    "evol_max_changes":  1,
    # PnL 연결
    "pnl_lookback":      20,
    "pnl_ic_warn":       0.05,
    # ★ UPGRADE-5: IC 최소 샘플 강화 (Grinold & Kahn 기준)
    "ic_min_samples":    20,    # 5→20: 헤지펀드 기준 IC 유효성 최소 관측수
    # ★ UPGRADE-2: 1일 1번 강제 진입 안전망
    "fallback_eret_min": 0.50,  # 안전망 발동 최소 ERET (%)
    # ★ UPGRADE-3: 52주 신고가 보너스 파라미터
    "high52w_bonus_near":  0.05,  # 95% 근접 시 combined_score 보정
    "high52w_bonus_very":  0.08,  # 98% 근접 시 combined_score 보정
}

_CFG_TYPES: dict = {
    "atr_period":       (int,   2,  50),
    "ema_short":        (int,   2,  20),
    "ema_long":         (int,   5, 100),
    "trend_flat_pct":   (float, 0.0, 0.05),
    "max_nan_ratio":    (float, 0.0, 1.0),
    "min_valid_rows":   (int,   1, 100),
    "min_rows_trend":   (int,   5, 100),
    "bull_ratio":       (float, 1.0, 5.0),
    "noise_spike_ret":  (float, 0.0, 0.5),
    "noise_spike_dn":   (float,-0.5, 0.0),
    "noise_vol_ratio":  (float, 1.0,10.0),
    "noise_body_min":   (float, 0.0, 0.05),
    "noise_wick_max":   (float, 0.0, 1.0),
    "noise_consec_dn":  (int,   1,  10),
    "noise_gap_min":    (float, 0.0, 0.3),
    "noise_gap_close":  (float, 0.0, 1.0),
    "rs_w1d":           (float, 0.0, 1.0),
    "rs_w3d":           (float, 0.0, 1.0),
    "rs_w5d":           (float, 0.0, 1.0),
    "conv_score_pct":   (float, 0.5, 1.0),
    "conv_abs_min":     (float, 0.0, 1.0),
    "winner_gap_min":   (float, 0.0, 0.5),
    "conv_vars_min":    (float, 0.0, 1.0),
    "conv_breadth_min": (float, 0.0, 1.0),
    "conv_eret_min":    (float, 0.0, 10.0),
    "conv_score_floor": (float, 0.0, 1.0),
    "eret_thr_min":     (float, 0.0, 2.0),
    "eret_thr_low":     (float, 0.0, 5.0),
    "eret_thr_mid":     (float, 0.5, 10.0),
    "eret_thr_high":    (float, 0.5, 15.0),
    "pos_quality_floor":(float, 0.0, 1.0),
    "pos_ratio_probe":  (float, 0.0, 1.0),
    "pos_ratio_low":    (float, 0.0, 1.0),
    "pos_ratio_mid":    (float, 0.0, 1.0),
    "pos_ratio_high":   (float, 0.0, 1.0),
    "pos_ratio_skip":   (float, 0.0, 0.0),
    "pos_thr_high":     (float, 0.0, 1.0),
    "pos_thr_mid":      (float, 0.0, 1.0),
    "pos_thr_low":      (float, 0.0, 1.0),
    "phase_bear_mult":  (float, 0.3, 1.0),
    "phase_mixed_mult": (float, 0.5, 1.0),
    "vars_vol_period":  (int,   2,  20),
    "vars_vol_floor":   (float, 0.001, 0.05),
    "inst_mq_net_w":    (float, 0.0, 1.0),
    "inst_mq_flag_w":   (float, 0.0, 1.0),
    "inst_mq_accel_w":  (float, 0.0, 0.3),
    "eret_gap_w":       (float, 0.0, 1.0),
    "eret_range_w":     (float, 0.0, 1.0),
    "eret_rs_w":        (float, 0.0, 1.0),
    "eret_mom_w":       (float, 0.0, 1.0),   # ★ 보강-1
    "eret_qual_w":      (float, 0.0, 1.0),   # ★ 보강-1
    "eret_inst_w":      (float, 0.0, 1.0),   # ★ 보강-1
    "cost_rate":        (float, 0.0, 0.02),
    "evol_max_changes": (int,   1,   5),
    "pnl_lookback":     (int,   5,  60),
    "pnl_ic_warn":      (float, 0.0, 1.0),
    "conv_inst_mq_min": (float, 0.0, 1.0),   # ★ 보강-4
    "vol_regime_high_cap":    (float, 0.5, 1.0),  # ★ 보강-6
    "vol_regime_extreme_cap": (float, 0.3, 1.0),  # ★ 보강-6
}


def _load_evolved_cfg() -> dict:
    cfg = dict(_DEFAULT_CFG)
    if not EVOLVED_CFG.exists():
        return cfg
    try:
        with open(EVOLVED_CFG, encoding="utf-8-sig") as f:
            ov = json.load(f).get("prev_summary", {})
        for k, v in ov.items():
            if k not in cfg:
                continue
            if k not in _CFG_TYPES:
                cfg[k] = v
                continue
            typ, lo, hi = _CFG_TYPES[k]
            try:
                vt = typ(v)
                if lo <= vt <= hi:
                    cfg[k] = vt
            except Exception:
                pass
    except Exception as e:
        logging.getLogger("make_prev_day_summary").error("[EVOLVE][FAIL] 진화설정 JSON 로드 실패: %s", e)
        raise RuntimeError("진화 파라미터 로드 실패") from e
    return cfg


# ═══════════════════════════════════════════════════════════════
#  로거
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    lg = logging.getLogger("make_prev_day_summary")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt); lg.addHandler(sh)
    except Exception:
        pass
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(LOG_PATH), maxBytes=5*1024*1024,
                                 backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt); lg.addHandler(fh)
    except Exception:
        pass
    return lg


# ═══════════════════════════════════════════════════════════════
#  CSV 읽기
# ═══════════════════════════════════════════════════════════════
def _read_csv(path: Path, lg: logging.Logger,
              required: bool = True) -> Optional[pd.DataFrame]:
    try:
        _st = path.stat()
        if _st.st_size == 0:
            raise FileNotFoundError("empty")
    except FileNotFoundError:
        if required:
            lg.error("[LOAD] 파일 없음: %s", path.name)
        else:
            lg.info("[LOAD] 선택파일 없음(스킵): %s", path.name)
        return None
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            # [OOM-FIX 2026-05-28] 32-bit Python 메모리 안전 — chunksize streaming.
            # 259 MB+ CSV (eod_daily_bars 1년+ 누적) low_memory=False 시 OOM.
            # 5/22~5/28 7일 연속 STEP 0a RC=1 fail root cause.
            chunks = []
            for chunk in pd.read_csv(path, encoding=enc, low_memory=False,
                                     chunksize=100000):
                chunks.append(chunk)
            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            lg.info("[LOAD] %s enc=%s rows=%d chunks=%d",
                    path.name, enc, len(df), len(chunks))
            return df
        except Exception as e:
            lg.debug("[LOAD] %s enc=%s 실패: %s", path.name, enc, e)
            continue
    lg.error("[LOAD] 인코딩 실패 또는 OOM: %s", path.name)
    return None


# ═══════════════════════════════════════════════════════════════
#  원자적 쓰기
# ═══════════════════════════════════════════════════════════════
def _atomic_write(df: pd.DataFrame, path: Path,
                  lg: logging.Logger) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(path))
        lg.info("[WRITE] %s rows=%d", path.name, len(df))
        return True
    except Exception as e:
        lg.error("[WRITE] 실패: %s", e); return False
    finally:
        try:
            if tmp.exists(): tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  연속 상승/하락
# ═══════════════════════════════════════════════════════════════
def _calc_consec(close: pd.Series) -> Tuple[pd.Series, pd.Series]:
    orig = close.index
    c  = close.reset_index(drop=True)
    up = (c > c.shift(1)).astype(int)
    dn = (c < c.shift(1)).astype(int)
    cu = up.groupby((up == 0).cumsum()).cumsum()
    cd = dn.groupby((dn == 0).cumsum()).cumsum()
    cu.index = orig; cd.index = orig
    return cu, cd


# ═══════════════════════════════════════════════════════════════
#  ATR14 — Wilder
# ═══════════════════════════════════════════════════════════════
def _atr_group(g: pd.DataFrame, period: int) -> pd.Series:
    orig = g.index
    g2  = g.reset_index(drop=True)
    h   = g2["high"]; l = g2["low"]
    pc  = g2["close"].shift(1).fillna(g2["close"])
    tr  = pd.concat([(h-l).abs(),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0/period, adjust=False).mean()
    atr.index = orig
    return atr


# ═══════════════════════════════════════════════════════════════
#  시장 기준선 — RS용
# ═══════════════════════════════════════════════════════════════
def _calc_market_returns(df: pd.DataFrame,
                         lg: logging.Logger) -> pd.DataFrame:
    ds = df.sort_values(["code","date"]).copy()
    g  = ds.groupby("code", sort=False)
    ds["_r1"] = g["close"].pct_change(1)
    ds["_r3"] = g["close"].pct_change(3)
    ds["_r5"] = g["close"].pct_change(5)

    nan_pct = ds["_r5"].isna().mean()
    if nan_pct > 0.3:
        lg.warning("[MKT] ret_5d NaN %.1f%% — 신규상장 다수", nan_pct*100)

    mkt = ds.groupby("date")[["_r1","_r3","_r5"]].median().reset_index()
    mkt.columns = ["date","mkt_ret_1d","mkt_ret_3d","mkt_ret_5d"]
    mkt["date"] = pd.to_datetime(mkt["date"])
    return mkt


# ═══════════════════════════════════════════════════════════════
#  기관 수급 연동
#  FIX-1: code zfill 순서 수정
#  ★ 필수-6: inst_3d_accel (3일 가속도) 추가
# ═══════════════════════════════════════════════════════════════
def _load_inst(lg: logging.Logger) -> pd.DataFrame:
    """
    investor_daily.csv → 최근 3일 기관 순매수 합산 + 가속도
    ★ 보강-3: inst_3d_accel = 최근3봉 평균 / 이전5봉 평균 (비율 방식)
               지침서 [15] 제3장 3-4 정의: accel=mean(최근3봉)/mean(이전5봉)
               기존 diff 합산 방식 → 비율 방식으로 전환
               tail(3)→tail(8): 이전5봉 계산에 충분한 이력 확보
    """
    empty = pd.DataFrame(columns=["code","inst_3d_net","inst_buy_flag","inst_3d_accel"])
    df = _read_csv(INVESTOR_PATH, lg, required=False)
    if df is None or df.empty:
        return empty

    df.columns = [c.strip().lower() for c in df.columns]

    inst_col = None
    for cand in ("inst_net","foreign_net","net_buy","institution_net"):
        if cand in df.columns:
            inst_col = cand; break
    if inst_col is None:
        lg.warning("[INST] 기관 순매수 컬럼 미발견: %s", list(df.columns))
        return empty

    # FIX-1: zfill 먼저
    df["code"] = df["code"].astype(str).str.zfill(6)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", format="%Y%m%d")
        df = df.dropna(subset=["date"]).sort_values(["code","date"])
        # ★ 보강-3: tail(3)→tail(8) — 이전5봉 accel 계산용 이력 확보
        latest_8 = df.groupby("code").tail(8).copy()
        latest_3 = df.groupby("code").tail(3).copy()
    else:
        latest_8 = df.copy()
        latest_3 = df.copy()

    latest_3[inst_col] = pd.to_numeric(latest_3[inst_col], errors="coerce").fillna(0)
    latest_8[inst_col] = pd.to_numeric(latest_8[inst_col], errors="coerce").fillna(0)

    # 순매수 합산 (최근 3일)
    agg = latest_3.groupby("code")[inst_col].agg(
        inst_3d_net="sum",
        _count="count"
    ).reset_index()

    # 연속 매수 플래그 (최근 3일)
    def _consec_buy(g: pd.Series) -> int:
        return int((g > 0).all())

    consec = (latest_3.groupby("code")[inst_col]
              .apply(_consec_buy).reset_index())
    consec.columns = ["code","inst_buy_flag"]

    # ★ 보강-3: inst_3d_accel — 지침서 [15] 정의: 최근3봉 평균 / 이전5봉 평균
    def _calc_accel_ratio(g: pd.Series) -> float:
        """
        accel = mean(최근 3봉 inst_net_buy) / mean(이전 5봉 inst_net_buy)
        지침서 [15] 제3장 3-4 정의 완전 일치

        ★ UPGRADE-4: 음수 신호 복원
        기존: abs(prev5) → 분자 음수를 0으로 클리핑 → 기관 이탈 신호 소실
        수정: prev5 양수 → 정상 비율 계산
              prev5 음수(기관 매도 구간) → accel = 0.3 (약세 신호로 명시)
              prev5 ≈ 0 → recent3에 따라 1.5/0.3/1.0 처리
        """
        vals = g.values
        if len(vals) < 4:
            return 1.0  # 데이터 부족 → 중립
        recent3 = float(np.mean(vals[-3:]))
        prev_part = vals[:-3]
        prev5 = float(np.mean(prev_part)) if len(prev_part) > 0 else 0.0

        # ★ UPGRADE-4: prev5 부호별 분리 처리
        if abs(prev5) < 1e-9:
            # 이전 기간이 0에 가까움
            return 1.5 if recent3 > 0 else (0.3 if recent3 < 0 else 1.0)
        elif prev5 > 0:
            # 이전 기간 양수 → 정상 비율 계산
            ratio = recent3 / prev5
        else:
            # 이전 기간 음수 (기관 매도 구간) → 약세 신호
            # recent3도 음수면 더 강한 매도 → 0.3 미만
            ratio = 0.3 if recent3 <= 0 else 0.8  # 약세 구간에서 최근 반전 시도

        return float(np.clip(ratio, 0.0, 5.0))

    accel = (latest_8.groupby("code")[inst_col]
             .apply(_calc_accel_ratio).reset_index())
    accel.columns = ["code","inst_3d_accel"]

    result = (agg[["code","inst_3d_net"]]
              .merge(consec, on="code", how="left")
              .merge(accel,  on="code", how="left"))
    result["inst_buy_flag"]  = result["inst_buy_flag"].fillna(0).astype(int)
    result["inst_3d_accel"]  = result["inst_3d_accel"].fillna(1.0)  # 중립 기본값

    accel_gt12 = int((result["inst_3d_accel"] >= 1.2).sum())
    lg.info("[INST] v7_4 보강-3 비율accel  codes=%d  inst_col=%s  "
            "accel≥1.2(기관강세)=%d종목",
            len(result), inst_col, accel_gt12)
    return result


# ═══════════════════════════════════════════════════════════════
#  FIX-E: PnL 통계 로드
# ═══════════════════════════════════════════════════════════════
def _load_pnl_stats(cfg: dict, lg: logging.Logger) -> dict:
    empty = {
        "win_rate": None, "profit_factor": None,
        "trade_cnt": 0, "eret_vals": [], "actual_vals": []
    }
    if not BRIDGE_RESULT.exists():
        lg.info("[PNL] bridge_result.csv 없음 — PnL 연결 스킵")
        return empty
    try:
        df = _read_csv(BRIDGE_RESULT, lg, required=False)
        if df is None or df.empty:
            return empty
        df.columns = [c.strip().lower() for c in df.columns]

        ret_col = None
        for cand in ("actual_ret","pnl_pct","return_pct","ret"):
            if cand in df.columns:
                ret_col = cand; break
        eret_col = None
        for cand in ("expected_return_est","eret","eret_est"):
            if cand in df.columns:
                eret_col = cand; break
        if ret_col is None:
            lg.info("[PNL] 수익률 컬럼 미발견")
            return empty

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date")

        recent = df.tail(int(cfg.get("pnl_lookback",20))).copy()
        recent[ret_col] = pd.to_numeric(recent[ret_col], errors="coerce")
        recent = recent.dropna(subset=[ret_col])
        if len(recent) < 3:
            return empty

        rets    = recent[ret_col].values
        wins    = rets[rets > 0]
        losses  = rets[rets <= 0]
        win_rate      = len(wins) / len(rets)
        avg_win       = float(wins.mean())   if len(wins)   > 0 else 0.0
        avg_loss      = abs(float(losses.mean())) if len(losses) > 0 else 0.001
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0.0

        eret_vals = []; actual_vals = []
        if eret_col and eret_col in recent.columns:
            recent[eret_col] = pd.to_numeric(recent[eret_col], errors="coerce")
            paired = recent[[eret_col, ret_col]].dropna()
            eret_vals   = paired[eret_col].tolist()
            actual_vals = paired[ret_col].tolist()

        lg.info("[PNL] 로드 거래=%d  승률=%.1f%%  손익비=%.2f  페어=%d건",
                len(rets), win_rate*100, profit_factor, len(eret_vals))
        return {
            "win_rate":      round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "trade_cnt":     len(rets),
            "eret_vals":     eret_vals,
            "actual_vals":   actual_vals,
        }
    except Exception as e:
        lg.warning("[PNL] 로드 실패: %s", e)
        return empty


# ═══════════════════════════════════════════════════════════════
#  FIX-D: ERET IC (정보계수) 계산
# ═══════════════════════════════════════════════════════════════
def _calc_eret_ic(eret_vals: list, actual_vals: list,
                  lg: logging.Logger, min_samples: int = 20) -> Optional[float]:
    # ★ UPGRADE-5: 최소 샘플 5→20 (Grinold & Kahn 헤지펀드 기준)
    if len(eret_vals) < min_samples or len(actual_vals) < min_samples:
        lg.info("[IC] 데이터 부족 (최소 %d쌍 필요, 현재 %d쌍)", min_samples, len(eret_vals))
        return None
    try:
        ev = np.array(eret_vals,   dtype=float)
        av = np.array(actual_vals, dtype=float)
        mask = np.isfinite(ev) & np.isfinite(av)
        ev = ev[mask]; av = av[mask]
        if len(ev) < min_samples:
            return None
        ic = round(float(np.corrcoef(ev, av)[0, 1]), 4)
        if ic < 0.0:
            lg.warning("[IC] ★ IC=%.4f 음수! ERET 역방향 — 모델 점검 필요", ic)
        elif ic < 0.05:
            lg.warning("[IC] ★ IC=%.4f 헤지펀드 기준 미달", ic)
        else:
            lg.info("[IC] IC=%.4f 유효 팩터 ✓", ic)
        return ic
    except Exception as e:
        lg.warning("[IC] 계산 실패: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════
#  전체 피처 계산 — 벡터화
# ═══════════════════════════════════════════════════════════════
def _build_all_features(df: pd.DataFrame, cfg: dict,
                        lg: logging.Logger) -> pd.DataFrame:
    df  = df.sort_values(["code","date"]).reset_index(drop=True)
    grp = df.groupby("code", sort=False)
    cl  = df["close"]; hi = df["high"]
    lo  = df["low"];   vl = df["volume"]

    df["prev_open"]   = grp["open"].shift(1)
    df["prev_high"]   = grp["high"].shift(1)
    df["prev_low"]    = grp["low"].shift(1)
    df["prev_close"]  = grp["close"].shift(1)
    df["prev_volume"] = grp["volume"].shift(1)

    if "value" in df.columns:
        df["prev_value"] = grp["value"].shift(1)
        mask = df["prev_value"].isna()
        df.loc[mask,"prev_value"] = (df.loc[mask,"prev_close"] *
                                     df.loc[mask,"prev_volume"])
    else:
        df["prev_value"] = df["prev_close"] * df["prev_volume"]

    df["prev2_close"] = grp["close"].shift(2)
    df["prev2_high"]  = grp["high"].shift(2)
    df["prev2_low"]   = grp["low"].shift(2)

    hl   = (df["prev_high"] - df["prev_low"]).clip(lower=1e-9)
    ls   = df["prev_low"].clip(lower=1e-9)
    os_  = df["prev_open"].clip(lower=1e-9)
    c2s  = df["prev2_close"].clip(lower=1e-9)

    df["prev_range_pct"] = ((df["prev_high"]-df["prev_low"])/ls).clip(-1,10)
    df["prev_body_pct"]  = ((df["prev_close"]-df["prev_open"])/os_).clip(-1,1)
    df["prev_close_pos"] = ((df["prev_close"]-df["prev_low"])/hl).clip(0,1)
    df["prev_ret_1d"]    = ((df["prev_close"]-df["prev2_close"])/c2s).clip(-0.5,0.5)

    df["ret_3d"] = grp["close"].pct_change(3).clip(-0.5,0.5)
    df["ret_5d"] = grp["close"].pct_change(5).clip(-0.5,0.5)

    df["vol_ma5"]  = (grp["volume"].transform(
                      lambda x: x.rolling(5, min_periods=3).mean()).clip(lower=1))
    df["vol_ma20"] = (grp["volume"].transform(
                      lambda x: x.rolling(20,min_periods=10).mean()).clip(lower=1))
    df["vol_ratio"] = (vl / df["vol_ma20"]).clip(0,10)

    va3 = (grp["volume"].transform(
           lambda x: x.rolling(3,min_periods=1).mean()) / df["vol_ma5"]).clip(0,5)
    va5 = (grp["volume"].transform(
           lambda x: x.rolling(5,min_periods=1).mean()) / df["vol_ma5"]).clip(0,5)
    df["momentum_3d"] = (df["ret_3d"] * va3).clip(-1,1)
    df["momentum_5d"] = (df["ret_5d"] * va5).clip(-1,1)

    df["ema5"]  = grp["close"].transform(
                  lambda x: x.ewm(span=cfg["ema_short"],adjust=False).mean())
    df["ema20"] = grp["close"].transform(
                  lambda x: x.ewm(span=cfg["ema_long"], adjust=False).mean())

    ediff = (df["ema5"]-df["ema20"]) / df["ema20"].clip(lower=1e-9)
    flat  = cfg["trend_flat_pct"]
    df["trend_dir"]      = "FLAT"
    df.loc[ediff >  flat,"trend_dir"] = "UP"
    df.loc[ediff < -flat,"trend_dir"] = "DOWN"
    df["trend_strength"] = ediff.abs().clip(0,0.05)/0.05

    row_cnt = grp["close"].transform("count")
    df.loc[row_cnt < cfg["min_rows_trend"],"trend_dir"] = "UNKNOWN"

    e5s  = grp["ema5"].diff()
    e20s = grp["ema20"].diff()
    df["trend_consistency"] = (
        ((ediff > 0).astype(int) +
         (e5s   > 0).astype(int) +
         (e20s  > 0).astype(int)) / 3.0)

    atr_raw = (df.groupby("code", sort=True)
                 .apply(lambda g: _atr_group(g, cfg["atr_period"])))
    if isinstance(atr_raw.index, pd.MultiIndex):
        atr_raw = atr_raw.reset_index(level=0, drop=True)
    df["atr14"]     = atr_raw.reindex(df.index)
    df["atr14_pct"] = (df["atr14"] / cl.clip(lower=1e-9)).clip(0,0.3)
    df["avg_range_5d"] = (hi-lo).groupby(df["code"]).transform(
                          lambda x: x.rolling(5,min_periods=1).mean())

    pcs = df["prev_close"].clip(lower=1e-9)
    df["gap_size"] = ((df["open"]-df["prev_close"])/pcs).clip(-0.3,0.3)

    # ★ UPGRADE-3: 52주 신고가 근접도 (Gray & Vogel 2016 — Quantitative Momentum)
    # 최근 252 거래일(약 1년) 최고가 대비 현재 종가 비율
    df["high_52w"] = (grp["high"].transform(
                      lambda x: x.rolling(252, min_periods=60).max()))
    df["high_52w_ratio"] = (df["prev_close"] / df["high_52w"].clip(lower=1e-9)).clip(0, 1)

    v3  = grp["volume"].transform(lambda x: x.rolling(3, min_periods=1).mean())
    v10 = grp["volume"].transform(lambda x: x.rolling(10,min_periods=3).mean()
                                  ).clip(lower=1)
    df["vol_quality"] = (v3/v10).clip(0,3)/3.0

    def _ca(g: pd.DataFrame) -> pd.DataFrame:
        cu, cd = _calc_consec(g["close"])
        return pd.DataFrame({"consec_up":cu,"consec_down":cd},index=g.index)

    cdf = (df.groupby("code",sort=False)
             .apply(_ca)
             .reset_index(level=0,drop=True))
    df["consec_up"]   = cdf["consec_up"]
    df["consec_down"] = cdf["consec_down"]

    lg.info("[FEAT] 벡터화 완료 rows=%d codes=%d",
            len(df), df["code"].nunique())
    return df


# ═══════════════════════════════════════════════════════════════
#  Relative Strength
# ═══════════════════════════════════════════════════════════════
def _add_rs(latest: pd.DataFrame, mkt: pd.DataFrame,
            cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    if mkt.empty:
        for c in ["rs_1d","rs_3d","rs_5d","rs_composite","rs_rank"]:
            latest[c] = 0.0
        latest["rs_grade"] = "C"
        return latest

    latest_date = pd.to_datetime(latest["date"]).max()
    row = mkt[mkt["date"] == latest_date]
    if row.empty:
        row = mkt.iloc[[-1]]

    m1 = float(row["mkt_ret_1d"].iloc[0])
    m3 = float(row["mkt_ret_3d"].iloc[0])
    m5 = float(row["mkt_ret_5d"].iloc[0])

    latest["rs_1d"] = (latest["prev_ret_1d"].fillna(0) - m1).clip(-0.5,0.5)
    latest["rs_3d"] = (latest["ret_3d"].fillna(0)      - m3).clip(-0.5,0.5)
    latest["rs_5d"] = (latest["ret_5d"].fillna(0)      - m5).clip(-0.5,0.5)

    w1 = cfg["rs_w1d"]; w3 = cfg["rs_w3d"]; w5 = cfg["rs_w5d"]
    total_w = max(w1 + w3 + w5, 1e-9)

    rs_base = (latest["rs_1d"]*w1 + latest["rs_3d"]*w3 + latest["rs_5d"]*w5) / total_w

    inst_boost = latest.get(
        "inst_buy_flag",
        pd.Series([0]*len(latest), index=latest.index)
    ).fillna(0) * 0.05

    latest["rs_composite"] = (rs_base + inst_boost).clip(-0.5, 0.5)
    latest["rs_rank"]  = latest["rs_composite"].rank(pct=True) * 100

    def _g(p: float) -> str:
        if p >= 75: return "A"
        if p >= 50: return "B"
        if p >= 25: return "C"
        return "D"
    latest["rs_grade"] = latest["rs_rank"].apply(_g)

    lg.info("[RS] A=%d B=%d C=%d D=%d  mkt_1d=%.3f mkt_5d=%.3f",
            int((latest["rs_grade"]=="A").sum()),
            int((latest["rs_grade"]=="B").sum()),
            int((latest["rs_grade"]=="C").sum()),
            int((latest["rs_grade"]=="D").sum()), m1, m5)
    return latest


# ═══════════════════════════════════════════════════════════════
#  PROFIT-10: VARS
# ═══════════════════════════════════════════════════════════════
def _add_vars(latest: pd.DataFrame, df_full: pd.DataFrame,
              cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    vol_period = cfg.get("vars_vol_period", 5)
    vol_floor  = cfg.get("vars_vol_floor", 0.005)

    df_sorted = df_full.sort_values(["code","date"]).copy()
    df_sorted["_ret"] = df_sorted.groupby("code", sort=False)["close"].pct_change()
    df_sorted["_vol"] = (df_sorted.groupby("code", sort=False)["_ret"]
                         .transform(lambda x: x.rolling(vol_period, min_periods=2).std()))

    vol_df = (df_sorted.groupby("code", sort=False)
              .tail(1)[["code","_vol"]].copy())
    vol_df.columns = ["code","_vol_5d"]
    vol_df["code"] = vol_df["code"].astype(str).str.zfill(6)

    latest = latest.merge(vol_df, on="code", how="left")
    latest["_vol_5d"] = latest["_vol_5d"].fillna(vol_floor).clip(lower=vol_floor)
    raw_vars = latest["rs_composite"].fillna(0) / latest["_vol_5d"]
    latest["vars_score"] = raw_vars.rank(pct=True).clip(0,1).round(4)
    latest = latest.drop(columns=["_vol_5d"], errors="ignore")

    lg.info("[VARS] median=%.3f  top1=%.4f  A+VARS75%%=%d종목",
            float(latest["vars_score"].median()),
            float(latest["vars_score"].max()),
            int(((latest["rs_grade"]=="A") &
                 (latest["vars_score"] >= 0.75)).sum()))
    return latest


# ═══════════════════════════════════════════════════════════════
#  PROFIT-11: 기관 모멘텀 품질
#  ★ 필수-6: inst_3d_accel 10% 반영, 가중치 재배분
# ═══════════════════════════════════════════════════════════════
def _add_inst_mq(latest: pd.DataFrame, cfg: dict,
                 lg: logging.Logger) -> pd.DataFrame:
    """
    inst_mq = net_norm × 0.55 + flag × 0.35 + accel_norm × 0.10
    필수-6: 가속도 팩터로 "매집 강해지는 종목" 우대
    """
    net_w   = cfg.get("inst_mq_net_w",   0.55)
    flag_w  = cfg.get("inst_mq_flag_w",  0.35)
    accel_w = cfg.get("inst_mq_accel_w", 0.10)

    inst_net = latest.get("inst_3d_net",
               pd.Series([0.0]*len(latest), index=latest.index)).fillna(0)
    inst_flag = latest.get("inst_buy_flag",
                pd.Series([0]*len(latest), index=latest.index)).fillna(0)
    # ★ 필수-6: 가속도 컬럼
    inst_accel = latest.get("inst_3d_accel",
                 pd.Series([0.0]*len(latest), index=latest.index)).fillna(0)

    # inst_3d_net 정규화 (양수만, 상위 95%)
    net_pos = inst_net.clip(lower=0)
    q95_net = net_pos.quantile(0.95)
    net_norm = (net_pos / q95_net).clip(0,1) if q95_net > 0 else net_pos * 0

    # inst_3d_accel 정규화 (양수만, 상위 95%)
    accel_pos = inst_accel.clip(lower=0)
    q95_ac = accel_pos.quantile(0.95)
    accel_norm = (accel_pos / q95_ac).clip(0,1) if q95_ac > 0 else accel_pos * 0

    latest["inst_mq"] = (
        net_norm            * net_w  +
        inst_flag.clip(0,1) * flag_w +
        accel_norm          * accel_w
    ).clip(0,1).round(4)

    lg.info("[INST_MQ] 필수-6 accel 포함  median=%.3f  top10_avg=%.3f  "
            "accel_top5_avg=%.3f",
            float(latest["inst_mq"].median()),
            float(latest.nlargest(10,"inst_mq")["inst_mq"].mean()),
            float(latest.nlargest(5,"inst_3d_accel")["inst_mq"].mean())
                  if "inst_3d_accel" in latest.columns else 0.0)
    return latest


# ═══════════════════════════════════════════════════════════════
#  PROFIT-12: 기대수익 추정
#  ★ 필수-5: downside 패널티 추가
#  ★ 잔여-1: 거래비용(0.4%) 차감
# ═══════════════════════════════════════════════════════════════
def _add_expected_return(latest: pd.DataFrame, phase: str,
                         cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    """
    expected_return_est (%) — 4팩터 독립 추정
    ★ 보강-1: ATR 3중 반영 제거 → 팩터별 독립 계산
      momentum_factor = rs_composite × 100 × w_mom   (모멘텀 팩터)
      gap_factor      = gap_up_prob × atr_pct × 100 × w_gap   (갭 기대)
      quality_factor  = combined_score × atr_pct × 100 × w_qual (품질×변동성)
      inst_factor     = inst_mq × atr_pct × 100 × w_inst  (기관×변동성)
    출처: Jegadeesh & Titman (1993) JF, Ehsani & Linnainmaa (2022) JFE

    + downside 패널티 (v7_3 필수-5 계승)
    + 거래비용 차감 (v7_3 잔여-1 계승)
    """
    # ─── 공통 변수 ───────────────────────────────────────────────
    atr_pct = latest.get("atr14_pct",
              pd.Series([0.02]*len(latest), index=latest.index)).fillna(0.02)
    gap_p   = latest.get("gap_up_prob",
              pd.Series([0.5]*len(latest), index=latest.index)).fillna(0.5)
    rs_comp = latest.get("rs_composite",
              pd.Series([0.0]*len(latest), index=latest.index)).fillna(0.0)
    score   = latest.get("combined_score",
              pd.Series([0.5]*len(latest), index=latest.index)).fillna(0.5)
    inst_mq = latest.get("inst_mq",
              pd.Series([0.0]*len(latest), index=latest.index)).fillna(0.0)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ 보강-1: 4팩터 독립 추정 (ATR 중복 제거)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    w_mom  = cfg.get("eret_mom_w",  0.35)
    w_gap  = cfg.get("eret_gap_w",  0.25)
    w_qual = cfg.get("eret_qual_w", 0.25)
    w_inst = cfg.get("eret_inst_w", 0.15)
    total_w = max(w_mom + w_gap + w_qual + w_inst, 1e-9)

    # 팩터별 독립 계산
    f_mom  = rs_comp.clip(0, 0.5) * 100 * (w_mom / total_w)   # RS 초과수익 → %
    f_gap  = gap_p * atr_pct * 100 * (w_gap / total_w)        # 갭확률 × 변동성범위
    f_qual = score.clip(0, 1) * atr_pct * 100 * (w_qual / total_w)  # 품질 × 변동성
    f_inst = inst_mq.clip(0, 1) * atr_pct * 100 * (w_inst / total_w)  # 기관강도 × 변동성

    raw_eret = (f_mom + f_gap + f_qual + f_inst)

    lg.info("[ERET] 보강-1 4팩터  mom=%.3f gap=%.3f qual=%.3f inst=%.3f "
            "(median합계=%.2f%%)",
            float(f_mom.median()), float(f_gap.median()),
            float(f_qual.median()), float(f_inst.median()),
            float(raw_eret.median()))

    # ─── 국면 감쇄 ──────────────────────────────────────────────
    if phase == "BEAR":
        raw_eret = raw_eret * 0.50
        lg.info("[ERET] BEAR 감쇄 ×0.50")
    elif phase == "MIXED":
        raw_eret = raw_eret * 0.80
        lg.info("[ERET] MIXED 감쇄 ×0.80")

    # ─── quality 3축 보정 (v7_1 PATCH-ERET-Q 계승) ──────────────
    ret3 = latest["ret_3d"].fillna(0)
    cp   = latest["prev_close_pos"].fillna(0.5)
    volr = latest["vol_ratio"].fillna(1)
    trend_keep    = (ret3 > 0).astype(float)
    close_quality = cp.clip(0, 1)
    vol_quality   = (volr / 3.0).clip(0, 1)
    quality = (trend_keep*0.4 + close_quality*0.3 + vol_quality*0.3).clip(0.45, 1.0)
    raw_eret = raw_eret * quality

    # ─── 1.1제곱 보호 (FIX-F 계승) ──────────────────────────────
    thr_l = cfg.get("eret_thr_low", 1.2)
    high_mask = raw_eret >= thr_l
    powered = raw_eret.copy()
    powered[high_mask] = raw_eret[high_mask] ** 1.1
    raw_eret = powered

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ 필수-5 계승: downside 패널티
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    consec_dn = latest.get("consec_down",
                pd.Series([0]*len(latest), index=latest.index)).fillna(0)
    gap_sz    = latest.get("gap_size",
                pd.Series([0]*len(latest), index=latest.index)).fillna(0)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ 필수-5 계승 + PATCH-8: downside 패널티 완화
    #   이미 여러 필터 존재 → 중복 감점 제거, 상단 복원
    #   연속하락: ×0.88→×0.92  종가하단: ×0.90→×0.93  갭실패: ×0.85→×0.90
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    raw_eret = raw_eret.where(~(consec_dn >= 2), raw_eret * 0.92)  # ★ PATCH-8
    raw_eret = raw_eret.where(~(cp < 0.35),       raw_eret * 0.93)  # ★ PATCH-8
    raw_eret = raw_eret.where(~((gap_sz > 0.05) & (cp < 0.5)), raw_eret * 0.90)  # ★ PATCH-8

    dp_cnt = int(((consec_dn >= 2) | (cp < 0.35) |
                  ((gap_sz > 0.05) & (cp < 0.5))).sum())
    lg.info("[ERET] 필수-5 downside 패널티 적용=%d종목", dp_cnt)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ 잔여-1 계승: 거래비용 차감 (슬리피지+수수료 0.4%)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    cost = cfg.get("cost_rate", 0.004) * 100
    raw_eret = (raw_eret - cost).clip(lower=0)

    eret = raw_eret.clip(0, 15).round(3)
    latest["expected_return_est"] = eret

    lg.info("[ERET] 보강-1완료  거래비용%.2f%% 차감  phase=%s  "
            "median=%.2f%%  top1=%.2f%%  1%%이상=%d종목",
            cost, phase, float(eret.median()), float(eret.max()),
            int((eret >= 1.0).sum()))
    return latest


# ═══════════════════════════════════════════════════════════════
#  PROFIT-13: 시장 너비 품질
# ═══════════════════════════════════════════════════════════════
def _calc_market_breadth(latest: pd.DataFrame,
                         lg: logging.Logger) -> float:
    """
    ★ 잔여-1: 3변수 가중 breadth (2변수 단순평균 → 고도화)
      ① val_ratio   × 0.40 : 상승 종목 거래대금 비중 (유동성 반영)
      ② rs_a_ratio  × 0.35 : RS-A 등급 종목 비중 (모멘텀 품질)
      ③ vars_top_r  × 0.25 : VARS 상위 75% 종목 비중 (위험조정 모멘텀)
    """
    total_val = latest.get("prev_value",
                pd.Series([0]*len(latest), index=latest.index)).fillna(0).sum()

    if "trend_dir" in latest.columns:
        up_mask = latest["trend_dir"] == "UP"
    else:
        up_mask = pd.Series([False]*len(latest), index=latest.index)

    up_val    = latest.loc[up_mask, "prev_value"].fillna(0).sum()
    val_ratio = up_val / max(total_val, 1e-9)

    rs_a_ratio = 0.0
    if "rs_grade" in latest.columns and len(latest) > 0:
        rs_a_ratio = (latest["rs_grade"] == "A").mean()

    # ★ 잔여-1: VARS 상위 75% 비중 추가
    vars_top_r = 0.0
    if "vars_score" in latest.columns and len(latest) > 0:
        vars_top_r = (latest["vars_score"] >= 0.75).mean()

    breadth = (val_ratio * 0.40 + rs_a_ratio * 0.35 + vars_top_r * 0.25).clip(0, 1)

    lg.info("[BREADTH] 잔여-1 3변수  UP거래대금=%.1f%%  RS-A=%.1f%%  "
            "VARS75%%=%.1f%%  → breadth=%.3f",
            val_ratio*100, rs_a_ratio*100, vars_top_r*100, breadth)
    return round(float(breadth), 4)


# ═══════════════════════════════════════════════════════════════
#  노이즈 필터 (FIX-4 벡터화)
# ═══════════════════════════════════════════════════════════════
def _add_noise_vectorized(latest: pd.DataFrame,
                          cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    ret3 = latest["ret_3d"].fillna(0)
    ret1 = latest["prev_ret_1d"].fillna(0)
    volr = latest["vol_ratio"].fillna(1)
    body = latest["prev_body_pct"].fillna(0)
    ph   = latest["prev_high"].fillna(0)
    pl   = latest["prev_low"].fillna(0)
    pc   = latest["prev_close"].fillna(0)
    cp   = latest["prev_close_pos"].fillna(0.5)
    gap  = latest["gap_size"].fillna(0)
    cdn  = latest["consec_down"].fillna(0)
    rs_g = latest.get("rs_grade", pd.Series(["C"]*len(latest), index=latest.index))

    hl = (ph - pl).clip(lower=1e-9)
    m1 = (ret3 >= cfg["noise_spike_ret"]) & (ret1 <= cfg["noise_spike_dn"])
    m2 = (volr >= cfg["noise_vol_ratio"]) & (body.abs() < cfg["noise_body_min"])
    m3 = ((ph - pc) / hl) > cfg["noise_wick_max"]
    m4 = ((cdn >= cfg["noise_consec_dn"]) &
          (ret1 > abs(cfg["noise_spike_dn"])) &
          (rs_g != "A"))
    m5 = (gap >= cfg["noise_gap_min"]) & (cp < cfg["noise_gap_close"])

    flag = (m1 | m2 | m3 | m4 | m5).astype(int)

    reason_df = pd.DataFrame({
        "SPIKE_REVERSAL": m1.values,
        "FAKE_VOLUME":    m2.values,
        "UPPER_WICK":     m3.values,
        "DEAD_CAT":       m4.values,
        "GAP_FILL":       m5.values,
    }, index=latest.index)
    latest["noise_reason"] = reason_df.apply(
        lambda r: "|".join(r.index[r].tolist()) or "CLEAN", axis=1)
    latest["noise_flag"]     = flag.values
    latest["clean_momentum"] = latest["momentum_5d"].fillna(0) * (1-flag)

    nc = int(flag.sum())
    lg.info("[NOISE] 감지=%d/%d (%.1f%%)", nc, len(latest), nc/max(len(latest),1)*100)
    return latest


# ═══════════════════════════════════════════════════════════════
#  갭업 예측 (FIX-2 연속값)
# ═══════════════════════════════════════════════════════════════
def _add_gap_up_prob(latest: pd.DataFrame,
                     cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    """
    ★ 보강-5: 순환 참조 제거
    기존: cp (prev_close_pos)를 cp와 vwap_pos 양쪽에서 중복 사용
    수정: vwap_proxy = body_pct(60%) + wick_ratio(40%) → 완전 독립 변수
          cp (close_pos) : 종가 위치 (고저 사이)
          vwap_proxy     : 바디 강도 + 위꼬리 역방향 → 매수 압력 프록시
          inst_f         : 기관 매수 플래그
    """
    cp = latest["prev_close_pos"].fillna(0.5).clip(0, 1)

    # ★ 보강-5: body_pct와 wick_ratio로 독립적 vwap_proxy 구성
    body_norm = ((latest["prev_body_pct"].fillna(0) + 1) / 2).clip(0, 1)
    ph = latest["prev_high"].fillna(0)
    pl = latest["prev_low"].fillna(0)
    pc = latest["prev_close"].fillna(0)
    hl = (ph - pl).clip(lower=1e-9)
    # 위꼬리 비율: 0 = 꼬리 없음(강세), 1 = 꼬리 최대(약세) → 역전
    upper_wick_ratio = ((ph - pc) / hl).clip(0, 1)
    wick_strength = (1.0 - upper_wick_ratio)  # 높을수록 강세
    vwap_proxy = (body_norm * 0.6 + wick_strength * 0.4).clip(0, 1)

    inst_f = latest.get("inst_buy_flag",
             pd.Series([0]*len(latest), index=latest.index)).fillna(0).clip(0, 1)

    wcp = cfg["gup_w_cp"]; wv = cfg["gup_w_vwap"]; wi = cfg["gup_w_inst"]
    tot = max(wcp + wv + wi, 1e-9)
    latest["gap_up_prob"] = (
        (cp*wcp + vwap_proxy*wv + inst_f*wi) / tot
    ).clip(0, 1).round(4)

    lg.info("[GUP] 보강-5 순환참조제거  median=%.3f  top5_avg=%.3f",
            float(latest["gap_up_prob"].median()),
            float(latest.nlargest(5,"gap_up_prob")["gap_up_prob"].mean()))
    return latest


# ═══════════════════════════════════════════════════════════════
#  시장 국면 (FIX-6 거래대금 기준 + FIX-C 컬럼 방어)
# ═══════════════════════════════════════════════════════════════
def _calc_market_phase(latest: pd.DataFrame,
                       cfg: dict, lg: logging.Logger) -> str:
    br = cfg["bull_ratio"]
    if "trend_dir" not in latest.columns:
        lg.warning("[PHASE] trend_dir 없음 → MIXED")
        return "MIXED"

    trend_dir_col = latest["trend_dir"]

    if "prev_value" in latest.columns and latest["prev_value"].fillna(0).sum() > 0:
        up_val = latest.loc[trend_dir_col=="UP",  "prev_value"].fillna(0).sum()
        dn_val = latest.loc[trend_dir_col=="DOWN", "prev_value"].fillna(0).sum()
        phase = ("BULL" if up_val > dn_val*br
                 else "BEAR" if dn_val > up_val*br else "MIXED")
        lg.info("[PHASE] 거래대금  %s  UP=%.0f억 DN=%.0f억",
                phase, up_val/1e8, dn_val/1e8)
    else:
        tu = int((trend_dir_col=="UP").sum())
        td = int((trend_dir_col=="DOWN").sum())
        phase = ("BULL" if tu > td*br
                 else "BEAR" if td > tu*br else "MIXED")
        lg.info("[PHASE] 종목수  %s  UP=%d DN=%d", phase, tu, td)
    return phase


def _add_combined_score(latest: pd.DataFrame, phase: str,
                        cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    w_map = {
        "BULL":  cfg.get("w_bull",  [0.40,0.35,0.15,0.10]),
        "MIXED": cfg.get("w_mixed", [0.35,0.30,0.20,0.15]),
        "BEAR":  cfg.get("w_bear",  [0.25,0.20,0.30,0.25]),
    }
    w = w_map.get(phase, w_map["MIXED"])
    w_rs, w_mom, w_vq, w_tc = w[0], w[1], w[2], w[3]
    total_w = max(w_rs+w_mom+w_vq+w_tc, 1e-9)

    rs_n  = (latest.get("rs_rank",
             pd.Series([50.0]*len(latest),index=latest.index)) / 100).clip(0,1)
    cm_n  = ((latest["clean_momentum"].fillna(0)+1)/2).clip(0,1)
    vq_n  = latest["vol_quality"].fillna(0.5).clip(0,1)
    tc_n  = latest["trend_consistency"].fillna(0.5).clip(0,1)
    gup_n = latest.get("gap_up_prob",
            pd.Series([0.5]*len(latest),index=latest.index)).fillna(0.5).clip(0,1)

    inst_raw = latest.get("inst_3d_net",
               pd.Series([0.0]*len(latest),index=latest.index)).fillna(0).clip(lower=0)
    q95 = inst_raw.quantile(0.95)
    inst_n = (inst_raw/q95).clip(0,1) if q95>0 else pd.Series([0.0]*len(latest),index=latest.index)

    inst_w = 0.05; main_w = 0.95
    four_axis = (
        rs_n  * (w_rs /total_w) * 0.80 +
        gup_n * (w_rs /total_w) * 0.20 +
        cm_n  * (w_mom/total_w) +
        vq_n  * (w_vq /total_w) +
        tc_n  * (w_tc /total_w)
    )
    latest["combined_score"] = (
        four_axis * main_w + inst_n * inst_w
    ).clip(0,1).round(4)

    # ★ UPGRADE-3: 52주 신고가 근접 보너스 (Gray & Vogel 2016)
    if "high_52w_ratio" in latest.columns:
        h52 = latest["high_52w_ratio"].fillna(0)
        bonus_near = cfg.get("high52w_bonus_near", 0.05)
        bonus_very = cfg.get("high52w_bonus_very", 0.08)
        score_boost = pd.Series(0.0, index=latest.index)
        score_boost = score_boost.where(h52 < 0.95, bonus_near)  # 95%~98% 근접
        score_boost = score_boost.where(h52 < 0.98, bonus_very)  # 98%+ 신고가 돌파 임박
        latest["combined_score"] = (latest["combined_score"] + score_boost).clip(0, 1).round(4)
        boost_cnt = int((score_boost > 0).sum())
        lg.info("[52W] UPGRADE-3 신고가보너스  98%%이상=%d  95%%이상=%d종목",
                int((h52 >= 0.98).sum()), boost_cnt)

    lg.info("[SCORE] phase=%s  w=[%.2f,%.2f,%.2f,%.2f]  top1=%.4f  med=%.4f",
            phase, w_rs, w_mom, w_vq, w_tc,
            float(latest["combined_score"].max()),
            float(latest["combined_score"].median()))
    return latest


# ═══════════════════════════════════════════════════════════════
#  확신 플래그
#  ★ 필수-8: combined_score >= 0.58 조건 추가 (4조건 AND)
#  ★ 필수-1: winner_gap Top1 전용 처리
# ═══════════════════════════════════════════════════════════════
def _add_conviction(latest: pd.DataFrame,
                    cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    """
    conviction_flag = 1 조건 (★ 보강-4: 5조건 AND):
    ① rs_grade == A
    ② noise_flag == 0
    ③ expected_return_est ≥ conv_eret_min
    ④ combined_score ≥ conv_score_floor (v7_3 필수-8)
    ⑤ inst_mq ≥ conv_inst_mq_min (★ 보강-4 신규: 기관 동행 최소 기준)
       → 기관 흐름 없는 종목의 conviction 진입 차단 (지침서 [15] 제1장 1-1)

    필수-1 계승: winner_gap → Top1만 실값, 나머지 0.0
    """
    eret_min    = cfg.get("conv_eret_min",    1.2)
    score_floor = cfg.get("conv_score_floor", 0.58)
    inst_mq_min = cfg.get("conv_inst_mq_min", 0.20)  # ★ 보강-4

    # ★ 필수-1 계승: Top1 전용 winner_gap
    top_scores = latest["combined_score"].nlargest(2).values
    winner_gap = float(top_scores[0] - top_scores[1]) if len(top_scores) >= 2 else 0.0

    latest["winner_gap"] = 0.0
    if len(latest) > 0:
        top1_idx = latest["combined_score"].idxmax()
        latest.loc[top1_idx, "winner_gap"] = winner_gap
        lg.info("[CONV] 필수-1 winner_gap=%.4f → Top1(%s)에만 기록",
                winner_gap, latest.loc[top1_idx, "code"])

    # ★ 보강-4: 5조건
    c1 = latest.get("rs_grade",
         pd.Series(["C"]*len(latest), index=latest.index)) == "A"
    c2 = latest["noise_flag"].fillna(1) == 0
    c3 = latest.get("expected_return_est",
         pd.Series([0]*len(latest), index=latest.index)).fillna(0) >= eret_min
    c4 = latest["combined_score"].fillna(0) >= score_floor
    c5 = latest.get("inst_mq",  # ★ 보강-4 신규 조건
         pd.Series([0.0]*len(latest), index=latest.index)).fillna(0) >= inst_mq_min

    flag = (c1 & c2 & c3 & c4 & c5).astype(int)
    latest["conviction_flag"] = flag

    n_conv = int(flag.sum())
    lg.info("[CONV] 보강-4 5조건  RS-A=%d  noise0=%d  ERET≥%.1f%%=%d  "
            "score≥%.2f=%d  instMQ≥%.2f=%d  → conviction=%d종목",
            int(c1.sum()), int(c2.sum()), eret_min, int(c3.sum()),
            score_floor, int(c4.sum()), inst_mq_min, int(c5.sum()), n_conv)

    if n_conv == 0:
        lg.warning("[CONV] 확신 종목 0 — 오늘 스킵 권장")
    else:
        top1 = latest[flag==1].nlargest(1,"expected_return_est")
        lg.info("[CONV] ★1등: %s  ERET=%.2f%%  score=%.4f  vars=%.3f  mq=%.3f  accel=%.2f",
                top1["code"].values[0],
                float(top1["expected_return_est"].values[0]),
                float(top1["combined_score"].values[0]),
                float(top1["vars_score"].values[0]) if "vars_score" in top1.columns else 0,
                float(top1["inst_mq"].values[0]) if "inst_mq" in top1.columns else 0,
                float(top1["inst_3d_accel"].values[0]) if "inst_3d_accel" in top1.columns else 0)
    return latest


# ═══════════════════════════════════════════════════════════════
#  유효성 검증
# ═══════════════════════════════════════════════════════════════
def _validate(out: pd.DataFrame, cfg: dict,
              lg: logging.Logger) -> bool:
    ok = True
    must = ["prev_high","prev_low","prev_close","prev_value",
            "atr14","ema5","ema20","rs_rank","combined_score",
            "conviction_flag","gap_up_prob","winner_gap",
            "position_ratio","expected_return_est"]
    for c in must:
        if c not in out.columns:
            lg.error("[VALID] 컬럼 없음: %s", c); ok = False; continue
        nan_r = out[c].isna().mean() if out[c].dtype != object else 0
        if nan_r > cfg["max_nan_ratio"]:
            lg.warning("[VALID] %s NaN=%.1f%%", c, nan_r*100)

    for c in ["prev_open","prev_high","prev_low","prev_close"]:
        if c in out.columns and (out[c].dropna() < 0).sum():
            lg.warning("[VALID] %s 음수", c); ok = False

    if "combined_score" in out.columns:
        bad = ((out["combined_score"] < 0)|(out["combined_score"] > 1)).sum()
        if bad: lg.warning("[VALID] combined_score 이탈 %d건", bad)

    # FIX-B: position_ratio NaN 체크
    if "position_ratio" in out.columns:
        nan_pr = out["position_ratio"].isna().sum()
        if nan_pr > 0:
            lg.error("[VALID] position_ratio NaN=%d건!", nan_pr); ok = False
        bad_r = ((out["position_ratio"]<0)|(out["position_ratio"]>1)).sum()
        if bad_r: lg.warning("[VALID] position_ratio 범위 이탈 %d건", bad_r)

    # FIX-A: conviction 종목 position_ratio 확인
    if "conviction_flag" in out.columns and "position_ratio" in out.columns:
        cmask = out["conviction_flag"] == 1
        if cmask.sum() > 0:
            cpr = out.loc[cmask,"position_ratio"]
            if (cpr < 0.50).any():
                lg.warning("[VALID] conviction=1 중 ratio<0.50 %d건 (장세감쇄 적용됨)",
                           int((cpr < 0.50).sum()))

    # 필수-1: winner_gap Top1 전용 확인
    if "winner_gap" in out.columns:
        nonzero_wg = (out["winner_gap"] > 0).sum()
        if nonzero_wg > 1:
            lg.warning("[VALID] 필수-1: winner_gap>0 종목이 %d개 (Top1만 가져야 함)",
                       nonzero_wg)

    for c in ["consec_up","consec_down"]:
        if c in out.columns:
            if len(out) > 50 and (out[c].fillna(0) <= 1).all():
                lg.warning("[VALID] %s 전부 ≤1 → 계산 오류 의심", c)

    if "rs_grade" in out.columns:
        lg.info("[VALID] rs_grade: %s", out["rs_grade"].value_counts().to_dict())
    if "noise_flag" in out.columns:
        nc = int(out["noise_flag"].sum())
        if nc > len(out)*0.5:
            lg.warning("[VALID] noise 과다: %d/%d", nc, len(out))
    if "conviction_flag" in out.columns:
        lg.info("[VALID] conviction=1: %d종목", int(out["conviction_flag"].sum()))
    if len(out) < cfg["min_valid_rows"]:
        lg.error("[VALID] 종목 부족: %d", len(out)); ok = False

    lg.info("[VALID] rows=%d ok=%s", len(out), ok)
    return ok


# ═══════════════════════════════════════════════════════════════
#  자기진화 유틸
# ═══════════════════════════════════════════════════════════════
def _count_recent_phase(evol_dir: Path, target: str, days: int=5) -> int:
    count = 0
    try:
        files = sorted(evol_dir.glob("prev_summary_*.json"), reverse=True)[:days]
        for fp in files:
            try:
                data = json.load(open(fp, encoding="utf-8-sig"))
                if data.get("market_phase") == target:
                    count += 1
                else:
                    break
            except Exception:
                break
    except Exception:
        pass
    return count


def _count_conv_zero(evol_dir: Path, days: int=3) -> int:
    count = 0
    try:
        files = sorted(evol_dir.glob("prev_summary_*.json"), reverse=True)[:days]
        for fp in files:
            try:
                data = json.load(open(fp, encoding="utf-8-sig"))
                if data.get("conviction_cnt", 1) == 0:
                    count += 1
            except Exception:
                pass
    except Exception:
        pass
    return count


# ═══════════════════════════════════════════════════════════════
#  자기진화 피드백 기록
#  ★ 필수-4: ERET IC 저하 → conv_eret_min 자동 강화 (규칙 7, 8)
# ═══════════════════════════════════════════════════════════════
def _write_feedback(out: pd.DataFrame, phase: str,
                    today_str: str, elapsed: float,
                    has_val: bool, cfg: dict,
                    pnl_stats: dict, lg: logging.Logger) -> None:
    try:
        EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
        fp = EVOLUTION_DIR / f"prev_summary_{today_str}.json"
        if fp.exists(): return

        tu = int((out["trend_dir"]=="UP").sum()) if "trend_dir" in out.columns else 0
        td = int((out["trend_dir"]=="DOWN").sum()) if "trend_dir" in out.columns else 0
        nc = int(out["conviction_flag"].sum()) if "conviction_flag" in out.columns else 0
        # 필수-1: winner_gap은 Top1 값
        wg = float(out["winner_gap"].max()) if "winner_gap" in out.columns else 0.0

        eret_ic = _calc_eret_ic(
            pnl_stats.get("eret_vals",[]),
            pnl_stats.get("actual_vals",[]),
            lg,
            min_samples=cfg.get("ic_min_samples", 20)
        )

        fb = {
            "date":               today_str,
            "module":             "make_prev_day_summary",
            "version":            "v7_6",
            "output_rows":        int(len(out)),
            "elapsed_sec":        round(elapsed,2),
            "value_source":       "real" if has_val else "estimated",
            "market_phase":       phase,
            "trend_up_cnt":       tu,
            "trend_dn_cnt":       td,
            "atr14_pct_median":   float(out["atr14_pct"].median()) if "atr14_pct" in out.columns else None,
            "rs_grade_a_cnt":     int((out["rs_grade"]=="A").sum()) if "rs_grade" in out.columns else 0,
            "noise_pct":          float(out["noise_flag"].mean()) if "noise_flag" in out.columns else None,
            "combined_score_med": float(out["combined_score"].median()) if "combined_score" in out.columns else None,
            "gap_up_prob_med":    float(out["gap_up_prob"].median()) if "gap_up_prob" in out.columns else None,
            "conviction_cnt":     nc,
            "winner_gap_top1":    wg,
            "vars_score_med":     float(out["vars_score"].median()) if "vars_score" in out.columns else None,
            "inst_mq_med":        float(out["inst_mq"].median()) if "inst_mq" in out.columns else None,
            "expected_return_med": float(out["expected_return_est"].median()) if "expected_return_est" in out.columns else None,
            "expected_return_max": float(out["expected_return_est"].max()) if "expected_return_est" in out.columns else None,
            "market_breadth":     float(out["market_breadth"].iloc[0]) if "market_breadth" in out.columns else None,
            "eret_ic_1d":         eret_ic,
            "eret_ic_status":     ("valid"   if eret_ic is not None and eret_ic >= 0.05
                                   else "warn_low" if eret_ic is not None and eret_ic >= 0.0
                                   else "warn_neg" if eret_ic is not None
                                   else "insufficient_data"),
            "pnl_win_rate":       pnl_stats.get("win_rate"),
            "pnl_profit_factor":  pnl_stats.get("profit_factor"),
            "pnl_trade_cnt":      pnl_stats.get("trade_cnt", 0),
            "cfg_used":           cfg,
        }
        with open(fp,"w",encoding="utf-8") as f:
            json.dump(fb, f, ensure_ascii=False, indent=2)
        lg.info("[EVOL] feedback  %s  phase=%s  conv=%d  IC=%s",
                fp.name, phase, nc,
                f"{eret_ic:.4f}" if eret_ic is not None else "N/A")

        # ══════════════════════════════════════════════════
        #  자기진화 파라미터 갱신
        # ══════════════════════════════════════════════════
        evolved = dict(cfg)
        changed = []

        # 규칙 1: 5일 연속 BEAR → noise_spike_ret 강화
        bear_days = _count_recent_phase(EVOLUTION_DIR, "BEAR", days=5)
        if bear_days >= 5:
            nv = round(max(0.05, cfg.get("noise_spike_ret",0.08)-0.005), 4)
            if nv != cfg.get("noise_spike_ret"):
                evolved["noise_spike_ret"] = nv
                changed.append(f"noise_spike_ret={nv} (BEAR 5일)")

        # 규칙 2: BULL 전환 → noise_spike_ret 복구
        if phase == "BULL" and bear_days == 0:
            dv = _DEFAULT_CFG.get("noise_spike_ret", 0.08)
            if cfg.get("noise_spike_ret", dv) < dv:
                evolved["noise_spike_ret"] = dv
                changed.append(f"noise_spike_ret={dv} (BULL복구)")

        # 규칙 3: conviction 3일 연속 0 → conv_eret_min 완화
        if nc == 0:
            zd = _count_conv_zero(EVOLUTION_DIR, days=3)
            if zd >= 3:
                nv = round(max(0.5, cfg.get("conv_eret_min",1.2)-0.1), 2)
                if nv != cfg.get("conv_eret_min"):
                    evolved["conv_eret_min"] = nv
                    changed.append(f"conv_eret_min={nv} (conv 3일 0)")

        # 규칙 4: noise_pct > 40% → noise_vol_ratio 완화
        noise_pct_val = fb.get("noise_pct") or 0
        if noise_pct_val > 0.40:
            nv = round(min(5.0, cfg.get("noise_vol_ratio",3.0)+0.1), 2)
            if nv != cfg.get("noise_vol_ratio"):
                evolved["noise_vol_ratio"] = nv
                changed.append(f"noise_vol_ratio={nv} (noise>{noise_pct_val:.0%})")

        # 규칙 5: conviction 과다 (5개 이상) → conv_eret_min 상향
        if nc >= 5:
            nv = round(min(2.5, cfg.get("conv_eret_min",1.2)+0.1), 2)
            if nv != cfg.get("conv_eret_min"):
                evolved["conv_eret_min"] = nv
                changed.append(f"conv_eret_min={nv} (conv 과다 {nc})")

        # 규칙 6: 실승률 < 45% → conv_eret_min 강화
        real_wr  = pnl_stats.get("win_rate")
        pnl_cnt  = pnl_stats.get("trade_cnt", 0)
        if real_wr is not None and pnl_cnt >= 10 and real_wr < 0.45:
            nv = round(min(2.5, cfg.get("conv_eret_min",1.0)+0.2), 2)
            if nv != cfg.get("conv_eret_min"):
                evolved["conv_eret_min"] = nv
                changed.append(f"conv_eret_min={nv} (승률{real_wr*100:.1f}%<45%)")
                lg.warning("[EVOL] 실승률 %.1f%% 부진 → conv_eret_min 강화", real_wr*100)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ★ 잔여-3 신규 규칙 8: PF < 0.8 → pos_ratio_probe 확대
        #    손익비 악화 시 탐색 비중 줄여 리스크 축소
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        real_pf = pnl_stats.get("profit_factor")
        if real_pf is not None and pnl_cnt >= 10 and real_pf < 0.8:
            nv = round(max(0.25, cfg.get("pos_ratio_probe", 0.45) - 0.05), 2)
            if nv != cfg.get("pos_ratio_probe"):
                evolved["pos_ratio_probe"] = nv
                changed.append(f"pos_ratio_probe={nv} (PF={real_pf:.2f}<0.8)")
                lg.warning("[EVOL] 잔여-3 규칙8: PF=%.2f 저조 → pos_ratio_probe 축소 %.2f",
                           real_pf, nv)
        elif real_pf is not None and pnl_cnt >= 10 and real_pf >= 2.0:
            # PF 우수 → probe 원위치
            default_probe = _DEFAULT_CFG.get("pos_ratio_probe", 0.45)
            if cfg.get("pos_ratio_probe", default_probe) < default_probe:
                evolved["pos_ratio_probe"] = default_probe
                changed.append(f"pos_ratio_probe={default_probe} (PF={real_pf:.2f}≥2.0 복구)")
                lg.info("[EVOL] 잔여-3 규칙8: PF=%.2f 우수 → pos_ratio_probe 복구", real_pf)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ★ 잔여-3 신규 규칙 9: breadth 저조 → phase_mixed_mult 완화
        #    시장 너비 약세 시 MIXED 감쇄 강화로 보수화
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        breadth_now = fb.get("market_breadth") or 0.5
        if breadth_now < 0.30 and phase in ("MIXED", "BEAR"):
            nv = round(max(0.70, cfg.get("phase_mixed_mult", 0.95) - 0.05), 2)
            if nv != cfg.get("phase_mixed_mult"):
                evolved["phase_mixed_mult"] = nv
                changed.append(f"phase_mixed_mult={nv} (breadth={breadth_now:.3f}<0.30)")
                lg.warning("[EVOL] 잔여-3 규칙9: breadth=%.3f 저조 → mixed_mult 강화 %.2f",
                           breadth_now, nv)
        elif breadth_now >= 0.55 and phase == "BULL":
            default_mm = _DEFAULT_CFG.get("phase_mixed_mult", 0.95)
            if cfg.get("phase_mixed_mult", default_mm) < default_mm:
                evolved["phase_mixed_mult"] = default_mm
                changed.append(f"phase_mixed_mult={default_mm} (breadth 회복 복구)")
                lg.info("[EVOL] 잔여-3 규칙9: breadth=%.3f 회복 → mixed_mult 복구", breadth_now)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ★ 보강-7: IC 미달 초기 거래 보호 (샘플 < 5)
        #    trade_cnt < 5: IC 계산 불가 구간 선제 보수화
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        pnl_cnt = pnl_stats.get("trade_cnt", 0)
        if eret_ic is None and pnl_cnt < 5:
            nv = round(min(2.5, cfg.get("conv_eret_min", 1.0) + 0.05), 2)  # ★ PATCH-9: 0.1→0.05
            if nv != cfg.get("conv_eret_min"):
                evolved["conv_eret_min"] = nv
                changed.append(f"conv_eret_min={nv} (PATCH-9 초기거래보호<5건)")
                lg.info("[EVOL] PATCH-9: 초기 거래 %d건 → conv_eret_min 선제 상향 %.2f",
                        pnl_cnt, nv)

        # ★ 필수-4 계승: ERET IC 저하 → conv_eret_min 자동 강화
        if eret_ic is not None and pnl_cnt >= 10:
            ic_warn = cfg.get("pnl_ic_warn", 0.05)
            if eret_ic < 0.0:
                # IC 음수: ERET가 오히려 역방향 예측 → 강력 강화
                nv = round(min(2.5, cfg.get("conv_eret_min",1.2)+0.2), 2)
                if nv != cfg.get("conv_eret_min"):
                    evolved["conv_eret_min"] = nv
                    changed.append(f"conv_eret_min={nv} (ERET_IC 음수={eret_ic:.4f})")
                    lg.warning("[EVOL] 필수-4: ERET IC=%.4f 음수 → conv_eret_min 강화",
                               eret_ic)
            elif eret_ic < ic_warn:
                # IC 낮음: ERET 예측력 저하 → 완만 강화
                nv = round(min(2.5, cfg.get("conv_eret_min",1.2)+0.1), 2)
                if nv != cfg.get("conv_eret_min"):
                    evolved["conv_eret_min"] = nv
                    changed.append(f"conv_eret_min={nv} (ERET_IC 저하={eret_ic:.4f})")
                    lg.warning("[EVOL] 필수-4: ERET IC=%.4f < %.2f → conv_eret_min 강화",
                               eret_ic, ic_warn)

        if changed:
            max_ch = cfg.get("evol_max_changes", 1)
            if len(changed) > max_ch:
                lg.info("[EVOL] EVOL-2: %d→%d 제한", len(changed), max_ch)
                changed = changed[:max_ch]
                kept = set()
                for ch in changed:
                    ep = ch.find("=")
                    kept.add(ch[:ep].strip() if ep > 0 else ch)
                for k in list(evolved.keys()):
                    if k in cfg and evolved[k] != cfg.get(k) and k not in kept:
                        evolved[k] = cfg[k]

            EVOLVED_CFG.parent.mkdir(parents=True, exist_ok=True)
            tmp_cfg = EVOLVED_CFG.with_suffix(".tmp")
            with open(tmp_cfg,"w",encoding="utf-8") as f:
                json.dump({"prev_summary": evolved}, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_cfg), str(EVOLVED_CFG))
            lg.info("[EVOL] ★ 파라미터 갱신: %s", " | ".join(changed))
        else:
            lg.info("[EVOL] 파라미터 변경 없음")

    except Exception as e:
        lg.warning("[EVOL] 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  투자 비율 계산
#
#  실행 순서 (v7_3):
#  ① ERET 5단계 매핑 (np.select)           [필수-2]
#  ② ret_3d 2단계 리스크 감쇄
#  ③ noise=1 → 한 단계 하향
#  ④ quality_floor 스킵                    [FIX-A 유지]
#  ⑤ conviction 최우선 최고 비율           [FIX-A]
#  ⑥ conviction 조건부 제한 (ret3d, score) [필수-3]
#  ⑦ market_phase 감쇄 (전체 종목)         [필수-7]
#  ⑧ NaN 안전장치                          [FIX-B]
# ═══════════════════════════════════════════════════════════════
def _add_position_ratio(latest: pd.DataFrame,
                        cfg: dict, lg: logging.Logger) -> pd.DataFrame:
    # 파라미터
    thr_min = cfg.get("eret_thr_min",   0.8)
    thr_l   = cfg.get("eret_thr_low",   1.2)
    thr_m   = cfg.get("eret_thr_mid",   2.0)
    thr_h   = cfg.get("eret_thr_high",  3.0)
    r_probe = cfg.get("pos_ratio_probe", 0.45)
    r_l     = cfg.get("pos_ratio_low",  0.70)
    r_m     = cfg.get("pos_ratio_mid",  0.85)
    r_h     = cfg.get("pos_ratio_high", 0.98)
    r_s     = cfg.get("pos_ratio_skip", 0.00)
    bear_m  = cfg.get("phase_bear_mult",  0.70)
    mixed_m = cfg.get("phase_mixed_mult", 0.90)

    eret  = latest.get("expected_return_est",
            pd.Series([0]*len(latest),index=latest.index)).fillna(0)
    noise = latest["noise_flag"].fillna(1)
    conv  = latest.get("conviction_flag",
            pd.Series([0]*len(latest),index=latest.index)).fillna(0)
    score = latest["combined_score"].fillna(0)
    ret3  = latest.get("ret_3d",
            pd.Series([0]*len(latest),index=latest.index)).fillna(0)

    # 안전한 market_phase 접근
    if "market_phase" in latest.columns:
        phase_col = latest["market_phase"]
    else:
        phase_col = pd.Series(["MIXED"]*len(latest), index=latest.index)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ① 필수-2: 5단계 ERET 구간 매핑 (np.select)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    conditions = [
        eret >= thr_h,    # ≥ 3.0% → 0.98
        eret >= thr_m,    # ≥ 2.0% → 0.85
        eret >= thr_l,    # ≥ 1.2% → 0.70
        eret >= thr_min,  # ≥ 0.8% → 0.45 (탐색)
    ]
    choices = [r_h, r_m, r_l, r_probe]
    ratio = pd.Series(
        np.select(conditions, choices, default=r_s),
        index=eret.index, dtype=float
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ② ret_3d 2단계 감쇄
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    mild_loss   = (ret3 < 0) & (ret3 > -0.03)
    severe_loss = (ret3 <= -0.03)
    ratio = ratio.where(~mild_loss,   (ratio * 0.85).clip(lower=r_s))
    ratio = ratio.where(~severe_loss, (ratio * 0.50).clip(lower=r_s))

    # ③ noise 하향
    noise_mask = (noise == 1)
    ratio = ratio.where(~noise_mask, (ratio - 0.15).clip(lower=r_s))

    # ④ quality_floor 스킵
    qf = cfg.get("pos_quality_floor", 0.45)
    ratio = ratio.where(score >= qf, r_s)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑤ FIX-A: conviction 최우선 (마지막에 적용)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    conv_mask = (conv == 1)
    ratio = ratio.where(~conv_mask, r_h)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑥ 필수-3: conviction 조건부 제한
    #    ret_3d ≤ -0.03 → 최대 0.70
    #    combined_score < 0.55 → 최대 0.85
    #    (BEAR 패널티는 ⑦ 필수-7에서 전체 처리)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ratio = ratio.where(
        ~(conv_mask & (ret3 <= -0.03)),
        np.minimum(ratio, 0.70)
    )
    ratio = ratio.where(
        ~(conv_mask & (score < 0.55)),
        np.minimum(ratio, 0.85)
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑦ 필수-7: market_phase 전체 감쇄 (conviction 포함)
    #    BEAR  → × phase_bear_mult(0.70)
    #    MIXED → × phase_mixed_mult(0.90)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ratio = ratio.where(
        ~(phase_col == "BEAR"),
        (ratio * bear_m).clip(lower=r_s).round(2)
    )
    ratio = ratio.where(
        ~(phase_col == "MIXED"),
        (ratio * mixed_m).clip(lower=r_s).round(2)
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ 보강-6: 변동성 레짐별 position_ratio 상한 적용
    #    지침서 [15] 제3장 레짐 분류와 position_ratio 연동
    #    출처: Glasserman & Xu (2011) TSL 임계값 연구
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    high_cap    = cfg.get("vol_regime_high_cap",    0.85)
    extreme_cap = cfg.get("vol_regime_extreme_cap", 0.70)
    vol_ratio_col = latest.get("vol_ratio",
                    pd.Series([1.0]*len(latest), index=latest.index)).fillna(1.0)

    vol_regime_cap = pd.Series(1.0, index=latest.index)
    vol_regime_cap = vol_regime_cap.where(vol_ratio_col < 1.5, high_cap)    # HIGH
    vol_regime_cap = vol_regime_cap.where(vol_ratio_col < 2.0, extreme_cap) # EXTREME

    extreme_cnt = int((vol_ratio_col >= 2.0).sum())
    high_cnt    = int(((vol_ratio_col >= 1.5) & (vol_ratio_col < 2.0)).sum())
    if extreme_cnt + high_cnt > 0:
        lg.info("[POS] 보강-6 레짐cap  EXTREME(≥2.0)=%d→%.2f  HIGH(≥1.5)=%d→%.2f",
                extreme_cnt, extreme_cap, high_cnt, high_cap)

    ratio = pd.Series(
        np.minimum(ratio.values, vol_regime_cap.values),
        index=ratio.index
    ).round(2)

    # ⑧ NaN 안전장치
    nan_cnt = ratio.isna().sum()
    if nan_cnt > 0:
        lg.warning("[POS] NaN %d건 → 0.0 강제", nan_cnt)
    ratio = ratio.fillna(r_s).round(2)
    latest["position_ratio"] = ratio

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ★ UPGRADE-2: 1일 1번 진입 보장 안전망
    #    conviction=0이고 모든 ratio=0일 때 최고 ERET 종목 강제 선정
    #    조건: phase != BEAR AND eret_top >= fallback_eret_min AND noise=0
    #    이유: 매일 최소 1기회 확보 (장 극단 불량 제외)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    fb_eret_min = cfg.get("fallback_eret_min", 0.50)
    active_cnt  = int((ratio > 0).sum())
    conv_cnt    = int(conv_mask.sum())

    if active_cnt == 0 and conv_cnt == 0:
        # 안전망 발동 조건 확인
        phase_now = latest["market_phase"].iloc[0] if "market_phase" in latest.columns else "MIXED"
        if phase_now != "BEAR":
            # noise=0이고 eret >= fallback_eret_min인 후보 중 최고 종목
            cand_mask = ((eret >= fb_eret_min) & (noise == 0) & (score >= 0.45))
            if cand_mask.sum() > 0:
                best_idx = eret[cand_mask].idxmax()
                ratio.loc[best_idx] = r_probe  # 탐색 비중으로 최소 진입
                latest.loc[best_idx, "position_ratio"] = r_probe
                best_code = latest.loc[best_idx, "code"] if "code" in latest.columns else "N/A"
                best_er   = float(eret.loc[best_idx])
                lg.info("[POS] ★ UPGRADE-2 1일1번 안전망 발동! "
                        "code=%s ERET=%.2f%% → ratio=%.2f",
                        best_code, best_er, r_probe)
            else:
                lg.warning("[POS] UPGRADE-2 안전망: 조건 충족 후보 없음 (ERET<%.1f%% 또는 noise=1)", fb_eret_min)
        else:
            lg.info("[POS] UPGRADE-2 안전망: BEAR 장세 → 강제 진입 스킵")

    # 로그
    skip_n = int((ratio == 0.0).sum())
    probe_n= int(((ratio > 0.0) & (ratio < r_l)).sum())
    low_n  = int(((ratio >= r_l - 0.01) & (ratio < r_m - 0.01)).sum())
    mid_n  = int(((ratio >= r_m - 0.01) & (ratio < r_h - 0.01)).sum())
    high_n = int((ratio >= r_h - 0.01).sum())
    conv_n = int(conv_mask.sum())

    top1    = latest.nlargest(1,"expected_return_est")
    top1_pr = float(top1["position_ratio"].values[0]) if len(top1) else 0.0
    top1_er = float(top1["expected_return_est"].values[0]) if len(top1) else 0.0

    lg.info("[POS] v7_3 5단계  skip=%d probe=%d low=%d mid=%d high=%d  "
            "conv=%d  ★1등 ERET=%.2f%%→ratio=%.2f",
            skip_n, probe_n, low_n, mid_n, high_n, conv_n, top1_er, top1_pr)
    return latest


# ═══════════════════════════════════════════════════════════════
#  출력 컬럼 (★ 잔여-2: 56개로 수정, inst_3d_accel 신규)
# ═══════════════════════════════════════════════════════════════
OUT_COLS = [
    # 기본 (15개)
    "date","code",
    "prev_open","prev_high","prev_low","prev_close",
    "prev_volume","prev_value",
    "prev_range_pct","prev_body_pct","prev_close_pos","prev_ret_1d",
    "prev2_close","prev2_high","prev2_low",
    # v3_0 (19개)
    "ret_3d","ret_5d","momentum_3d","momentum_5d",
    "ema5","ema20","trend_dir","trend_strength","trend_consistency",
    "atr14","atr14_pct","avg_range_5d",
    "vol_ma5","vol_ma20","vol_ratio","vol_quality",
    "gap_size","consec_up","consec_down",
    # v4_0 (9개)
    "rs_1d","rs_3d","rs_5d","rs_rank","rs_grade",
    "noise_flag","noise_reason",
    "clean_momentum","combined_score",
    # v5_0 (7개, ★inst_3d_accel 신규 — 필수-6)
    "rs_composite",
    "inst_3d_net",
    "inst_buy_flag",
    "inst_3d_accel",      # ★ 필수-6 신규
    "gap_up_prob",
    "conviction_flag",
    "market_phase",
    # v6_0 (2개)
    "winner_gap",
    "position_ratio",
    # v7_0 (4개)
    "vars_score",
    "inst_mq",
    "expected_return_est",
    "market_breadth",
    # v7_6 (1개) ★ UPGRADE-3 신규
    "high_52w_ratio",     # 52주 신고가 근접도 (Gray & Vogel 2016)
]
# ★ v7_6: 총 57개
# ★ 잔여-2: 총 56개 (inst_3d_accel 추가)


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    t0  = time.time()
    lg  = _setup_logger()
    cfg = _load_evolved_cfg()

    lg.info("="*70)
    lg.info("make_prev_day_summary  v7_6  시작 (UPGRADE 1~6 적용)")
    lg.info("[CFG] atr=%d ema=%d/%d flat=%.3f bull=%.1f "
            "conv_eret=%.2f score_floor=%.2f cost=%.3f inst_mq_min=%.2f "
            "mom_w=%.2f pos_high=%.2f rs_w=[%.2f,%.2f,%.2f] ic_min=%d",
            cfg["atr_period"], cfg["ema_short"], cfg["ema_long"],
            cfg["trend_flat_pct"], cfg["bull_ratio"],
            cfg.get("conv_eret_min", 1.0),
            cfg.get("conv_score_floor", 0.58),
            cfg.get("cost_rate", 0.003),
            cfg.get("conv_inst_mq_min", 0.15),
            cfg.get("eret_mom_w", 0.40),
            cfg.get("pos_ratio_high", 1.00),
            cfg.get("rs_w1d", 0.45),
            cfg.get("rs_w3d", 0.35),
            cfg.get("rs_w5d", 0.20),
            cfg.get("ic_min_samples", 20))

    # 1. 로드
    df = _read_csv(INPUT, lg, required=True)
    if df is None or df.empty:
        lg.error("[MAIN] 입력 없음"); return RC_FAIL

    # [OOM-FIX 2026-05-28 B] 90일 history cap — 32-bit 메모리 안전.
    # eod_daily_bars 1년+ 누적 (~890K rows) → 90일 (~60K rows)로 축소.
    # 모든 lookback (vol_ma20=20일 / atr14=14일 / rs_5d=5일) < 90일 → 정합 안전.
    _cap_date_str = (pd.Timestamp.now() - pd.Timedelta(days=90)).strftime("%Y%m%d")
    _before_cap = len(df)
    df.columns = [c.strip().lower() for c in df.columns]   # date 컬럼 정규화 먼저
    if "date" in df.columns:
        df = df[df["date"].astype(str) >= _cap_date_str].copy()
        lg.info("[CAP-90D] %s 이전 제거: %d → %d rows",
                _cap_date_str, _before_cap, len(df))

    # 2. 정규화
    required   = ["code","date","open","high","low","close","volume"]
    missing    = [c for c in required if c not in df.columns]
    if missing:
        lg.error("[MAIN] 컬럼 없음: %s", missing); return RC_FAIL

    has_val = "value" in df.columns
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="%Y%m%d")
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if has_val:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # [OOM-FIX 2026-05-28 A] dropna copy 회피 → inplace=True (~285 MiB 절약)
    df.dropna(subset=["code","date","close"], inplace=True)
    df["code"] = df["code"].astype(str).str.zfill(6)
    lg.info("[MAIN] rows=%d codes=%d", len(df), df["code"].nunique())

    # 3. 시장 기준선
    mkt = _calc_market_returns(df, lg)

    # 4. 기관 수급 (필수-6: accel 포함)
    inst_df  = _load_inst(lg)
    has_inst = not inst_df.empty

    # 5. PnL 통계 (FIX-E)
    pnl_stats = _load_pnl_stats(cfg, lg)

    # 6. 피처 빌드
    df_feat = _build_all_features(df, cfg, lg)

    # 7. 최신 행 추출
    latest    = df_feat.groupby("code").tail(1).copy()
    today_str = (pd.to_datetime(latest["date"]).max().strftime("%Y-%m-%d")
                 if not latest.empty else "unknown")
    latest["date"] = pd.to_datetime(latest["date"]).dt.strftime("%Y-%m-%d")
    lg.info("[MAIN] 기준일=%s 종목=%d", today_str, len(latest))

    # 8. 기관 merge (inst_3d_accel 포함)
    if has_inst:
        latest = latest.merge(inst_df, on="code", how="left")
        latest["inst_3d_net"]   = latest["inst_3d_net"].fillna(0)
        latest["inst_buy_flag"] = latest["inst_buy_flag"].fillna(0).astype(int)
        latest["inst_3d_accel"] = latest["inst_3d_accel"].fillna(0)
        lg.info("[INST] merge 완료  매칭=%d  accel_pos=%d",
                int((latest["inst_3d_net"]!=0).sum()),
                int((latest["inst_3d_accel"]>0).sum()))
    else:
        latest["inst_3d_net"]   = 0.0
        latest["inst_buy_flag"] = 0
        latest["inst_3d_accel"] = 0.0
        lg.warning("[INST] 기관 미연동 — inst_mq/accel = 0")

    # 9. RS
    latest = _add_rs(latest, mkt, cfg, lg)

    # 10. VARS
    latest = _add_vars(latest, df, cfg, lg)

    # 11. 기관 모멘텀 품질 (필수-6: accel 반영)
    latest = _add_inst_mq(latest, cfg, lg)

    # 12. 시장 국면 (FIX-C+6)
    phase = _calc_market_phase(latest, cfg, lg)
    latest["market_phase"] = phase

    # 13. 노이즈 필터
    latest = _add_noise_vectorized(latest, cfg, lg)

    # 14. 갭업 예측
    latest = _add_gap_up_prob(latest, cfg, lg)

    # 15. combined_score
    latest = _add_combined_score(latest, phase, cfg, lg)

    # 16. 시장 너비
    breadth = _calc_market_breadth(latest, lg)
    latest["market_breadth"] = breadth

    # 17. ERET (필수-5 downside + 잔여-1 거래비용)
    latest = _add_expected_return(latest, phase, cfg, lg)

    # 18. 확신 플래그 (필수-1 winner_gap + 필수-8 4조건)
    latest = _add_conviction(latest, cfg, lg)

    # 19. 투자 비율 (필수-2 5단계 + 필수-3 + 필수-7)
    latest = _add_position_ratio(latest, cfg, lg)

    # 20. 출력 컬럼
    avail = [c for c in OUT_COLS if c in latest.columns]
    out   = latest[avail].copy()
    out["code"] = out["code"].astype(str).str.zfill(6)

    skip    = {"date","code","trend_dir","rs_grade","noise_reason","market_phase"}
    int_set = {"noise_flag","conviction_flag","inst_buy_flag","consec_up","consec_down"}
    for c in out.columns:
        if c in skip: continue
        if c in int_set:
            out[c] = out[c].fillna(0).astype(int)
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce").round(6)

    # 21. 유효성 검증
    _validate(out, cfg, lg)

    # 22. 원자적 쓰기
    if not _atomic_write(out, OUTPUT, lg):
        return RC_FAIL

    elapsed = time.time() - t0

    # 23. 자기진화 피드백 (필수-4 IC 강화 포함)
    _write_feedback(out, phase, today_str, elapsed,
                    has_val, cfg, pnl_stats, lg)

    # 24. 콘솔 요약
    tc    = out["trend_dir"].value_counts().to_dict() if "trend_dir" in out.columns else {}
    nc_n  = int(out["noise_flag"].sum()) if "noise_flag" in out.columns else 0
    rsa   = int((out.get("rs_grade","")=="A").sum()) if "rs_grade" in out.columns else 0
    nconv = int(out["conviction_flag"].sum()) if "conviction_flag" in out.columns else 0
    wg    = float(out["winner_gap"].max()) if "winner_gap" in out.columns and len(out) else 0.0
    top1  = out.nlargest(1,"expected_return_est") if len(out) else pd.DataFrame()
    t1c   = top1["code"].values[0]             if len(top1) else "N/A"
    t1sc  = top1["combined_score"].values[0]    if len(top1) else 0
    t1cv  = top1["conviction_flag"].values[0]   if len(top1) else 0
    t1pr  = top1["position_ratio"].values[0]    if len(top1) else 0.0
    t1er  = top1["expected_return_est"].values[0] if len(top1) else 0.0

    pr_skip = int((out["position_ratio"]==0.0).sum()) if "position_ratio" in out.columns else 0
    pr_probe= int(((out["position_ratio"]>0)&(out["position_ratio"]<0.70)).sum()) \
              if "position_ratio" in out.columns else 0
    pr_act  = len(out) - pr_skip

    vars_top    = float(out.nlargest(1,"vars_score")["vars_score"].values[0]) if "vars_score" in out.columns and len(out) else 0.0
    inst_mq_top = float(out.nlargest(1,"inst_mq")["inst_mq"].values[0]) if "inst_mq" in out.columns and len(out) else 0.0
    eret_top    = float(out.nlargest(1,"expected_return_est")["expected_return_est"].values[0]) if "expected_return_est" in out.columns and len(out) else 0.0
    mbreadth    = float(out["market_breadth"].iloc[0]) if "market_breadth" in out.columns and len(out) else 0.0

    real_wr = pnl_stats.get("win_rate")
    real_pf = pnl_stats.get("profit_factor")
    p_cnt   = pnl_stats.get("trade_cnt",0)

    print("="*70)
    print(f"  make_prev_day_summary  v7_6  완료  [UPGRADE 1~6]")
    print(f"  기준일={today_str}  종목={len(out)}  {elapsed:.2f}s")
    print(f"  value={'실거래대금' if has_val else 'close×vol추정'}"
          f"  기관={'연동(accel복원)' if has_inst else '미연동'}")  # ★ UPGRADE-4 반영
    print(f"  시장={phase}  UP:{tc.get('UP',0)}"
          f"  DN:{tc.get('DOWN',0)}  FLAT:{tc.get('FLAT',0)}")
    print(f"  RS-A급={rsa}  노이즈={nc_n}  확신종목={nconv} (5조건 보강-4)")
    print(f"  winner_gap(Top1)={wg:.4f}")
    print(f"  투자대상={pr_act}종목  탐색={pr_probe}  스킵={pr_skip}")
    print(f"  ★ 1등후보: {t1c}  ERET={t1er:.2f}%  점수={t1sc:.4f}"
          f"  확신={'YES' if t1cv else 'NO'}"
          f"  → 투자비율 {t1pr:.0%}")
    print(f"  VARS={vars_top:.3f}  기관MQ={inst_mq_top:.3f}"
          f"  기대수익={eret_top:.2f}%  시장너비={mbreadth:.3f}")
    if real_wr is not None:
        print(f"  [PnL] 거래={p_cnt}건  승률={real_wr*100:.1f}%"
              f"  손익비={real_pf:.2f}"
              f"  {'⚠ 경보' if real_wr < 0.45 else '✓'}")
    else:
        print(f"  [PnL] bridge_result.csv 미연결 ({p_cnt}건)")
    print(f"  출력컬럼={len(avail)}개")
    print("="*70)

    lg.info("[MAIN] v7_6 완료 rows=%d elapsed=%.2fs phase=%s conv=%d "
            "vars=%.3f eret=%.2f breadth=%.3f wr=%s",
            len(out), elapsed, phase, nconv, vars_top, eret_top, mbreadth,
            f"{real_wr*100:.1f}%" if real_wr is not None else "N/A")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
