# -*- coding: utf-8 -*-
"""
rt_hoga_live_v1.py  (축④ 호가/체결강도 실시간 조회 — rt_execution 1등 선별 실반영용)
=====================================================================================
최종 8후보에 대해 broker로 호가(opt10004) + 체결강도(opt10001)를 실시간 조회한다.
SHADOW/테스트 아님 — rt_execution이 이 값을 1등 점수(turn_z 축④)에 즉시 반영한다.

[데이터]
  - opt10004 (주식호가요청, read-only): 매도/매수 1~5호가 잔량 → spread_pct, imbalance(매수압력)
      · 재사용: eod_pickup_orderbook_v1.fetch_orderbook (production 검증됨)
  - opt10001 (주식기본정보요청, read-only): 체결강도 (best-effort, 필드 없으면 0=중립)

[안전 — 매수결정 무손상 원칙]
  - broker DEAD / TR 실패 / 필드 누락 → 해당 신호 0(중립) 반환. 예외는 절대 밖으로 던지지 않음.
  - read-only TR만 사용(주문 무관). 호출은 후보 ≤8개로 한정.
  - 60초 in-process 캐시(같은 종목 중복 조회 방지 → broker 부하·지연 최소화).

[반환] get_hoga_strength(code) -> dict
  {"ok":bool, "spread_pct":float, "imbalance":float(매수/매도 5호가 잔량비, 1=중립),
   "strength":float(체결강도, 100=중립/없으면 0)}
"""
from __future__ import annotations
import time
from typing import Dict, Any

_CACHE: Dict[str, Any] = {}        # code -> (ts_epoch, result)
_CACHE_TTL = 60.0                  # 초

_NEUTRAL = {"ok": False, "spread_pct": 0.0, "imbalance": 1.0, "strength": 0.0}


def _safe_float(v, d=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return d


def _fetch_strength_opt10001(code: str, timeout_sec: float = 4.0) -> float:
    """opt10001 체결강도(best-effort). 실패/필드없음 → 0.0(중립)."""
    try:
        from broker_client import BrokerClient
        bc = BrokerClient()
        if not bc.alive():
            return 0.0
        res = bc.tr(
            tr_code="opt10001",
            inputs={"종목코드": str(code).zfill(6)},
            output_fields=["체결강도"],
            rqname=f"strength_{code}",
            screen_no="0803",
            timeout_sec=timeout_sec,
        )
        if res.get("status") != "OK":
            return 0.0
        recs = (res.get("data") or {}).get("records") or []
        if not recs:
            return 0.0
        return abs(_safe_float(recs[0].get("체결강도", 0)))
    except Exception:
        return 0.0


def get_hoga_strength(code: str, with_strength: bool = True) -> Dict[str, Any]:
    """호가(spread, 매수압력 imbalance) + 체결강도. 모든 실패는 중립 dict로 흡수."""
    code = str(code).zfill(6)
    now = time.time()
    cached = _CACHE.get(code)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    out = dict(_NEUTRAL)
    try:
        from eod_pickup_orderbook_v1 import fetch_orderbook
        ob = fetch_orderbook(code)
        if ob:
            bid_t = float(ob.get("bid_total_5", 0) or 0)
            ask_t = float(ob.get("ask_total_5", 0) or 0)
            out["spread_pct"] = float(ob.get("spread_pct", 0.0) or 0.0)
            out["imbalance"] = (bid_t / ask_t) if ask_t > 0 else 1.0   # >1 = 매수잔량 우위 = 매수압력
            out["ok"] = True
    except Exception:
        pass

    if with_strength:
        try:
            out["strength"] = _fetch_strength_opt10001(code)
        except Exception:
            out["strength"] = 0.0

    _CACHE[code] = (now, out)
    return out


def prefetch(codes, with_strength: bool = True) -> Dict[str, Dict[str, Any]]:
    """후보 리스트 일괄 조회(≤8 권장). 반환: code -> dict."""
    res = {}
    for c in codes:
        res[str(c).zfill(6)] = get_hoga_strength(c, with_strength=with_strength)
    return res
