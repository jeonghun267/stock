# -*- coding: utf-8 -*-
"""
[눌림 4단 퍼널 — 공용 코어  2026-06-13 친구님 설계]
그림자(BACKTEST/pullback_funnel_shadow_v1)와 실거래 엔진(rt_risk_engine)이 '같은 코드'를 쓰도록 분리.
철학: 리스크=죽을놈 버림 / 익스큐션=우승자 1개. 검증된 로직(첫눌림 카운터·미세4요소·중복제거).

핵심 함수:
  count_pullback_episodes(highs, closes)         → (눌림회차, 진행중여부)
  pb_metrics(g_min)                              → 분봉 1종목 → 눌림품질 지표 dict
  load_pb_metrics(codes, p1m_path, cache)        → {code: metrics} (mtime 캐시)
  step1_die(row, low5, hmin)                     → 죽을놈 사유 or None
  funnel_score(row, m, r_dv_pct)                 → (총점, 내역dict)  [품질40+돈25+첫눌림20+미세15]
⚠칸 스케일(실측): dv_accel<0=거래대금줆 / price_vs_day_high=비율(0.92=고점-8%) / last3_ret=% / value_now(1분)≠value_5m(5분).
"""
from pathlib import Path
import os
import numpy as np
import pandas as pd


def count_pullback_episodes(highs, closes, dd_thresh=0.015, reset_thresh=0.005):
    """고점 대비 ≥dd_thresh 빠졌다가 reset_thresh 이내 회복 = 눌림 1회. (분봉 pullback 플래그는 깜빡이라 못 셈)"""
    if len(closes) == 0:
        return 0, False
    peak = highs[0]; ep = 0; in_pb = False
    for i in range(len(closes)):
        if highs[i] > peak:
            peak = highs[i]
        dd = (closes[i] - peak) / peak if peak > 0 else 0.0
        if not in_pb and dd <= -dd_thresh:
            ep += 1; in_pb = True
        elif in_pb and dd >= -reset_thresh:
            in_pb = False
    return ep, in_pb


def pb_metrics(g):
    """한 종목 분봉(시간순 df) → 눌림 품질 지표. prices_1m 사전계산 필드 활용. n<10이면 None."""
    g = g.sort_values("ts")
    for col in ("low", "high", "close", "volume", "ret_1m", "ret_3bar_sum", "hl",
                "close_strength", "vwap_reclaim", "vwap_dev"):
        if col in g.columns:
            g[col] = pd.to_numeric(g[col], errors="coerce")
    n = len(g)
    if n < 10:
        return None
    day_low = g["low"].min(); last_close = g["close"].iloc[-1]
    _h = g["high"].ffill().fillna(0).values; _c = g["close"].ffill().fillna(0).values
    pb_count, pb_active = count_pullback_episodes(_h, _c)
    hl = g["hl"].fillna(0).values if "hl" in g else np.zeros(n)
    hl_recent = float(np.mean(hl[-20:])) if n >= 20 else float(np.mean(hl))
    r3 = g["ret_3bar_sum"].fillna(0).values if "ret_3bar_sum" in g else np.zeros(n)
    decel = float(r3[-1] - r3[-4]) if n >= 4 else 0.0
    vol = g["volume"].fillna(0).values
    vol_dry = 1.0 if (n >= 10 and vol[-5:].mean() < vol[-10:-5].mean()) else 0.0
    above_low = (last_close / day_low - 1) * 100 if day_low > 0 else 0
    # 미세모멘텀 4요소
    r1 = g["ret_1m"].fillna(0).values if "ret_1m" in g else np.zeros(n)
    last5 = r1[-5:]; prev5 = r1[-10:-5] if n >= 10 else r1[:max(1, n - 5)]
    m_red_dec = 1.0 if (last5 < 0).sum() < max((prev5 < 0).sum(), 1) else 0.0
    m_last_up = 1.0 if r1[-1] > 0 else 0.0
    vdev = g["vwap_dev"].fillna(0).values if "vwap_dev" in g else np.zeros(n)
    m_vwap = 1.0 if vdev[-1] >= 0 else 0.0
    highs = g["high"].fillna(0).values
    micro_high = float(max(highs[-6:-1])) if n >= 6 else float(highs.max())
    m_retry = 1.0 if (micro_high > 0 and last_close >= micro_high * 0.998) else 0.0
    micro_mom = (m_red_dec + m_last_up + m_vwap + m_retry) / 4.0
    cl = g["close"].values
    if n >= 9:
        am = cl[:n // 3].mean(); pm = cl[-n // 3:].mean()
        leader_hold = 1.0 if (am > 0 and pm >= am * 0.985) else 0.0
    else:
        leader_hold = 0.5
    brk_dist = (micro_high / last_close - 1) * 100 if last_close > 0 else 99.0
    # [V2 2026-06-16 친구님 설계] 거래대금 지속성(오후/오전)·눌림깊이·최근3봉·고점대비
    persist = 0.0; depth = 0.0; last3 = 0.0; pdh = 0.0
    try:
        if "value" in g.columns and "ts" in g.columns:
            vv = pd.to_numeric(g["value"], errors="coerce").fillna(0).values
            _ts = g["ts"].astype(str)
            _hm = (pd.to_numeric(_ts.str[11:13], errors="coerce") * 100
                   + pd.to_numeric(_ts.str[14:16], errors="coerce")).fillna(0).values
            am = vv[_hm < 1300].sum(); pm = vv[_hm >= 1300].sum()
            persist = min(pm / am, 2.0) if am > 0 else 0.0
        _peak = np.maximum.accumulate(_h)
        depth = float(np.max((_peak - _c) / np.where(_peak > 0, _peak, 1) * 100)) if n else 0.0
        last3 = float((_c[-1] / _c[-4] - 1) * 100) if n >= 4 else 0.0
        pdh = float((_c[-1] / _h.max() - 1) * 100) if _h.max() > 0 else 0.0
    except Exception:
        pass
    return {"pb_count": pb_count, "pb_active": pb_active, "hl_recent": hl_recent, "decel": decel,
            "vol_dry": vol_dry, "above_low": above_low, "micro_mom": micro_mom,
            "leader_hold": leader_hold, "brk_dist": brk_dist,
            "persist": persist, "depth": depth, "last3": last3, "pdh": pdh,
            "m_red_dec": m_red_dec, "m_last_up": m_last_up, "m_vwap": m_vwap, "m_retry": m_retry}


# [V2 persist-fix 2026-06-16] 거래대금 지속성(오후/오전)은 prices_3m(완전수집)로 계산.
#   prices_1m은 600종목 순환=종목별 일부분봉만(오후 데이터 없는 종목 다수)이라 persist 0→레드카드 오발동. prices_3m는 완전.
P3M_PATH = os.environ.get("PULLBACK_P3M_PATH", r"C:\stock_bot\data\prices_3m.csv")
_persist3_cache = {"mtime": None, "map": {}}
def _load_persist_3m(codes):
    """prices_3m 당일 → {code: 오후/오전 거래대금비(상한2.0)}. mtime 캐시."""
    try:
        p = Path(P3M_PATH)
        if not p.exists():
            return {}
        mt = p.stat().st_mtime
        if _persist3_cache["mtime"] != mt or not _persist3_cache["map"]:
            d = pd.read_csv(p, usecols=["ts", "code", "value"], dtype={"code": str})
            d["code"] = d["code"].str.zfill(6)
            today = d["ts"].str[:10].max()
            d = d[d["ts"].str[:10] == today].copy()
            d["hm"] = (pd.to_numeric(d["ts"].str[11:13], errors="coerce") * 100
                       + pd.to_numeric(d["ts"].str[14:16], errors="coerce")).fillna(0)
            d["value"] = pd.to_numeric(d["value"], errors="coerce").fillna(0)
            mp = {}
            for c, g in d.groupby("code"):
                am = g.loc[g["hm"] < 1300, "value"].sum(); pm = g.loc[g["hm"] >= 1300, "value"].sum()
                mp[c] = min(pm / am, 2.0) if am > 0 else 0.0
            _persist3_cache.update({"mtime": mt, "map": mp})
        return {c: _persist3_cache["map"].get(c) for c in codes if c in _persist3_cache["map"]}
    except Exception:
        return {}


def load_pb_metrics(codes, p1m_path, cache):
    """prices_1m → {code: pb_metrics}. cache={'mtime','codes_key','map'} mtime+종목셋 같으면 재사용. persist는 prices_3m로 덮어씀."""
    try:
        p = Path(p1m_path)
        if not p.exists():
            return {}
        mt = p.stat().st_mtime
        ck = tuple(sorted(codes))
        if cache.get("mtime") == mt and cache.get("codes_key") == ck and cache.get("map"):
            return cache["map"]
        df = pd.read_csv(p, dtype=str)
        if "code" not in df.columns:
            return {}
        df["code"] = df["code"].str.zfill(6)
        cset = set(codes)
        out = {}
        for c, g in df[df["code"].isin(cset)].groupby("code"):
            m = pb_metrics(g)
            if m:
                out[c] = m
        # [V2 persist-fix] 거래대금 지속성을 prices_3m(완전수집)로 덮어씀
        try:
            _p3 = _load_persist_3m(cset)
            for _c, _v in _p3.items():
                if _c in out and _v is not None:
                    out[_c]["persist"] = _v
        except Exception:
            pass
        cache.update({"mtime": mt, "codes_key": ck, "map": out})
        return out
    except Exception:
        return {}


# [2026-06-18 친구님] 눌림 거래대금 50억 미만 컷. 롤백/조절 setx PULLBACK_MIN_VALUE_KRW (0=끔)
_PB_MIN_VALUE = float(os.environ.get("PULLBACK_MIN_VALUE_KRW", "5000000000"))   # 50억


def step1_die(row, low5, hmin=20.0, hmax=30.0):
    """STEP1 죽을놈 사유 반환(or None). row=rt_intraday 한 행(dict-like). low5=5일저점."""
    def g(k, d=None):
        v = row.get(k, d) if hasattr(row, "get") else d
        return v
    # [2026-06-18 친구님] 거래대금 50억 미만 = 컷(안 들어오게). value_day=당일 거래대금(원)
    if _PB_MIN_VALUE > 0:
        try:
            _vd = g("value_day")
            if _vd is not None and pd.notna(_vd) and float(_vd) < _PB_MIN_VALUE:
                return "거래대금부족(50억↓)"
        except (TypeError, ValueError):
            pass
    price_now = g("price_now")
    try:
        if low5 and price_now and float(price_now) < float(low5):
            return "전저점붕괴"
    except (TypeError, ValueError):
        pass
    l3 = g("last3_ret")
    if l3 is not None and pd.notna(l3) and float(l3) < -1.5:
        return "최근급락"
    dv = g("dv_accel")
    if dv is not None and pd.notna(dv) and float(dv) < 0:
        return "거래대금감소"
    pdh = g("price_vs_day_high")
    if pdh is not None and pd.notna(pdh) and float(pdh) < 0.92:
        return "고점-8%급락"
    # 높이 극단만 제거(천정50%+, 바닥<10%) — 20~30% '대상'은 점수로 우대
    if low5 and price_now:
        try:
            h = (float(price_now) / float(low5) - 1) * 100
            if h >= 50 or h < (hmin - 10):
                return f"높이{h:.0f}%"
        except (TypeError, ValueError):
            return "높이계산불가"
    else:
        return "5일저점없음"
    return None


def step2_score(row, r_dv_pct, m):
    """STEP2 대장자격(80→25): ①거래대금 유지율 ②종가강도(고가대비) ③장중대장 유지. 0~100. (친구님 스펙 그대로)"""
    def g(k, d=0.0):
        v = row.get(k, d) if hasattr(row, "get") else d
        try:
            return float(v)
        except (TypeError, ValueError):
            return d
    money = max(0.0, min(r_dv_pct, 1.0)) * 40.0                       # ① 거래대금 유지/증가(생존자 내 순위)
    pdh = g("price_vs_day_high", 0.0)                                 # 비율(1.0=고점, 0.95=-5%, 0.98=-2%)
    close_str = max(0.0, min((pdh - 0.95) / 0.05, 1.0)) * 30.0        # ② 종가강도(-2%이내 우대 / -5%이하 0)
    lead = (m.get("leader_hold", 0.0) if m else 0.0) * 30.0           # ③ 장중 대장유지(오전→오후)
    return round(money + close_str + lead, 1)


def step3_score(m):
    """STEP3 건강한눌림(25→8): ①첫눌림 ②전저점유지 ③HigherLow ④거래량감소 ⑤하락둔화. 0~100. 분봉없음=-1. (친구님 스펙)"""
    if not m:
        return -1.0
    pc = m.get("pb_count", 9)
    first = {1: 30, 2: 18, 0: 8}.get(pc, 0)                          # ① 첫눌림 우대(1회 최고·3회+ 0)
    low_hold = min(max(m.get("above_low", 0), 0) / 3.0, 1.0) * 20    # ② 전저점 유지(손절기준 명확)
    hl = min(max(m.get("hl_recent", 0), 0), 1) * 20                  # ③ Higher Low
    voldry = m.get("vol_dry", 0) * 15                                # ④ 거래량 감소
    decel = 15 if m.get("decel", 0) > 0 else 0                       # ⑤ 하락 가속도 둔화
    return round(first + low_hold + hl + voldry + decel, 1)


def _pq(m):
    """PULLBACK_QUALITY 40 (HigherLow+하락둔화+거래량감소+전저점유지+장중대장) — ★첫눌림 제외(중복방지)."""
    return round(min(max(m.get("hl_recent", 0), 0), 1) * 12
                 + (10 if m.get("decel", 0) > 0 else 0)
                 + m.get("vol_dry", 0) * 8
                 + min(max(m.get("above_low", 0), 0) / 3.0, 1) * 6
                 + m.get("leader_hold", 0) * 4, 1)


def _funnel_score_v2(row, m, r_dv_pct):
    """[V2 2026-06-16 친구님 설계] 진입높이35 + 첫눌림품질25(횟수+깊이) + 돈지속20 + 테마대장15 + 생존5.
    레드카드(-1000): 최근3봉≤-3% / 고점대비≤-10% / 오후거래대금비율<0.2. (전저점·테마5위는 STEP1/별도)"""
    def _g(k, d=None): return row.get(k, d) if hasattr(row, "get") else d
    try: h = float(_g("_pb_height"))
    except (TypeError, ValueError): h = 99.0
    h35 = 30 if h < 10 else 35 if h < 18 else 30 if h < 25 else 20 if h < 35 else 10 if h < 45 else 0  # 진입높이(낮을수록)
    if not m:   # 분봉 없음 → 후순위(진입높이 절반만)
        return round(h35 * 0.5, 1), {"v2": True, "no_min": True, "h35": h35, "pb_count": None, "brk_dist": 99.0}
    persist = m.get("persist", 0.0)
    red = ""
    if m.get("last3", 0.0) <= -3: red = "3봉-3%"
    elif m.get("pdh", 0.0) <= -10: red = "고점-10%"
    elif persist < 0.2: red = "오후<0.2"
    pc = m.get("pb_count", 9)
    cnt = 15 if pc == 1 else 8 if pc == 2 else 5 if pc == 0 else 0                   # 첫눌림 횟수
    dep = m.get("depth", 0.0); depS = 5 if dep < 3 else 10 if dep < 8 else 5 if dep < 12 else 0  # 눌림 깊이
    q25 = cnt + depS
    d20 = 20 if persist >= 0.8 else 15 if persist >= 0.6 else 10 if persist >= 0.4 else 5 if persist >= 0.3 else 0  # 돈지속
    th15 = 15 if (_g("_is_leader") or _g("is_leader") or _g("_theme_leader")) else 0  # 테마대장(근사)
    al = m.get("above_low", 0.0); hl = m.get("hl_recent", 0.0)
    s5 = 5 if (al > 0 and hl > 0.5) else 2 if (al > 0 or hl > 0.5) else 0             # 생존력
    total = -1000.0 if red else round(h35 + q25 + d20 + th15 + s5, 1)
    return total, {"v2": True, "h35": h35, "q25": q25, "d20": d20, "th15": th15, "s5": s5,
                   "red": red, "pb_count": pc, "brk_dist": m.get("brk_dist", 99.0), "no_min": False}


def funnel_score(row, m, r_dv_pct, height=None):
    """EXEC 합성점수. PULLBACK_SCORE_V2=YES(기본)면 친구님 신규설계(진입높이35+첫눌림25+돈지속20+테마15+생존5). 롤백 setx NO."""
    if os.environ.get("PULLBACK_SCORE_V2", "YES").strip().upper() == "YES":
        return _funnel_score_v2(row, m, r_dv_pct)
    # ── 기존 (품질40+돈25+첫눌림20+미세15) ──
    if not m:
        # 분봉 없음 → 품질/첫눌림/미세 0, 돈지속만(순위) — 사실상 후순위
        dv25 = r_dv_pct * 25
        return round(dv25, 1), {"q40": 0, "dv25": round(dv25, 1), "f20": 0, "mm15": 0,
                                "pb_count": None, "brk_dist": 99.0, "no_min": True}
    q40 = _pq(m)
    dv25 = r_dv_pct * 25
    pc = m.get("pb_count", 9)
    f20 = 20 if pc == 1 else (10 if pc == 2 else 0)
    mm15 = m.get("micro_mom", 0.0) * 15
    total = round(q40 + dv25 + f20 + mm15, 1)
    return total, {"q40": q40, "dv25": round(dv25, 1), "f20": f20, "mm15": round(mm15, 1),
                   "pb_count": pc, "brk_dist": m.get("brk_dist", 99.0), "no_min": False}
