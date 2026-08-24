# -*- coding: utf-8 -*-
"""
eod_pickup_market_cap_v1.py
============================
시가총액 측정 + 100억 미만 차단 모듈 (소형주 리스크 사전 차단).

[데이터 source]:
  - broker IPC opt10001 (주식기본정보요청, read-only TR)
  - broker_client.tr() 사용
  - eod_daily_bars.csv에 market_cap 컬럼 없음 → broker IPC 사용

[차단 임계]:
  - 시가총액 < 100억원 (소형주 슬리피지 + 호가 spread 큼 + 변동성 outlier 위험)
  - 시가총액 == 0 (응답 결함 / 신규상장 일부)

[측정 빈도]:
  - 1일 1회 EOD 직전 (watchlist 통과 30~50건만)
  - 시가총액은 EOD 시점만 변동 (시가 × 발행주식수)

[활용]:
  eod_pickup_signal_v2_hedge가 Stage 4 진입부에서 호출.
  blocked codes set 반환 → final list 차단.

[안전 가드]:
  - read-only TR (SendOrder 0건)
  - broker_client.tr() 검증된 API
  - 종목별 try/except 격리
  - screen_no="0802" (SIGA 9301 / orderbook 0801 / 종가매수 9305 와 격리)
"""
from __future__ import annotations

import os
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

VERSION = "eod_pickup_market_cap_v1"
BASE_DIR = Path(r"C:\stock_bot")
RUN_DIR = BASE_DIR / "RUN"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "LOG"
SIGNAL_DIR = DATA_DIR / "eod_pickup"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SIGNAL_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "eod_pickup_market_cap.log"
MARKET_CAP_CACHE = SIGNAL_DIR / "market_cap_cache.json"

# 차단 임계 (단위: 억원 = 1억원 단위)
# BAEKMAN(=백만) 명칭이 단위 혼동을 유발하여 EOK(=억원)로 통일 (5/28)
MIN_MARKET_CAP_EOK = 1000     # ★1000억 미만 차단 (친구님 2026-07-01: 과거 100억이 마니커(256억) 잡주 통과시킴·글로벌 SAFEPLUS_MIN_MARKETCAP 1000억과 통일)

# broker IPC
TR_TIMEOUT_SEC = 5.0

# 로거
_logger = logging.getLogger("eod_pickup_market_cap")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("[%(asctime)s][market_cap][%(levelname)s] %(message)s"))
    _logger.addHandler(_fh)
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("[%(asctime)s][market_cap][%(levelname)s] %(message)s"))
    _logger.addHandler(_ch)

# broker_client 동적 import
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────
# opt10001 호출 (broker IPC)
# ─────────────────────────────────────────────────────────────
def fetch_market_cap(code: str, timeout_sec: float = TR_TIMEOUT_SEC) -> Optional[Dict[str, Any]]:
    """broker IPC opt10001 호출 → 종목 시가총액 dict 반환.

    Returns:
        {"code", "name", "market_cap_eok", "listed_shares", "current_price", "per", "eps", ...}
        or None (실패)
    """
    try:
        from broker_client import BrokerClient
    except ImportError as e:
        _logger.error(f"broker_client import 실패: {e}")
        return None

    code = str(code).zfill(6)
    output_fields = [
        "종목명",
        "시가총액",         # 억원 단위 (키움 표준)
        "상장주식",         # 천주 단위
        "현재가",
        "PER",
        "EPS",
        "액면가",
        "자본금",
        "외인소진율",       # 외국인 보유 한도 소진율 (5/28 옵션 6번 보강)
    ]
    try:
        bc = BrokerClient()
        if not bc.alive():
            _logger.warning(f"broker DEAD → 시가총액 조회 보류 ({code})")
            return None
        res = bc.tr(
            tr_code="opt10001",
            inputs={"종목코드": code},
            output_fields=output_fields,
            rqname=f"market_cap_{code}",
            screen_no="0802",
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        _logger.warning(f"tr 예외 ({code}): {e}")
        return None

    if res.get("status") != "OK":
        return None
    data = res.get("data") or {}
    records = data.get("records") or []
    if not records:
        return None
    r = records[0]

    market_cap = _safe_float(r.get("시가총액", 0))
    if market_cap <= 0:
        _logger.warning(f"시가총액 0 또는 음수 ({code}): raw={r.get('시가총액')}")
        # 0은 결함 응답 (또는 신규상장) → 일단 dict 반환 (차단 판정은 evaluate_block에서)

    return {
        "code": code,
        "name": str(r.get("종목명", "")).strip(),
        "market_cap_eok": market_cap,
        "listed_shares_kju": _safe_int(r.get("상장주식", 0)),
        "current_price": abs(_safe_float(r.get("현재가", 0))),
        "per": _safe_float(r.get("PER", 0)),
        "eps": _safe_float(r.get("EPS", 0)),
        "face_value": _safe_float(r.get("액면가", 0)),
        "capital": _safe_float(r.get("자본금", 0)),
        "foreign_ratio_pct": _safe_float(r.get("외인소진율", 0)),  # 5/28 옵션 6번
        "ts": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 차단 판정
# ─────────────────────────────────────────────────────────────
def evaluate_block(mc: Dict[str, Any]) -> List[str]:
    """시가총액 데이터 → 차단 사유 list."""
    reasons = []
    cap = mc.get("market_cap_eok", 0)
    if cap <= 0:
        reasons.append(f"market_cap_zero_or_negative_{cap}")
    elif cap < MIN_MARKET_CAP_EOK:
        reasons.append(f"market_cap_{cap:.0f}억<{MIN_MARKET_CAP_EOK}억")
    return reasons


# ─────────────────────────────────────────────────────────────
# 다중 종목 일괄 호출
# ─────────────────────────────────────────────────────────────
def check_market_caps(codes: List[str]) -> Dict[str, Any]:
    """종목 list → 시가총액 측정 + 차단 판정.

    Returns:
        {"market_caps": {code: {...}}, "blocked": {code: [reasons]}, "stats": {...}}
    """
    market_caps = {}
    blocked = {}
    n_total = len(codes)
    n_ok = 0
    n_fail = 0

    sample_logged = False
    for i, code in enumerate(codes):
        mc = fetch_market_cap(code)
        if mc is None:
            n_fail += 1
            continue
        # 5/28 옵션 A #10: 첫 OK 응답 1건 raw sample 핵심 필드 INFO 로그
        if not sample_logged:
            _logger.info(f"[RAW SAMPLE] code={mc.get('code')} name={mc.get('name')} "
                         f"market_cap={mc.get('market_cap_eok'):.0f}억 "
                         f"per={mc.get('per'):.1f} eps={mc.get('eps'):.0f} "
                         f"foreign={mc.get('foreign_ratio_pct'):.2f}% "
                         f"price={mc.get('current_price'):.0f}")
            sample_logged = True
        market_caps[code] = mc
        reasons = evaluate_block(mc)
        if reasons:
            blocked[code] = reasons
        n_ok += 1
        if (i + 1) % 10 == 0:
            _logger.info(f"[BATCH] {i+1}/{n_total} 진행 (OK={n_ok} FAIL={n_fail} BLOCKED={len(blocked)})")

    _logger.info(f"[CHECK_DONE] 총 {n_total} / OK {n_ok} / FAIL {n_fail} / BLOCKED {len(blocked)}")
    if blocked:
        for code, reasons in list(blocked.items())[:5]:
            mc_eok = market_caps.get(code, {}).get("market_cap_eok", 0)
            name = market_caps.get(code, {}).get("name", "")
            _logger.info(f"  blocked {code} {name}: cap={mc_eok:.0f}억 reasons=[{','.join(reasons)}]")

    # cache 저장 (5/28 옵션 A #5: trade_date + source 추가)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "trade_date": datetime.now().strftime("%Y%m%d"),
        "source": "broker_ipc_opt10001",
        "version": VERSION,
        "n_total": n_total, "n_ok": n_ok, "n_fail": n_fail,
        "n_blocked": len(blocked),
        "market_caps": market_caps,
        "blocked": blocked,
    }
    try:
        tmp = MARKET_CAP_CACHE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        os.replace(str(tmp), str(MARKET_CAP_CACHE))
    except Exception as e:
        _logger.error(f"cache save 실패: {e}")

    return payload


def load_blocked_codes() -> set:
    """현재 cache에서 blocked 종목 set 반환 (signal_v2 호출용).

    5/28 옵션 A #5: trade_date 오늘 검증, stale 시 WARNING + 빈 set 반환.
    """
    if not MARKET_CAP_CACHE.exists():
        return set()
    try:
        with MARKET_CAP_CACHE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        today = datetime.now().strftime("%Y%m%d")
        td = str(payload.get("trade_date", "")).strip()
        if td and td != today:
            _logger.warning(f"[STALE] market_cap_cache trade_date={td} != today={today} → 차단 무시")
            return set()
        return set(payload.get("blocked", {}).keys())
    except Exception as e:
        _logger.warning(f"load_blocked_codes 예외: {e}")
        return set()


def load_market_cap(code: str) -> Optional[float]:
    """특정 종목의 시가총액 (억원) 반환. cache 없으면 None."""
    if not MARKET_CAP_CACHE.exists():
        return None
    try:
        with MARKET_CAP_CACHE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        mc = payload.get("market_caps", {}).get(str(code).zfill(6))
        return mc.get("market_cap_eok") if mc else None
    except Exception:
        return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="EOD pickup market cap checker")
    parser.add_argument("--codes", type=str, default=None,
                        help="콤마 분리 종목 코드 (예: 005930,082920)")
    parser.add_argument("--from_watchlist", action="store_true",
                        help="eod_pickup_v2_watchlist json에서 종목 read")
    parser.add_argument("--show", action="store_true", help="cache 표시")
    args = parser.parse_args()

    print(f"\n{VERSION}\n")

    if args.show:
        if MARKET_CAP_CACHE.exists():
            with MARKET_CAP_CACHE.open("r", encoding="utf-8") as f:
                print(f.read())
        else:
            print("cache 없음")
    elif args.from_watchlist:
        today = datetime.now().strftime("%Y%m%d")
        wl = SIGNAL_DIR / f"eod_pickup_v2_watchlist_{today}.json"
        if not wl.exists():
            print(f"watchlist 없음: {wl}")
        else:
            with wl.open("r", encoding="utf-8") as f:
                watchlist = json.load(f)
            codes = [str(r.get("code", "")).zfill(6) for r in watchlist]
            result = check_market_caps(codes)
            print(json.dumps({"n_total": result["n_total"], "n_ok": result["n_ok"],
                              "n_blocked": result["n_blocked"]},
                             indent=2, ensure_ascii=False))
    elif args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
        result = check_market_caps(codes)
        print(json.dumps({"n_total": result["n_total"], "n_ok": result["n_ok"],
                          "n_blocked": result["n_blocked"],
                          "blocked": result["blocked"]},
                         indent=2, ensure_ascii=False))
    else:
        print("--codes 005930,082920 또는 --from_watchlist 또는 --show 필요")
