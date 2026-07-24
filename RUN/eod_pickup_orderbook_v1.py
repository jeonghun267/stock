# -*- coding: utf-8 -*-
"""
eod_pickup_orderbook_v1.py
===========================
호가 spread 실시간 측정 모듈 (slippage 정밀 추정).

[데이터 source]:
  - broker IPC opt10004 (주식호가요청, read-only TR)
  - broker_client.tr() 사용

[측정 항목]:
  - 매도1호가 (ask1) / 매수1호가 (bid1)
  - spread_won = ask1 - bid1
  - spread_pct = spread_won / bid1 * 100
  - 매도1호가잔량 (ask1_qty) / 매수1호가잔량 (bid1_qty)
  - 호가 깊이 5호가까지 누적 잔량

[차단 임계]:
  - spread_pct > 1.0% → 슬리피지 과대, 차단
  - bid1_qty < 100주 → 매도 시 호가 부족, 차단
  - 매수/매도 호가 불균형 (bid1_qty < ask1_qty × 0.1) → 매수 압력 부족

[안전 가드]:
  - 매매 chain 무관 (read-only TR)
  - broker 부담 최소화 (Stage 1 후 1차 후보만 측정)
  - broker_client.tr() 사용 (검증된 read-only API)

[활용]:
  eod_pickup_signal_v2_hedge가 Stage 1 후 호출 (선택적, 활성화 flag)
  또는 14:30~15:18 사이 1회 측정 → 결과 blocklist 추가
"""
from __future__ import annotations

import os
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

VERSION = "eod_pickup_orderbook_v1"
BASE_DIR = Path(r"C:\stock_bot")
RUN_DIR = BASE_DIR / "RUN"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "LOG"
SIGNAL_DIR = DATA_DIR / "eod_pickup"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SIGNAL_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "eod_pickup_orderbook.log"
ORDERBOOK_CACHE = SIGNAL_DIR / "orderbook_cache.json"

# 차단 임계
SPREAD_PCT_BLOCK = 1.0      # spread > 1.0% 차단
MIN_BID1_QTY = 100          # 매수1호가 잔량 < 100주 (보조 참고만, 5/28 옵션 A로 우선순위 낮춤)
BID_ASK_IMBALANCE_RATIO = 0.1   # bid_total < ask_total × 0.1 차단

# 금액 기준 (5/28 옵션 A #4 — 주식 수 절대값은 주가에 따라 의미 다름)
DEFAULT_PLANNED_ORDER_KRW = 2_000_000        # 사용자 자본 200만원 기준 단일 매수 금액
BID1_VALUE_MIN_RATIO = 0.3                   # bid1_value ≥ planned × 0.3
BID_TOTAL_5_VALUE_MIN_RATIO = 1.0            # bid_total_5_value ≥ planned × 1.0
BID_TOTAL_5_VALUE_PREF_RATIO = 2.0           # 우선주는 ≥ planned × 2.0

# broker IPC
TR_TIMEOUT_SEC = 5.0

# 로거
_logger = logging.getLogger("eod_pickup_orderbook")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("[%(asctime)s][orderbook][%(levelname)s] %(message)s"))
    _logger.addHandler(_fh)
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("[%(asctime)s][orderbook][%(levelname)s] %(message)s"))
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
# opt10004 호출 (broker IPC)
# ─────────────────────────────────────────────────────────────
def fetch_orderbook(code: str, timeout_sec: float = TR_TIMEOUT_SEC) -> Optional[Dict[str, Any]]:
    """broker IPC opt10004 호출 → 종목 호가 dict 반환.

    Returns:
        {"code", "ask1", "bid1", "ask1_qty", "bid1_qty",
         "ask_total_5", "bid_total_5", "spread_won", "spread_pct"}
        or None (실패)
    """
    try:
        from broker_client import BrokerClient
    except ImportError as e:
        _logger.error(f"broker_client import 실패: {e}")
        return None

    code = str(code).zfill(6)
    output_fields = [
        "매도1호가", "매수1호가",
        "매도1호가잔량", "매수1호가잔량",
        "매도2호가잔량", "매수2호가잔량",
        "매도3호가잔량", "매수3호가잔량",
        "매도4호가잔량", "매수4호가잔량",
        "매도5호가잔량", "매수5호가잔량",
    ]
    try:
        bc = BrokerClient()
        if not bc.alive():
            _logger.warning(f"broker DEAD → 호가 조회 보류 ({code})")
            return None
        res = bc.tr(
            tr_code="opt10004",
            inputs={"종목코드": code},
            output_fields=output_fields,
            rqname=f"orderbook_{code}",
            screen_no="0801",
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

    ask1 = _safe_float(r.get("매도1호가", 0))
    bid1 = _safe_float(r.get("매수1호가", 0))
    if ask1 <= 0 or bid1 <= 0:
        return None

    # 한국 거래소 호가는 음수로 부호 표시 (보통 절댓값 사용)
    ask1 = abs(ask1)
    bid1 = abs(bid1)

    ask_total_5 = sum(_safe_int(r.get(f"매도{i}호가잔량", 0)) for i in range(1, 6))
    bid_total_5 = sum(_safe_int(r.get(f"매수{i}호가잔량", 0)) for i in range(1, 6))

    spread_won = ask1 - bid1
    spread_pct = (spread_won / bid1 * 100) if bid1 > 0 else 0.0

    return {
        "code": code,
        "ask1": ask1, "bid1": bid1,
        "ask1_qty": _safe_int(r.get("매도1호가잔량", 0)),
        "bid1_qty": _safe_int(r.get("매수1호가잔량", 0)),
        "ask_total_5": ask_total_5,
        "bid_total_5": bid_total_5,
        "spread_won": spread_won,
        "spread_pct": round(spread_pct, 4),
        "ts": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 차단 판정
# ─────────────────────────────────────────────────────────────
def evaluate_block(ob: Dict[str, Any], is_preferred: bool = False,
                   planned_order_krw: float = DEFAULT_PLANNED_ORDER_KRW) -> List[str]:
    """호가 데이터 → 차단 사유 list.

    5/28 옵션 A #4: 금액 기준 주요 차단 + 주식 수 100주 절대값은 보조 참고.
    우선주는 더 강한 호가 깊이 요구 (planned × 2.0).
    """
    reasons = []
    spread_pct = ob.get("spread_pct", 0)
    bid1 = ob.get("bid1", 0)
    bid1_qty = ob.get("bid1_qty", 0)
    bid_total = ob.get("bid_total_5", 0)
    ask_total = ob.get("ask_total_5", 0)

    # 금액 환산
    bid1_value = bid1 * bid1_qty
    bid_total_5_value = bid1 * bid_total  # 1호가 기준 근사 (정확도는 호가별 잔량 가중평균보다 보수적)

    # 1. spread (변경 없음)
    if spread_pct > SPREAD_PCT_BLOCK:
        reasons.append(f"spread_pct_{spread_pct:.2f}%>1.0%")

    # 2. ⭐ 금액 기준 (5/28 옵션 A #4 주요 차단)
    bid1_min_krw = planned_order_krw * BID1_VALUE_MIN_RATIO
    if bid1_value < bid1_min_krw:
        reasons.append(f"bid1_value_{bid1_value:,.0f}원<{bid1_min_krw:,.0f}원")

    bid_total_5_ratio = BID_TOTAL_5_VALUE_PREF_RATIO if is_preferred else BID_TOTAL_5_VALUE_MIN_RATIO
    bid_total_5_min_krw = planned_order_krw * bid_total_5_ratio
    if bid_total_5_value < bid_total_5_min_krw:
        suffix = "_pref" if is_preferred else ""
        reasons.append(f"bid_total_5_value_{bid_total_5_value:,.0f}원<{bid_total_5_min_krw:,.0f}원{suffix}")

    # 3. 매수/매도 호가 불균형 (변경 없음)
    if ask_total > 0 and bid_total < ask_total * BID_ASK_IMBALANCE_RATIO:
        reasons.append(f"bid_imbalance_{bid_total}/{ask_total}")

    # 4. bid1_qty 100주 절대값 — 보조 참고 (로그만, 차단 X로 약화)
    if bid1_qty < MIN_BID1_QTY:
        # 금액 기준에 이미 걸렸으면 reason 중복 없음. 단독 차단은 안 함.
        _logger.debug(f"[bid1_qty_low_ref] qty={bid1_qty} <{MIN_BID1_QTY} (참고)")

    return reasons


# ─────────────────────────────────────────────────────────────
# 다중 종목 일괄 호출
# ─────────────────────────────────────────────────────────────
def check_orderbooks(codes: List[str]) -> Dict[str, Any]:
    """종목 list → 호가 측정 + 차단 판정.

    Returns:
        {"orderbooks": {code: {...}}, "blocked": {code: [reasons]}, "stats": {...}}
    """
    orderbooks = {}
    blocked = {}
    n_total = len(codes)
    n_ok = 0
    n_fail = 0

    sample_logged = False
    for i, code in enumerate(codes):
        ob = fetch_orderbook(code)
        if ob is None:
            n_fail += 1
            continue
        # 5/28 옵션 A #10: 첫 OK 응답 1건 raw sample 핵심 필드 INFO 로그
        if not sample_logged:
            _logger.info(f"[RAW SAMPLE] code={ob.get('code')} ask1={ob.get('ask1'):.0f} "
                         f"bid1={ob.get('bid1'):.0f} bid1_qty={ob.get('bid1_qty')} "
                         f"spread_pct={ob.get('spread_pct'):.3f}")
            sample_logged = True
        orderbooks[code] = ob
        reasons = evaluate_block(ob)
        if reasons:
            blocked[code] = reasons
        n_ok += 1
        if (i + 1) % 10 == 0:
            _logger.info(f"[BATCH] {i+1}/{n_total} 진행 (OK={n_ok} FAIL={n_fail} BLOCKED={len(blocked)})")

    _logger.info(f"[CHECK_DONE] 총 {n_total} / OK {n_ok} / FAIL {n_fail} / BLOCKED {len(blocked)}")
    if blocked:
        for code, reasons in list(blocked.items())[:5]:
            _logger.info(f"  blocked {code}: {','.join(reasons)}")

    # cache 저장 (5/28 옵션 A #5: trade_date + source 추가)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "trade_date": datetime.now().strftime("%Y%m%d"),
        "source": "broker_ipc_opt10004",
        "version": VERSION,
        "n_total": n_total, "n_ok": n_ok, "n_fail": n_fail,
        "n_blocked": len(blocked),
        "orderbooks": orderbooks,
        "blocked": blocked,
    }
    try:
        tmp = ORDERBOOK_CACHE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        os.replace(str(tmp), str(ORDERBOOK_CACHE))
    except Exception as e:
        _logger.error(f"cache save 실패: {e}")

    return payload


ORDERBOOK_STALE_MAX_AGE_SEC = 10 * 60   # 10분 age 한도 (5/28 옵션 A #5)


def load_blocked_codes() -> set:
    """현재 cache에서 blocked 종목 set 반환 (signal_v2 호출용).

    5/28 옵션 A #5: trade_date 오늘 + age ≤ 10분 검증.
    호가는 분 단위 변동성 큼 → 10분 이내만 유효.
    """
    if not ORDERBOOK_CACHE.exists():
        return set()
    try:
        with ORDERBOOK_CACHE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        today = datetime.now().strftime("%Y%m%d")
        td = str(payload.get("trade_date", "")).strip()
        if td and td != today:
            _logger.warning(f"[STALE] orderbook_cache trade_date={td} != today={today} → 차단 무시")
            return set()
        # age 검증
        gen_at = str(payload.get("generated_at", ""))
        if gen_at:
            try:
                gt = datetime.fromisoformat(gen_at)
                age_sec = (datetime.now() - gt).total_seconds()
                if age_sec > ORDERBOOK_STALE_MAX_AGE_SEC:
                    _logger.warning(f"[STALE] orderbook_cache age={age_sec:.0f}s > {ORDERBOOK_STALE_MAX_AGE_SEC}s → 차단 무시")
                    return set()
            except Exception:
                pass
        return set(payload.get("blocked", {}).keys())
    except Exception as e:
        _logger.warning(f"load_blocked_codes 예외: {e}")
        return set()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="EOD pickup orderbook checker")
    parser.add_argument("--codes", type=str, default=None,
                        help="콤마 분리 종목 코드 (예: 005930,082920)")
    parser.add_argument("--from_watchlist", action="store_true",
                        help="eod_pickup_v2_watchlist json에서 종목 read")
    parser.add_argument("--show", action="store_true", help="cache 표시")
    args = parser.parse_args()

    print(f"\n{VERSION}\n")

    if args.show:
        if ORDERBOOK_CACHE.exists():
            with ORDERBOOK_CACHE.open("r", encoding="utf-8") as f:
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
            result = check_orderbooks(codes)
            print(json.dumps({"n_total": result["n_total"], "n_ok": result["n_ok"],
                              "n_blocked": result["n_blocked"]},
                             indent=2, ensure_ascii=False))
    elif args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
        result = check_orderbooks(codes)
        print(json.dumps({"n_total": result["n_total"], "n_ok": result["n_ok"],
                          "n_blocked": result["n_blocked"],
                          "blocked": result["blocked"]},
                         indent=2, ensure_ascii=False))
    else:
        print("--codes 005930,082920 또는 --from_watchlist 또는 --show 필요")
